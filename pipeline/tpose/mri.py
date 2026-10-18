"""MRI scan of a garment on the body: cross-section slices at the collar, sleeves, cuffs, waistband/hem and legs.

At each station a plane cuts the body and the garment. In the slice the body is one ring and the garment another
(drawn in two colours on 08_inspect/mri_<key>.png). Rays go out from the limb's own centre (the skin's centre at
that point of the bone); along each ray the gap is how far the garment's INNER wall is outside the skin. A station
counts only where the garment goes all the way round (>= 90 % of rays meet it): an open hem or a sleeve that has
already ended is not a ring.

  gap <= 0 on a ray   the rings touch or cross: skin through fabric, or fabric inside the limb
  centre offset       how far the garment ring's centre is from the limb's (a sleeve hanging off the arm)

FAILS (every garment, every track):
  collar / sleeve / cuff / leg slices   the rings touch on more than TOUCH_SHARE of the rays, where that skin shows
  waistband / hem slices                skin shows through the fabric on more than OUTSIDE_SHARE (a band grips by
                                        design, so touching there is fine)
Garment geometry wholly inside the body (hidden) is drawn but cannot fail a slice on its own.
Run alone: blender -b --factory-startup -P pipeline/tpose/mri.py -- <look_dir> [Xander]
Called by inspect_look.py (its numbers go into inspect.json, its fails into the look's fails).
"""
import json, math, sys
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'pipeline'))
sys.path.insert(0, str(ROOT / 'pipeline' / 'tpose'))
try:
    import metrics as M  # noqa: E402  (Blender only; drawing runs in plain Python)
except ImportError:
    M = None

RAYS = 96
COVER = 0.9            # share of rays that must meet the garment for the slice to be a ring
TOUCH_MM = 0.0         # a gap at or below this is touching
TOUCH_SHARE = 0.08     # a ring station fails when more of its rays than this touch (on skin that shows)
OUTSIDE_SHARE = 0.05   # a waistband / hem station fails when skin shows through on more of its rays than this
TORSO_STATIONS = ('waistband', 'hips', 'hem', 'waist')
REACH = 0.25
LIMB_TS = {0: (0.35, 0.65, 0.9), 1: (0.2, 0.45, 0.7, 0.85, 0.95)}   # upper bone / lower bone of each limb
LIMB_NAMES = {'arm_L': 'L arm', 'arm_R': 'R arm', 'leg_L': 'L leg', 'leg_R': 'R leg'}
BONE_PART = {0: {'arm': 'upper arm', 'leg': 'thigh'}, 1: {'arm': 'forearm', 'leg': 'shin'}}


def ray_hits(segs, dirs):
    """Per direction: sorted distances where rays from the origin cross the 2D segments."""
    if not len(segs):
        return [np.array([])] * len(dirs)
    p, q = segs[:, 0], segs[:, 1]
    e = q - p
    out = []
    for d in dirs:
        den = d[0] * e[:, 1] - d[1] * e[:, 0]
        ok = np.abs(den) > 1e-12
        t = np.where(ok, (p[:, 0] * e[:, 1] - p[:, 1] * e[:, 0]) / np.where(ok, den, 1), -1)   # along the ray
        s = np.where(ok, (p[:, 0] * d[1] - p[:, 1] * d[0]) / np.where(ok, den, 1), -1)        # along the segment
        hit = ok & (t > 0) & (t < REACH) & (s >= 0) & (s <= 1)
        out.append(np.sort(t[hit]))
    return out


def slice_station(bco, btri, gco, gtri, o, n, u, v):
    """Measure one slice. o: the limb/neck/waist centre (3D); n, u, v: the plane's normal and axes."""
    bsegs = M.plane_section(bco, btri, o, n, u, v)
    gsegs = M.plane_section(gco, gtri, o, n, u, v)
    ang = np.linspace(0, 2 * np.pi, RAYS, endpoint=False)
    dirs = np.stack([np.cos(ang), np.sin(ang)], 1)
    bh, gh = ray_hits(bsegs, dirs), ray_hits(gsegs, dirs)
    rb = np.array([h[0] if len(h) else np.nan for h in bh])
    rg = np.array([h[0] if len(h) else np.nan for h in gh])
    rg_out = np.array([h[-1] if len(h) else np.nan for h in gh])             # the garment's outermost wall
    valid = ~np.isnan(rb)
    met = valid & ~np.isnan(rg)
    cover = met.sum() / max(valid.sum(), 1)
    gap = (rg - rb) * 1000
    res = {'cover': round(float(cover), 3), 'rays': int(valid.sum())}
    if valid.sum() < RAYS * 0.5 or cover < COVER:
        res['ring'] = False
        return res, bsegs, gsegs
    g = gap[met]
    touch = g <= TOUCH_MM
    outside = rb[met] > rg_out[met] + 0.001                                  # skin beyond every wall: showing through
    bc = (dirs[met] * rb[met, None]).mean(0)
    gc = (dirs[met] * rg[met, None]).mean(0)
    res.update({'ring': True, 'gap_min_mm': round(float(g.min()), 1), 'gap_median_mm': round(float(np.median(g)), 1),
                'touch_share': round(float(touch.mean()), 3), 'outside_share': round(float(outside.mean()), 3), 'r_draw': round(float(np.nanmax(np.maximum(rb, rg)[met])), 4), 'offset_cm': round(float(np.linalg.norm(gc - bc)) * 100, 2),
                'touch_dirs': [round(float(a), 3) for a in ang[met][touch]]})
    return res, bsegs, gsegs


def stations(arm, slot, gco, body_co, body_bone):
    """Where to slice for this kind of garment: (name, origin, normal, u, v)."""
    out = []
    for limb in M.SLOT_LIMBS.get(slot, []):
        kind = 'arm' if limb.startswith('arm') else 'leg'
        for si, (bone, child) in enumerate(M.LIMB_CHAINS[limb]):
            a, b = np.array(M.joint(arm, bone)), np.array(M.joint(arm, child))
            skin = M.limb_skin(body_co, body_bone, bone, child)
            n, u, v = M.plane_basis(b - a)
            for t in LIMB_TS[si]:
                c = M.skin_centre(skin, a, b, t)
                if c is not None:
                    out.append((f'{LIMB_NAMES[limb]} {BONE_PART[si][kind]} {int(t * 100)}%', c, n, u, v))
    if slot in M.TORSO_SLOTS:
        hips = np.array(M.joint(arm, 'Hips'))
        axis_xy = hips[:2]
        n, u, v = np.array([0, 0, 1.0]), np.array([1.0, 0, 0]), np.array([0, 1.0, 0])
        tor = gco[(np.linalg.norm(gco[:, :2] - axis_xy, axis=1) < 0.25) & (gco[:, 2] > hips[2] - 0.15)
                  & (gco[:, 2] < float(M.joint(arm, 'Neck')[2]))]
        if len(tor) > 50:
            angb = ((np.arctan2(tor[:, 1] - axis_xy[1], tor[:, 0] - axis_xy[0]) + np.pi) / (2 * np.pi) * 24).astype(int) % 24
            bins = [b_ for b_ in range(24) if (angb == b_).sum() > 10]
            top = min(tor[angb == b_, 2].max() for b_ in bins)
            bot = max(tor[angb == b_, 2].min() for b_ in bins)
            pelvis = hips[2] - 0.03
            if slot == 'bottom':
                zs = [('waistband', top - 0.012), ('hips', max(pelvis, (top + pelvis) / 2))]
            else:
                zs = [('hem', max(bot + 0.015, pelvis)), ('waist', float(M.joint(arm, 'Spine1')[2]))]
            for name, z in zs:
                if top - 0.005 > z > max(bot, pelvis) - 1e-6:
                    out.append((name, np.array([axis_xy[0], axis_xy[1], z]), n, u, v))
    if slot in ('top', 'outerwear', 'fullbody'):
        neck, head = np.array(M.joint(arm, 'Neck')), np.array(M.joint(arm, 'Head'))
        near = gco[np.linalg.norm(gco[:, :2] - neck[:2], axis=1) < 0.12]
        if len(near) > 50 and near[:, 2].max() < neck[2] + 0.09:                 # a neckline (not a hood)
            angb = ((np.arctan2(near[:, 1] - neck[1], near[:, 0] - neck[0]) + np.pi) / (2 * np.pi) * 24).astype(int) % 24
            tops = [near[angb == b_, 2].max() for b_ in range(24) if (angb == b_).sum() > 5]
            z = min(tops) - 0.01                                                   # just under the lowest collar edge
            n, u, v = M.plane_basis(head - neck)
            o = neck + (head - neck) / max(head[2] - neck[2], 1e-6) * (z - neck[2])
            out.append(('collar', o, n, u, v))
    return out


def scan(arm, slot, gco, gtri, bco, btri, body_bone, body_vis=None):
    """All stations of one garment: {name: result}, and the slices for the picture."""
    res, pics = {}, []
    for name, o, n, u, v in stations(arm, slot, gco, bco, body_bone):
        r, bs, gs = slice_station(bco, btri, gco, gtri, o, n, u, v)
        if r.get('ring') and body_vis is not None:
            # touching only counts where that skin is shown: the nearest body vertex to each touching ray's skin point
            vis = []
            for a_ in r['touch_dirs']:
                d = bco - o
                along = d @ (u * math.cos(a_) + v * math.sin(a_))
                plane = np.abs(d @ n) < 0.01
                cand = np.where(plane & (along > 0))[0]
                if len(cand):
                    vis.append(bool(body_vis[cand[np.argmax(along[cand])]]))
            r['touch_visible_share'] = round(float(np.mean(vis)) if vis else 0.0, 3)
        r['kind'] = 'torso' if name in TORSO_STATIONS else 'ring'
        r.pop('touch_dirs', None)
        res[name] = r
        pics.append((name, r, bs, gs))
    return res, pics


def bad(r):
    """Collar, sleeves, cuffs, legs: the rings must not touch where the skin shows. Waistband and hem grip the body
    by design (a band sits snug), so there only skin showing THROUGH the fabric counts."""
    if not r.get('ring'):
        return False
    if r.get('kind') == 'torso':
        return r.get('outside_share', 0) * r.get('touch_visible_share', 1.0) > OUTSIDE_SHARE
    return r['touch_share'] * r.get('touch_visible_share', 1.0) > TOUCH_SHARE


def check(key, res):
    fails = []
    for name, r in res.items():
        if not bad(r):
            continue
        if r.get('kind') == 'torso':
            fails.append(f'{key}: MRI {name} - skin shows through the garment on {r["outside_share"]:.0%} of the slice')
        else:
            fails.append(f'{key}: MRI {name} - garment and body rings touch on {r["touch_share"]:.0%} of the slice '
                         f'where the skin shows (min gap {r["gap_min_mm"]:.1f} mm, off-centre {r["offset_cm"]:.1f} cm)')
    return fails


def save_slices(pics, path, title):
    """The rings of every slice, for sheet() (Blender's Python has no imaging library)."""
    data = {'title': title, 'slices': [{'name': n, 'r': r, 'body': np.round(bs, 4).tolist(), 'garment': np.round(gs, 4).tolist()}
                                       for n, r, bs, gs in pics if r.get('ring')]}
    path.write_text(json.dumps(data), encoding='utf-8')


def draw(json_path):
    """Draw the sheet next to its data: mri_<key>.json -> mri_<key>.png (plain Python, with Pillow)."""
    data = json.loads(Path(json_path).read_text(encoding='utf-8'))
    pics = [(x['name'], x['r'], np.array(x['body']).reshape(-1, 2, 2), np.array(x['garment']).reshape(-1, 2, 2))
            for x in data['slices']]
    sheet(pics, Path(json_path).with_suffix('.png'), data['title'])


def _fonts(size=13, title=16):
    from PIL import ImageFont
    for reg, bold in (('segoeui.ttf', 'segoeuib.ttf'), ('arial.ttf', 'arialbd.ttf'), ('DejaVuSans.ttf', 'DejaVuSans-Bold.ttf')):
        try:
            return ImageFont.truetype(reg, size), ImageFont.truetype(bold, title)
        except OSError:
            pass
    f = ImageFont.load_default()
    return f, f


def tile(name, r, bs, gs, T=240, label=None):
    """One slice as a picture (clipped to its tile): skin ring orange, garment teal, verdict underneath."""
    from PIL import Image, ImageDraw
    S = 2
    im = Image.new('RGB', (T * S, T * S), (255, 255, 255))
    dr = ImageDraw.Draw(im)
    f, fb = _fonts(13 * S, 14 * S)
    bad_ = bad(r)
    r_ = max(0.02, r.get('r_draw', 0.1) * 1.1)
    sc = (T / 2 - 36) / r_ * S
    cx, cy = T / 2 * S, (T / 2 + 4) * S

    def line(segs, col, w):
        for q in segs:
            dr.line([(cx + q[0, 0] * sc, cy - q[0, 1] * sc), (cx + q[1, 0] * sc, cy - q[1, 1] * sc)], fill=col, width=w * S)
    line(gs, (14, 165, 183), 3)
    line(bs, (222, 120, 96), 3)
    dr.ellipse([cx - 2 * S, cy - 2 * S, cx + 2 * S, cy + 2 * S], fill=(60, 60, 60))
    dr.rectangle([0, 0, T * S, 30 * S], fill=(255, 255, 255))
    dr.rectangle([0, (T - 30) * S, T * S, T * S], fill=(255, 255, 255))
    dr.text((10 * S, 8 * S), label or name, fill=(20, 30, 40), font=fb)
    hidden = r.get('touch_share', 0) > TOUCH_SHARE and not bad_ and r.get('kind') != 'torso'
    txt = (f'gap {r["gap_min_mm"]:.0f}-{r["gap_median_mm"]:.0f} mm · off {r["offset_cm"]:.1f} cm'
           + (' · hidden' if hidden else ''))
    dr.text((10 * S, (T - 24) * S), txt, fill=(214, 69, 65) if bad_ else (110, 122, 133) if hidden else (40, 130, 70), font=f)
    dr.rectangle([1, 1, T * S - 2, T * S - 2], outline=(214, 69, 65) if bad_ else (205, 214, 220), width=(3 if bad_ else 1) * S)
    return im.resize((T, T), Image.LANCZOS)


def sheet(pics, path, title):
    """The scan as a picture: one tile per slice, skin ring and garment ring in two colours."""
    from PIL import Image, ImageDraw
    pics = [p for p in pics if p[1].get('ring')]
    if not pics:
        return
    T, cols, gap = 240, 5, 8
    rows = math.ceil(len(pics) / cols)
    im = Image.new('RGB', (cols * (T + gap) + gap, rows * (T + gap) + 44), (245, 248, 250))
    dr = ImageDraw.Draw(im)
    dr.text((10, 12), title + '    skin = orange, garment = teal', fill=(20, 30, 40), font=_fonts(13, 16)[1])
    for i, (name, r, bs, gs) in enumerate(pics):
        im.paste(tile(name, r, bs, gs, T), (gap + (i % cols) * (T + gap), 40 + (i // cols) * (T + gap)))
    im.save(path, optimize=True)


def run_look(d, arm, pieces, body, body_co, body_bone, body_vis):
    """Scan every piece of a look (masks off, look pose): numbers, fails, and the slices saved for the sheets."""
    bco, btri = M.tri_mesh(body)
    out = d / '08_inspect'
    out.mkdir(exist_ok=True)
    allres, fails = {}, []
    for o in pieces:
        key, slot = o.name.split('__')[-1], o.name.split('__')[1]
        gco, gtri = M.tri_mesh(o)
        res, pics = scan(arm, slot, gco, gtri, bco, btri, body_bone, body_vis)
        allres[key] = res
        fails += check(key, res)
        save_slices(pics, out / f'mri_{key}.json', f'MRI  {key}  ({d.name})')
        for name, r in res.items():
            if r.get('ring'):
                print(f'[mri] {key:28s} {name:22s} gap {r["gap_min_mm"]:6.1f}..{r["gap_median_mm"]:5.1f} mm  '
                      f'touch {r["touch_share"]:.0%} (visible {r.get("touch_visible_share", 1):.0%})  '
                      f'off {r["offset_cm"]:.1f} cm', flush=True)
    (out / 'mri.json').write_text(json.dumps({'stations': allres, 'fails': fails}, indent=1), encoding='utf-8')
    print('[mri] ' + ('PASS' if not fails else 'FAIL\n  - ' + '\n  - '.join(fails)), flush=True)
    draw_all(out)
    return allres, fails


def draw_all(out):
    """Draw every sheet with the system Python (garment.py sets AN_PYTHON; else python on PATH)."""
    import os, shutil, subprocess
    py = os.environ.get('AN_PYTHON') or shutil.which('python') or shutil.which('py')
    if py:
        env = {k: v for k, v in os.environ.items() if k not in ('PYTHONHOME', 'PYTHONPATH')}   # not Blender's Python
        subprocess.run([py, __file__, '--draw', *map(str, sorted(Path(out).glob('mri_*.json')))], env=env)


def visible_skin(body):
    """Per body vertex: is it shown in this look (part of a face the look's mask keeps)?"""
    g = None
    for nm in ('hidden_in_this_look', 'hidden_under_this_outfit', 'hide_covered_by_look', 'hide_covered_by_outfit'):
        g = g or body.vertex_groups.get(nm)
    hid = np.zeros(len(body.data.vertices), bool)
    if g is not None:
        hid = np.array([any(e.group == g.index for e in v.groups) for v in body.data.vertices])
    vis = np.zeros(len(hid), bool)
    for f in body.data.polygons:
        vi = list(f.vertices)
        if not hid[vi].any():
            vis[vi] = True
    return vis


def main():
    import bpy
    import fit_outfit as F
    argv = sys.argv[sys.argv.index('--') + 1:]
    d = Path(argv[0]).resolve()
    base = argv[1] if len(argv) > 1 else 'Xander'
    bpy.ops.wm.open_mainfile(filepath=str(d / '06_fitted' / f'{d.name}__{base}.blend'))
    arm = next(o for o in bpy.data.objects if o.type == 'ARMATURE')
    F.apply_look_pose(arm, d)
    meshes = [o for o in bpy.data.objects if o.type == 'MESH']
    pieces = [o for o in meshes if o.name.startswith(d.name + '__')]
    body = max((o for o in meshes if o not in pieces), key=lambda o: len(o.data.vertices))
    for m in [m for o in meshes for m in o.modifiers if m.type == 'MASK']:
        m.show_viewport = False
    bpy.context.view_layer.update()
    names, Wb = F.body_weights(body)
    body_co, _ = F.world_verts(body, evaluated=True)
    run_look(d, arm, pieces, body, body_co, M.chain_bone_of(names, Wb), visible_skin(body))


if __name__ == '__main__':
    if '--draw' in sys.argv:
        for j in sys.argv[sys.argv.index('--draw') + 1:]:
            draw(j)
    else:
        main()
