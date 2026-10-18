"""Fitted garments made FROM THE BODY (Bitmoji-style): the base's own skin surface, cut at the neckline / sleeve / hem
lines, smoothed into clean fabric panels and offset a few mm out. Fit is exact by construction (0 mm in the rest
pose, the body's own skin weights, so it moves exactly with the body) and the design lives in the texture.

The piece is written like a step-6 output (06_fitted/<outfit>__<key>.glb + manifest.json), so equip, inspect_look and
pipeline/web/export_web.py treat it like any other piece. Its fit pose is the rest pose (no rig fitting needed).

Run: blender -b --factory-startup -P pipeline/tpose/shell_garment.py -- --base Xander --out Outfits/template-tee
         [--key template_tee] [--neck crew|scoop] [--neck-front-cm 1.5] [--collar-ease-mm 12]
         [--sleeve 0.45] [--hem-cm -2] [--offset-mm 4] [--thick-mm 1.5] [--smooth 12] [--color 0.93,0.93,0.92]
         [--graphic path.png] [--graphic-width-cm 14] [--kit <texture kit folder>] [--tex 2048]
  --neck-front-cm                 how much lower the neckline's front sits than its back (before the ring is smoothed;
                                  1.5 gives a ~2-2.5 cm dip). The ring hugs the neck, symmetric, capped at the sides
  --collar-ease-mm                how far the collar stands off the neck
  --sleeve                        sleeve length as a fraction of the upper arm (0 = sleeveless/tank, 1 = elbow)
  --hem-cm                        hem height relative to the Hips joint (negative = below it; crop tops are positive)
"""
import bpy, bmesh, sys, json, argparse, math
from pathlib import Path
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'pipeline'))
sys.path.insert(0, str(ROOT / 'pipeline' / 'tpose'))
import fit_outfit as F  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument('--base', default='Xander')
ap.add_argument('--out', required=True)
ap.add_argument('--key', default='template_tee')
ap.add_argument('--layer', type=int, default=2, help='2 = over the bottoms (default); 0 = tucked under them')
ap.add_argument('--neck', default='crew', choices=['crew', 'scoop'])
ap.add_argument('--neck-front-cm', type=float, default=0.35)
ap.add_argument('--neck-back-cm', type=float, default=0.5)
ap.add_argument('--neck-width-cm', type=float, default=5.2)
ap.add_argument('--sleeve', type=float, default=0.45)
ap.add_argument('--hem-cm', type=float, default=-2.0)
ap.add_argument('--offset-mm', type=float, default=7.0)
ap.add_argument('--sleeve-offset-mm', type=float, default=8.0, help='ease around the arm (sleeves sit loosely)')
ap.add_argument('--thick-mm', type=float, default=3.0)
ap.add_argument('--smooth', type=int, default=12)
ap.add_argument('--color', default='0.93,0.93,0.92')
ap.add_argument('--graphic', default='')
ap.add_argument('--graphic-width-cm', type=float, default=14.0)
ap.add_argument('--tex', type=int, default=2048, help='texture width in px (height keeps the pattern layout aspect)')
ap.add_argument('--kit', default='', help='texture kit folder (tee_kit.py): spec.json, pattern / normal / roughness tiles, graphics')
ap.add_argument('--drape', type=float, default=1.0, help='0 = follows the waist in, 1 = falls straight from the chest')
ap.add_argument('--hem-flare-mm', type=float, default=6.0)
ap.add_argument('--hem-band-cm', type=float, default=4.0, help='height of the hem band the customizer wraps over bottoms')
ap.add_argument('--sleeve-flare-mm', type=float, default=4.0)
ap.add_argument('--back-ease-mm', type=float, default=12.0, help='extra room over the upper back (not stuck to it)')
ap.add_argument('--collar-ease-mm', type=float, default=10.0, help='the neckline sits this far off the neck')
ap.add_argument('--edge-smooth', type=int, default=25, help='smoothing passes along the hem / collar / sleeve edges')
a = ap.parse_args(sys.argv[sys.argv.index('--') + 1:])

out_dir = Path(a.out).resolve()
fitted = out_dir / '06_fitted'
fitted.mkdir(parents=True, exist_ok=True)
lm = json.loads((ROOT / 'Bases' / f'{a.base}.json').read_text())['landmarks']
J = {k: np.array(v) for k, v in lm.items()}

arm, body, _ = F.load_base(a.base)
for pb in arm.pose.bones:
    pb.matrix_basis.identity()
bpy.context.view_layer.update()

# ---- 1. a copy of the body surface (rest pose), with its skin weights, without blend shapes / modifiers
shell = body.copy()
shell.data = body.data.copy()
shell.name = shell.data.name = a.key
bpy.context.scene.collection.objects.link(shell)
if shell.data.shape_keys:
    shell.shape_key_clear()
for m in list(shell.modifiers):
    shell.modifiers.remove(m)
shell.parent = None
shell.matrix_world = body.matrix_world.copy()
shell.data.transform(shell.matrix_world)
shell.matrix_world.identity()
for g in list(shell.vertex_groups):  # keep only bone weights (masks etc. are not skinning)
    if g.name not in arm.data.bones:
        shell.vertex_groups.remove(g)

hips_z = J['Hips'][2]
hem_z = hips_z + a.hem_cm / 100
neck_z = J['Neck'][2]
sl = {}
for side in ('Left', 'Right'):
    p0, p1 = J[f'{side}Arm'], J[f'{side}ForeArm']
    d = (p1 - p0) / np.linalg.norm(p1 - p0)
    sl[side] = (p0 + max(a.sleeve, 0.0) * (p1 - p0), d)

bm = bmesh.new()
bm.from_mesh(shell.data)
# coarse keep-box first (head, hands, legs out) so the subdivision only works on the garment region
reach_x = max(abs(sl['Left'][0][0]), abs(sl['Right'][0][0])) + 0.03 if a.sleeve > 0 else 0.2
drop = [f for f in bm.faces if not (hem_z - 0.03 < f.calc_center_median().z < neck_z + 0.04
                                    and abs(f.calc_center_median().x) < reach_x)]
bmesh.ops.delete(bm, geom=drop, context='FACES')
# ---- 2. fine SMOOTH subdivision (Genies body faces are ~2 cm). Catmull-Clark, not linear: linear cuts keep the
# body's coarse edge loops as faint lengthwise ridges, which read as stripes along the sleeves and chest
bm.to_mesh(shell.data)
bm.free()
ss = shell.modifiers.new('smooth_subdiv', 'SUBSURF')
ss.levels = ss.render_levels = 2
bpy.context.view_layer.objects.active = shell
shell.select_set(True)
bpy.ops.object.modifier_apply(modifier='smooth_subdiv')
bm = bmesh.new()
bm.from_mesh(shell.data)
bmesh.ops.triangulate(bm, faces=bm.faces[:])


def bisect(co, no):
    geom = bm.verts[:] + bm.edges[:] + bm.faces[:]
    bmesh.ops.bisect_plane(bm, geom=geom, plane_co=Vector(co), plane_no=Vector(no), clear_outer=True)


# ---- 3. cut lines: hem (straight plane), sleeves (planes across the arm), neckline (a curve around the neck)
bisect((0, 0, hem_z), (0, 0, -1))
for side, (p, d) in sl.items():
    if a.sleeve > 0:
        bisect(p, d)  # keep the shoulder side of the sleeve end
    else:  # sleeveless: an armhole - only the arm and the shoulder cap above the armpit go (the torso sides stay)
        pass
cy = (J['Neck'][1] + J['Spine2'][1]) / 2


# neckline: a true crew neck, as an explicit ring around the neck axis. For each direction the ring sits at a target
# height (the back just above the Neck joint, the front a.neck_front_cm lower, blended smoothly) and at the neck's own
# radius there (ray cast from the axis). The sides, where the neck runs into steep shoulder slopes, are capped to the
# front/back radius, so the opening is a near-circle that hugs the neck instead of sliding out over the shoulders.
# Removed: the shell inside that radius and above that height. Mirrored left/right, so exactly symmetric.
_bco, _bp = F.world_verts(body, evaluated=True)
_bb = F.bvh_of(_bco, _bp)
scoop = a.neck == 'scoop'
z_back = neck_z + 0.002 - (0.02 if scoop else 0.0)  # the smoothing below lifts the back ~1 cm
z_front = z_back - (a.neck_front_cm if not scoop else 2.2 * a.neck_front_cm) / 100


def _ray_r(cx, cy_, z, t):  # the neck skin's horizontal distance from (cx, cy_) at height z, direction t (0 = front)
    d = Vector((math.sin(t), -math.cos(t), 0))
    h = _bb.ray_cast(Vector((cx, cy_, z)), d, 0.3)
    return h[3] if h[0] is not None else None


ncx = 0.0  # centred left-right by design; front-back: midway between the neck's front and back skin at the ring
ncy = J['Neck'][1]
for _ in range(3):
    f_, b_ = _ray_r(0, ncy, z_front, 0.0), _ray_r(0, ncy, z_back, math.pi)
    ncy = ncy + ((b_ or 0) - (f_ or 0)) / 2
NT = np.linspace(-np.pi, np.pi, 72, endpoint=False)  # 0 = front, +-pi = back, +pi/2 = +x
NW = (1 - np.cos(NT)) / 2
NZ = z_front * (1 - NW) + z_back * NW
r_cap = (_ray_r(0, ncy, z_front, 0.0) + _ray_r(0, ncy, z_back, math.pi)) / 2


def _rise(t, z0):  # the lowest height >= z0 at which the neck in direction t is within the cap radius
    z = z0
    while z < neck_z + 0.07 and (_ray_r(0, ncy, z, t) or 0) > r_cap:
        z += 0.002
    return z


# the ring's height: the target height, raised where the shoulders slope out (sides), then smoothed around the neck
# (circular Gaussian, ~20 deg) so the line rises gently from the back / front to the shoulders - no notch
NH = np.array([_rise(t, z) for t, z in zip(NT, NZ)])
NH = (NH + NH[(72 - np.arange(72)) % 72]) / 2  # mirror x -> -x (angle -t)
_k = np.exp(-0.5 * (np.arange(-12, 13) / 4.0) ** 2)
NH = np.convolve(np.r_[NH[-12:], NH, NH[:12]], _k / _k.sum(), mode='valid')
NZ = np.maximum(NZ, NH)
NR = np.array([min(_ray_r(0, ncy, z, t) or r_cap, r_cap + 0.003) for t, z in zip(NT, NZ)])
NR = (NR + NR[(72 - np.arange(72)) % 72]) / 2
print(f'NECKLINE centre y {ncy:.3f}  radius front {NR[36]*1000:.0f} side {NR[54]*1000:.0f} back {NR[0]*1000:.0f} mm  '
      f'height front {(NZ[36]-neck_z)*100:+.1f} side {(NZ[54]-neck_z)*100:+.1f} back {(NZ[0]-neck_z)*100:+.1f} cm', flush=True)


def _nt(co):
    return math.atan2(co.x - ncx, -(co.y - ncy))


def neck_reach(co):  # how far out from the neck axis the collar band reaches (cut radius + the collar ease + 4 mm)
    return float(np.interp(_nt(co), NT, NR, period=2 * np.pi)) + a.collar_ease_mm / 1000 + 0.004


def neck_cut_z(co):
    return float(np.interp(_nt(co), NT, NZ, period=2 * np.pi))


def in_neck(co):
    return (math.hypot(co.x - ncx, co.y - ncy) < float(np.interp(_nt(co), NT, NR, period=2 * np.pi)) + 0.002
            and co.z > neck_cut_z(co))


gone = [v for v in bm.verts if in_neck(v.co)]
gone += [v for v in bm.verts if v.co.z > neck_z + 0.06]  # nothing up the neck / head
if a.sleeve <= 0:  # armholes: everything outside the shoulder joint that is above the armpit
    armpit_z = J['LeftArm'][2] - 0.07
    gone += [v for v in bm.verts if abs(v.co.x) > abs(J['LeftArm'][0]) - 0.012 and v.co.z > armpit_z]
    gone += [v for v in bm.verts if abs(v.co.x) > abs(J['LeftArm'][0]) + 0.03]  # and the arms themselves
bmesh.ops.delete(bm, geom=list(set(gone)), context='VERTS')
# keep the main piece only (stray islands from the cuts)
bm.verts.ensure_lookup_table()
seen, best = set(), []
for v in bm.verts:
    if v in seen:
        continue
    comp, stack = [], [v]
    seen.add(v)
    while stack:
        u = stack.pop()
        comp.append(u)
        for e in u.link_edges:
            w = e.other_vert(u)
            if w not in seen:
                seen.add(w)
                stack.append(w)
    if len(comp) > len(best):
        best = comp
keep = set(best)
bmesh.ops.delete(bm, geom=[v for v in bm.verts if v not in keep], context='VERTS')

# ---- 4. clean panels: smooth away anatomy (interior), smooth the cut edges (boundary loops), then push out to the
# offset from the real skin everywhere (so smoothing can never sink it into the body)
bco, bpolys = F.world_verts(body, evaluated=True)
bbvh = F.bvh_of(bco, bpolys)
off = a.offset_mm / 1000
off_sleeve = a.sleeve_offset_mm / 1000
for it in range(a.smooth):
    inner = [v for v in bm.verts if not v.is_boundary]
    bmesh.ops.smooth_vert(bm, verts=inner, factor=0.5, use_axis_x=True, use_axis_y=True, use_axis_z=True)
    edge = [v for v in bm.verts if v.is_boundary]
    for v in edge:  # along the loop only: average the two boundary neighbours
        nb = [e.other_vert(v) for e in v.link_edges if e.is_boundary]
        if len(nb) == 2:
            v.co = v.co * 0.5 + (nb[0].co + nb[1].co) * 0.25
    bm.normal_update()
    for v in bm.verts:
        loc, nrm, _, dist = bbvh.find_nearest(v.co)
        if loc is None:
            continue
        side = (v.co - loc).dot(nrm)
        need = off_sleeve if abs(v.co.x) > J['LeftArm'][0] + 0.015 else off
        if v.co.z > neck_z - 0.05 and math.hypot(v.co.x - ncx, v.co.y - ncy) < 0.10:  # the collar band
            need = max(need, a.collar_ease_mm / 1000)
        if side < need:  # too close / inside: lift it along its OWN normal (never toward a hollow in the skin)
            v.co = v.co + v.normal * (need - side)
bm.normal_update()

# ---- 4b. drape (Bitmoji/Snap): fitted at the shoulders, upper chest and sleeves; below the chest the shirt does not
# follow the waist in - each horizontal slice takes the larger of its own outline and the chest's widest outline
# (blended in over 6 cm, so no crease), with a slight flare in the hem band. Sleeves flare a little at the opening.
sx_split = J['LeftArm'][0] + 0.015
tors = [v for v in bm.verts if abs(v.co.x) < sx_split]
tz = np.array([v.co.z for v in tors])
tang = np.array([math.atan2(v.co.x, -(v.co.y - cy)) for v in tors])
trad = np.array([math.hypot(v.co.x, v.co.y - cy) for v in tors])
NB = 72
best_z, best_r = None, -1
for zc in np.arange(J['Spine'][2], J['Spine2'][2] + 0.06, 0.005):
    m = np.abs(tz - zc) < 0.006
    if m.sum() > 40 and trad[m].mean() > best_r:
        best_z, best_r = zc, trad[m].mean()
hem_band = np.zeros(len(tors))
if best_z is not None and a.drape > 0:
    m = np.abs(tz - best_z) < 0.008
    bins = ((tang[m] + math.pi) / (2 * math.pi) * NB).astype(int) % NB
    R = np.full(NB, np.nan)
    for b in range(NB):
        if (bins == b).any():
            R[b] = trad[m][bins == b].max()
    idx = np.arange(NB)
    ok = ~np.isnan(R)
    R = np.interp(idx, idx[ok], R[ok], period=NB)
    R = np.convolve(np.r_[R[-3:], R, R[:3]], np.ones(7) / 7, mode='valid')  # circular smoothing
    for i, v in enumerate(tors):
        z = tz[i]
        if z >= best_z:
            continue
        w = a.drape * min(1.0, (best_z - z) / 0.06)
        w = w * w * (3 - 2 * w)  # smoothstep: no crease where the drape starts
        fb = (tang[i] + math.pi) / (2 * math.pi) * NB - 0.5  # bin centres; interpolate between neighbours
        b0 = int(math.floor(fb)) % NB
        t_ = fb - math.floor(fb)
        Rb = R[b0] * (1 - t_) + R[(b0 + 1) % NB] * t_
        r_new = trad[i] + w * max(0.0, Rb - trad[i])
        band_top = hem_z + a.hem_band_cm / 100
        if z < band_top:
            f = (band_top - z) / (a.hem_band_cm / 100)
            r_new += a.hem_flare_mm / 1000 * f * f
            hem_band[i] = min(1.0, f)
        d = Vector((v.co.x, v.co.y - cy, 0))
        if d.length > 1e-6:
            d.normalize()
            v.co.x, v.co.y = d.x * r_new, cy + d.y * r_new
# the back hangs straight from the shoulder-blade line (like the front from the chest): below it, every back-facing
# slice takes at least the blade line's outline, blended in over 5 cm
z_blade = J['Spine2'][2] + 0.06
mb_ = (np.abs(tz - z_blade) < 0.008)
if mb_.sum() > 20:
    bins = ((tang[mb_] + math.pi) / (2 * math.pi) * NB).astype(int) % NB
    RB = np.full(NB, np.nan)
    for b in range(NB):
        if (bins == b).any():
            RB[b] = trad[mb_][bins == b].max()
    ok = ~np.isnan(RB)
    RB = np.interp(np.arange(NB), np.arange(NB)[ok], RB[ok], period=NB)
    RB = np.convolve(np.r_[RB[-3:], RB, RB[:3]], np.ones(7) / 7, mode='valid')
    for i, v in enumerate(tors):
        if v.co.y <= cy or v.co.z >= z_blade:
            continue
        w = min(1.0, (z_blade - v.co.z) / 0.05)
        w = w * w * (3 - 2 * w)
        ang = math.atan2(v.co.x, -(v.co.y - cy))
        fb = (ang + math.pi) / (2 * math.pi) * NB - 0.5
        b0 = int(math.floor(fb)) % NB
        t_ = fb - math.floor(fb)
        Rb = RB[b0] * (1 - t_) + RB[(b0 + 1) % NB] * t_
        r0 = math.hypot(v.co.x, v.co.y - cy)
        rn = r0 + w * max(0.0, Rb - r0)
        if r0 > 1e-6:
            v.co.x, v.co.y = v.co.x / r0 * rn, cy + (v.co.y - cy) / r0 * rn
for side in ('Left', 'Right'):
    if a.sleeve <= 0:
        continue
    p_end, ax_ = sl[side]
    a0 = J[f'{side}Arm']
    for v in bm.verts:
        rel = np.array(v.co[:]) - a0
        along = rel @ ax_
        if np.sign(v.co.x) != np.sign(ax_[0]) or abs(v.co.x) < sx_split:
            continue
        end = (p_end - a0) @ ax_
        f = (along - (end - 0.015)) / 0.015
        if f > 0:
            perp = rel - along * ax_
            n_ = np.linalg.norm(perp)
            if n_ > 1e-6:
                push = a.sleeve_flare_mm / 1000 * min(1.0, f) ** 2
                v.co = Vector(np.array(v.co[:]) + perp / n_ * push)
# fabric spans hollows instead of sinking into them: every horizontal slice of the torso is filled out to its
# convex outline (spine groove, between the shoulder blades and the chest), and the upper back gets a little extra
# room - the shirt hangs from the shoulders instead of being stuck to the back
def _hull(pts):
    pts = sorted(map(tuple, pts))
    if len(pts) < 3:
        return np.array(pts)
    def cross(o, a_, b_):
        return (a_[0] - o[0]) * (b_[1] - o[1]) - (a_[1] - o[1]) * (b_[0] - o[0])
    lo, up = [], []
    for q in pts:
        while len(lo) >= 2 and cross(lo[-2], lo[-1], q) <= 0:
            lo.pop()
        lo.append(q)
    for q in reversed(pts):
        while len(up) >= 2 and cross(up[-2], up[-1], q) <= 0:
            up.pop()
        up.append(q)
    return np.array(lo[:-1] + up[:-1])


tz = np.array([v.co.z for v in tors])
xy0 = np.array([[v.co.x, v.co.y] for v in tors])
z_top = neck_z - 0.01
for zc in np.arange(hem_z, z_top, 0.01):
    # the neck area is left alone: at neck height the slice's convex outline spans out to the shoulders, and filling
    # to it pushed the fabric around the neck out onto the shoulder slopes (a boat neck)
    sel_i = [i for i in range(len(tors)) if zc <= tz[i] < zc + 0.01 and not tors[i].is_boundary
             and not (tz[i] > neck_z - 0.06 and math.hypot(tors[i].co.x - ncx, tors[i].co.y - ncy) < neck_reach(tors[i].co) + 0.02)]
    if len(sel_i) < 12:
        continue
    P = np.array([[tors[i].co.x, tors[i].co.y] for i in sel_i])
    c0 = P.mean(0)
    H = _hull(P)
    if len(H) < 3:
        continue
    # the hull as a radius-per-angle function around the slice centre (dense samples along its edges)
    E = np.concatenate([np.linspace(H[k], H[(k + 1) % len(H)], 12, endpoint=False) for k in range(len(H))])
    ang_h = np.arctan2(E[:, 1] - c0[1], E[:, 0] - c0[0])
    rad_h = np.linalg.norm(E - c0, axis=1)
    o_ = np.argsort(ang_h)
    ang_h, rad_h = ang_h[o_], rad_h[o_]
    for i in sel_i:
        v = tors[i]
        dvec = np.array([v.co.x - c0[0], v.co.y - c0[1]])
        r = np.linalg.norm(dvec)
        if r < 1e-6:
            continue
        rh = float(np.interp(math.atan2(dvec[1], dvec[0]), ang_h, rad_h, period=2 * math.pi))
        # the back ease ramps in around the side (by angle), not on/off at the side seam - a step there read as a line
        cb = (v.co.y - cy) / max(1e-6, math.hypot(v.co.x, v.co.y - cy))   # 1 = straight back, 0 = side, -1 = front
        wb = min(1.0, max(0.0, (cb + 0.1) / 0.6))
        wb = wb * wb * (3 - 2 * wb) if tz[i] > hem_z + a.hem_band_cm / 100 else 0.0
        fade = min(1.0, max(0.0, (neck_z - 0.03 - tz[i]) / 0.05))  # no extra ease right at the collar
        rn = max(r, rh) + a.back_ease_mm / 1000 * fade * wb
        v.co.x, v.co.y = c0[0] + dvec[0] / r * rn, c0[1] + dvec[1] / r * rn
# each slice is filled on its own, so its outline can jump from one slice to the next (where the hull starts to take
# in the armpits / blades) - smooth the fill's displacement over the surface so no slice step shows as a crease
bm.verts.index_update()
_ti = {v.index: i for i, v in enumerate(tors)}
_nbr = [[_ti[e.other_vert(v).index] for e in v.link_edges if e.other_vert(v).index in _ti] for v in tors]
disp = np.array([[v.co.x, v.co.y] for v in tors]) - xy0
for it in range(30):
    disp = np.array([disp[i] * 0.5 + disp[nb].mean(0) * 0.5 if nb else disp[i] for i, nb in enumerate(_nbr)])
for i, v in enumerate(tors):
    if not v.is_boundary:
        v.co.x, v.co.y = xy0[i, 0] + disp[i, 0], xy0[i, 1] + disp[i, 1]
# the hem zone clears the BOTTOMS SHELL (shells.BANDS + GAP): any in-spec trousers fit under it - a top worn over
# bottoms must stand off the hips and waistband by their standard envelope, not hug them (layer 2 only)
if a.layer >= 2:
    import shells as SH
    hz0 = J['Hips'][2]
    knots_z = np.array([-0.06, 0.0, 0.05, 0.10, 0.14])  # rel. to the Hips joint
    # the bottoms shell is a 95th percentile; pocket flaps and tabs stick out a few mm past it, so the hem keeps a
    # little extra (HEM_EXTRA_MM) - a straight, slightly boxy hem like the reference, not a hip-hugging one
    HEM_EXTRA_MM = 5
    hb, wb = SH.BANDS['hips']['bottom_max'] + SH.GAP_MM, SH.BANDS['waistband']['bottom_max'] + SH.GAP_MM
    knots_r = np.array([hb + HEM_EXTRA_MM + 2, hb + HEM_EXTRA_MM, wb + 2, wb, 0.0]) / 1000
    for it in range(3):
        for v, z in zip(tors, tz):
            need = float(np.interp(v.co.z - hz0, knots_z, knots_r))
            if need <= off:
                continue
            loc, nrm, _, dd_ = bbvh.find_nearest(v.co)
            if loc is None:
                continue
            gap = (v.co - loc).dot(nrm)
            if gap < need:
                d = Vector((v.co.x, v.co.y - cy, 0))
                if d.length > 1e-6:
                    d.normalize()
                    v.co += d * (need - gap)
# relax the draped panels (radial moves leave small ripples), never back inside the offset
draped = [v for v, z in zip(tors, tz) if best_z is not None and z < best_z and not v.is_boundary]
for it in range(8):
    bmesh.ops.smooth_vert(bm, verts=draped, factor=0.5, use_axis_x=True, use_axis_y=True, use_axis_z=False)
    bm.normal_update()
    for v in draped:
        loc, nrm, _, dist = bbvh.find_nearest(v.co)
        if loc is not None and (v.co - loc).dot(nrm) < off:
            v.co = v.co + v.normal * (off - (v.co - loc).dot(nrm))
allin = [v for v in bm.verts if not v.is_boundary and abs(v.co.x) < sx_split]
for it in range(4):  # the convex fill and back ease leave steps between slices: relax them away
    bmesh.ops.smooth_vert(bm, verts=allin, factor=0.5, use_axis_x=True, use_axis_y=True, use_axis_z=True)


def need_at(co):  # the ease off the skin: body 'off', sleeves 'off_sleeve', blended across the armhole (no step)
    t = min(1.0, max(0.0, (abs(co.x) - (sx_split - 0.015)) / 0.03))
    n_ = off + (off_sleeve - off) * t * t * (3 - 2 * t)
    if co.z > neck_z - 0.05 and math.hypot(co.x - ncx, co.y - ncy) < 0.10:  # the collar band
        n_ = max(n_, a.collar_ease_mm / 1000)
    return n_


def push_out(vs):
    bm.normal_update()
    for v in vs:
        loc, nrm, _, _ = bbvh.find_nearest(v.co)
        if loc is not None and (v.co - loc).dot(nrm) < need_at(v.co):
            v.co = v.co + v.normal * (need_at(v.co) - (v.co - loc).dot(nrm))


# armhole: the body panels (drape, fills, relax) stop at the sleeve/body split and the sleeves do not, which left a
# ridge from the shoulder to the underarm. Smooth a band across the join (weight fading out over 2.5 cm each side), so
# the surface runs continuously from body to sleeve; the seam is texture only
armpit_z = J['LeftArm'][2] - 0.07
band = [(v, 1 - abs(abs(v.co.x) - sx_split) / 0.025) for v in bm.verts if not v.is_boundary
        and abs(abs(v.co.x) - sx_split) < 0.025 and v.co.z > armpit_z - 0.04]
for it in range(20):
    nco = {}
    for v, w in band:
        nb = [e.other_vert(v).co for e in v.link_edges]
        nco[v] = v.co.lerp(sum(nb, Vector()) / len(nb), 0.5 * w)
    for v, c_ in nco.items():
        v.co = c_
    if it % 5 == 4:
        push_out([v for v, _ in band])

# back: hang straight from the shoulder-blade line. The back is sampled as a height field y(x, z) (rays from behind on
# an exact 2.5 x 4 mm grid), each x column is filled out to its convex outline between the blades and the waist (no
# dip below the blades), the fill is blurred a little, and every back-facing vertex takes it (bilinear), weighted by
# how squarely it faces the back. Exact columns (not slices of scattered vertices) keep neighbouring columns from
# stepping, so there are no ridges or edges


def gaussian_filter(A, sigma):  # separable Gaussian blur, edges held (no scipy in Blender)
    for ax_, sg in enumerate(sigma):
        r_ = int(3 * sg + 0.5)
        k_ = np.exp(-0.5 * (np.arange(-r_, r_ + 1) / sg) ** 2)
        k_ /= k_.sum()
        pad = [(0, 0), (0, 0)]
        pad[ax_] = (r_, r_)
        Ap = np.pad(A, pad, mode='edge')
        A = np.apply_along_axis(lambda m: np.convolve(m, k_, mode='valid'), ax_, Ap)
    return A


z_bt, z_bw = J['Spine2'][2] + 0.08 + 0.025, J['Spine'][2] - 0.02 - 0.025  # +-2.5 cm: the fill fades out past the band
GX = np.arange(-0.14, 0.14 + 1e-6, 0.0025)
GZ = np.arange(z_bw, z_bt + 1e-6, 0.004)
for _pass in range(3):
    bm.normal_update()
    tree = BVHTree.FromBMesh(bm)
    H = np.full((len(GX), len(GZ)), np.nan)
    for i, x_ in enumerate(GX):
        for j, z_ in enumerate(GZ):
            hit = tree.ray_cast(Vector((x_, cy + 0.4, z_)), Vector((0, -1, 0)), 0.5)
            if hit[0] is not None and hit[1].y > 0.15:
                H[i, j] = hit[0].y
    Fl = np.zeros_like(H)
    for i in range(len(GX)):
        ok = ~np.isnan(H[i])
        if ok.sum() < 6:
            continue
        zz, yy = GZ[ok], H[i, ok]
        hull = []
        for q in zip(zz, yy):
            while len(hull) >= 2 and (hull[-1][0] - hull[-2][0]) * (q[1] - hull[-2][1]) - (hull[-1][1] - hull[-2][1]) * (q[0] - hull[-2][0]) >= 0:
                hull.pop()
            hull.append(q)
        hz_, hy_ = np.array(hull).T
        Fl[i, ok] = np.interp(zz, hz_, hy_) - yy
    Fl = gaussian_filter(Fl, (2.0, 1.0))
    for v in bm.verts:
        if v.is_boundary or v.co.y <= cy or not (z_bw < v.co.z < z_bt) or abs(v.co.x) > GX[-1]:
            continue
        ny = min(1.0, max(0.0, (v.normal.y - 0.15) / 0.3))
        if ny <= 0:
            continue
        fi = (v.co.x - GX[0]) / 0.0025
        fj = (v.co.z - GZ[0]) / 0.004
        i0_, j0_ = min(int(fi), len(GX) - 2), min(int(fj), len(GZ) - 2)
        tx, tz_ = fi - i0_, fj - j0_
        f_ = (Fl[i0_, j0_] * (1 - tx) * (1 - tz_) + Fl[i0_ + 1, j0_] * tx * (1 - tz_)
              + Fl[i0_, j0_ + 1] * (1 - tx) * tz_ + Fl[i0_ + 1, j0_ + 1] * tx * tz_)
        fz = max(0.0, min(1.0, (z_bt - v.co.z) / 0.02, (v.co.z - z_bw) / 0.02))
        v.co.y += f_ * ny * ny * (3 - 2 * ny) * fz

# sleeves and the armhole: fill the valleys of the small-scale relief (a vertex below the mean of its neighbours, along
# its normal, moves out to it; nothing ever moves in), which irons out the faint ribs that the arm's own surface printed
# into the sleeve tube. Sleeve ends (the flare and the rolled rim) are left as they are
sl_end = {}
for side, (p_end, ax_) in sl.items():
    sl_end[side] = (np.asarray(J[f'{side}Arm']), ax_, float((p_end - J[f'{side}Arm']) @ ax_))


def near_sleeve_end(co):
    if a.sleeve <= 0:
        return False
    a0, ax_, end = sl_end['Left' if co.x > 0 else 'Right']
    return (np.array(co[:]) - a0) @ ax_ > end - 0.012


vf = [v for v in bm.verts if not v.is_boundary and abs(v.co.x) > sx_split - 0.025 and not near_sleeve_end(v.co)
      and (abs(v.co.x) > sx_split + 0.005 or v.co.z > armpit_z - 0.04)]
for it in range(40):
    bm.normal_update()
    mv = {}
    for v in vf:
        nb = [e.other_vert(v).co for e in v.link_edges]
        d_ = (sum(nb, Vector()) / len(nb) - v.co).dot(v.normal)
        if d_ > 0:
            mv[v] = v.co + v.normal * d_ * 0.7
    for v, c_ in mv.items():
        v.co = c_
push_out(vf + [v for v, _ in band])
# then smooth the tube both ways (peaks too) and lift it back out by a SMOOTH amount where it sank under the ease: a
# per-vertex push along the normal would print the arm's surface back into the sleeve
def end_fade(co):  # 1 on the tube, fading to 0 at the sleeve's cut edge (the flare and the rim stay as they are)
    if a.sleeve <= 0:
        return 1.0
    a0, ax_, end = sl_end['Left' if co.x > 0 else 'Right']
    return min(1.0, max(0.0, (end - (np.array(co[:]) - a0) @ ax_ - 0.004) / 0.016))


tube = [v for v in bm.verts if not v.is_boundary and abs(v.co.x) > sx_split + 0.005 and end_fade(v.co) > 0]
if tube:
    tset = set(tube)
    tw = {v: end_fade(v.co) for v in tube}
    for it in range(25):
        nco = {v: v.co.lerp(sum((e.other_vert(v).co for e in v.link_edges), Vector()) / len(v.link_edges), 0.5 * tw[v]) for v in tube}
        for v, c_ in nco.items():
            v.co = c_
    bm.normal_update()
    lift = {}
    for v in tube:
        loc, nrm, _, _ = bbvh.find_nearest(v.co)
        lift[v] = max(0.0, need_at(v.co) - (v.co - loc).dot(nrm)) if loc is not None else 0.0
    base_ = dict(lift)
    for it in range(15):  # spread the lift into a smooth cap that is never below any vertex's own deficit
        lift = {v: max(base_[v], sum(lift[e.other_vert(v)] for e in v.link_edges if e.other_vert(v) in tset)
                       / max(1, sum(1 for e in v.link_edges if e.other_vert(v) in tset))) for v in tube}
    for it in range(4):
        lift = {v: max(base_[v], 0.5 * lift[v] + 0.5 * sum(lift[e.other_vert(v)] for e in v.link_edges if e.other_vert(v) in tset)
                       / max(1, sum(1 for e in v.link_edges if e.other_vert(v) in tset))) for v in tube}
    for v in tube:
        v.co = v.co + v.normal * lift[v]
# clean cut edges: the hem, collar and sleeve ends were cut through ~5 mm faces and read as spiky/wavy; smooth each
# boundary loop along itself (the hem stays exactly level), and pull the first ring inside along with it
for it in range(a.edge_smooth):
    bnd = [v for v in bm.verts if v.is_boundary]
    newco = {}
    for v in bnd:
        nb = [e.other_vert(v) for e in v.link_edges if e.is_boundary]
        if len(nb) == 2:
            c_ = v.co * 0.5 + (nb[0].co + nb[1].co) * 0.25
            if abs(v.co.z - hem_z) < 0.004:
                c_.z = hem_z
            newco[v] = c_
    for v, c_ in newco.items():
        v.co = c_
    ring = {e.other_vert(v) for v in bnd for e in v.link_edges if not e.other_vert(v).is_boundary}
    bmesh.ops.smooth_vert(bm, verts=list(ring), factor=0.3, use_axis_x=True, use_axis_y=True, use_axis_z=True)
bm.normal_update()
for v in bm.verts:  # never inside the ease after all the smoothing
    loc, nrm, _, dist = bbvh.find_nearest(v.co)
    if loc is not None:
        need = need_at(v.co)
        if (v.co - loc).dot(nrm) < need:
            v.co = v.co + v.normal * (need - (v.co - loc).dot(nrm))
bm.verts.index_update()
hem_attr = np.zeros(len(bm.verts))
for v, hb in zip(tors, hem_band):
    hem_attr[v.index] = hb
bm.normal_update()
bm.to_mesh(shell.data)
bm.free()
shell.data.update()
ha = shell.data.attributes.new('_hem_band', 'FLOAT', 'POINT')  # exported as glTF _HEM_BAND (customizer hem wrap)
ha.data.foreach_set('value', hem_attr.astype(np.float32))

# boundary info per vertex for the texture (distance to the nearest cut edge and which edge)
me = shell.data
bm = bmesh.new()
bm.from_mesh(me)
bm.verts.ensure_lookup_table()
bverts = [v for v in bm.verts if v.is_boundary]
bco_b = np.array([v.co[:] for v in bverts])


def kind(p):
    if p[2] < hem_z + 0.015:
        return 0  # hem
    if abs(p[0]) > 0.15 and a.sleeve > 0:
        return 1  # sleeve
    return 2  # neckline (or armhole of a tank)


bkind = np.array([kind(p) for p in bco_b])
vco = np.array([v.co[:] for v in bm.verts])
from mathutils.kdtree import KDTree  # noqa: E402
kd = KDTree(len(bco_b))
for i, p in enumerate(bco_b):
    kd.insert(Vector(p), i)
kd.balance()
vdist = np.zeros(len(vco))
vkind = np.zeros(len(vco), int)
for i, p in enumerate(vco):
    _, j, dd = kd.find(Vector(p))
    vdist[i], vkind[i] = dd, bkind[j]
# the cut edges themselves, sampled every 0.5 mm: the texture measures each pixel's exact distance to them, so the
# collar band and the stitch lines have clean, even edges (per-vertex distances blended across triangles zig-zag)
_ep, _ek = [], []
for e in bm.edges:
    if e.is_boundary:
        p0, p1 = np.array(e.verts[0].co[:]), np.array(e.verts[1].co[:])
        k_ = kind((p0 + p1) / 2)
        n_ = max(1, int(np.linalg.norm(p1 - p0) / 0.0005))
        for t in np.linspace(0, 1, n_, endpoint=False):
            _ep.append(p0 + (p1 - p0) * t)
            _ek.append(k_)
edge_kd = KDTree(len(_ep))
for i, p in enumerate(_ep):
    edge_kd.insert(Vector(p), i)
edge_kd.balance()
edge_kind = np.array(_ek)
bm.free()
# a clean rolled rim of constant width on every edge (hem, sleeve ends, collar): a soft bead ~2 mm in from the edge
me.calc_normals_split() if hasattr(me, 'calc_normals_split') else None
vn_ = np.array([v.normal[:] for v in me.vertices])
bead = 0.0012 * np.exp(-((vdist - 0.0025) / 0.0018) ** 2)
co_ = np.array([v.co[:] for v in me.vertices]) + vn_ * bead[:, None]
me.vertices.foreach_set('co', co_.ravel())
me.update()

# ---- 5. fabric thickness (inner surface toward the body; the rim closes the cut edges)
sol = shell.modifiers.new('thickness', 'SOLIDIFY')
sol.thickness = a.thick_mm / 1000
sol.offset = -1.0
sol.use_rim = True
bpy.context.view_layer.objects.active = shell
shell.select_set(True)
# per-vertex attributes for the texture BEFORE solidify adds vertices (the modifier copies them along)
attr_d = me.attributes.new('edge_dist', 'FLOAT', 'POINT')
attr_k = me.attributes.new('edge_kind', 'FLOAT', 'POINT')
attr_d.data.foreach_set('value', vdist.astype(np.float32))
attr_k.data.foreach_set('value', vkind.astype(np.float32))
bpy.ops.object.modifier_apply(modifier='thickness')
me = shell.data
bm = bmesh.new()
bm.from_mesh(me)
bmesh.ops.triangulate(bm, faces=bm.faces[:])  # one polygon per triangle: every corner belongs to one triangle
bm.to_mesh(me)
bm.free()
# shading from the shirt's OWN surface: the body copy carried the body's stored (custom) normals, which no longer
# match after the reshaping and showed as stripes along the sleeves and chest
for nm in ('custom_normal', 'sharp_edge', 'sharp_face'):
    if nm in me.attributes:
        me.attributes.remove(me.attributes[nm])
me.shade_smooth()

# ---- 6. texture: ONE true-scale sewing pattern shared by every variant (tee_layout.py): front and back pieces
# unrolled around the torso by arc length, sleeves unrolled around the arm. A shorter sleeve or a cropped hem uses less
# of its piece, so one texture kit (--kit: print tile, graphics, normal / roughness tiles, colours) dresses all six
# variants at the same print scale. Colours are computed from the 3D surface, so graphics sit where they belong.
import tee_layout as TL  # noqa: E402
SS = 2  # painted at 2x and averaged down: stitches, band edges and graphics come out anti-aliased, not stair-stepped
TW, TH_ = TL.tex_size(a.tex * SS)
PPM = TL.px_per_m(a.tex * SS)


def hexrgb(h, fallback):
    if not h:
        return np.array(fallback, float)
    h = h.lstrip('#')
    return np.array([int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)], float)


def load_px(p):  # an image as a float array, bottom row first (Blender's order), RGBA
    im = bpy.data.images.load(str(p))
    w_, h_ = im.size
    return np.array(im.pixels[:], np.float32).reshape(h_, w_, 4)


kit = {}
if a.kit:
    kd = Path(a.kit).resolve()
    kit = json.loads((kd / 'spec.json').read_text(encoding='utf-8'))
    for nm in ('pattern_tile', 'torso_print', 'sleeve_print', 'normal_tile', 'roughness_tile', 'chest_graphic', 'back_graphic'):
        if (kd / f'{nm}.png').exists():
            kit[nm] = load_px(kd / f'{nm}.png')
col = hexrgb(kit.get('base_color'), [float(c) for c in a.color.split(',')])
trim = hexrgb(kit.get('trim_color'), col * 0.94)
stitch = hexrgb(kit.get('stitch_color'), col * 0.88)
tile_m = float(kit.get('pattern_tile_cm', 12)) / 100
for l in list(me.uv_layers):
    me.uv_layers.remove(l)
uvl = me.uv_layers.new(name='UVMap')
tris = np.array([p.vertices[:] for p in me.polygons])
fn = np.array([p.normal[:] for p in me.polygons])
vco = np.array([v.co[:] for v in me.vertices])
cen = vco[tris].mean(1)
z_lo = J['Hips'][2] - TL.Z_LO_BELOW_HIPS
sx = J['LeftArm'][0] + 0.015  # torso | sleeve split (just outside the shoulder joint)
# the torso's arc length around each height, from the centre front: S[k, i] at height ZT[k], angle THG[i] (0 = front)
NTH = 360
THG = np.linspace(-np.pi, np.pi, NTH + 1)
ZT = np.arange(z_lo, z_lo + TL.TORSO_H + 1e-6, 0.005)
tm_ = np.abs(vco[:, 0]) < sx
t_th = np.arctan2(vco[tm_, 0], -(vco[tm_, 1] - cy))
t_r = np.hypot(vco[tm_, 0], vco[tm_, 1] - cy)
t_z = vco[tm_, 2]
S = np.zeros((len(ZT), NTH + 1))
thc = (THG[:-1] + THG[1:]) / 2
for k, z in enumerate(ZT):
    m = np.abs(t_z - z) < 0.008
    if m.sum() < 20:
        S[k] = S[k - 1] if k else THG * 0.13
        continue
    R = np.full(NTH, -1.0)
    np.maximum.at(R, ((t_th[m] + np.pi) / (2 * np.pi) * NTH).astype(int) % NTH, t_r[m])
    ok = R > 0
    if k and np.convolve(ok, np.ones(9), 'same').clip(0, 1).mean() < 0.9:
        # an open ring (the neck opening): measuring across the gap would pull the collar's sides inward and fold them
        # over the front in the texture - the shirt above the last complete ring keeps that ring's arc lengths
        S[k] = S[k - 1]
        continue
    R = np.interp(np.arange(NTH), np.arange(NTH)[ok], R[ok], period=NTH)
    R = np.convolve(np.r_[R[-4:], R, R[:4]], np.ones(9) / 9, mode='valid')
    P = np.stack([R * np.sin(thc), R * np.cos(thc)], -1)
    seg = np.linalg.norm(np.diff(P, axis=0), axis=1)
    C = np.r_[0.0, np.cumsum(seg)]
    S[k] = (np.interp(THG, thc, C, left=C[0] - R[0] * np.pi / NTH, right=C[-1] + R[-1] * np.pi / NTH)
            - np.interp(0.0, thc, C))


def arc(th, z):  # bilinear lookup of S
    fk = np.clip((z - ZT[0]) / 0.005, 0, len(ZT) - 1.001)
    k0 = fk.astype(int)
    tk = fk - k0
    fi = np.clip((th + np.pi) / (2 * np.pi) * NTH, 0, NTH - 0.001)
    i0 = fi.astype(int)
    ti = fi - i0
    s0 = S[k0, i0] * (1 - ti) + S[k0, i0 + 1] * ti
    s1 = S[k0 + 1, i0] * (1 - ti) + S[k0 + 1, i0 + 1] * ti
    return s0 * (1 - tk) + s1 * tk


def ends(z):  # S at +pi and -pi (the centre back, reached round either side)
    fk = np.clip((z - ZT[0]) / 0.005, 0, len(ZT) - 1.001)
    k0 = fk.astype(int)
    tk = fk - k0
    return (S[k0, NTH] * (1 - tk) + S[k0 + 1, NTH] * tk), (S[k0, 0] * (1 - tk) + S[k0 + 1, 0] * tk)


PIECES = ['front', 'back', 'left', 'right']
th_c = np.arctan2(cen[:, 0], -(cen[:, 1] - cy))
piece = np.where(np.abs(cen[:, 0]) > sx, np.where(cen[:, 0] > 0, 2, 3), np.where(np.abs(th_c) < np.pi / 2, 0, 1))
if a.sleeve <= 0:
    piece = np.where(piece >= 2, np.where(np.abs(th_c) < np.pi / 2, 0, 1), piece)
# the fabric's inner side faces the skin: its normal points toward the nearest body point
near = np.array([bbvh.find_nearest(Vector(c))[0][:] for c in cen])
inner = np.einsum('ij,ij->i', fn, cen - near) < 0


def metric(P, pn):
    """Pattern coordinates (metres) of points P (n,3) on piece pn."""
    if pn in (0, 1):
        th = np.arctan2(P[:, 0], -(P[:, 1] - cy))
        s = arc(th, P[:, 2])
        if pn == 1:  # from the centre back, + toward the wearer's right (reads correctly from behind)
            sp, sm = ends(P[:, 2])
            s = np.where(th > 0, -(sp - s), s - sm)
        return np.stack([s, P[:, 2] - z_lo], -1)
    side = 'Left' if pn == 2 else 'Right'
    a_, b_ = J[f'{side}Arm'], J[f'{side}ForeArm']
    ax = (b_ - a_) / np.linalg.norm(b_ - a_)
    rel = P - a_
    along = rel @ ax
    perp = rel - np.outer(along, ax)
    ang = np.arctan2(perp[:, 1], perp[:, 2])  # 0 on top of the arm, the unroll seam (+-pi) underneath
    return np.stack([ang * TL.SLEEVE_R, along - (sx - abs(a_[0]))], -1)


def texel_metric(P):
    """Print coordinates of surface points. Round the torso the print runs continuously (front, sides and back are one
    band, no seam in the print where the pattern pieces meet), with the repeat nudged at each height so a whole number
    of repeats fits round the body (no join at the centre back either). Sleeves are their own band. Each point is
    placed by its OWN position, so the armhole is a smooth line rather than following triangle edges."""
    th = np.arctan2(P[:, 0], -(P[:, 1] - cy))
    sp, sm = ends(P[:, 2])
    circ = np.maximum(sp - sm, 1e-3)
    k = np.maximum(1, np.round(circ / tile_m)) * tile_m / circ
    out = np.stack([arc(th, P[:, 2]) * k, P[:, 2] - z_lo], -1)
    if a.sleeve > 0:
        for side_pn, sgn in ((2, 1), (3, -1)):
            m = (np.abs(P[:, 0]) > sx) & (np.sign(P[:, 0]) == sgn)
            if m.any():
                out[m] = metric(P[m], side_pn)
    return out


tri_m = np.zeros((len(tris), 3, 2))
for pn in range(4):
    m = piece == pn
    if m.any():
        tri_m[m] = metric(vco[tris[m]].reshape(-1, 3), pn).reshape(-1, 3, 2)
# a sleeve triangle straddling the unroll seam: keep it on one side
wrap = (piece >= 2) & (np.ptp(tri_m[:, :, 0], axis=1) > np.pi * TL.SLEEVE_R)
for i in np.nonzero(wrap)[0]:
    u = tri_m[i, :, 0]
    u[u < 0] += 2 * np.pi * TL.SLEEVE_R
uv_loops = np.zeros_like(tri_m)
for pn, nm in enumerate(PIECES):
    m = piece == pn
    w_, h_ = TL.SIZE[nm]
    ox, oy = TL.ORIGIN[nm]
    uu = np.clip(tri_m[m, :, 0], -w_ / 2 - TL.GAP / 2, w_ / 2 + TL.GAP / 2)
    vv = np.clip(tri_m[m, :, 1], -TL.GAP / 2, h_ + TL.GAP / 2)
    uv_loops[m, :, 0] = (ox + uu) / TL.CANVAS_W
    uv_loops[m, :, 1] = (oy + vv) / TL.CANVAS_H
uv_loops = np.clip(uv_loops, 0.0005, 0.9995)
uvl.data.foreach_set('uv', uv_loops.astype(np.float32).ravel())
print(f'[shell] texture {TW}x{TH_} px, {PPM / 1000:.2f} px/mm; pieces: '
      + ', '.join(f'{nm} u {tri_m[piece == pn, :, 0].min():+.3f}..{tri_m[piece == pn, :, 0].max():+.3f} '
                  f'v {tri_m[piece == pn, :, 1].min():.3f}..{tri_m[piece == pn, :, 1].max():.3f}'
                  for pn, nm in enumerate(PIECES) if (piece == pn).any()), flush=True)
# raster each triangle into its piece (outer faces last, so the visible side wins where inner/outer overlap)
vnr = np.array([v.normal[:] for v in me.vertices])
dist = np.array([d.value for d in me.attributes['edge_dist'].data])
kinds = np.array([d.value for d in me.attributes['edge_kind'].data])
gimg = None
gw = a.graphic_width_cm / 100
if 'chest_graphic' in kit:
    gimg = kit['chest_graphic'][::-1]  # top row first
    gw = float(kit.get('chest_graphic_width_cm') or 16) / 100
elif a.graphic:
    gi = bpy.data.images.load(str(Path(a.graphic).resolve()))
    gimg = np.array(gi.pixels[:], np.float32).reshape(gi.size[1], gi.size[0], 4)[::-1]
bimg = kit['back_graphic'][::-1] if 'back_graphic' in kit else None
bw = float(kit.get('back_graphic_width_cm') or 20) / 100
chest_c = np.array([0.0, J['Spine2'][1], (J['Spine2'][2] + J['Neck'][2]) / 2 - 0.035])
back_c = np.array([0.0, J['Spine2'][1], J['Spine2'][2] + 0.02])


def sample(tex, uvm):  # bilinear, tiling, from a bottom-row-first array; uvm in tiles
    h_, w_ = tex.shape[:2]
    x = (uvm[:, 0] % 1.0) * w_ - 0.5
    y = (uvm[:, 1] % 1.0) * h_ - 0.5
    x0 = np.floor(x).astype(int)
    y0 = np.floor(y).astype(int)
    fx = (x - x0)[:, None]
    fy = (y - y0)[:, None]
    x0 %= w_
    y0 %= h_
    x1 = (x0 + 1) % w_
    y1 = (y0 + 1) % h_
    return (tex[y0, x0] * (1 - fx) * (1 - fy) + tex[y0, x1] * fx * (1 - fy) + tex[y1, x0] * (1 - fx) * fy
            + tex[y1, x1] * fx * fy)


def decal(c, ink, pos, nrm, img_, centre, width, facing):  # a graphic projected straight onto the front (-1) / back (+1)
    gh_, gw_ = img_.shape[:2]
    gx = (pos[:, 0] - centre[0]) / width * (-facing) + 0.5
    gy = 0.5 - (pos[:, 2] - centre[2]) / (width * gh_ / gw_)
    on = (nrm[:, 1] * facing > 0.3) & (gx >= 0) & (gx < 1) & (gy >= 0) & (gy < 1)
    if on.any():
        gp = img_[(gy[on] * (gh_ - 1)).astype(int), (gx[on] * (gw_ - 1)).astype(int)]
        c[on] = c[on] * (1 - gp[:, 3:4]) + gp[:, :3] * gp[:, 3:4]
        ink[on] = np.maximum(ink[on], gp[:, 3])  # where the print's ink sits (for the ink layer of the material)


def fabric_xy(P):
    """Where each point falls on the kit's full-size printed fabric (made for the LONGEST shirt: elbow sleeves, full
    length; shorter sleeves and cropped hems use less of it). torso_print wraps round the body: its centre is the centre
    front, its left / right edges meet at the centre back, bottom = Z_LO under the longest hem, top = TORSO_H above it.

    Sleeves (kit "sleeves"):
      continuous (default) - cut from the SAME fabric as the body, continuing straight out from the armhole: the front
                  half of each sleeve carries on from the front of the shirt and the back half from the back, so the
                  print flows across the armhole and the seams fall where they are hidden - along the top of the
                  shoulder / sleeve and under the arm. Within 3 cm of the armhole the sleeve's height on the fabric
                  eases from the true height to the unrolled height round the arm, so the print does not smear along
                  the top of the arm.
      set-in      - sleeve_print, one sleeve unrolled (centre = top of the arm, edges meet under the arm).
    Returns fabric (x, y) in 0..1 and which points use sleeve_print."""
    th = np.arctan2(P[:, 0], -(P[:, 1] - cy))
    sp, sm = ends(P[:, 2])
    out = np.stack([(arc(th, P[:, 2]) / np.maximum(sp - sm, 1e-3) + 0.5) % 1.0,
                    np.clip((P[:, 2] - z_lo) / TL.TORSO_H, 0, 0.999)], -1)
    use_sleeve_print = np.zeros(len(P), bool)
    if a.sleeve <= 0:
        return out, use_sleeve_print
    continuous = kit.get('sleeves', 'continuous') != 'set-in' or 'sleeve_print' not in kit
    for side, side_pn, sgn in (('Left', 2, 1), ('Right', 3, -1)):
        m = (np.abs(P[:, 0]) > sx) & (np.sign(P[:, 0]) == sgn)
        if not m.any():
            continue
        if not continuous:
            mm = metric(P[m], side_pn)
            out[m] = np.stack([(mm[:, 0] / (2 * np.pi * TL.SLEEVE_R) + 0.5) % 1.0,
                               np.clip(1 - mm[:, 1] / TL.SLEEVE_H, 0, 0.999)], -1)
            use_sleeve_print |= m
            continue
        Q = P[m]
        a_, b_ = J[f'{side}Arm'], J[f'{side}ForeArm']
        ax = (b_ - a_) / np.linalg.norm(b_ - a_)
        rel = Q - a_
        along_all = rel @ ax
        along = np.maximum(along_all - (sx - abs(a_[0])), 0.0)  # distance out from the armhole
        Q0 = Q - along[:, None] * ax                            # the point's place on the armhole
        th0 = np.arctan2(Q0[:, 0], -(Q0[:, 1] - cy))
        sp0, sm0 = ends(Q0[:, 2])
        perp = rel - np.outer(along_all, ax)
        front = perp[:, 1] < 0                                  # in front of the arm's axis
        # outward along the arm continues the panel it starts on: on the front panel the fabric runs outward toward
        # the wearer's side, on the back panel the other way (as the back reads from behind)
        u = arc(th0, Q0[:, 2]) + np.where(front, 1.0, -1.0) * sgn * along
        ang = np.arctan2(perp[:, 1], perp[:, 2])                # 0 on top of the arm, +-pi underneath
        r = np.linalg.norm(perp, axis=1)
        axis_z = (a_ + np.outer(along_all, ax))[:, 2]
        v_unrolled = axis_z + r * (np.pi / 2 - np.abs(ang))      # height measured round the arm from its side line
        w = np.clip(along / 0.03, 0, 1)
        w = w * w * (3 - 2 * w)
        v = Q[:, 2] * (1 - w) + v_unrolled * w
        out[m] = np.stack([(u / np.maximum(sp0 - sm0, 1e-3) + 0.5) % 1.0,
                           np.clip((v - z_lo) / TL.TORSO_H, 0, 0.999)], -1)
    return out, use_sleeve_print


def shade(pos, nrm, dd, kk, puv):
    if 'torso_print' in kit:
        fxy, on_sleeve = fabric_xy(pos)
        c = sample(kit['torso_print'], fxy)[:, :3].astype(float)
        if on_sleeve.any():
            c[on_sleeve] = sample(kit['sleeve_print'], fxy[on_sleeve])[:, :3]
    elif 'pattern_tile' in kit:
        c = sample(kit['pattern_tile'], puv / tile_m)[:, :3].astype(float)
    else:
        c = np.broadcast_to(col, pos.shape).copy()
    # near an edge: the exact distance to the cut edge (mm) and which edge it is
    near_ = np.nonzero(dd < 25)[0]
    for i_ in near_:
        _, j_, d_ = edge_kd.find(Vector(pos[i_]))
        dd[i_], kk[i_] = d_ * 1000, edge_kind[j_]
    px_mm = 1000 / PPM  # one texel in mm: edges are anti-aliased over about one texel

    def line(d0, half):  # coverage of a stitch line d0 +- half mm
        return np.clip((half + px_mm / 2 - np.abs(dd - d0)) / px_mm, 0, 1)[:, None]

    arc_mm = np.arctan2(pos[:, 0] - ncx, -(pos[:, 1] - ncy)) * 0.07 * 1000
    rib = 0.5 + 0.5 * np.sin(2 * np.pi * arc_mm / 2.5)
    wb = ((kk == 2) * np.clip((12 - dd) / px_mm + 0.5, 0, 1))[:, None]  # collar: a constant 12 mm band, soft rib
    c = c * (1 - wb) + trim * (0.94 + 0.06 * rib)[:, None] * wb
    ws = (kk == 2)[:, None] * line(12.5, 0.35) + (kk != 2)[:, None] * line(9.0, 0.35)  # stitch lines
    c = c * (1 - ws) + stitch * ws
    ink = np.zeros(len(pos))
    if gimg is not None:
        decal(c, ink, pos, nrm, gimg, chest_c, gw, -1)
    if bimg is not None:
        decal(c, ink, pos, nrm, bimg, back_c, bw, 1)
    return c, ink


img = np.broadcast_to(col, (TH_, TW, 3)).astype(np.float32).copy()
nimg = np.broadcast_to(np.array([0.5, 0.5, 1.0], np.float32), (TH_, TW, 3)).copy()
rimg = np.full((TH_, TW), float(kit.get('roughness', 0.9)), np.float32)
written = np.zeros((TH_, TW), bool)
core = np.zeros((TH_, TW), bool)  # pixels a triangle covers itself; overspill from a neighbour never overwrites them
inkimg = np.zeros((TH_, TW), np.float32)
aoimg = np.ones((TH_, TW), np.float32)
# ambient occlusion baked from the geometry: per vertex, how much of the hemisphere over it the shirt itself and the
# body block within 4 cm (12 cosine-weighted rays, nearer blockers count more) - soft shade in the collar roll, the
# cuffs, under the arms and where the hem turns. Kept gentle: the customizer adds its own screen-space AO on top.
shirt_bvh = BVHTree.FromPolygons([v.co.copy() for v in me.vertices], [tuple(t) for t in tris])
AO_DIRS = [Vector((math.sqrt((i + 0.5) / 12) * math.cos(i * 2.39996), math.sqrt((i + 0.5) / 12) * math.sin(i * 2.39996),
                   math.sqrt(1 - (i + 0.5) / 12))) for i in range(12)]
vao = np.ones(len(vco))
for vi in range(len(vco)):
    n_ = Vector(vnr[vi])
    if n_.length < 1e-6:
        continue
    q_ = n_.to_track_quat('Z', 'Y')
    o_ = Vector(vco[vi]) + n_ * 0.0006
    blk = 0.0
    for d_ in AO_DIRS:
        dw = q_ @ d_
        best = 0.04
        for tree in (shirt_bvh, bbvh):
            hit = tree.ray_cast(o_, dw, 0.04)
            if hit[0] is not None and hit[3] < best:
                best = hit[3]
        blk += 1 - best / 0.04
    vao[vi] = 1 - 0.55 * blk / len(AO_DIRS)
order = np.argsort(~inner)  # inner faces first, outer faces painted over them
for i in order:
    U = uv_loops[i] * np.array([TW - 1, TH_ - 1])
    x0, y0 = np.floor(U.min(0)).astype(int) - 1
    x1, y1 = np.ceil(U.max(0)).astype(int) + 1
    xs, ys = np.meshgrid(np.arange(max(x0, 0), min(x1, TW - 1) + 1), np.arange(max(y0, 0), min(y1, TH_ - 1) + 1))
    P = np.stack([xs.ravel(), ys.ravel()], -1).astype(float)
    (ax_, ay_), (bx_, by_), (cx_, cy_) = U
    den = (by_ - cy_) * (ax_ - cx_) + (cx_ - bx_) * (ay_ - cy_)
    if abs(den) < 1e-9:
        continue
    l0 = ((by_ - cy_) * (P[:, 0] - cx_) + (cx_ - bx_) * (P[:, 1] - cy_)) / den
    l1 = ((cy_ - ay_) * (P[:, 0] - cx_) + (ax_ - cx_) * (P[:, 1] - cy_)) / den
    l2 = 1 - l0 - l1
    ins = (l0 >= -0.15) & (l1 >= -0.15) & (l2 >= -0.15)  # a little bleed past the edges against seams
    if not ins.any():
        continue
    own = (l0 >= -1e-3) & (l1 >= -1e-3) & (l2 >= -1e-3)
    pp_all = P.astype(int)
    ins &= own | ~core[pp_all[:, 1], pp_all[:, 0]]
    if not ins.any():
        continue
    Lx = np.stack([l0, l1, l2], -1)[ins]  # overspill pixels: the triangle's plane continued, not clamped to its edge
    L = np.clip(Lx, 0, 1)
    L /= L.sum(1, keepdims=True)
    tv = tris[i]
    pos_ = Lx @ vco[tv]
    puv = texel_metric(pos_)
    pp = P[ins].astype(int)
    core[pp_all[own, 1], pp_all[own, 0]] = True
    c_, ink_ = shade(pos_, L @ vnr[tv], L @ dist[tv] * 1000, np.round(L @ kinds[tv]), puv)
    img[pp[:, 1], pp[:, 0]] = c_
    inkimg[pp[:, 1], pp[:, 0]] = ink_
    aoimg[pp[:, 1], pp[:, 0]] = L @ vao[tv]
    written[pp[:, 1], pp[:, 0]] = True
    if 'normal_tile' in kit:
        nimg[pp[:, 1], pp[:, 0]] = sample(kit['normal_tile'], puv / tile_m)[:, :3]
    if 'roughness_tile' in kit:
        rimg[pp[:, 1], pp[:, 0]] = sample(kit['roughness_tile'], puv / tile_m)[:, 0]
if 'pattern_tile' not in kit:
    img += ((np.random.default_rng(0).random((TH_, TW)) - 0.5) * 0.006)[..., None]  # a trace of fabric grain
img = np.clip(img, 0, 1)
# edge padding: grow every pattern piece 12 px (final) into the empty canvas around it, so texture filtering and
# mipmaps at the seams pick up the piece's own colours instead of the background
for _ in range(12 * SS):
    grow = ~written & (np.roll(written, 1, 0) | np.roll(written, -1, 0) | np.roll(written, 1, 1) | np.roll(written, -1, 1))
    if not grow.any():
        break
    for arr in (img, nimg, rimg, inkimg, aoimg):
        acc = np.zeros_like(arr)
        cnt = np.zeros((TH_, TW))
        for sh in ((1, 0), (-1, 0), (1, 1), (-1, 1)):
            src = np.roll(written, sh[0], sh[1])
            acc[grow & src] += np.roll(arr, sh[0], sh[1])[grow & src]
            cnt[grow & src] += 1
        arr[grow] = acc[grow] / (cnt[grow][:, None] if arr.ndim == 3 else cnt[grow])
    written |= grow
# average the 2x painting down to the final size (a box filter per output pixel)
TW, TH_ = TW // SS, TH_ // SS
img = img[:TH_ * SS, :TW * SS].reshape(TH_, SS, TW, SS, 3).mean((1, 3))
nimg = nimg[:TH_ * SS, :TW * SS].reshape(TH_, SS, TW, SS, 3).mean((1, 3))
nimg = (nimg - 0.5) / np.maximum(np.linalg.norm(nimg - 0.5, axis=-1, keepdims=True), 1e-6) * 0.5 + 0.5
rimg = rimg[:TH_ * SS, :TW * SS].reshape(TH_, SS, TW, SS).mean((1, 3))
inkimg = inkimg[:TH_ * SS, :TW * SS].reshape(TH_, SS, TW, SS).mean((1, 3))
aoimg = aoimg[:TH_ * SS, :TW * SS].reshape(TH_, SS, TW, SS).mean((1, 3))
# the ink layer: printed graphics are smoother than the cotton (spec ink_roughness), can be metallic foil
# (spec graphic_metallic), and stand a fraction of a millimetre proud of the knit (spec ink_height_mm): the knit is
# flattened under the ink and the ink's edge is raised in the normal map
ink_r = float(kit.get('ink_roughness', 0.55))
rimg = rimg * (1 - inkimg) + ink_r * inkimg
metal_amt = float(kit.get('graphic_metallic', 0) or 0)
mimg = (inkimg * metal_amt).astype(np.float32)
ink_h = float(kit.get('ink_height_mm', 0.3)) / (1000 / PPM * SS)  # height in texels of the final map
gxh = (np.roll(inkimg, -1, 1) - np.roll(inkimg, 1, 1)) * 0.5 * ink_h
gyh = (np.roll(inkimg, -1, 0) - np.roll(inkimg, 1, 0)) * 0.5 * ink_h
nk = nimg * 2 - 1
nk[..., 0] = nk[..., 0] * (1 - 0.7 * inkimg) - gxh
nk[..., 1] = nk[..., 1] * (1 - 0.7 * inkimg) - gyh
nimg = (nk / np.maximum(np.linalg.norm(nk, axis=-1, keepdims=True), 1e-6)) * 0.5 + 0.5


def save_img(name, arr, non_color=False):
    im = bpy.data.images.new(name, TW, TH_, alpha=False)
    if non_color:
        im.colorspace_settings.name = 'Non-Color'
    a3 = arr if arr.ndim == 3 else np.repeat(arr[..., None], 3, -1)
    im.pixels.foreach_set(np.concatenate([a3, np.ones((TH_, TW, 1), np.float32)], -1).astype(np.float32).ravel())
    im.filepath_raw = str(fitted / f'{name}.png')
    im.file_format = 'PNG'
    im.save()
    return im


pimg = save_img(f'{a.key}_albedo', img)
mat = bpy.data.materials.new(f'{a.key}_fabric')
mat.use_nodes = True
nt = mat.node_tree
bsdf = nt.nodes['Principled BSDF']
tn = nt.nodes.new('ShaderNodeTexImage')
tn.image = pimg
nt.links.new(tn.outputs['Color'], bsdf.inputs['Base Color'])
bsdf.inputs['Roughness'].default_value = float(kit.get('roughness', 0.9))
bsdf.inputs['Metallic'].default_value = 0.0
if kit:
    # glTF packs these as one occlusion / roughness / metallic (ORM) set plus a normal map
    rn = nt.nodes.new('ShaderNodeTexImage')
    rn.image = save_img(f'{a.key}_roughness', rimg, non_color=True)
    nt.links.new(rn.outputs['Color'], bsdf.inputs['Roughness'])
    if metal_amt > 0:
        mn = nt.nodes.new('ShaderNodeTexImage')
        mn.image = save_img(f'{a.key}_metallic', mimg, non_color=True)
        nt.links.new(mn.outputs['Color'], bsdf.inputs['Metallic'])
    nn = nt.nodes.new('ShaderNodeTexImage')
    nn.image = save_img(f'{a.key}_normal', nimg, non_color=True)
    nm_ = nt.nodes.new('ShaderNodeNormalMap')
    nm_.inputs['Strength'].default_value = float(kit.get('normal_strength', 1.0))
    nt.links.new(nn.outputs['Color'], nm_.inputs['Color'])
    nt.links.new(nm_.outputs['Normal'], bsdf.inputs['Normal'])
    an = nt.nodes.new('ShaderNodeTexImage')
    an.image = save_img(f'{a.key}_ao', aoimg, non_color=True)
    ng = bpy.data.node_groups.get('glTF Material Output') or bpy.data.node_groups.new('glTF Material Output', 'ShaderNodeTree')
    if 'Occlusion' not in [it.name for it in ng.interface.items_tree]:
        ng.interface.new_socket('Occlusion', in_out='INPUT', socket_type='NodeSocketFloat')
    gn = nt.nodes.new('ShaderNodeGroup')
    gn.node_tree = ng
    sep = nt.nodes.new('ShaderNodeSeparateColor')
    nt.links.new(an.outputs['Color'], sep.inputs['Color'])
    nt.links.new(sep.outputs['Red'], gn.inputs['Occlusion'])
me.materials.clear()
me.materials.append(mat)
for attr in ('edge_dist', 'edge_kind'):
    me.attributes.remove(me.attributes[attr])

# ---- 7. skinned to the rig with the body's own weights; written like a step-6 piece
F.attach(shell, arm)
bco_e, _ = F.world_verts(body, evaluated=True)
bn = np.array([(body.matrix_world.to_3x3() @ v.normal).normalized()[:] for v in body.data.vertices])
covered = F.covered_body_verts(bco_e, bn, [shell])
name = out_dir.name
shell.name = f'{name}__top__{a.key}'
bpy.ops.object.select_all(action='DESELECT')
for o in (arm, shell):
    o.select_set(True)
bpy.context.view_layer.objects.active = arm
stem = f'{name}__{a.key}'
bpy.ops.export_scene.gltf(filepath=str(fitted / f'{stem}.glb'), export_format='GLB', use_selection=True,
                          export_skins=True, export_animations=False, export_morph=False, export_attributes=True)
params = {k: v for k, v in vars(a).items() if k not in ('out',)}
params['hem_z_m'] = round(float(hem_z), 4)
params['hem_band_top_z_m'] = round(float(hem_z + a.hem_band_cm / 100), 4)
desc = (f"Fitted body-shell {'scoop-neck' if a.neck == 'scoop' else 'crew-neck'} "
        f"{'tank' if a.sleeve <= 0 else 'tee'} (Bitmoji-style): made from the {a.base} body surface, "
        f"{a.offset_mm:g} mm off the skin, design in the texture")
manifest = {'outfit': name, 'base': a.base, 'rest_pose': 'T-pose', 'meshes': 'body shell (shell_garment.py)',
            'pieces': {a.key: {'slot': 'top', 'layer': a.layer, 'rigid': False, 'rigid_bones': None,
                               'fit': {'slot': 'top', 'shell': params, 'fit_pose': {}, 'rest_copy_max_mm': 0.0},
                               'files': [f'{stem}.glb'], 'body_verts_covered': covered,
                               'hidden_verts_while_under': {}}}}
(fitted / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
(out_dir / 'outfit.json').write_text(json.dumps({'pieces': [{'key': a.key, 'slot': 'top', 'description': desc,
                                                             'shell': params}]}, indent=2), encoding='utf-8')
bpy.ops.wm.save_as_mainfile(filepath=str(fitted / f'{name}__{a.base}.blend'))
print(f'[shell] {a.key}: {len(me.vertices)} verts, {len(covered)} body verts covered -> {fitted / (stem + ".glb")}',
      flush=True)
