"""Skin-tight bottoms made FROM THE BODY (leggings, capris, bike shorts): the base's own skin surface from the waist
down, cut at a level waistline and a level leg hem, smoothed a little, offset a hair off the skin. Fit is exact by
construction (the body's own skin weights, fit pose = rest pose); the design lives in the texture.

One system, cut by two numbers:
  --rise-cm   waistline height above the Hips joint (high-rise ~9, mid ~6)
  --leg       how far down the leg: 0 = at the crotch, 1 = at the ankle (bike shorts ~0.3, capris ~0.72, full 1)

Texture: printed FABRIC (legging_kit.py: Codex paints leg_print.png, the yardage for one leg of the LONGEST, highest
pair; every shorter cut uses less of it). Each leg is cut from it like a real pattern piece: the fabric's centre column
runs down the outside of the leg, its left half is the front, and the edges are the seams (inside leg, centre front /
back). Both legs use the same fabric, mirrored, so the design is symmetric. Waistband, hem and seam stitching are
drawn by code.

Run: blender -b --factory-startup -P pipeline/tpose/legging_shell.py -- --base Xander --out Outfits/leggings-x
         --key x_leggings [--leg 1] [--rise-cm 9.5] [--offset-mm 1.5] [--thick-mm 1.2] [--kit <kit folder>] [--tex 2048]
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
ap.add_argument('--key', default='template_leggings')
ap.add_argument('--leg', type=float, default=1.0, help='0 = crotch, 1 = ankle')
ap.add_argument('--rise-cm', type=float, default=9.5, help='waistline above the Hips joint (9.5 covers the navel; the bottoms shell allows 11)')
ap.add_argument('--offset-mm', type=float, default=1.5)
ap.add_argument('--thick-mm', type=float, default=1.2)
ap.add_argument('--smooth', type=int, default=8)
ap.add_argument('--max-bridge-mm', type=float, default=8.0, help='how far the fabric may span a hollow (crotch, seat)')
ap.add_argument('--edge-smooth', type=int, default=25)
ap.add_argument('--waistband-cm', type=float, default=5.0)
ap.add_argument('--smooth-body', type=int, default=1, help='offset from a smooth body (1) or the raw low-poly one (0, stripes)')
ap.add_argument('--max-ripple-mm', type=float, default=0.9, help='fail if the fabric keeps facet ripples above this')
ap.add_argument('--color', default='0.10,0.10,0.11')
ap.add_argument('--tex', type=int, default=2048, help='texture width in px (height keeps the layout aspect)')
ap.add_argument('--kit', default='', help='texture kit folder (legging_kit.py)')
a = ap.parse_args(sys.argv[sys.argv.index('--') + 1:])

FAB_W = FAB_H = 0.80          # leg_print.png covers 80 x 80 cm of fabric
FAB_TOP_ABOVE_HIPS = 0.11     # the fabric's top edge: the highest rise any cut uses (the bottoms shell limit)

out_dir = Path(a.out).resolve()
fitted = out_dir / '06_fitted'
fitted.mkdir(parents=True, exist_ok=True)
lm = json.loads((ROOT / 'Bases' / f'{a.base}.json').read_text())['landmarks']
J = {k: np.array(v) for k, v in lm.items()}
arm, body, _ = F.load_base(a.base)
for pb in arm.pose.bones:
    pb.matrix_basis.identity()
bpy.context.view_layer.update()

hips_z = J['Hips'][2]
waist_z = hips_z + a.rise_cm / 100
crotch_joint_z = J['LeftUpLeg'][2]
ankle_z = J['LeftFoot'][2] + 0.02
leg_z = crotch_joint_z - a.leg * (crotch_joint_z - ankle_z)
fab_top = hips_z + FAB_TOP_ABOVE_HIPS

# ---- 1. a copy of the body surface (rest pose) with its skin weights, waist to hem
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
for g in list(shell.vertex_groups):
    if g.name not in arm.data.bones:
        shell.vertex_groups.remove(g)
bm = bmesh.new()
bm.from_mesh(shell.data)
drop = [f for f in bm.faces if not (leg_z - 0.03 < f.calc_center_median().z < waist_z + 0.04 and abs(f.calc_center_median().x) < 0.3)]
bmesh.ops.delete(bm, geom=drop, context='FACES')
bm.to_mesh(shell.data)
bm.free()
# ---- 2. fine smooth subdivision (Catmull-Clark: linear cuts keep the body's edge loops as faint ridges)
ss = shell.modifiers.new('smooth_subdiv', 'SUBSURF')
ss.levels = ss.render_levels = 2
bpy.context.view_layer.objects.active = shell
shell.select_set(True)
bpy.ops.object.modifier_apply(modifier='smooth_subdiv')
bm = bmesh.new()
bm.from_mesh(shell.data)
bmesh.ops.triangulate(bm, faces=bm.faces[:])
# ---- 3. cuts: a level waistline and a level hem across both legs (the legs hang straight down)
for co, no in (((0, 0, waist_z), (0, 0, 1)), ((0, 0, leg_z), (0, 0, -1))):
    bmesh.ops.bisect_plane(bm, geom=bm.verts[:] + bm.edges[:] + bm.faces[:], plane_co=Vector(co), plane_no=Vector(no),
                           clear_outer=True)
bm.verts.ensure_lookup_table()
seen, best = set(), []
for v in bm.verts:  # the main piece only
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

# ---- 4. smooth the skin's small anatomy away, keep the fabric between off and off + max_bridge from the skin: it hugs
# every convex form and spans hollows (seat, crotch, behind the knee) by at most max_bridge, never sinks in
bco, bpolys = F.world_verts(body, evaluated=True)
bbvh = F.bvh_of(bco, bpolys)                  # the real skin (faceted): occlusion, covered skin, reports
off = a.offset_mm / 1000
# The body is low-poly (flat faces about 2 cm across). Fabric held a fixed distance off THAT surface takes every flat
# face and crease into its own shape, and skin-tight it shows as lengthwise stripes down the legs ("watermelon
# stripes", the same thing the tee sleeves had). So the fabric is held off a SMOOTH body instead (the same skin,
# Catmull-Clark subdivided twice), by the ease plus however far the real skin's corners stand out past the smooth one
# nearby (the most within 4 cm, blurred over the fabric): a gently varying distance, and no corner of the real skin is
# ever outside the fabric (so all of it stays hidden under it).
from mathutils.kdtree import KDTree  # noqa: E402
if a.smooth_body:
    _bm = bmesh.new()
    for p_ in bco:
        _bm.verts.new(Vector(p_))
    _bm.verts.ensure_lookup_table()
    for p_ in bpolys:
        try:
            _bm.faces.new([_bm.verts[i] for i in p_])
        except ValueError:
            pass
    bmesh.ops.delete(_bm, geom=[f for f in _bm.faces if not (leg_z - 0.12 < f.calc_center_median().z < waist_z + 0.12)],
                     context='FACES')
    _me = bpy.data.meshes.new('smooth_body')
    _bm.to_mesh(_me)
    _bm.free()
    _ob = bpy.data.objects.new('smooth_body', _me)
    bpy.context.scene.collection.objects.link(_ob)
    _sd = _ob.modifiers.new('cc', 'SUBSURF')
    _sd.levels = 2
    _eo = _ob.evaluated_get(bpy.context.evaluated_depsgraph_get())
    _ev = _eo.to_mesh()
    sbvh = BVHTree.FromPolygons([v.co.copy() for v in _ev.vertices], [tuple(p_.vertices) for p_ in _ev.polygons])
    _eo.to_mesh_clear()
    bpy.data.objects.remove(_ob)
else:
    sbvh = bbvh
_sel = [i for i, p_ in enumerate(bco) if leg_z - 0.06 < p_[2] < waist_z + 0.06]
dev_co = np.asarray(bco)[_sel]
dev = np.zeros(len(dev_co))
for i, p_ in enumerate(dev_co):
    loc, nrm, _, _ = sbvh.find_nearest(Vector(p_))
    if loc is not None:
        dev[i] = max(0.0, (Vector(p_) - loc).dot(nrm))
dkd = KDTree(len(dev_co))
for i, p_ in enumerate(dev_co):
    dkd.insert(Vector(p_), i)
dkd.balance()
print(f'[legs] skin corners stand out past the smooth body: median {np.median(dev) * 1000:.1f} max {dev.max() * 1000:.1f} mm',
      flush=True)
NEED = {}


def settle(v):
    loc, nrm, _, _ = sbvh.find_nearest(v.co)
    if loc is None:
        return
    need = NEED.get(v, off)
    side = (v.co - loc).dot(nrm)
    if side < need:  # too close / inside: out along its OWN normal
        v.co = v.co + v.normal * (need - side)
    elif (v.co - loc).length > need + a.max_bridge_mm / 1000:  # spanning a hollow too far: back toward the skin
        v.co = loc + (v.co - loc).normalized() * (need + a.max_bridge_mm / 1000)


def edge_z(co):  # boundary loops stay exactly level
    return waist_z if abs(co.z - waist_z) < 0.006 else leg_z if abs(co.z - leg_z) < 0.006 else None


# the distance each point of the fabric keeps off the smooth body: the ease plus the local corner allowance, blurred
for v in bm.verts:
    near_ = dkd.find_range(v.co, 0.04)
    NEED[v] = off + (max(dev[j] for _, j, _ in near_) if near_ and a.smooth_body else 0.0)
for _ in range(30):
    NEED = {v: 0.5 * NEED[v] + 0.5 * sum(NEED[e.other_vert(v)] for e in v.link_edges) / max(1, len(v.link_edges))
            for v in bm.verts}
for it in range(a.smooth):
    inner = [v for v in bm.verts if not v.is_boundary]
    bmesh.ops.smooth_vert(bm, verts=inner, factor=0.5, use_axis_x=True, use_axis_y=True, use_axis_z=True)
    bm.normal_update()
    for v in bm.verts:
        settle(v)
for it in range(a.edge_smooth):
    bnd = [v for v in bm.verts if v.is_boundary]
    newco = {}
    for v in bnd:
        nb = [e.other_vert(v) for e in v.link_edges if e.is_boundary]
        if len(nb) == 2:
            c_ = v.co * 0.5 + (nb[0].co + nb[1].co) * 0.25
            ez = edge_z(v.co)
            if ez is not None:
                c_.z = ez
            newco[v] = c_
    for v, c_ in newco.items():
        v.co = c_
    ring = {e.other_vert(v) for v in bnd for e in v.link_edges if not e.other_vert(v).is_boundary}
    bmesh.ops.smooth_vert(bm, verts=list(ring), factor=0.3, use_axis_x=True, use_axis_y=True, use_axis_z=True)
bm.normal_update()
for v in bm.verts:
    settle(v)
bm.normal_update()
bm.to_mesh(shell.data)
bm.free()
me = shell.data
me.update()
sa = me.attributes.new('_shell', 'FLOAT', 'POINT')  # body-made piece: exported as PNG at full size (export_web)
sa.data.foreach_set('value', np.ones(len(me.vertices), np.float32))

# a soft rolled bead along the hem, and the waistband standing 0.8 mm proud of the leg below it
vco = np.array([v.co[:] for v in me.vertices])
vn_ = np.array([v.normal[:] for v in me.vertices])
d_hem = vco[:, 2] - leg_z
d_wst = waist_z - vco[:, 2]
wb_m = a.waistband_cm / 100
band = 0.0008 * np.clip((wb_m - d_wst) / 0.004 + 0.5, 0, 1)
bead = 0.001 * np.exp(-((np.minimum(d_hem, d_wst) - 0.0025) / 0.0018) ** 2)
me.vertices.foreach_set('co', (vco + vn_ * (band + bead)[:, None]).ravel())
me.update()
dists = np.array([bbvh.find_nearest(Vector(p))[3] for p in vco])
# facet ripple: in 2 cm slices round each leg, the sharpest crease in the fabric's outline (the bend between
# neighbouring 3 degree samples; a smooth leg bends gently, the body's flat faces meet in creases) - what the eye reads
# as lengthwise stripes. And no corner of the real skin may sit outside the fabric.
gbvh0 = BVHTree.FromPolygons([Vector(p) for p in vco], [tuple(pl.vertices) for pl in me.polygons])
ripple = []
for sgn in (1, -1):
    ax_, ay_ = (J['LeftUpLeg'] if sgn > 0 else J['RightUpLeg'])[:2]
    for z in np.arange(leg_z + 0.03, min(waist_z, J['LeftUpLeg'][2] - 0.08), 0.02):
        R = np.zeros(120)
        for k_, t_ in enumerate(np.linspace(-np.pi, np.pi, 120, endpoint=False)):   # rays out from the leg's axis
            hit = gbvh0.ray_cast(Vector((ax_, ay_, z)), Vector((math.cos(t_), math.sin(t_), 0)), 0.3)
            R[k_] = hit[3] if hit[0] is not None else -1
        if (R < 0).any():
            continue
        ripple.append(np.abs(np.roll(R, 1) - 2 * R + np.roll(R, -1)).max())   # creases: kinks between 3 degree steps
ripple_mm = float(np.percentile(ripple, 90) * 1000) if ripple else 0.0
outside = 0
for p_ in dev_co:
    if leg_z + 0.01 < p_[2] < waist_z - 0.01:
        hit = gbvh0.find_nearest(Vector(p_))
        loc_s, nrm_s, _, _ = sbvh.find_nearest(Vector(p_))
        if hit[0] is not None and loc_s is not None and (Vector(p_) - hit[0]).dot(nrm_s) > 0 and                 (Vector(p_) - loc_s).dot(nrm_s) > (hit[0] - loc_s).dot(nrm_s):
            outside += 1
print(f'[legs] facet ripple p90 {ripple_mm:.2f} mm over {len(ripple)} slices (limit {a.max_ripple_mm}); '
      f'skin corners outside the fabric: {outside}', flush=True)
if a.smooth_body and (ripple_mm > a.max_ripple_mm or outside):
    raise SystemExit(f'[legs] {a.key}: facet ripple {ripple_mm:.2f} mm or {outside} skin corners outside - stripes or poke-through')
print(f'[legs] {a.key}: waist {waist_z:.3f} hem {leg_z:.3f} m; off the skin median {np.median(dists) * 1000:.1f} '
      f'p99 {np.percentile(dists, 99) * 1000:.1f} max {dists.max() * 1000:.1f} mm', flush=True)

# ---- 5. fabric thickness (inward; the rim closes the cut edges)
sol = shell.modifiers.new('thickness', 'SOLIDIFY')
sol.thickness = a.thick_mm / 1000
sol.offset = -1.0
sol.use_rim = True
bpy.ops.object.modifier_apply(modifier='thickness')
me = shell.data
bm = bmesh.new()
bm.from_mesh(me)
bmesh.ops.triangulate(bm, faces=bm.faces[:])
bm.to_mesh(me)
bm.free()
for nm in ('custom_normal', 'sharp_edge', 'sharp_face'):
    if nm in me.attributes:
        me.attributes.remove(me.attributes[nm])
me.shade_smooth()

# ---- 6. texture: each leg unrolled round its own axis by true arc length (0 = the outside of the leg, + toward the
# front), height measured down from the fabric's top edge. UVs place the two legs side by side at true scale.
SS = 2


def hexrgb(h, fallback):
    if not h:
        return np.array(fallback, float)
    h = h.lstrip('#')
    return np.array([int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)], float)


def load_px(p):  # bottom row first (Blender's order), RGBA
    im = bpy.data.images.load(str(p))
    return np.array(im.pixels[:], np.float32).reshape(im.size[1], im.size[0], 4)


kit = {}
if a.kit:
    kd_ = Path(a.kit).resolve()
    kit = json.loads((kd_ / 'spec.json').read_text(encoding='utf-8'))
    for nm in ('leg_print', 'normal_tile', 'roughness_tile'):
        if (kd_ / f'{nm}.png').exists():
            kit[nm] = load_px(kd_ / f'{nm}.png')
    for d_ in kit.get('decals', []):
        d_['px'] = load_px(kd_ / d_['image'])[::-1]  # top row first
    if kit.get('waistband_text'):
        kit['waistband_text']['px'] = load_px(kd_ / kit['waistband_text']['image'])[::-1]
col = hexrgb(kit.get('base_color'), [float(c) for c in a.color.split(',')])
trim = hexrgb(kit.get('trim_color'), col * 0.9)
stitch = hexrgb(kit.get('stitch_color'), col * 0.8 + 0.1)
tile_m = float(kit.get('knit_tile_cm', 24)) / 100

tris = np.array([p.vertices[:] for p in me.polygons])
fn = np.array([p.normal[:] for p in me.polygons])
vco = np.array([v.co[:] for v in me.vertices])
vnr = np.array([v.normal[:] for v in me.vertices])
cen = vco[tris].mean(1)
# the crotch: the lowest point of the skin between the legs (the centre seams run above it, the inside-leg seams below)
_h = bbvh.ray_cast(Vector((0, 0.0, 0.3)), Vector((0, 0, 1)), 1.0)  # from between the shins straight up
crotch_z = _h[0].z if _h[0] is not None else crotch_joint_z - 0.06
AXY = {1: J['LeftUpLeg'][:2], -1: J['RightUpLeg'][:2]}  # each leg's axis (the legs hang straight down)

# arc-length tables per leg: S[side][k, i] = arc from the outside of the leg at height ZL[k], angle PH[i]
NPH = 360
PH = np.linspace(-np.pi, np.pi, NPH + 1)
phc = (PH[:-1] + PH[1:]) / 2
ZL = np.arange(leg_z - 0.01, waist_z + 0.015, 0.005)


def leg_phi(P, sgn):  # 0 = outside of the leg, +pi/2 = front, +-pi = inside (the inside-leg seam)
    ax_, ay_ = AXY[sgn]
    return np.arctan2(-(P[:, 1] - ay_), sgn * (P[:, 0] - ax_))


S = {}
for sgn in (1, -1):
    m_ = np.sign(vco[:, 0]) == sgn
    P_ = vco[m_]
    ph_ = leg_phi(P_, sgn)
    r_ = np.hypot(P_[:, 0] - AXY[sgn][0], P_[:, 1] - AXY[sgn][1])
    T = np.zeros((len(ZL), NPH + 1))
    for k, z in enumerate(ZL):
        mm = np.abs(P_[:, 2] - z) < 0.008
        if mm.sum() < 20:
            T[k] = T[k - 1] if k else PH * 0.06
            continue
        R = np.full(NPH, -1.0)
        np.maximum.at(R, ((ph_[mm] + np.pi) / (2 * np.pi) * NPH).astype(int) % NPH, r_[mm])
        ok = R > 0
        R = np.interp(np.arange(NPH), np.arange(NPH)[ok], R[ok], period=NPH)
        R = np.convolve(np.r_[R[-4:], R, R[:4]], np.ones(9) / 9, mode='valid')
        Q = np.stack([R * np.cos(phc), R * np.sin(phc)], -1)
        C = np.r_[0.0, np.cumsum(np.linalg.norm(np.diff(Q, axis=0), axis=1))]
        T[k] = np.interp(PH, phc, C, left=C[0] - R[0] * np.pi / NPH, right=C[-1] + R[-1] * np.pi / NPH) - np.interp(0.0, phc, C)
    S[sgn] = T


def leg_uv(P, sgn):
    """Fabric coordinates in metres: u = arc length from the outside of the leg (+ toward the front), v = down from the
    fabric's top edge."""
    T = S[sgn]
    ph = leg_phi(P, sgn)
    fk = np.clip((P[:, 2] - ZL[0]) / 0.005, 0, len(ZL) - 1.001)
    k0 = fk.astype(int)
    tk = fk - k0
    fi = np.clip((ph + np.pi) / (2 * np.pi) * NPH, 0, NPH - 0.001)
    i0 = fi.astype(int)
    ti = fi - i0
    s0 = T[k0, i0] * (1 - ti) + T[k0, i0 + 1] * ti
    s1 = T[k0 + 1, i0] * (1 - ti) + T[k0 + 1, i0 + 1] * ti
    return np.stack([s0 * (1 - tk) + s1 * tk, fab_top - P[:, 2]], -1)


def side_of(P):  # which leg piece a point belongs to: the centre seams are x = 0 (straight lines on the body)
    return np.where(P[:, 0] >= 0, 1, -1)


tri_side = side_of(cen)
tri_m = np.zeros((len(tris), 3, 2))
for sgn in (1, -1):
    m_ = tri_side == sgn
    tri_m[m_] = leg_uv(vco[tris[m_]].reshape(-1, 3), sgn).reshape(-1, 3, 2)
# a triangle straddling the inside-leg seam (+-pi): keep it on one side (its back-side corners go round once more)
for i in range(len(tris)):
    ph_t = leg_phi(vco[tris[i]], tri_side[i])
    if np.ptp(ph_t) > np.pi:
        T = S[tri_side[i]]
        k = int(np.clip((cen[i, 2] - ZL[0]) / 0.005, 0, len(ZL) - 1))
        tri_m[i, ph_t < 0, 0] += T[k, -1] - T[k, 0]
# layout: the left leg's piece, then the right leg's, side by side, true scale
U_LO, U_HI = tri_m[:, :, 0].min() - 0.01, tri_m[:, :, 0].max() + 0.01
V_LO, V_HI = tri_m[:, :, 1].min() - 0.01, tri_m[:, :, 1].max() + 0.01
GAP = 0.02
CW = 2 * (U_HI - U_LO) + GAP
CH = V_HI - V_LO
TW = a.tex * SS
TH_ = int(round(TW * CH / CW / 8)) * 8
PPM = TW / CW
ORIG = {1: 0.0, -1: (U_HI - U_LO) + GAP}
uv_loops = np.zeros_like(tri_m)
for sgn in (1, -1):
    m_ = tri_side == sgn
    uv_loops[m_, :, 0] = (ORIG[sgn] + tri_m[m_, :, 0] - U_LO) / CW
    uv_loops[m_, :, 1] = 1 - (tri_m[m_, :, 1] - V_LO) / CH       # the fabric's top at the top of the texture
uv_loops = np.clip(uv_loops, 0.0005, 0.9995)
for l in list(me.uv_layers):
    me.uv_layers.remove(l)
uvl = me.uv_layers.new(name='UVMap')
uvl.data.foreach_set('uv', uv_loops.astype(np.float32).ravel())
print(f'[legs] texture {TW // SS}x{TH_ // SS} px, {PPM / SS / 1000:.2f} px/mm; u {U_LO:+.3f}..{U_HI:+.3f} v {V_LO:.3f}..{V_HI:.3f} m; '
      f'crotch z {crotch_z:.3f}', flush=True)


def sample(tex, uvm):  # bilinear, tiling, bottom-row-first array; uvm in tiles
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


def texel(P):
    """Colour, print coordinates and seam distance of surface points. Each point is placed by its OWN position (its own
    leg piece by x, its own angle), so seams are straight lines on the body, not triangle edges."""
    sd = side_of(P)
    m_ = np.zeros((len(P), 2))
    for sgn in (1, -1):
        k = sd == sgn
        if k.any():
            m_[k] = leg_uv(P[k], sgn)
    if 'leg_print' in kit:  # fabric x: centre = outside of the leg, left half = front; y from the top edge
        fx = np.clip(0.5 - m_[:, 0] / FAB_W, 0, 0.999)
        fy = np.clip(1 - m_[:, 1] / FAB_H, 0, 0.999)
        c = sample(kit['leg_print'], np.stack([fx, fy], -1))[:, :3].astype(float)
    else:
        c = np.broadcast_to(col, P.shape).copy()
    # seams (mm): the centre front / back seam above the crotch, the inside-leg seam below
    half = np.zeros(len(P))
    for sgn in (1, -1):
        k = sd == sgn
        if k.any():
            T = S[sgn]
            fk = np.clip((P[k, 2] - ZL[0]) / 0.005, 0, len(ZL) - 1).astype(int)
            half[k] = np.minimum(T[fk, -1] - m_[k, 0], m_[k, 0] - T[fk, 0])
    d_seam = np.where(P[:, 2] > crotch_z + 0.01, np.abs(P[:, 0]), half) * 1000
    return c, m_, d_seam


px_mm = 1000 / PPM
# ---- prints (spec "decals"): logos projected straight onto the surface from one side, at a named spot
#   side: front | back | left (the wearer's left hip / thigh, seen from the side) | left_front (front-outer of the left
#   thigh, seen from 35 deg round); z: waist | hips | hem, plus dz_cm; width_cm. Waistband text (spec "waistband_text"):
#   a wordmark repeated round the waistband by true arc length.
UP = np.array([0.0, 0.0, 1.0])
VIEW = {'front': np.array([0.0, 1, 0]), 'back': np.array([0.0, -1, 0]), 'left': np.array([-1.0, 0, 0]),
        'left_front': np.array([-math.sin(math.radians(35)), math.cos(math.radians(35)), 0])}
ZREF = {'waist': waist_z - a.waistband_cm / 200, 'hips': hips_z, 'hem': leg_z}
for d_ in kit.get('decals', []):
    vd = VIEW[d_['side']]
    cx_ = 0.0 if d_['side'] in ('front', 'back') else AXY[1][0]
    d_['c'] = np.array([cx_, AXY[1][1], ZREF[d_['z']] + float(d_.get('dz_cm', 0)) / 100])
    d_['vd'], d_['right'] = vd, np.cross(vd, UP)
    d_['w'] = float(d_['width_cm']) / 100
# the waistband's arc length round the body (from the centre front, + toward +x), for the repeated text
wb_c = waist_z - a.waistband_cm / 200
_m = np.abs(vco[:, 2] - wb_c) < 0.01
WCY = float(np.median(vco[_m, 1])) if _m.any() else 0.0
_th = np.arctan2(vco[_m, 0], -(vco[_m, 1] - WCY))
_r = np.hypot(vco[_m, 0], vco[_m, 1] - WCY)
_R = np.full(NPH, -1.0)
np.maximum.at(_R, ((_th + np.pi) / (2 * np.pi) * NPH).astype(int) % NPH, _r)
_ok = _R > 0
_R = np.interp(np.arange(NPH), np.arange(NPH)[_ok], _R[_ok], period=NPH) if _ok.any() else np.full(NPH, 0.15)
_Q = np.stack([_R * np.sin(phc), _R * np.cos(phc)], -1)
WARC = np.interp(PH, phc, np.r_[0.0, np.cumsum(np.linalg.norm(np.diff(_Q, axis=0), axis=1))])
WARC -= np.interp(0.0, PH, WARC)
WCIRC = float(WARC[-1] - WARC[0])


def prints(c, P, nrm):
    """Logos and waistband text over the fabric colour; returns the colour and the ink coverage (0..1)."""
    ink = np.zeros(len(P))
    for d_ in kit.get('decals', []):
        g = d_['px']
        gh_, gw_ = g.shape[:2]
        rel = P - d_['c']
        gx = rel @ d_['right'] / d_['w'] + 0.5
        gy = 0.5 - rel @ UP / (d_['w'] * gh_ / gw_)
        on = (nrm @ -d_['vd'] > 0.3) & (gx >= 0) & (gx < 1) & (gy >= 0) & (gy < 1)
        if on.any():
            gp = sample(g[::-1], np.stack([gx[on], 1 - gy[on]], -1) * 0.9999)
            c[on] = c[on] * (1 - gp[:, 3:4]) + gp[:, :3] * gp[:, 3:4]
            ink[on] = np.maximum(ink[on], gp[:, 3])
    wt = kit.get('waistband_text')
    if wt:
        g = wt['px']
        gh_, gw_ = g.shape[:2]
        h_ = float(wt.get('height_cm', 2.0)) / 100
        per = h_ * gw_ / gh_ + float(wt.get('gap_cm', 3.0)) / 100
        n_ = max(1, round(WCIRC / per))
        th = np.arctan2(P[:, 0], -(P[:, 1] - WCY))
        s_ = np.interp(th, PH, WARC)
        cell = (s_ / (WCIRC / n_)) % 1.0 * (WCIRC / n_)          # metres into this repeat
        gx = (cell - (WCIRC / n_ - h_ * gw_ / gh_) / 2) / (h_ * gw_ / gh_)
        gy = 0.5 - (P[:, 2] - wb_c) / h_
        on = (gx >= 0) & (gx < 1) & (gy >= 0) & (gy < 1)
        if on.any():
            gp = sample(g[::-1], np.stack([gx[on], 1 - gy[on]], -1) * 0.9999)
            c[on] = c[on] * (1 - gp[:, 3:4]) + gp[:, :3] * gp[:, 3:4]
            ink[on] = np.maximum(ink[on], gp[:, 3])
    return c, ink



def line(dd, d0, half):
    return np.clip((half + px_mm / 2 - np.abs(dd - d0)) / px_mm, 0, 1)[:, None]


def shade(P, nrm):
    c, m_, d_seam = texel(P)
    dw = (waist_z - P[:, 2]) * 1000
    dh = (P[:, 2] - leg_z) * 1000
    wb = np.clip((a.waistband_cm * 10 - dw) / px_mm + 0.5, 0, 1)[:, None]  # the waistband in the trim colour
    c = c * (1 - wb) + trim * wb
    ws = np.maximum.reduce([line(dw, a.waistband_cm * 10 + 2.5, 0.35), line(dw, 6.0, 0.3),
                            line(dh, 7.0, 0.3), line(dh, 10.0, 0.3),                       # twin-needle hem
                            line(d_seam, 1.6, 0.3) * (dw > a.waistband_cm * 10)[:, None]])  # flatlock seams
    c = c * (1 - ws) + stitch * ws
    c, ink = prints(c, P, nrm)
    return c, m_, ink


img = np.broadcast_to(col, (TH_, TW, 3)).astype(np.float32).copy()
nimg = np.broadcast_to(np.array([0.5, 0.5, 1.0], np.float32), (TH_, TW, 3)).copy()
rimg = np.full((TH_, TW), float(kit.get('roughness', 0.6)), np.float32)
aoimg = np.ones((TH_, TW), np.float32)
inkimg = np.zeros((TH_, TW), np.float32)
written = np.zeros((TH_, TW), bool)
core = np.zeros((TH_, TW), bool)
near = np.array([bbvh.find_nearest(Vector(c))[0][:] for c in cen])
inner = np.einsum('ij,ij->i', fn, cen - near) < 0
# baked AO (12 rays within 4 cm against the garment and the body): soft shade in the crotch, behind the knees
gbvh = BVHTree.FromPolygons([Vector(p) for p in vco], [tuple(t) for t in tris])
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
        dw_ = q_ @ d_
        bd = 0.04
        for tree in (gbvh, bbvh):
            hit = tree.ray_cast(o_, dw_, 0.04)
            if hit[0] is not None and hit[3] < bd:
                bd = hit[3]
        blk += 1 - bd / 0.04
    vao[vi] = 1 - 0.55 * blk / len(AO_DIRS)
for i in np.argsort(~inner):  # inner faces first, outer faces painted over them
    Uv = uv_loops[i] * np.array([TW - 1, TH_ - 1])
    x0, y0 = np.floor(Uv.min(0)).astype(int) - 1
    x1, y1 = np.ceil(Uv.max(0)).astype(int) + 1
    xs, ys = np.meshgrid(np.arange(max(x0, 0), min(x1, TW - 1) + 1), np.arange(max(y0, 0), min(y1, TH_ - 1) + 1))
    Pp = np.stack([xs.ravel(), ys.ravel()], -1).astype(float)
    (ax_, ay_), (bx_, by_), (cx_, cy_) = Uv
    den = (by_ - cy_) * (ax_ - cx_) + (cx_ - bx_) * (ay_ - cy_)
    if abs(den) < 1e-9:
        continue
    l0 = ((by_ - cy_) * (Pp[:, 0] - cx_) + (cx_ - bx_) * (Pp[:, 1] - cy_)) / den
    l1 = ((cy_ - ay_) * (Pp[:, 0] - cx_) + (ax_ - cx_) * (Pp[:, 1] - cy_)) / den
    l2 = 1 - l0 - l1
    ins = (l0 >= -0.15) & (l1 >= -0.15) & (l2 >= -0.15)
    if not ins.any():
        continue
    own = (l0 >= -1e-3) & (l1 >= -1e-3) & (l2 >= -1e-3)
    pa = Pp.astype(int)
    ins &= own | ~core[pa[:, 1], pa[:, 0]]
    if not ins.any():
        continue
    Lx = np.stack([l0, l1, l2], -1)[ins]
    L = np.clip(Lx, 0, 1)
    L /= L.sum(1, keepdims=True)
    tv = tris[i]
    pos_ = Lx @ vco[tv]
    pp = Pp[ins].astype(int)
    core[pa[own, 1], pa[own, 0]] = True
    nv_ = L @ vnr[tv]
    c_, m_, ink_ = shade(pos_, nv_ / np.maximum(np.linalg.norm(nv_, axis=1, keepdims=True), 1e-9))
    img[pp[:, 1], pp[:, 0]] = c_
    inkimg[pp[:, 1], pp[:, 0]] = ink_
    aoimg[pp[:, 1], pp[:, 0]] = L @ vao[tv]
    written[pp[:, 1], pp[:, 0]] = True
    if 'normal_tile' in kit:
        nimg[pp[:, 1], pp[:, 0]] = sample(kit['normal_tile'], m_ / tile_m)[:, :3]
    if 'roughness_tile' in kit:
        rimg[pp[:, 1], pp[:, 0]] = sample(kit['roughness_tile'], m_ / tile_m)[:, 0]
img = np.clip(img, 0, 1)
for _ in range(12 * SS):  # edge padding
    grow = ~written & (np.roll(written, 1, 0) | np.roll(written, -1, 0) | np.roll(written, 1, 1) | np.roll(written, -1, 1))
    if not grow.any():
        break
    for arr in (img, nimg, rimg, aoimg, inkimg):
        acc = np.zeros_like(arr)
        cnt = np.zeros((TH_, TW))
        for sh in ((1, 0), (-1, 0), (1, 1), (-1, 1)):
            src = np.roll(written, sh[0], sh[1])
            acc[grow & src] += np.roll(arr, sh[0], sh[1])[grow & src]
            cnt[grow & src] += 1
        arr[grow] = acc[grow] / (cnt[grow][:, None] if arr.ndim == 3 else cnt[grow])
    written |= grow
TW, TH_ = TW // SS, TH_ // SS
img = img[:TH_ * SS, :TW * SS].reshape(TH_, SS, TW, SS, 3).mean((1, 3))
nimg = nimg[:TH_ * SS, :TW * SS].reshape(TH_, SS, TW, SS, 3).mean((1, 3))
nimg = (nimg - 0.5) / np.maximum(np.linalg.norm(nimg - 0.5, axis=-1, keepdims=True), 1e-6) * 0.5 + 0.5
rimg = rimg[:TH_ * SS, :TW * SS].reshape(TH_, SS, TW, SS).mean((1, 3))
aoimg = aoimg[:TH_ * SS, :TW * SS].reshape(TH_, SS, TW, SS).mean((1, 3))
inkimg = inkimg[:TH_ * SS, :TW * SS].reshape(TH_, SS, TW, SS).mean((1, 3))
# the ink layer: printed logos are smoother than the knit (spec ink_roughness), can be reflective / foil (spec
# graphic_metallic), and stand a fraction of a millimetre proud (spec ink_height_mm): knit flattened under the ink,
# the ink's edge raised in the normal map
rimg = rimg * (1 - inkimg) + float(kit.get('ink_roughness', 0.35)) * inkimg
metal_amt = float(kit.get('graphic_metallic', 0) or 0)
mimg = (inkimg * metal_amt).astype(np.float32)
ink_h = float(kit.get('ink_height_mm', 0.3)) / (1000 / PPM * SS)
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


mat = bpy.data.materials.new(f'{a.key}_fabric')
mat.use_nodes = True
nt = mat.node_tree
bsdf = nt.nodes['Principled BSDF']
tn = nt.nodes.new('ShaderNodeTexImage')
tn.image = save_img(f'{a.key}_albedo', img)
nt.links.new(tn.outputs['Color'], bsdf.inputs['Base Color'])
bsdf.inputs['Metallic'].default_value = 0.0
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
nm_.inputs['Strength'].default_value = float(kit.get('normal_strength', 0.5))
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

# ---- 7. skinned with the body's own weights; written like a step-6 piece
F.attach(shell, arm)
bco_e, _ = F.world_verts(body, evaluated=True)
bn = np.array([(body.matrix_world.to_3x3() @ v.normal).normalized()[:] for v in body.data.vertices])
covered = F.covered_body_verts(bco_e, bn, [shell])
name = out_dir.name
shell.name = f'{name}__bottom__{a.key}'
bpy.ops.object.select_all(action='DESELECT')
for o in (arm, shell):
    o.select_set(True)
bpy.context.view_layer.objects.active = arm
stem = f'{name}__{a.key}'
bpy.ops.export_scene.gltf(filepath=str(fitted / f'{stem}.glb'), export_format='GLB', use_selection=True,
                          export_skins=True, export_animations=False, export_morph=False, export_attributes=True)
params = {k: v for k, v in vars(a).items() if k not in ('out',)}
params.update(waist_z_m=round(float(waist_z), 4), hem_z_m=round(float(leg_z), 4))
kind_ = 'leggings' if a.leg > 0.85 else 'capris' if a.leg > 0.5 else 'bike shorts'
desc = f'Skin-tight body-shell {kind_}: made from the {a.base} body surface, {a.offset_mm:g} mm off the skin, design in the texture'
manifest = {'outfit': name, 'base': a.base, 'rest_pose': 'T-pose', 'meshes': 'body shell (legging_shell.py)',
            'pieces': {a.key: {'slot': 'bottom', 'layer': 1, 'rigid': False, 'rigid_bones': None,
                               'fit': {'slot': 'bottom', 'shell': params, 'fit_pose': {}, 'rest_copy_max_mm': 0.0},
                               'files': [f'{stem}.glb'], 'body_verts_covered': covered, 'hidden_verts_while_under': {}}}}
(fitted / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
(out_dir / 'outfit.json').write_text(json.dumps({'pieces': [{'key': a.key, 'slot': 'bottom', 'description': desc,
                                                             'shell': params}]}, indent=2), encoding='utf-8')
bpy.ops.wm.save_as_mainfile(filepath=str(fitted / f'{name}__{a.base}.blend'))
print(f'[legs] {a.key}: {len(me.vertices)} verts, {len(covered)} body verts covered -> {fitted / (stem + ".glb")}', flush=True)
