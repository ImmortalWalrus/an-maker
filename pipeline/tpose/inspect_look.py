"""Step 8 - inspection of a fitted outfit or equipped look: every opening, from every side, plus pass/fail numbers.

Features (located from the rig, so they work for any outfit): left/right cuff, left/right armpit, collar, back of
neck/hood, waist, left/right ankle, chest front and back (straps). Each is rendered as worn (masks on) from 6
directions - front, back, outside, inside, below and along the limb / straight on.

Numbers (same maths as the fitting - pipeline/tpose/metrics.py), each with a threshold:
  sleeve / leg sections - planar cross-sections of the garment along each limb (metrics.SectionField - rays are
                     fooled by double-walled AI sleeves): in a HOLLOW part the limb must be in the hole, not the
                     lining (<= 10 % of its outline) and centred on the hole (<= 0.8 cm); in a SOLID part (limb
                     embedded) the limb must stay inside until the hem (<= 10 % outside)
  mask overreach   - masked-out surface that a camera can see in the unmasked look from any direction within
                     55 deg of its normal shows nothing, a back face, or something beyond the limb instead
                     = a see-through hole or slit (e.g. ankle skin removed above a shoe)                    == 0
  (all checks count VISIBLE geometry only - skin or layers hidden under clothes cannot show a defect)
  limb skin outside - skin inside a sleeve/leg's length that is outside it (poke-through)  == 0
  flap past opening - generated pieces: garment material that comes back after an empty gap past a cuff/hem's rim
                     (a thin hoop or flap standing beyond the opening)   <= 1 cm, unless over < 20 deg of the rim
  sleeve opening   - generated sleeves: opening radius minus the forearm's (room round the wrist)      <= 2.5 cm
  layer order      - share of a piece's camera-facing OUTER surface (facing away from the body) that a LOWER
                     layer shows in front of, seen from 10 directions                    <= 0.5 %
  skin poke        - body vertices whose skin pokes through a garment (any region), seen by a camera and
                     exposing >= 3 mm2 of skin around them (a seam-crevice speck is not a poke)  == 0
  layer spacing    - RPG shells: rays straight out from the skin give each piece's outer surface; where two pieces
                     overlap, the higher layer must be >= 3 mm outside the lower one (over >= 95 % of the overlap)
                     and rest on it, not float (median <= 20 mm); each piece's median distance off the body is
                     capped per slot (top 30, bottom 40, outerwear 60 mm); drape over the layer beneath
                     at most 30 mm (outerwear 40) - consistent with the shells
  layer shells     - each piece against its layer's standard envelope at the hips/waistband (shells.py), reported as
                     a WARNING (generation guidance); clashes are failed by the exact pairwise checks above, run
                     on every combination a new piece is worn in (gate.py --combo)
  neckline         - a top's collar (its top 2 cm) off the neck skin, front and back (neckline.py; tops without a
                     hood) - REPORTED only: the customizer settles collars to ~5 mm (user-approved, v38)
  torso sections   - horizontal slices through a top/bottom from the crotch to its waistband (bottoms) or chest
                     (tops): share of the VISIBLE torso skin outline outside everything the garment encloses
                     = skin through a waistband, hem or side seam                                       <= 5 %

Run: blender -b --factory-startup -P pipeline/tpose/inspect_look.py -- <look_or_outfit_dir> <base>
Writes <dir>/08_inspect/<feature>_<view>.png, inspect.json, sheet.png (via inspect_sheet.py).
"""
import os
import bpy, sys, json, math
from pathlib import Path
import numpy as np
from mathutils import Vector, Matrix

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'pipeline'))
sys.path.insert(0, str(ROOT / 'pipeline' / 'tpose'))
import fit_outfit as F  # noqa: E402
import metrics as M  # noqa: E402
import shells as S  # noqa: E402
import neckline as NL  # noqa: E402

SLOTS = json.loads((ROOT / 'pipeline' / 'slots.json').read_text(encoding='utf-8'))['slots']
LIMITS = {'skin_poke_verts': 0, 'end_offset_cm': 0.8, 'mean_offset_cm': 1.5, 'limb_skin_outside': 0, 'layer_clip_pct': 0.5,
          'mask_overreach_pts': 0, 'limb_in_lining': 0.1, 'torso_outside': 0.05,
          'exposed_mm2': 3.0, 'rim_touch': 0.25, 'layer_gap_mm': 3, 'skin_gap_mm': 1, 'layer_spacing_share': 0.05, 'drape_max_mm': 20,
          'limb_outside_solid': 0.1, 'flap_past_opening_cm': 1.0, 'flap_arc_deg': 20,
          'sleeve_opening_room_cm': 2.5}
# median outer surface off the skin, and median gap over the layer beneath where they overlap. A top must clear the
# bottoms shell (>= 29 mm at the hips, >= 20 at the waistband - shells.py), so a compliant relaxed tee sits ~25 mm off
# the body and ~25 mm over the trousers; 30 still catches the floating tee (33-36 mm off the body, 45 at the hips)
BODY_GAP_MAX_MM = {'top': 30, 'bottom': 40, 'fullbody': 40, 'outerwear': 60}
LOFT_MM = {}   # filled per look in main()
DRAPE_MAX_MM = {'top': 30, 'fullbody': 30, 'outerwear': 40}
SECTION_TS = {0: np.linspace(0.15, 0.95, 9), 1: np.linspace(0.1, 1.1, 11)}
MIN_SAMPLES = 40  # every measurement must look at at least this many points, or the look FAILS (no silent passes)


def J(arm, b):
    return np.array(M.joint(arm, b))


def ray_walls(segs, angles, reach=0.15):
    """Per direction in a cross-section: the garment's material intervals (r0, r1) along a 2D ray from the origin
    (even-odd: a ray from inside the material starts with an interval at 0)."""
    p, e = segs[:, 0], segs[:, 1] - segs[:, 0]
    out = []
    for a in angles:
        dv = np.array([math.cos(a), math.sin(a)])
        den = dv[0] * e[:, 1] - dv[1] * e[:, 0]
        ok = np.abs(den) > 1e-12
        den = np.where(ok, den, 1)
        s = (p[:, 0] * e[:, 1] - p[:, 1] * e[:, 0]) / den
        w = (p[:, 0] * dv[1] - p[:, 1] * dv[0]) / den
        r = np.sort(s[ok & (s > 0) & (w >= 0) & (w <= 1)])
        iv = [(0.0, r[0])] if len(r) % 2 else []
        iv += [(r[i], r[i + 1]) for i in range(len(r) % 2, len(r) - 1, 2)]
        out.append([x for x in iv if x[0] < reach])
    return out


def flap_past_opening(gco, gtri, skin, a, b, end_t, step=0.003, sectors=72, back=0.07, band=0.03):
    """Garment material standing past an opening, detached from it: a thin hoop or flap hanging beyond a cuff/hem
    (a Tripo artifact - MONCHILL puffer, left cuff). Cross-sections every `step` along the limb, from `back` inside
    the tube to the garment's far end (thread_check's end_t), each cut by `sectors` rays round a straight axis
    through the skin centre. Per sector, the sleeve wall is followed outward (material within `band` of its radial
    span a slice before) until it ends - that sector's rim. Material that reappears in the same sector after an
    empty gap stands past the opening. The hoop is ~1 cm thick, like a normal puffer rim, so wall thickness does not
    tell it apart; being cut off from the cuff by a gap does.
    Returns {'flap_cm', 'arc_deg', 'sectors_measured', 'where': [(point, outward dir)]}."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    L = float(np.linalg.norm(b - a))
    n, u, v = M.plane_basis(b - a)
    s_end = end_t * L
    c0 = None
    for s0 in np.arange(max(0.1 * L, s_end - back), s_end, step):
        c0 = M.skin_centre(skin, a, b, s0 / L)
        if c0 is not None:
            break
    if c0 is None:
        return None
    angles = np.linspace(0, 2 * math.pi, sectors, endpoint=False)
    ss = np.arange(s0, s_end + step, step)
    walls = []
    for s in ss:
        o = c0 + n * (s - s0)
        segs = M.plane_section(gco, gtri, o, n, u, v)
        walls.append(ray_walls(segs, angles) if len(segs) else [[] for _ in angles])
    flap = np.zeros(sectors)   # metres past that sector's rim
    where = [None] * sectors
    measured = 0
    for k in range(sectors):
        if not walls[0][k]:
            continue   # no wall here at the start (a slanted hem already open on this side)
        measured += 1
        # the sector's whole material span (an embedded limb can have a sliver of sleeve right at its centre too)
        lo, hi = min(x[0] for x in walls[0][k]), max(x[1] for x in walls[0][k])
        rim = 0
        for i in range(1, len(ss)):
            near = [x for x in walls[i][k] if x[0] < hi + band and x[1] > lo - band]
            if not near:
                continue
            if i == rim + 1:   # still on the wall
                rim, lo, hi = i, min(x[0] for x in near), max(x[1] for x in near)
            else:              # back again after an empty gap, beside where the wall ended
                flap[k] = (i - rim) * step
                d2 = math.cos(angles[k]) * u + math.sin(angles[k]) * v
                where[k] = (c0 + n * (ss[i] - s0) + d2 * np.mean(near[0]), d2)
    # the flap is the longest run of neighbouring sectors (round the rim) with material past the opening
    flagged = flap * 100 > LIMITS['flap_past_opening_cm']
    best = list(range(sectors)) if flagged.all() else []
    if not flagged.all():
        start, run = int(np.argmin(flagged)), []   # start the walk on an unflagged sector so runs wrap round
        for j in range(1, sectors + 1):
            k = (start + j) % sectors
            if flagged[k]:
                run.append(k)
            else:
                best, run = max(best, run, key=len), []
    return {'flap_cm': round(float(flap[best].max() * 100), 1) if best else 0.0,
            'arc_deg': round(len(best) * 360 / sectors), 'max_past_any_sector_cm': round(float(flap.max() * 100), 1),
            'sectors_measured': measured, 'where': [where[k] for k in best[::max(1, len(best) // 4)]]}


def features(arm):
    hand_l, hand_r = J(arm, 'LeftHand'), J(arm, 'RightHand')
    return {  # name: (centre, half-size, [(view, rotate_deg, elev_deg)])
        'cuff_L': (hand_l, 0.09, [('front', 0, 0), ('back', 180, 0), ('below', 0, -80), ('above', 0, 80), ('end_on', 90, 0), ('inner', 30, -30)]),
        'cuff_R': (hand_r, 0.09, [('front', 0, 0), ('back', 180, 0), ('below', 0, -80), ('above', 0, 80), ('end_on', -90, 0), ('inner', -30, -30)]),
        'armpit_L': (J(arm, 'LeftArm') + [0.02, 0, -0.05], 0.11, [('front', 0, 0), ('back', 180, 0), ('below', 0, -80), ('side', 90, -20), ('front_low', 20, -35), ('back_low', 160, -35)]),
        'armpit_R': (J(arm, 'RightArm') + [-0.02, 0, -0.05], 0.11, [('front', 0, 0), ('back', 180, 0), ('below', 0, -80), ('side', -90, -20), ('front_low', -20, -35), ('back_low', -160, -35)]),
        'collar': (J(arm, 'Neck'), 0.10, [('front', 0, 0), ('left', 90, 0), ('right', -90, 0), ('above', 0, 70), ('front_high', 30, 35), ('front_low', 0, -25)]),
        'hood_back': (J(arm, 'Neck') + [0, 0.04, 0.02], 0.12, [('back', 180, 0), ('back_left', 135, 0), ('back_right', -135, 0), ('above', 180, 60), ('left', 90, 0), ('right', -90, 0)]),
        'waist': (J(arm, 'Hips') + [0, 0, 0.03], 0.15, [('front', 0, 0), ('back', 180, 0), ('left', 90, 0), ('right', -90, 0), ('below', 0, -45), ('front_left', 45, -10)]),
        'ankle_L': (J(arm, 'LeftFoot') + [0, 0, 0.03], 0.09, [('front', 0, 0), ('back', 180, 0), ('outside', 90, 0), ('inside', -90, 5), ('low', 45, -20), ('above', 0, 70)]),
        'ankle_R': (J(arm, 'RightFoot') + [0, 0, 0.03], 0.09, [('front', 0, 0), ('back', 180, 0), ('outside', -90, 0), ('inside', 90, 5), ('low', -45, -20), ('above', 0, 70)]),
        'chest_front': (J(arm, 'Spine1') + [0, -0.05, 0], 0.17, [('front', 0, 0), ('front_left', 35, 0), ('front_right', -35, 0), ('front_high', 0, 35), ('front_low', 0, -30), ('left', 90, 0)]),
        'chest_back': (J(arm, 'Spine1') + [0, 0.05, 0], 0.17, [('back', 180, 0), ('back_left', 145, 0), ('back_right', -145, 0), ('back_high', 180, 35), ('back_low', 180, -30), ('right', -90, 0)]),
    }


def render_defects(out, shown, defects, max_views=16):
    """Close-up of every defect cluster, seen from the direction it is visible from, with red markers."""
    for f in out.glob('defect_*.png'):
        f.unlink()
    if not defects:
        return
    pts = np.array([p for _, p, _ in defects])
    left = list(range(len(defects)))
    clusters = []
    while left and len(clusters) < max_views:
        i = left[0]
        near = [j for j in left if np.linalg.norm(pts[j] - pts[i]) < 0.06 and defects[j][0] == defects[i][0]]
        clusters.append(near)
        left = [j for j in left if j not in near]
    marks = []
    for j in range(len(defects)):
        bpy.ops.mesh.primitive_uv_sphere_add(radius=0.0025, location=pts[j])
        s = bpy.context.active_object
        mat = bpy.data.materials.get('DEFECT') or bpy.data.materials.new('DEFECT')
        mat.diffuse_color = (1, 0, 0, 1)
        s.data.materials.append(mat)
        marks.append(s)
    for k, cl in enumerate(clusters):
        c = pts[cl].mean(0)
        d = np.mean([defects[j][2] for j in cl], 0)
        d /= np.linalg.norm(d)
        rot = math.atan2(d[0], -d[1])
        el = math.asin(max(-1, min(1, d[2])))
        F.render(out / f'defect_{k:02d}_{defects[cl[0]][0]}.png', shown + marks, rotate=rot, elev=el,
                 focus=(c - 0.09, c + 0.09), res=(300, 300), clip=False)
    for s in marks:
        bpy.data.objects.remove(s, do_unlink=True)


def main():
    d = Path(sys.argv[sys.argv.index('--') + 1]).resolve()
    base = sys.argv[sys.argv.index('--') + 2]
    out = d / '08_inspect'
    out.mkdir(exist_ok=True)
    bpy.ops.wm.open_mainfile(filepath=str(d / '06_fitted' / f'{d.name}__{base}.blend'))
    arm = next(o for o in bpy.data.objects if o.type == 'ARMATURE')
    F.apply_look_pose(arm, d)  # the pose in which visible pieces are shown exactly as generated
    meshes = [o for o in bpy.data.objects if o.type == 'MESH']
    pieces = [o for o in meshes if o.name.startswith(d.name + '__')]
    body = max((o for o in meshes if o not in pieces), key=lambda o: len(o.data.vertices))
    shown = [o for o in meshes if not o.hide_render]
    # padding each piece declares (outfit.json "loft_mm": a down puffer stands off what it covers by its fill, by design)
    global LOFT_MM
    LOFT_MM = {}
    try:
        for ref in json.loads((d / '06_fitted' / 'manifest.json').read_text())['pieces']:
            of, k = ref.split(':')
            for pc in json.loads((ROOT / 'Outfits' / of / 'outfit.json').read_text())['pieces']:
                if pc['key'] == k and pc.get('loft_mm'):
                    LOFT_MM[k] = float(pc['loft_mm'])
    except Exception:
        pass

    # ---- renders
    for name, (c, half, views) in features(arm).items():
        box = (c - half, c + half)
        for view, rot, el in views:
            F.render(out / f'{name}_{view}.png', shown, rotate=math.radians(rot), elev=math.radians(el),
                     focus=box, res=(300, 300))
    print('[inspect] renders done', flush=True)

    # ---- numbers (whole meshes, masks off)
    masks = [m for o in meshes for m in o.modifiers if m.type == 'MASK']
    for m in masks:
        m.show_viewport = False
    bpy.context.view_layer.update()
    names, Wb = F.body_weights(body)
    body_co, _ = F.world_verts(body, evaluated=True)
    body_bone = M.chain_bone_of(names, Wb)

    def hidden_idx(o):
        g = None
        for nm in ('hidden_in_this_look', 'hidden_under_this_outfit', 'hide_covered_by_look', 'hide_covered_by_outfit'):
            g = g or o.vertex_groups.get(nm)
        if g is None:
            return np.zeros(len(o.data.vertices), bool)
        return np.array([any(e.group == g.index for e in v.groups) for v in o.data.vertices])
    hid_b = hidden_idx(body)
    # visible skin = a vertex of at least one face the mask keeps (the Mask modifier drops every face touching a
    # hidden vertex, so a kept vertex whose faces are all dropped is not shown either)
    body_vis = np.zeros(len(body.data.vertices), bool)
    for f in body.data.polygons:
        vi = list(f.vertices)
        if not hid_b[vi].any():
            body_vis[vi] = True
    vis_bone = np.where(body_vis, body_bone, '')  # only visible skin can poke through visibly
    body_n = np.array([(body.matrix_world.to_3x3() @ v.normal).normalized()[:] for v in body.data.vertices])
    body_bvh = F.bvh_of(*F.world_verts(body, evaluated=True))
    for m in masks:
        m.show_viewport = True
    bpy.context.view_layer.update()
    body_shown = M.tri_mesh(body)  # the body as shown (hidden skin removed): only visible skin can poke out
    for m in masks:
        m.show_viewport = False
    bpy.context.view_layer.update()
    body_full = M.tri_mesh(body)
    from mathutils.kdtree import KDTree
    _kd = KDTree(len(body_co))
    for i, q in enumerate(body_co):
        _kd.insert(Vector(q), i)
    _kd.balance()

    def body_kd_idx(pts):
        return np.array([_kd.find(Vector(q))[1] for q in pts])

    # the look as SHOWN (masks on), for "can a camera see this skin point" (first hit = the body, at the point)
    for m in masks:
        m.show_viewport = True
    bpy.context.view_layer.update()
    _allco, _allp, _off = [], [], 0
    for o in [body] + pieces:
        c, pl = F.world_verts(o, evaluated=True)
        if not len(c):
            continue  # hidden entirely
        if o is body:
            _n_body = len(pl)  # polygons 0.._n_body-1 of the shown look are the (masked) body
        _allco.append(c); _allp += [tuple(i + _off for i in q) for q in pl]; _off += len(c)
    for m in masks:
        m.show_viewport = False
    bpy.context.view_layer.update()
    _shown_bvh = F.bvh_of(np.concatenate(_allco), _allp)

    def visible_from(q):
        """A direction from which the skin point q is seen in the shown look, or None."""
        i = _kd.find(Vector(q))[1]
        for d_ in M.cone_dirs(body_n[i]):
            h = _shown_bvh.ray_cast(Vector(q) + d_ * 1.5, -d_, 1.51)
            # the first surface the camera meets must be the shown SKIN right there - not a garment lip over it
            if h[0] is not None and (h[0] - Vector(q)).length < 0.004 and h[2] < _n_body:
                return np.array(d_)
        return None
    _bs_co, _bs_tri = body_shown
    _exposure = {}  # poke point -> (exposed mm2, direction it is seen best from)
    _bs_cen = _bs_co[_bs_tri].mean(1)

    def exposed_mm2(q, radius=0.004):
        """Skin area (mm2) around poke point q that a camera actually sees, from the best direction in the cone
        around its normal: the shown skin within `radius` is sampled densely and ray-tested. A single vertex in a
        seam crevice exposes a speck; skin through a garment exposes a patch."""
        q = np.asarray(q, float)
        near = np.nonzero(np.linalg.norm(_bs_cen - q, axis=1) < radius + 0.02)[0]
        if not len(near):
            print(f'[inspect] exposure at {np.round(q, 3)}: no shown skin near', flush=True)
            return 0.0
        k_ = 40  # ~0.5 mm spacing on the ~2 cm Genies body faces
        uv = np.array([(a / k_, b / k_) for a in range(k_ + 1) for b in range(k_ + 1) if a + b <= k_], float)
        bary = np.c_[1 - uv.sum(1), uv]
        smp = np.einsum('kj,tjc->tkc', bary, _bs_co[_bs_tri[near]]).reshape(-1, 3)
        smp = smp[np.linalg.norm(smp - q, axis=1) < radius]
        if not len(smp):
            return 0.0
        i = _kd.find(Vector(q))[1]
        best, best_d = 0, None
        for d_ in M.cone_dirs(body_n[i]):
            seen_ = 0
            for sp in smp:
                h = _shown_bvh.ray_cast(Vector(sp) + d_ * 1.5, -d_, 1.51)
                if h[0] is not None and (h[0] - Vector(sp)).length < 0.0005 and h[2] < _n_body:
                    seen_ += 1
            if seen_ > best:
                best, best_d = seen_, np.array(d_)
        area = best / len(smp) * np.pi * (radius * 1000) ** 2
        _exposure[tuple(np.round(q, 5))] = (round(area, 1), best_d)
        print(f'[inspect] exposure at {np.round(q, 3)}: {area:.1f} mm2 ({best}/{len(smp)} samples), best dir '
              f'{None if best_d is None else np.round(best_d, 2)}', flush=True)
        return area
    slot_of = {o: o.name.split('__')[1] for o in pieces}
    bvh = {o: F.bvh_of(*F.world_verts(o, evaluated=True)) for o in pieces}
    hid = {o: hidden_idx(o) for o in pieces}
    hidden_entirely = {o for o in pieces if hid[o].mean() > 0.99}
    results, fails = {}, []
    poke_defects = []
    layer_defects = []
    for o in pieces:
        key = o.name.split('__')[-1]
        slot = slot_of[o]
        r = {'slot': slot, 'hidden_entirely': o in hidden_entirely}
        # body-made pieces (shell_garment / legging_shell: _hem_band / _shell) are the skin itself offset a few mm, so
        # they cannot sit shifted on a limb and their openings are the limb's own outline; skin-tight ones always touch,
        # and the bone is not in the middle of the flesh - their spacing is judged by the layer shells instead
        body_made = any(at.name.lower() in ('_shell', '_hem_band') for at in o.data.attributes)
        for limb in M.SLOT_LIMBS.get(slot, []):
            gco_o, gtri_o = M.tri_mesh(o)
            ops = {}
            for si, (bone, child) in enumerate(M.LIMB_CHAINS[limb]):
                a_, b_ = np.array(M.joint(arm, bone)), np.array(M.joint(arm, child))
                secs = [x for x in M.limb_sections(gco_o, gtri_o, M.limb_skin(body_co, body_bone, bone, child), a_, b_,
                                                   SECTION_TS[si]) if 'in_material' in x]
                if not secs or not any(x['cavity'] or x['in_material'] > 0 for x in secs):
                    continue  # no tube along this bone
                # past the last slice that still wraps the limb is beyond the sleeve's hem (a short sleeve)
                wraps = [k for k, x in enumerate(secs) if x.get('enclosed', 0) >= 0.5]
                if not wraps:
                    continue
                secs = secs[:wraps[-1] + 1]
                ops[bone] = secs
                if os.environ.get('INSPECT_DEBUG_SECTIONS'):
                    print('[sec]', key, bone, [(round(x['t'], 2), 'H' if x['cavity'] else 'S', round(x['in_material'], 2),
                                              round(x.get('enclosed', 0), 2), round((x['offset'] or 0) * 100, 1),
                                              round(x.get('touch', 0), 2)) for x in secs], flush=True)
                # the first hollow slice right after a solid one is the transition inside the sleeve (cannot be seen)
                cav = [x for i, x in enumerate(secs) if x['cavity'] and not (i and not secs[i - 1]['cavity'])]
                solid = [x for x in secs if not x['cavity']]
                # a solid sleeve must hold the limb all the way to the hem: the last 2 slices with garment may be the hem
                body_solid = solid[:-2] if si == len(M.LIMB_CHAINS[limb]) - 1 else solid
                # past a hollow sleeve's last hollow slice is its hem (a short sleeve ends on the UPPER arm; a slanted
                # hem is open on one side): not a solid sleeve the limb must stay inside
                # ... and before its first hollow slice is the armhole, where the sleeve opens into the body
                cav_k = [k for k, x in enumerate(secs) if x['cavity']]
                if cav_k:
                    body_solid = [x for x in body_solid if cav_k[0] < secs.index(x) < cav_k[-1]]
                lining = max([x['in_material'] for x in cav], default=0.0)
                hole_off = max([x['offset'] for x in cav], default=0.0) * 100
                # off-centre only matters where the limb is not clear of the rim (a wrist low in a roomy cuff is fine)
                rim_touch = max([x.get('touch', 0.0) for x in cav], default=0.0)
                outside = 1 - min([x['in_material'] for x in body_solid], default=1.0)
                r[f'{bone}_sections'] = {'hollow': len(cav), 'solid': len(solid), 'limb_in_lining_max': round(lining, 2),
                                         'hole_offset_cm_max': round(hole_off, 2), 'rim_touch_max': round(rim_touch, 2), 'limb_outside_solid_max': round(outside, 2)}
                if not r['hidden_entirely']:
                    if lining > LIMITS['limb_in_lining']:
                        fails.append(f'{key}: {bone} runs through the sleeve lining ({lining:.0%} of the limb outline inside it)')
                    # per slice: off-centre AND resting on the rim in the SAME cross-section (a wide armhole where the
                    # arm sits off-centre and a cuff it lightly touches are not one defect)
                    # only where the sleeve wraps the limb all round; at a slanted, partly open hem the "hole centre"
                    # slides to the open side - the opening itself is judged by the threading check
                    bad_off = [] if body_made else [
                        x['offset'] * 100 for x in cav if x.get('enclosed', 1) >= 0.9
                        and x['offset'] * 100 > LIMITS['end_offset_cm'] and x.get('touch', 0) > LIMITS['rim_touch']]
                    if bad_off:
                        fails.append(f'{key}: {bone} off-centre in the sleeve hole by {max(bad_off):.1f} cm (touching its rim)')
                    if outside > LIMITS['limb_outside_solid']:
                        fails.append(f'{key}: {bone} leaves the solid sleeve/leg before its hem ({outside:.0%} of the outline outside)')
            # threading: the limb must come out through the garment's OPENING (judged from the garment's own end)
            gco_t, _ = F.world_verts(o, evaluated=True)
            for bone, child in M.LIMB_CHAINS[limb]:
                th = M.thread_check(bvh[o], gco_t, M.limb_skin(body_co, body_bone, bone, child),
                                    M.joint(arm, bone), M.joint(arm, child))
                if th is None:
                    continue
                r[f'{bone}_thread'] = th
                misses_only = th['wall_exit_cm_before_opening'] is None   # the circle-round-the-bone opening test
                if not r['hidden_entirely'] and not th['threaded'] and not (body_made and misses_only):
                    how = (f"leaves through the wall {th['wall_exit_cm_before_opening']:.0f} cm before the opening"
                           if th['wall_exit_cm_before_opening'] is not None else
                           f"misses the opening (limb {th['offset_cm']:.1f} cm off its centre; opening radius "
                           f"{th['ring_r_cm']:.1f} cm, limb {th['limb_r_cm']:.1f} cm)")
                    fails.append(f'{key}: {bone} does not come out through its opening - it {how}')
                # a sleeve opening far wider than the wrist reads as a gaping bell and shows the arm deep inside it
                # (the MONCHILL puffer, 3.7-4.5 cm of room; the accepted hoodie leaves 2.0 cm)
                room = th['ring_r_cm'] - th['limb_r_cm']
                if (not r['hidden_entirely'] and not body_made and bone.endswith('ForeArm') and th['threaded']
                        and room > LIMITS['sleeve_opening_room_cm']):
                    fails.append(f'{key}: {bone} sleeve opening too wide - {room:.1f} cm of room round the wrist '
                                 f'(limit {LIMITS["sleeve_opening_room_cm"]:.1f}; opening radius {th["ring_r_cm"]:.1f} cm)')
                # a hoop / flap standing past the opening (generated pieces; body-made ones end on the skin's outline)
                if body_made:
                    continue
                fl = flap_past_opening(gco_o, gtri_o, M.limb_skin(body_co, body_bone, bone, child),
                                       M.joint(arm, bone), M.joint(arm, child), th['end_t'])
                if fl is None:
                    continue
                spots = fl.pop('where')
                r[f'{bone}_flap'] = fl
                if r['hidden_entirely']:
                    continue
                if fl['sectors_measured'] < MIN_SAMPLES:
                    fails.append(f'{key}: {bone} opening flap check had too little to measure ({fl["sectors_measured"]} '
                                 f'of 72 directions round the opening) - fix the check, do not trust a pass')
                elif fl['arc_deg'] >= LIMITS['flap_arc_deg']:
                    fails.append(f'{key}: thin flap past the {child} opening, {fl["flap_cm"]:.1f} cm '
                                 f'(detached from the {bone} cuff/hem over {fl["arc_deg"]} deg of its rim) - regenerate')
                    poke_defects += [(f'flap_{key}', p, d_) for p, d_ in spots]
            pk, ck, where = M.limb_poke(arm, body_co, vis_bone, bvh[o], limb, all_bone=body_bone, where=True)
            # a poke only counts if a camera can SEE that skin (armpit points next to the torso fool the ring test)
            seen_dirs = [visible_from(q) for q in where]
            keep_ = [dv is not None and exposed_mm2(q) >= LIMITS['exposed_mm2'] for q, dv in zip(where, seen_dirs)]
            seen_dirs = [dv for dv, k_ in zip(seen_dirs, keep_) if k_]
            where = [q for q, k_ in zip(where, keep_) if k_]
            poke_defects += [(f'limbpoke_{key}', q, dv) for q, dv in zip(where, [d_ for d_ in seen_dirs if d_ is not None])]
            pk = len(where)
            r[f'{limb}_skin_outside'] = f'{pk}/{ck}'
            n_skin = {b: int((body_bone == b).sum()) for b, _ in M.LIMB_CHAINS[limb]}
            if not r['hidden_entirely'] and min(n_skin.values()) < MIN_SAMPLES:
                fails.append(f'{key}: {limb} check had too little to measure (skin points per bone {n_skin}, '
                             f'segments measured {list(ops)}) - fix the check, do not trust a pass')
            if pk > LIMITS['limb_skin_outside'] and not r['hidden_entirely']:
                fails.append(f'{key}: {pk} of {ck} {limb} skin points poke through')
        if not r['hidden_entirely'] and slot in M.TORSO_SLOTS:
            # waistband / hem / side seams: horizontal sections through the torso part of the garment
            gco_t, gtri_t = M.tri_mesh(o)
            axis_xy = np.array(M.joint(arm, 'Hips'))[:2]
            tor = gco_t[(np.linalg.norm(gco_t[:, :2] - axis_xy, axis=1) < 0.25) & (gco_t[:, 2] > 0.6)]
            # the band's LOWEST top edge and the hem's HIGHEST bottom edge around the body (edges are not level)
            angb = ((np.arctan2(tor[:, 1] - axis_xy[1], tor[:, 0] - axis_xy[0]) + np.pi) / (2 * np.pi) * 24).astype(int) % 24
            tops = [tor[angb == b_, 2].max() for b_ in range(24) if (angb == b_).sum() > 20]
            bots = [tor[angb == b_, 2].min() for b_ in range(24) if (angb == b_).sum() > 20]
            zmin, zmax = float(max(bots)), float(min(tops))
            pelvis = float(np.array(M.joint(arm, 'Hips'))[2]) - 0.03  # below this the body splits into legs
            chest = float(np.array(M.joint(arm, 'Spine2'))[2])
            if slot == 'bottom':
                z_lo, z_hi = max(zmin + 0.01, pelvis), zmax - 0.008
            else:
                z_lo, z_hi = max(zmin + 0.01, pelvis), min(zmax - 0.01, chest)
            secs = M.torso_sections(gco_t, gtri_t, body_shown[0], body_shown[1], z_lo, z_hi, axis_xy)
            worst = max(secs, key=lambda x: x[1]) if secs else None
            r['torso_sections'] = {'slices': len(secs), 'z_range_m': [round(z_lo, 3), round(z_hi, 3)],
                                   'worst_outside': round(worst[1], 3) if worst else None,
                                   'worst_z_m': round(worst[0], 3) if worst else None}
            full = M.torso_sections(gco_t, gtri_t, body_full[0], body_full[1], z_lo, z_hi, axis_xy)
            if len(full) < 3:
                fails.append(f'{key}: torso check had too little to measure ({len(full)} slices) - fix the check')
            elif len(secs) < len(full):
                r['torso_sections']['covered_slices'] = len(full) - len(secs)  # no visible skin there: covered
            if secs and worst[1] > LIMITS['torso_outside']:
                bad = [x for x in secs if x[1] > LIMITS['torso_outside']]
                fails.append(f'{key}: body pokes out of it at the waist/torso ({worst[1]:.0%} of the skin outline '
                             f'outside at z {worst[0]:.2f} m; {len(bad)} of {len(secs)} slices)')
                for z_, sh, _ in bad[:6]:
                    poke_defects.append((f'torso_{key}', np.array([axis_xy[0], axis_xy[1] - 0.12, z_]), np.array([0, -1.0, 0])))
        if not r['hidden_entirely'] and slot in NL.SLOTS:
            gco_n, _ = F.world_verts(o, evaluated=True)
            if gco_n[:, 2].max() < float(J(arm, 'Neck')[2]) + 0.09:  # a neckline (a hood rises to head height)
                r['neckline'] = NL.collar_gaps(gco_n, body_bvh)
                # reported, not failed: the customizer settles every top's collar band to ~5 mm off the neck
                # (user-approved exception, customizer v38), so a looser generated neckline is fine
                r['neckline_warnings'] = NL.check(r['neckline'])
        if not r['hidden_entirely'] and slot not in ('hair', 'headwear', 'footwear'):
            pk = [i for i in M.skin_poke(body_co[body_vis], body_n[body_vis], bvh[o])  # only skin a camera can see,
                  if visible_from(body_co[body_vis][i]) is not None              # exposed as more than a speck
                  and exposed_mm2(body_co[body_vis][i]) >= LIMITS['exposed_mm2']]
            if pk:
                pts = body_co[body_vis][pk]
                regs = {}
                for b in body_bone[body_vis][pk]:
                    regs[b or 'torso/head'] = regs.get(b or 'torso/head', 0) + 1
                r['skin_poke_where'] = {'regions': regs, 'z_range_m': [round(float(pts[:, 2].min()), 3), round(float(pts[:, 2].max()), 3)]}
            r['skin_poke_verts'] = len(pk)
            poke_defects += [(f'poke_{key}', body_co[body_vis][i],
                              _exposure.get(tuple(np.round(body_co[body_vis][i], 5)), (0, None))[1]
                              if _exposure.get(tuple(np.round(body_co[body_vis][i], 5)), (0, None))[1] is not None
                              else body_n[body_vis][i]) for i in pk]
            r['skin_poke_exposed_mm2'] = [_exposure.get(tuple(np.round(body_co[body_vis][i], 5)), (0, None))[0] for i in pk]
            if len(pk) > LIMITS['skin_poke_verts']:
                fails.append(f'{key}: {len(pk)} body vertices poke through it')
        if not r['hidden_entirely']:
            co, _ = F.world_verts(o, evaluated=True)
            # layer order as SEEN: from 8 directions around (and 2 from above/below), each camera-facing visible point
            # of this piece casts a short ray toward the camera; if a LOWER layer's visible surface lies right on top
            # of it (within 12 mm), the lower layer pokes through (e.g. a hoodie through a strap that should be on top).
            ev = o.evaluated_get(bpy.context.evaluated_depsgraph_get()).to_mesh()
            vn = np.array([(o.matrix_world.to_3x3() @ v.normal).normalized()[:] for v in ev.vertices])
            o.evaluated_get(bpy.context.evaluated_depsgraph_get()).to_mesh_clear()
            # outer surface only: a garment's inner wall (the inside of a hem or cuff, facing the body) is SUPPOSED to
            # have the lower layer in front of it
            out_n = body_n[body_kd_idx(co)]
            outer = np.einsum('ij,ij->i', vn, out_n) > 0.3
            idx = np.nonzero(~hid[o] & outer)[0][::3]
            dirs = [np.array([math.sin(a), -math.cos(a), 0.0]) for a in np.radians(np.arange(0, 360, 45))]
            dirs += [np.array([0, -0.5, 0.87]), np.array([0, -0.5, -0.87])]
            lowers = [o2 for o2 in pieces if o2 is not o and o2 not in hidden_entirely
                      and SLOTS[slot_of[o2]]['layer'] < SLOTS[slot]['layer'] and slot_of[o2] not in ('hair', 'headwear')
                      and slot not in ('hair', 'headwear')]
            for o2 in lowers:
                vco, vpolys = F.world_verts(o2, evaluated=True)  # evaluated with its mask = only its visible part
                for m in o2.modifiers:
                    if m.type == 'MASK':
                        m.show_viewport = True
                bpy.context.view_layer.update()
                vco, vpolys = F.world_verts(o2, evaluated=True)
                for m in o2.modifiers:
                    if m.type == 'MASK':
                        m.show_viewport = False
                bpy.context.view_layer.update()
                if not len(vpolys):
                    continue
                vis_bvh = F.bvh_of(vco, vpolys)
                facing = blocked = 0
                for d in dirs:
                    dv = Vector(d)
                    for i in idx:
                        if np.dot(vn[i], d) <= 0.57:  # within 55 deg of the surface normal, as every other check
                            continue
                        facing += 1
                        # only a lower surface lying right on top of this point (poking through it) - not a
                        # different part of the body or garment further along the line of sight
                        if vis_bvh.ray_cast(Vector(co[i]) + dv * 1e-4, dv, 0.012)[0] is not None:
                            blocked += 1
                            if blocked % 5 == 1:
                                layer_defects.append((f'layer_{key}_under_{o2.name.split("__")[-1]}', co[i], d))
                pct = round(100 * blocked / max(facing, 1), 2)
                r[f'covered_by_{o2.name.split("__")[-1]}_pct'] = pct
                if pct > LIMITS['layer_clip_pct']:
                    fails.append(f'{key}: {pct}% of its visible surface is covered by {o2.name.split("__")[-1]} (layer order wrong)')
        results[key] = r
        print(f'[inspect] {key}: {r}', flush=True)
    # ---- layer spacing (RPG shells): body < bottoms < tops < outerwear, each with a gap where they overlap
    dg = bpy.context.evaluated_depsgraph_get()
    ev = body.evaluated_get(dg).to_mesh()
    R3 = body.matrix_world.to_3x3()
    pc = np.array([(body.matrix_world @ v.co)[:] for v in ev.vertices])
    pn = np.array([(R3 @ v.normal).normalized()[:] for v in ev.vertices])
    body.evaluated_get(dg).to_mesh_clear()
    head_z = float(np.array(M.joint(arm, 'Neck'))[2])
    hand = np.array([str(b).startswith(('LeftHand', 'RightHand')) for b in body_bone])
    samp = np.nonzero((pc[:, 2] < head_z) & ~hand)[0][::2]
    garm = sorted([o for o in pieces if o not in hidden_entirely and slot_of[o] not in ('hair', 'headwear', 'accessory')],
                  key=lambda o: SLOTS[slot_of[o]]['layer'])
    outer = {o: M.outer_heights(bvh[o], pc[samp], pn[samp], reach=0.15) for o in garm}
    spacing = {}
    for i_, lo in enumerate(garm):
        lk = lo.name.split('__')[-1]
        cov_lo = ~np.isnan(outer[lo])
        tight = cov_lo & (outer[lo] < LIMITS['skin_gap_mm'] / 1000)
        med_body = float(np.nanmedian(outer[lo]) * 1000) if cov_lo.any() else None
        spacing[f'{lk}|body'] = {'overlap_pts': int(cov_lo.sum()), 'too_close_share': round(float(tight.mean() if cov_lo.any() else 0), 3),
                                 'median_gap_mm': round(med_body, 1) if med_body is not None else None}
        cap = BODY_GAP_MAX_MM.get(slot_of[lo])
        if cap and med_body is not None and med_body > cap:
            fails.append(f'{lk}: floats off the body (median {med_body:.0f} mm, at most {cap} mm for a {slot_of[lo]})')
        for up in garm[i_ + 1:]:
            if SLOTS[slot_of[up]]['layer'] <= SLOTS[slot_of[lo]]['layer']:
                continue
            uk = up.name.split('__')[-1]
            both = cov_lo & ~np.isnan(outer[up])
            if both.sum() < 20:
                continue
            gap = outer[up][both] - outer[lo][both]
            bad = gap < LIMITS['layer_gap_mm'] / 1000
            share = float(bad.mean())
            spacing[f'{uk}|{lk}'] = {'overlap_pts': int(both.sum()), 'too_close_share': round(share, 3),
                                     'median_gap_mm': round(float(np.median(gap) * 1000), 1)}
            # insulated pieces (a down puffer) declare their padding: "loft_mm" in their outfit.json, added to the limit
            drape = DRAPE_MAX_MM.get(slot_of[up], LIMITS['drape_max_mm']) + LOFT_MM.get(uk, 0)
            if np.median(gap) * 1000 > drape:
                fails.append(f'{uk}: floats over {lk} (median {np.median(gap) * 1000:.0f} mm where they overlap; '
                             f'a {slot_of[up]} rests at most {drape} mm outside the one beneath)')
            if share > LIMITS['layer_spacing_share']:
                fails.append(f'{uk}: layer spacing over {lk} too small at {share:.0%} of their overlap '
                             f'(needs >= {LIMITS["layer_gap_mm"]} mm; median {np.median(gap) * 1000:.1f} mm)')
                where = np.nonzero(both)[0][bad]
                for w in where[::max(1, len(where) // 12)][:12]:
                    q = samp[w]
                    layer_defects.append((f'spacing_{uk}_over_{lk}', pc[q] + pn[q] * outer[up][w], pn[q]))
    rep_spacing = spacing
    print(f'[inspect] layer spacing: {spacing}', flush=True)
    # ---- layer shells: each piece against the STANDARD envelope of its layer (any bottoms under any top)
    # GUIDANCE, not a failure: percentiles of two pieces sit in different places around the body, so a standard tight
    # enough to guarantee every pair rejects good pairs. The guarantee is the combination test (gate.py --combo: the
    # exact pointwise spacing / visible-clip checks on every pair actually worn together); shells steer generation.
    shell_rep, _ = S.look_report(d)
    warnings = []
    for k, sr in shell_rep.items():
        if not any(o.name.endswith(k) and o in hidden_entirely for o in pieces):
            warnings += [f'{k}: {m}' for m in sr['fails']]
    print(f'[inspect] shells: {shell_rep}', flush=True)
    for w in warnings:
        print(f'[inspect] shell warning: {w}', flush=True)

    # ---- mask overreach: every face a mask removes must be invisible in the unmasked look
    worn = [body] + [o for o in pieces if o not in hidden_entirely]
    allco, allp, off = [], [], 0
    poly_range = {}
    for o in worn:
        c, pl = F.world_verts(o, evaluated=True)  # masks are off here
        poly_range[o] = (len(allp), len(allp) + len(pl))
        allco.append(c); allp += [tuple(i + off for i in q) for q in pl]; off += len(c)
    nude = F.bvh_of(np.concatenate(allco), allp)
    for m in masks:
        m.show_viewport = True
    bpy.context.view_layer.update()
    allco, allp, off = [], [], 0
    for o in worn:
        c, pl = F.world_verts(o, evaluated=True)  # as shown: masks on
        allco.append(c); allp += [tuple(i + off for i in q) for q in pl]; off += len(c)
    shown_bvh = F.bvh_of(np.concatenate(allco), allp)
    for m in masks:
        m.show_viewport = False
    bpy.context.view_layer.update()
    defects = []
    for o in worn:
        h = hidden_idx(o)
        if not h.any():
            continue
        co_o, _ = F.world_verts(o, evaluated=True)
        R3 = o.matrix_world.to_3x3()
        samples, normals = [], []
        for poly in o.data.polygons:
            vi = list(poly.vertices)
            if not h[vi].any():
                continue
            c = co_o[vi].mean(0)
            n = np.array((R3 @ poly.normal).normalized()[:])
            samples.append(c); normals.append(n)
            if o is body:  # coarse body faces: also right out at each corner and along each edge (a slit can be
                # one edge wide, and a face tip just past a hem is a notch a few mm across)
                for v in vi:
                    samples.append(c + 0.95 * (co_o[v] - c)); normals.append(n)
                for j in range(len(vi)):
                    samples.append(c + 0.95 * ((co_o[vi[j]] + co_o[vi[(j + 1) % len(vi)]]) / 2 - c)); normals.append(n)
        found = M.overreach(np.array(samples), np.array(normals), nude, shown_bvh, body_bvh=body_bvh, own=poly_range[o])
        name = 'body' if o is body else o.name.split('__')[-1]
        r = results.setdefault(name, {})
        r['mask_overreach_pts'] = len(found)
        if found:
            pts = np.array([p for p, _ in found])
            r['mask_overreach_z_m'] = [round(float(pts[:, 2].min()), 3), round(float(pts[:, 2].max()), 3)]
            fails.append(f'{name}: mask removes surface that can be seen at {len(found)} points '
                         f'(z {r["mask_overreach_z_m"]}) - see-through holes')
            defects += [(name, p, d) for p, d in found]
        print(f'[inspect] overreach {name}: {len(found)} of {len(samples)} masked samples visible', flush=True)
    for m in masks:
        m.show_viewport = True
    bpy.context.view_layer.update()
    render_defects(out, shown, defects + poke_defects + layer_defects)
    rep = {'limits': LIMITS, 'pass': not fails, 'fails': fails, 'pieces': results, 'layer_spacing': rep_spacing, 'shells': shell_rep,
           'warnings': warnings}
    (out / 'inspect.json').write_text(json.dumps(rep, indent=2), encoding='utf-8')
    print('[inspect] PASS' if not fails else '[inspect] FAIL\n  ' + '\n  '.join(fails), flush=True)


if __name__ == '__main__':
    main()
