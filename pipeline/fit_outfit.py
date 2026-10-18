"""Fit an AssetHub V5 assembled outfit onto a Genies base avatar as modular, skinned wardrobe pieces.

Run:
  blender -b --factory-startup -P pipeline/fit_outfit.py -- --assembly <assembled.glb> --base Xander --out <dir>
                                                         [--map part=slot,part=slot] [--name outfit-name]

Steps (all automatic):
  1. Import the V5 assembly (AssetHub body + garments, A-pose) and the Genies base (.blend from export_bases.py).
  2. Pose the Genies arms/legs and fit scale + offset so the Genies body overlays the AssetHub body
     (grid search over arm/leg angles, similarity ICP for each).
  3. Bind every garment to the AssetHub body (Surface Deform), then shrinkwrap that body onto the posed
     Genies body; garments follow it.
  4. Resolve clipping in slot-layer order: each piece is pushed outside the body and every lower layer.
  5. Copy Genies skin weights to each piece, unpose everything back to the Genies T-pose, attach to the rig.
  6. Export one skinned .glb/.fbx per wardrobe slot, a manifest with slot/layer/hidden-body-region data,
     and QA renders (rest pose + a deformation test pose).
"""
import bpy, bmesh, sys, json, math, argparse, heapq
from pathlib import Path
from mathutils import Vector, Matrix
from mathutils.bvhtree import BVHTree
from mathutils.interpolate import poly_3d_calc
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
SLOTS = json.loads((ROOT / 'pipeline' / 'slots.json').read_text(encoding='utf-8'))

# AssetHub part keys -> wardrobe slot. Unlisted parts are matched by keyword; base_body is the stand-in body.
KEYWORDS = [('hair', 'hair'), ('hat', 'headwear'), ('cap', 'headwear'), ('jacket', 'outerwear'), ('coat', 'outerwear'),
            ('hoodie', 'top'), ('shirt', 'top'), ('tee', 'top'), ('sweater', 'top'), ('dress', 'fullbody'),
            ('pants', 'bottom'), ('trouser', 'bottom'), ('jean', 'bottom'), ('short', 'bottom'), ('skirt', 'bottom'),
            ('sock', 'legwear'), ('stocking', 'legwear'), ('shoe', 'footwear'), ('boot', 'footwear'), ('sneaker', 'footwear'),
            ('glove', 'hands'), ('bag', 'accessory'), ('belt', 'accessory')]


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument('--assembly', required=True)
    p.add_argument('--base', required=True)
    p.add_argument('--out', required=True)
    p.add_argument('--map', default='')
    p.add_argument('--name', default=None)
    return p.parse_args(sys.argv[sys.argv.index('--') + 1:])


def log(*a):
    print('[fit]', *a, flush=True)


def world_verts(obj, evaluated=False):
    if evaluated:
        dg = bpy.context.evaluated_depsgraph_get()
        ev = obj.evaluated_get(dg)
        me = ev.to_mesh()
        co = np.array([obj.matrix_world @ v.co for v in me.vertices])
        polys = [tuple(p.vertices) for p in me.polygons]
        ev.to_mesh_clear()
        return co, polys
    return np.array([obj.matrix_world @ v.co for v in obj.data.vertices]), [tuple(p.vertices) for p in obj.data.polygons]


def bake_world(obj):
    """Move the object's world transform into its mesh data and unparent it."""
    mw = obj.matrix_world.copy()
    obj.parent = None
    obj.data.transform(mw)
    obj.matrix_world = Matrix.Identity(4)


def bvh_of(co, polys):
    return BVHTree.FromPolygons([Vector(c) for c in co], polys, all_triangles=False)


# ---------------------------------------------------------------- import

def load_base(avatar):
    bpy.ops.wm.open_mainfile(filepath=str(ROOT / 'Bases' / f'{avatar}.blend'))
    arm = next(o for o in bpy.data.objects if o.type == 'ARMATURE')
    meshes = [o for o in bpy.data.objects if o.type == 'MESH']
    body = max(meshes, key=lambda o: len(o.data.vertices))
    return arm, body, meshes


def load_assembly(path):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(path))
    new = [o for o in bpy.data.objects if o not in before]
    parts = {}
    for o in new:
        if o.type != 'MESH':
            continue
        key = (o.parent.name if o.parent else o.name).split('.')[0]
        bake_world(o)
        o.name = f'AH_{key}'
        parts[key] = o
    for o in new:
        if o.type != 'MESH':
            bpy.data.objects.remove(o, do_unlink=True)
    return parts


# ---------------------------------------------------------------- pose + similarity fit

def rotate_bone_world(arm, bone_name, axis, angle):
    pb = arm.pose.bones[bone_name]
    A = arm.matrix_world
    head_w = A @ pb.head
    T = Matrix.Translation(head_w) @ Matrix.Rotation(angle, 4, axis) @ Matrix.Translation(-head_w)
    pb.matrix = A.inverted() @ T @ A @ pb.matrix
    bpy.context.view_layer.update()


def set_pose(arm, arm_deg, leg_deg):
    for pb in arm.pose.bones:
        pb.matrix_basis = Matrix.Identity(4)
    bpy.context.view_layer.update()
    rotate_bone_world(arm, 'LeftArm', 'Y', math.radians(arm_deg))
    rotate_bone_world(arm, 'RightArm', 'Y', -math.radians(arm_deg))
    rotate_bone_world(arm, 'LeftUpLeg', 'Y', -math.radians(leg_deg))
    rotate_bone_world(arm, 'RightUpLeg', 'Y', math.radians(leg_deg))


def similarity_icp(src, dst_bvh, dst_pts, s, t, iters=8):
    """Fit uniform scale s and translation t so s*src+t lies on dst. Symmetric nearest-point correspondences."""
    for _ in range(iters):
        moved = src * s + t
        fwd = np.array([dst_bvh.find_nearest(Vector(p))[0] for p in moved])
        mv_bvh = BVHTree.FromPoints([Vector(p) for p in moved]) if hasattr(BVHTree, 'FromPoints') else None
        a, g = [src], [fwd]
        if mv_bvh is None:
            from mathutils.kdtree import KDTree
            kd = KDTree(len(moved))
            for i, p in enumerate(moved):
                kd.insert(Vector(p), i)
            kd.balance()
            idx = [kd.find(Vector(q))[1] for q in dst_pts]
            a.append(src[idx]); g.append(dst_pts)
        A = np.concatenate(a); G = np.concatenate(g)
        am, gm = A.mean(0), G.mean(0)
        s = float(((A - am) * (G - gm)).sum() / ((A - am) ** 2).sum())
        t = gm - s * am
    moved = src * s + t
    err = np.mean([dst_bvh.find_nearest(Vector(p))[3] for p in moved])
    return s, t, float(err)


def fit_pose(arm, body, ah_body):
    ah, _ = world_verts(ah_body)
    # Leave the head out of the fit: hair volume and head shape differ between the two bodies.
    zmax = ah[:, 2].max()
    neck_z = ah[(ah[:, 2] > 0.7 * zmax) & (np.abs(ah[:, 0]) < 0.3)]
    widths = []
    for z in np.linspace(0.75 * zmax, 0.92 * zmax, 30):
        sl = ah[np.abs(ah[:, 2] - z) < 0.01 * zmax]
        sl = sl[np.abs(sl[:, 0]) < 0.15 * zmax]
        if len(sl):
            widths.append((np.abs(sl[:, 0]).max(), z))
    ah_neck = min(widths)[1]
    src = ah[ah[:, 2] < ah_neck][::3]
    head_z = (arm.matrix_world @ arm.pose.bones['Head'].head).z
    best = None
    for arm_deg in range(45, 86, 5):
        for leg_deg in (0, 3, 6, 9, 12):
            set_pose(arm, arm_deg, leg_deg)
            gco, gpolys = world_verts(body, evaluated=True)
            keep = gco[:, 2] < head_z
            bvh = bvh_of(gco, gpolys)
            s0 = head_z / ah_neck
            t0 = np.array([0.0, gco[keep, 1].mean() - s0 * src[:, 1].mean(), 0.0])
            s, t, err = similarity_icp(src, bvh, gco[keep][::2], s0, t0, iters=6)
            if best is None or err < best[0]:
                best = (err, arm_deg, leg_deg, s, t)
    err, arm_deg, leg_deg, s, t = best
    log(f'pose fit: arms {arm_deg} deg, legs {leg_deg} deg, scale {s:.4f}, offset {np.round(t, 4)}, mean err {err * 1000:.1f} mm')
    set_pose(arm, arm_deg, leg_deg)
    return {'arm_deg': arm_deg, 'leg_deg': leg_deg, 'scale': s, 'offset': t.tolist(), 'mean_err_m': err}


# ---------------------------------------------------------------- transfer garments

def apply_similarity(objs, s, t):
    M = Matrix.Translation(Vector(t)) @ Matrix.Scale(s, 4)
    for o in objs:
        o.data.transform(M)
        o.data.update()


def umeyama(src, dst):
    """Best rotation R, uniform scale s and translation t with s*R@src+t ~= dst."""
    ms, md = src.mean(0), dst.mean(0)
    a, b = src - ms, dst - md
    U, S, Vt = np.linalg.svd(b.T @ a / len(src))
    D = np.eye(3)
    D[2, 2] = np.sign(np.linalg.det(U @ Vt))
    R = U @ D @ Vt
    s = float(np.trace(np.diag(S) @ D) / (a ** 2).sum(1).mean())
    return R, s, md - s * R @ ms


def anchor_verts(ah_co, piece_co, piece_polys, reach=0.03):
    """Indices of AssetHub body vertices inside or within reach of a piece (e.g. the foot inside a shoe)."""
    bvh = bvh_of(piece_co, piece_polys)
    lo, hi = piece_co.min(0) - reach, piece_co.max(0) + reach
    idx = []
    for i, p in enumerate(ah_co):
        if np.all(p > lo) and np.all(p < hi):
            hit, n, _, d = bvh.find_nearest(Vector(p))
            if hit is not None and (d < reach or (Vector(p) - hit).dot(n) < 0):
                idx.append(i)
    return np.array(idx, int)


def make_rigid(obj, original, anchors_before, anchors_after):
    """Restore a piece's original shape, moved/rotated/scaled the way the body underneath it moved."""
    R, s, t = umeyama(anchors_before, anchors_after)
    fitted = (s * (R @ original.T)).T + t
    for v, p in zip(obj.data.vertices, fitted):
        v.co = p
    obj.data.update()


def contain_foot(obj, body_co, length_margin=1.12, width_margin=1.2):
    """Footwear rule: scale the shoe uniformly so it is longer and wider than the foot it goes on,
    centre it on that foot and stand it on the floor."""
    co = np.array([v.co[:] for v in obj.data.vertices])
    side = np.sign(co[:, 0].mean())
    foot = body_co[(body_co[:, 2] < 0.15) & (np.sign(body_co[:, 0]) == side)]
    f_lo, f_hi = foot.min(0), foot.max(0)
    s_lo, s_hi = co.min(0), co.max(0)
    s = max(length_margin * (f_hi[1] - f_lo[1]) / (s_hi[1] - s_lo[1]),
            width_margin * (f_hi[0] - f_lo[0]) / (s_hi[0] - s_lo[0]))
    center = (s_lo + s_hi) / 2
    co = (co - center) * s
    target = (f_lo + f_hi) / 2
    co[:, 0] += target[0]
    co[:, 1] += target[1]
    co[:, 2] += -co[:, 2].min()
    for v, p in zip(obj.data.vertices, co):
        v.co = p
    obj.data.update()
    return s


def cull_stretched(obj, before_co, max_ratio=3.0):
    """Delete faces whose edges stretched more than max_ratio between the generated pose and the rest pose
    (filler webs between sleeve and torso, or between legs, that the generator fused in)."""
    me = obj.data
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.verts.ensure_lookup_table()
    doomed = []
    for f in bm.faces:
        for e in f.edges:
            a, b = e.verts
            l0 = np.linalg.norm(before_co[a.index] - before_co[b.index])
            l1 = (a.co - b.co).length
            if l0 > 1e-6 and l1 / l0 > max_ratio:
                doomed.append(f)
                break
    bmesh.ops.delete(bm, geom=doomed, context='FACES')
    loose = [v for v in bm.verts if not v.link_faces]
    bmesh.ops.delete(bm, geom=loose, context='VERTS')
    bm.to_mesh(me)
    bm.free()
    me.update()
    return len(doomed)


def shrink_body_carry_garments(ah_body, garments, genies_body):
    ctx = bpy.context
    for g in garments:
        mod = g.modifiers.new('carry', 'SURFACE_DEFORM')
        mod.target = ah_body
        mod.falloff = 4.0
        with ctx.temp_override(object=g, active_object=g, selected_objects=[g]):
            bpy.ops.object.surfacedeform_bind(modifier=mod.name)
        if not mod.is_bound:
            raise RuntimeError(f'Surface Deform failed to bind {g.name}')
    sw = ah_body.modifiers.new('onto_genies', 'SHRINKWRAP')
    sw.target = genies_body
    sw.wrap_method = 'NEAREST_SURFACEPOINT'
    sm = ah_body.modifiers.new('relax', 'CORRECTIVE_SMOOTH')
    sm.iterations = 10
    sm.smooth_type = 'LENGTH_WEIGHTED'
    bpy.context.view_layer.update()
    for g in garments:
        with ctx.temp_override(object=g, active_object=g, selected_objects=[g]):
            bpy.ops.object.modifier_apply(modifier='carry')


# ---------------------------------------------------------------- clipping

def welded(me, decimals=6):
    """AI meshes are split at every UV seam, so faces that touch rarely share vertices. Treat vertices at the same
    position as one: returns (unique positions, vertex -> unique index, unique edges) without changing the mesh."""
    co = np.array([v.co[:] for v in me.vertices])
    uco, wid = np.unique(np.round(co, decimals), axis=0, return_inverse=True)
    wid = wid.ravel()
    e = np.array([ed.vertices[:] for ed in me.edges], int).reshape(-1, 2)
    e = np.sort(wid[e], 1)
    e = np.unique(e[e[:, 0] != e[:, 1]], axis=0)
    return uco, wid, e


def neighbours(n, edges):
    nbrs = [[] for _ in range(n)]
    for a, b in edges:
        nbrs[a].append(b); nbrs[b].append(a)
    return nbrs


def smooth_on_edges(w, edges, iters, mask=None):
    """Laplacian smoothing over an edge list (vectorised); only rows in mask change when given."""
    if not len(edges):
        return w
    a, b = edges[:, 0], edges[:, 1]
    deg = np.bincount(np.concatenate([a, b]), minlength=len(w)).astype(np.float64)
    deg[deg == 0] = 1
    deg = deg.reshape(-1, *([1] * (w.ndim - 1)))
    for _ in range(iters):
        acc = np.zeros_like(w)
        np.add.at(acc, a, w[b])
        np.add.at(acc, b, w[a])
        new = 0.5 * w + 0.5 * acc / deg
        w = new if mask is None else np.where(mask.reshape(-1, *([1] * (w.ndim - 1))), new, w)
    return w


def push_outside(obj, collider_co, collider_polys, gap, smooth_iters=6):
    """Move any vertex of obj that is inside the collider, or closer than gap, to gap outside it; relax the moved area."""
    bvh = bvh_of(collider_co, collider_polys)
    me = obj.data
    co, wid, edges = welded(me)
    nbrs = neighbours(len(co), edges)

    def resolve(idx):
        hits = np.zeros(len(co), bool)
        for i in idx:
            hit, n, _, d = bvh.find_nearest(Vector(co[i]))
            if hit is not None and (Vector(co[i]) - hit).dot(n) < gap:
                co[i] = np.array(hit + n * gap)
                hits[i] = True
        return hits

    moved = resolve(range(len(co)))
    if moved.any():
        zone = moved.copy()
        for _ in range(2):
            zone = zone | np.array([any(zone[j] for j in nb) for nb in nbrs])
        for _ in range(smooth_iters):
            co[:] = smooth_on_edges(co, edges, 1, zone)
            resolve(np.nonzero(zone)[0])
    for v, i in zip(me.vertices, wid):
        v.co = co[i]
    me.update()
    return int(moved.sum())


# ---------------------------------------------------------------- skinning + unpose

def body_weights(body):
    """Skin weights per bone. Only groups that are bones of the body's armature count - a mask group (weight 1.0 on
    hidden skin) would otherwise win every argmax and silently turn hidden limbs into 'no bone'."""
    arm = body.find_armature() or next((o for o in bpy.data.objects if o.type == 'ARMATURE'), None)
    bones = set(arm.data.bones.keys()) if arm else None
    names = [vg.name for vg in body.vertex_groups]
    W = np.zeros((len(body.data.vertices), len(names)), np.float32)
    for v in body.data.vertices:
        for ge in v.groups:
            if bones is None or names[ge.group] in bones:
                W[v.index, ge.group] = ge.weight
    return names, W


REGION_RULES = [('head', ('Head', 'Neck', 'Face', 'Jaw', 'Eye', 'Brow', 'Mouth', 'Nose', 'Dyn')),
                ('arm_l', ('LeftArm', 'LeftForeArm', 'LeftHand')), ('arm_r', ('RightArm', 'RightForeArm', 'RightHand')),
                ('leg_l', ('LeftUpLeg', 'LeftLeg', 'LeftFoot', 'LeftToe')), ('leg_r', ('RightUpLeg', 'RightLeg', 'RightFoot', 'RightToe'))]


def region_of(bone):
    for region, keys in REGION_RULES:
        if any(bone.startswith(k) for k in keys):
            return region
    return 'torso'


REGION_IDS = ['torso', 'head', 'arm_l', 'arm_r', 'leg_l', 'leg_r']
ARM_SIDES = {'arm_l': 'Left', 'arm_r': 'Right'}


def region_labels(me, body_co, body_polys, names, W, rig=None):
    """Label every welded garment position with the body region it belongs to (torso, head, each arm, each leg).
    Vertices that clearly touch one region seed that label; the rest take the label of the nearest seed along the
    garment's own surface (multi-source Dijkstra), so a sleeve stays an arm where it brushes the torso and a hem
    that hangs next to the wrist stays torso."""
    uco, wid, edges = welded(me)
    nbrs = neighbours(len(uco), edges)
    bone_region = np.array([region_of(n) for n in names])
    vert_region = bone_region[W.argmax(1)]
    trees = {}
    for r in sorted(set(vert_region)):
        polys = [p for p in body_polys if sum(vert_region[i] == r for i in p) * 2 > len(p)]
        if polys:
            trees[r] = (bvh_of(body_co, polys), polys)
    regions = list(trees)
    dist = np.array([[trees[r][0].find_nearest(Vector(p))[3] for r in regions] for p in uco])
    order = np.sort(dist, 1)
    label = np.where((order[:, 0] < 0.4 * order[:, 1]) & (order[:, 1] > 0.05), dist.argmin(1), -1)
    best = np.where(label >= 0, 0.0, np.inf)
    heap = [(0.0, int(i)) for i in np.nonzero(label >= 0)[0]]
    heapq.heapify(heap)
    while heap:
        d, i = heapq.heappop(heap)
        if d > best[i]:
            continue
        for j in nbrs[i]:
            nd = d + float(np.linalg.norm(uco[i] - uco[j]))
            if nd < best[j]:
                best[j], label[j] = nd, label[i]
                heapq.heappush(heap, (nd, j))
    label[label < 0] = dist.argmin(1)[label < 0]
    names_of = np.array([regions[l] for l in label])
    if rig is not None and 'torso' in regions:
        # Skeleton check: a point only stays "arm" if it is nearer the arm bones than the spine/neck line,
        # so the label cannot creep over the shoulder into the hood or back.
        spine = [joint(rig, b) for b in ('Hips', 'Spine', 'Spine1', 'Spine2', 'Neck', 'Head')]
        d_spine = polyline_dist(uco, spine)
        for region, side in ARM_SIDES.items():
            chain = [joint(rig, f'{side}{b}') for b in ('Arm', 'ForeArm', 'Hand')]
            sel = names_of == region
            if sel.any():
                d_arm = polyline_dist(uco[sel], chain)
                idx = np.nonzero(sel)[0][d_spine[sel] < d_arm]
                names_of[idx] = 'torso'
    return uco, wid, edges, names_of, trees, bone_region


def polyline_dist(pts, joints):
    """Distance from each point to a chain of bone segments."""
    best = np.full(len(pts), np.inf)
    for a, b in zip(joints, joints[1:]):
        a, b = np.array(a), np.array(b)
        ab = b - a
        t = np.clip((pts - a) @ ab / max(ab @ ab, 1e-9), 0, 1)
        best = np.minimum(best, np.linalg.norm(pts - (a + t[:, None] * ab), axis=1))
    return best


def joint(arm, bone):
    return arm.matrix_world @ arm.pose.bones[bone].head


def sleeve_bvhs(me, wid, labels, matrix=None):
    """One BVH per sleeve, built from the faces whose welded positions are all labelled that arm."""
    co = np.array([(matrix @ v.co)[:] if matrix else v.co[:] for v in me.vertices])
    out = {}
    for region in ARM_SIDES:
        polys = [tuple(p.vertices) for p in me.polygons if all(labels[wid[i]] == region for i in p.vertices)]
        if len(polys) > 50:
            out[region] = BVHTree.FromPolygons([Vector(c) for c in co], polys, all_triangles=False)
    return out


def cuff_centres(uco, labels, arm, slice_m=0.025):
    """Centre of each sleeve's cuff opening: the bounding-box centre of the last slice of the sleeve along its own
    main axis (pointing away from the shoulder)."""
    out = {}
    for region, side in ARM_SIDES.items():
        pts = uco[labels == region]
        if len(pts) < 50:
            continue
        shoulder = np.array(joint(arm, f'{side}Arm'))
        c = pts.mean(0)
        axis = np.linalg.svd(pts - c, full_matrices=False)[2][0]
        if np.dot(axis, c - shoulder) < 0:
            axis = -axis
        t = (pts - c) @ axis
        end = pts[t > t.max() - slice_m]
        out[region] = ((end.min(0) + end.max(0)) / 2, axis)
    return out


def hand_tip(arm, side, reach=0.09):
    w, e = joint(arm, f'{side}Hand'), joint(arm, f'{side}ForeArm')
    return w + (w - e).normalized() * reach


def seg_point_dist(p, a, b):
    p, a, b = np.array(p), np.array(a), np.array(b)
    ab = b - a
    t = np.clip(np.dot(p - a, ab) / max(np.dot(ab, ab), 1e-9), 0, 1)
    return float(np.linalg.norm(p - (a + t * ab)))


def pierces_wall(bvh, arm, side):
    """True when the line from mid-forearm to the fingertips hits the sleeve, i.e. the hand would come out through
    the sleeve wall instead of the cuff opening."""
    e, w = joint(arm, f'{side}ForeArm'), joint(arm, f'{side}Hand')
    start = e.lerp(w, 0.5)
    tip = hand_tip(arm, side)
    d = tip - start
    return bvh.ray_cast(start, d.normalized(), d.length)[0] is not None


def inside_score(bvh, a, b, samples=6, dirs=8, reach=0.15):
    """Fraction of rays, cast in a ring around bone segment a->b, that hit the sleeve: ~1.0 means the bone runs
    inside the sleeve, ~0.5 or less means the sleeve is only beside it."""
    a, b = Vector(a), Vector(b)
    axis = (b - a).normalized()
    u = axis.orthogonal().normalized()
    v = axis.cross(u)
    hits = total = 0
    for t in np.linspace(0.15, 0.9, samples):
        o = a.lerp(b, float(t))
        for k in range(dirs):
            th = 2 * math.pi * k / dirs
            d = u * math.cos(th) + v * math.sin(th)
            hits += bvh.ray_cast(o, d, reach)[0] is not None
            total += 1
    return hits / total


def arm_scores(arm, bvhs, cuffs):
    """Per arm: how enclosed the upper arm / forearm are, how far (cm) the forearm line passes from the cuff
    opening's centre, and whether the hand pierces the sleeve wall."""
    out = {}
    for region, side in ARM_SIDES.items():
        if region in bvhs:
            s, e, w = joint(arm, f'{side}Arm'), joint(arm, f'{side}ForeArm'), joint(arm, f'{side}Hand')
            r = {'upper_arm': round(inside_score(bvhs[region], s, e), 3),
                 'forearm': round(inside_score(bvhs[region], e, w), 3),
                 'hand_through_wall': pierces_wall(bvhs[region], arm, side)}
            if region in cuffs:
                r['cuff_offset_cm'] = round(100 * seg_point_dist(cuffs[region][0], e, hand_tip(arm, side)), 1)
            out[side] = r
    return out


def _grid_rotate(arm, bone, score_fn, span_deg, step_deg, penalty=0.002):
    """Try rotations of bone about world X and Y on a grid; keep the best score (small rotations preferred)."""
    pb = arm.pose.bones[bone]
    base = pb.matrix_basis.copy()
    best = (score_fn(), 0, 0)
    steps = np.arange(-span_deg, span_deg + 1e-6, step_deg)
    for ax in steps:
        for ay in steps:
            if ax == 0 and ay == 0:
                continue
            pb.matrix_basis = base
            bpy.context.view_layer.update()
            rotate_bone_world(arm, bone, 'X', math.radians(ax))
            rotate_bone_world(arm, bone, 'Y', math.radians(ay))
            s = score_fn() - penalty * math.hypot(ax, ay)
            if s > best[0]:
                best = (s, ax, ay)
    pb.matrix_basis = base
    bpy.context.view_layer.update()
    rotate_bone_world(arm, bone, 'X', math.radians(best[1]))
    rotate_bone_world(arm, bone, 'Y', math.radians(best[2]))
    return best[1], best[2]


def refine_arms(arm, body, top):
    """Put each Genies arm inside its sleeve with the hand coming out of the cuff opening: search upper-arm then
    forearm rotations (coarse, then fine) scoring enclosure, distance of the forearm line from the cuff centre,
    and a heavy penalty when the hand would pierce the sleeve wall."""
    names, W = body_weights(body)
    bco, bpolys = world_verts(body, evaluated=True)
    uco, wid, edges, lab, _, _ = region_labels(top.data, bco, bpolys, names, W, rig=arm)
    bvhs = sleeve_bvhs(top.data, wid, lab)
    cuffs = cuff_centres(uco, lab, arm)
    before = arm_scores(arm, bvhs, cuffs)
    report = {}
    for region, side in ARM_SIDES.items():
        if region not in bvhs or region not in cuffs:
            continue
        bvh, cuff = bvhs[region], cuffs[region][0]

        def score(upper=True):
            s, e, w = joint(arm, f'{side}Arm'), joint(arm, f'{side}ForeArm'), joint(arm, f'{side}Hand')
            val = inside_score(bvh, e, w) - 8.0 * seg_point_dist(cuff, e, hand_tip(arm, side))
            val -= 1.0 * pierces_wall(bvh, arm, side)
            if upper:
                val += inside_score(bvh, s, e)
            return val

        rot = [_grid_rotate(arm, f'{side}Arm', score, 24, 4), _grid_rotate(arm, f'{side}Arm', score, 4, 1),
               _grid_rotate(arm, f'{side}ForeArm', lambda: score(False), 45, 3),
               _grid_rotate(arm, f'{side}ForeArm', lambda: score(False), 3, 1)]
        report[side] = {'upper_arm_rot_xy_deg': [float(rot[0][0] + rot[1][0]), float(rot[0][1] + rot[1][1])],
                        'forearm_rot_xy_deg': [float(rot[2][0] + rot[3][0]), float(rot[2][1] + rot[3][1])]}
    after = arm_scores(arm, bvhs, cuffs)
    for side in report:
        report[side]['before'] = before[side]
        report[side]['after'] = after[side]
    return report


def armpit_z(arm, margin=0.03):
    return {region: (joint(arm, f'{side}Arm')).z - margin for region, side in ARM_SIDES.items()}


def transfer_weights(garment, body_co, body_polys, names, W, smooth_iters=40, seam_iters=6, cut_z=None, rig=None):
    """Copy skin weights from the nearest body surface, restricted to the body region each garment position belongs
    to (see region_labels). Works on welded positions so labels and smoothing cross the generator's UV seams.
    Sleeve/torso seams below cut_z (the armpit) are not smoothed across: cut_webs separates them later."""
    me = garment.data
    uco, wid, edges, lab, trees, bone_region = region_labels(me, body_co, body_polys, names, W, rig=rig)
    palette = {'torso': (0.9, 0.9, 0.9), 'head': (0.9, 0.8, 0.2), 'arm_l': (0.9, 0.2, 0.2), 'arm_r': (0.2, 0.4, 0.9),
               'leg_l': (0.9, 0.5, 0.1), 'leg_r': (0.2, 0.8, 0.3)}
    attr = me.color_attributes.get('region') or me.color_attributes.new('region', 'FLOAT_COLOR', 'POINT')
    rid = me.attributes.get('region_id') or me.attributes.new('region_id', 'INT', 'POINT')
    for i, u in enumerate(wid):
        attr.data[i].color = (*palette[lab[u]], 1.0)
        rid.data[i].value = REGION_IDS.index(lab[u])
    # Each label may only use its own bones plus the torso; torso cloth uses torso bones only.
    allowed = {r: (bone_region == r) | (bone_region == 'torso') for r in set(lab)}
    out = np.zeros((len(uco), len(names)), np.float64)
    for u, p in enumerate(uco):
        tree, polys = trees[lab[u]]
        hit, n, fi, d = tree.find_nearest(Vector(p))
        poly = polys[fi]
        bw = poly_3d_calc([Vector(body_co[i]) for i in poly], hit)
        out[u] = sum(w * W[i] for w, i in zip(bw, poly)) * allowed[lab[u]]
        if out[u].sum() < 1e-6:
            out[u] = sum(w * W[i] for w, i in zip(bw, poly))
    seam = edges[lab[edges[:, 0]] != lab[edges[:, 1]]]
    if cut_z:
        a, b = lab[seam[:, 0]], lab[seam[:, 1]]
        web = np.zeros(len(seam), bool)
        for region, z in cut_z.items():
            pair = ((a == region) & (b == 'torso')) | ((b == region) & (a == 'torso'))
            low = np.maximum(uco[seam[:, 0], 2], uco[seam[:, 1], 2]) < z
            web |= pair & low
        seam = seam[~web]
    same = edges[lab[edges[:, 0]] == lab[edges[:, 1]]]
    used = out.max(0) > 1e-4
    out[:, used] = smooth_on_edges(out[:, used], same, smooth_iters)
    out[:, used] = smooth_on_edges(out[:, used], np.concatenate([same, seam]), seam_iters)
    out /= np.maximum(out.sum(1, keepdims=True), 1e-8)
    out = out[wid]
    garment.vertex_groups.clear()
    keep = [j for j in range(len(names)) if out[:, j].max() > 1e-3]
    for j in keep:
        vg = garment.vertex_groups.new(name=names[j])
        for i in np.nonzero(out[:, j] > 1e-3)[0]:
            vg.add([int(i)], float(out[i, j]), 'REPLACE')
    return out[:, keep], [names[j] for j in keep]


def split_webs(garment, cut_z):
    """Separate each sleeve from the torso below the armpit WITHOUT removing any cloth: every face goes wholly to
    the sleeve or the torso side, seam vertices are duplicated, and each copy takes its own side's weights. In the
    bind pose the garment is unchanged; when an arm rises only its sleeve follows and the seam opens.
    Returns (number of seam edges split, world positions of the seam) - covered skin near the seam stays visible."""
    from mathutils.kdtree import KDTree
    me = garment.data
    torso = REGION_IDS.index('torso')
    arms = {REGION_IDS.index(r): z for r, z in cut_z.items()}
    bm = bmesh.new()
    bm.from_mesh(me)
    rid = bm.verts.layers.int.get('region_id')
    deform = bm.verts.layers.deform.verify()

    def face_side(f):
        ids = [v[rid] for v in f.verts]
        return max(set(ids), key=ids.count)

    side = {f: face_side(f) for f in bm.faces}

    def low(region, co):
        return region in arms and co.z < arms[region]

    seam = [e for e in bm.edges if len(e.link_faces) == 2
            and {side[e.link_faces[0]], side[e.link_faces[1]]} - {torso}
            and torso in {side[e.link_faces[0]], side[e.link_faces[1]]}
            and low(next(iter({side[e.link_faces[0]], side[e.link_faces[1]]} - {torso})), (e.verts[0].co + e.verts[1].co) / 2)]
    bmesh.ops.split_edges(bm, edges=seam)
    side = {f: s for f, s in ((f, face_side(f) if f not in side else side[f]) for f in bm.faces)}

    # Vertices whose faces belong to the other side (seam copies, and UV-seam duplicates) take that side's weights.
    fix = []
    for v in bm.verts:
        if not v.link_faces:
            continue
        sides = [side.get(f, face_side(f)) for f in v.link_faces]
        s = max(set(sides), key=sides.count)
        r = v[rid]
        if s != r and {s, r} <= set(arms) | {torso} and (low(s, v.co) or low(r, v.co)):
            fix.append((v, s))
    donors = {}
    for s in {s for _, s in fix}:
        pool = [v for v in bm.verts if v[rid] == s and v.link_faces]
        kd = KDTree(len(pool))
        for i, v in enumerate(pool):
            kd.insert(v.co, i)
        kd.balance()
        donors[s] = (kd, pool)
    seam_pos = []
    for v, s in fix:
        kd, pool = donors[s]
        src = pool[kd.find(v.co)[1]]
        weights = dict(src[deform].items())
        v[deform].clear()
        for g, w in weights.items():
            v[deform][g] = w
        v[rid] = s
        seam_pos.append(v.co.copy())
    seam_pos += [v.co.copy() for e in seam if e.is_valid for v in e.verts]
    bm.to_mesh(me)
    bm.free()
    me.update()
    mw = garment.matrix_world
    return len(seam), np.array([(mw @ p)[:] for p in seam_pos]) if seam_pos else np.zeros((0, 3))


def release_stretched_faces(garment, arm, test_mats_fn, max_ratio=2.5):
    """Find faces that would stretch more than max_ratio in a test pose (string-like bridges between a sleeve
    and the torso), detach each one and give all its corners the weights of the side it mostly belongs to, so it
    rides with that side instead of stretching. The bind-pose shape is untouched."""
    from mathutils.kdtree import KDTree
    me = garment.data
    names = [vg.name for vg in garment.vertex_groups]
    W = np.zeros((len(me.vertices), len(names)))
    for v in me.vertices:
        for ge in v.groups:
            W[v.index, ge.group] = ge.weight
    W /= np.maximum(W.sum(1, keepdims=True), 1e-8)
    mats_bind = skin_matrices(arm, names)
    mats_test = test_mats_fn(names)
    co = np.array([v.co[:] + (1.0,) for v in me.vertices])
    rest = np.einsum('vij,vj->vi', np.linalg.inv(np.einsum('vb,bij->vij', W, mats_bind)), co)
    test = np.einsum('vij,vj->vi', np.einsum('vb,bij->vij', W, mats_test), rest)[:, :3]
    bind = co[:, :3]
    bad = []
    for p in me.polygons:
        vs = list(p.vertices)
        for a, b in zip(vs, vs[1:] + vs[:1]):
            l0 = np.linalg.norm(bind[a] - bind[b])
            if l0 > 1e-6 and np.linalg.norm(test[a] - test[b]) / l0 > max_ratio:
                bad.append(p.index)
                break
    if not bad:
        return 0
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.faces.ensure_lookup_table()
    rid = bm.verts.layers.int.get('region_id')
    deform = bm.verts.layers.deform.verify()
    bad_faces = [bm.faces[i] for i in bad]
    owner = {}
    for f in bad_faces:
        ids = [v[rid] for v in f.verts]
        owner[f] = max(set(ids), key=ids.count)
    bmesh.ops.split_edges(bm, edges=list({e for f in bad_faces for e in f.edges}))
    bad_verts = {v for f in bad_faces for v in f.verts}
    donors = {}
    for s in set(owner.values()):
        pool = [v for v in bm.verts if v[rid] == s and v not in bad_verts and v.link_faces]
        if not pool:
            continue
        kd = KDTree(len(pool))
        for i, v in enumerate(pool):
            kd.insert(v.co, i)
        kd.balance()
        donors[s] = (kd, pool)
    for f, s in owner.items():
        if s not in donors:
            continue
        kd, pool = donors[s]
        for v in f.verts:
            src = pool[kd.find(v.co)[1]]
            weights = dict(src[deform].items())
            v[deform].clear()
            for g, w in weights.items():
                v[deform][g] = w
            v[rid] = s
    bm.to_mesh(me)
    bm.free()
    me.update()
    return len(bad)


def skin_matrices(arm, names):
    A = arm.matrix_world
    mats = []
    for n in names:
        pb = arm.pose.bones.get(n)
        if pb is None:
            mats.append(np.eye(4)); continue
        M = A @ pb.matrix @ pb.bone.matrix_local.inverted() @ A.inverted()
        mats.append(np.array(M))
    return np.array(mats)


def unpose(garment, weights, names, arm):
    """Invert linear-blend skinning so the garment's rest shape matches the Genies T-pose."""
    mats = skin_matrices(arm, names)
    me = garment.data
    co = np.array([v.co[:] + (1.0,) for v in me.vertices])
    blend = np.einsum('vb,bij->vij', weights, mats)
    rest = np.einsum('vij,vj->vi', np.linalg.inv(blend), co)[:, :3]
    for v, p in zip(me.vertices, rest):
        v.co = p
    me.update()


def attach(garment, arm):
    garment.parent = arm
    garment.matrix_parent_inverse = arm.matrix_world.inverted()
    mod = garment.modifiers.new('Armature', 'ARMATURE')
    mod.object = arm


# ---------------------------------------------------------------- hidden body regions

def covered_body_verts(body_co, body_normals, garment_objs, max_dist=0.04):
    co, polys = [], []
    for g in garment_objs:
        gc, gp = world_verts(g)
        base = sum(len(c) for c in co)
        co.append(gc); polys += [tuple(i + base for i in p) for p in gp]
    bvh = bvh_of(np.concatenate(co), polys)
    covered = []
    for i, (p, n) in enumerate(zip(body_co, body_normals)):
        hit = bvh.ray_cast(Vector(p) + Vector(n) * 0.001, Vector(n), max_dist)
        if hit[0] is not None:
            covered.append(i)
    return covered


# ---------------------------------------------------------------- QA render

def render(path, objs, rotate=0.0, color='TEXTURE', focus=None, elev=0.0, res=(640, 800), clip=True):
    """Orthographic QA render. rotate: degrees-in-radians around the character (0 = front); elev: camera
    elevation in radians (negative looks up from below); focus: (lo, hi) world box to frame instead of everything."""
    scene = bpy.context.scene
    for o in scene.objects:
        o.hide_render = o not in objs and o.type == 'MESH'
    if focus is None:
        pts = np.concatenate([p for p in (world_verts(o, evaluated=True)[0] for o in objs) if len(p)])
        lo, hi = pts.min(0), pts.max(0)
    else:
        lo, hi = np.array(focus[0]), np.array(focus[1])
    center, size = (lo + hi) / 2, float((hi - lo).max())
    cam = bpy.data.objects.get('QA_cam') or bpy.data.objects.new('QA_cam', bpy.data.cameras.new('QA_cam'))
    if cam.name not in scene.collection.objects:
        scene.collection.objects.link(cam)
    cam.data.type = 'ORTHO'
    cam.data.ortho_scale = size * 1.1
    cam.data.clip_start, cam.data.clip_end = 0.001, 100
    if focus is not None and clip:  # close-ups: only what is inside the focus box, nothing in front of or behind it
        cam.data.clip_start, cam.data.clip_end = 10 - size * 1.6, 10 + size * 1.6
    d = Vector((math.sin(rotate) * math.cos(elev), -math.cos(rotate) * math.cos(elev), math.sin(elev)))
    cam.location = Vector(center) + d * 10
    cam.rotation_euler = (-d).to_track_quat('-Z', 'Y').to_euler()
    scene.camera = cam
    scene.render.engine = 'BLENDER_WORKBENCH'
    scene.display.shading.light = 'STUDIO'
    scene.display.shading.color_type = 'TEXTURE' if color == 'TEXTURE' else 'VERTEX'
    scene.display.shading.show_cavity = True
    scene.display.shading.background_type = 'WORLD'
    scene.world = scene.world or bpy.data.worlds.new('QA')
    scene.world.color = (0.82, 0.82, 0.85)
    scene.render.resolution_x, scene.render.resolution_y = res
    scene.render.film_transparent = False
    scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)


# ---------------------------------------------------------------- main

def repose(garment, weights, names, mats_from, mats_to):
    """Move a skinned piece from one pose to another (linear blend skinning, both relative to the same rest)."""
    me = garment.data
    co = np.array([v.co[:] + (1.0,) for v in me.vertices])
    b_from = np.einsum('vb,bij->vij', weights, mats_from)
    b_to = np.einsum('vb,bij->vij', weights, mats_to)
    rest = np.einsum('vij,vj->vi', np.linalg.inv(b_from), co)
    new = np.einsum('vij,vj->vi', b_to, rest)[:, :3]
    for v, p in zip(me.vertices, new):
        v.co = p
    me.update()


def main():
    args = parse_args()
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    name = args.name or Path(args.assembly).stem
    overrides = dict(kv.split('=') for kv in args.map.split(',') if kv)
    bind = SLOTS['bind_pose']

    # Phase 1 (T-pose base): pose the Genies rig into the assembled outfit. The garments keep the exact shape
    # V5 assembled; they are only scaled as a whole, and only vertices the Genies body pokes through are nudged.
    arm, body, base_meshes = load_base(args.base)
    parts = load_assembly(Path(args.assembly).resolve())
    ah_body = parts.pop('base_body')
    log('parts:', sorted(parts))
    slot_of = {}
    for key in parts:
        slot = overrides.get(key) or next((s for kw, s in KEYWORDS if kw in key.lower()), 'accessory')
        slot_of[key] = 'legwear_l' if slot == 'legwear' and key.endswith('_l') else 'legwear_r' if slot == 'legwear' else slot
    log('slots:', slot_of)
    rigid = {k for k in parts if SLOTS['slots'][slot_of[k]]['rigid']}

    fit = fit_pose(arm, body, ah_body)
    apply_similarity(list(parts.values()), fit['scale'], np.array(fit['offset']))
    bpy.data.objects.remove(ah_body, do_unlink=True)
    sleeved = [k for k in parts if slot_of[k] in ('top', 'outerwear', 'fullbody')]
    if sleeved:
        fit['arm_refine'] = refine_arms(arm, body, parts[max(sleeved, key=lambda k: SLOTS['slots'][slot_of[k]]['layer'])])
        for side, r in fit['arm_refine'].items():
            log(f'{side} arm vs sleeve: {r["before"]} -> {r["after"]} '
                f'(upper arm rotated {r["upper_arm_rot_xy_deg"]}, forearm {r["forearm_rot_xy_deg"]} deg)')
    posed_co, posed_polys = world_verts(body, evaluated=True)
    report = {}
    for k in sorted(parts, key=lambda k: SLOTS['slots'][slot_of[k]]['layer']):
        if slot_of[k] == 'footwear':
            log(f'{k}: sized around the foot (uniform scale x{contain_foot(parts[k], posed_co):.3f})')
        n = 0 if k in rigid else push_outside(parts[k], posed_co, posed_polys, SLOTS['skin_offset_m'])
        report[k] = {'slot': slot_of[k], 'layer': SLOTS['slots'][slot_of[k]]['layer'], 'rigid': k in rigid,
                     'verts_nudged_off_body': n}
        log(f'{k}: {n} verts nudged off the body')

    names, W = body_weights(body)
    fit_cut_z = armpit_z(arm)
    skin = {k: transfer_weights(g, posed_co, posed_polys, names, W, cut_z=fit_cut_z if k in sleeved else None, rig=arm)
            for k, g in parts.items()}
    render(out / 'qa_fit_regions.png', [body, *parts.values()], color='region')

    # Bring the outfit from its fitted pose to the canonical bind pose (identity when they already match).
    fitted_mats = {k: skin_matrices(arm, skin[k][1]) for k in parts}
    set_pose(arm, bind['arm_deg'], bind['leg_deg'])
    for k, g in parts.items():
        repose(g, skin[k][0], skin[k][1], fitted_mats[k], skin_matrices(arm, skin[k][1]))
    bind_cut_z = armpit_z(arm)
    seam_pts = [np.zeros((0, 3))]
    for k in sleeved:
        n, pts = split_webs(parts[k], bind_cut_z)
        seam_pts.append(pts)
        report[k]['sleeve_seam_edges_split'] = n
        log(f'{k}: split {n} seam edges so the sleeves move apart from the torso below the armpits (no cloth removed)')
        # The Phase-1 rig rests in the T-pose, so identity bone matrices are the T-pose test.
        released = release_stretched_faces(parts[k], arm, lambda names: np.array([np.eye(4)] * len(names)))
        report[k]['stretched_faces_released'] = released
        log(f'{k}: {released} faces that would stretch in a T-pose now ride with one side')
    seam_pts = np.concatenate(seam_pts)
    for k, g in parts.items():
        g.name = f'{name}__{slot_of[k]}__{k}'
    tmp = out / '_garments.blend'
    bpy.data.libraries.write(str(tmp), set(parts.values()), fake_user=True)
    part_names = {k: g.name for k, g in parts.items()}

    # Phase 2 (A-pose base): bind the pieces to the A-pose rig, record covered skin, export, QA.
    bpy.ops.wm.open_mainfile(filepath=str(ROOT / 'Bases' / f'{args.base}_Apose.blend'))
    arm = next(o for o in bpy.data.objects if o.type == 'ARMATURE')
    base_meshes = [o for o in bpy.data.objects if o.type == 'MESH']
    body = max(base_meshes, key=lambda o: len(o.data.vertices))
    with bpy.data.libraries.load(str(tmp)) as (src, dst):
        dst.objects = list(part_names.values())
    parts = {k: bpy.data.objects[n] for k, n in part_names.items()}
    for g in parts.values():
        bpy.context.scene.collection.objects.link(g)
        g.use_fake_user = False
        attach(g, arm)
    tmp.unlink()

    items = {}
    for k, slot in slot_of.items():
        items.setdefault(slot, []).append(parts[k])
    rest_co, _ = world_verts(body)
    normals = np.array([body.matrix_world.to_3x3() @ v.normal for v in body.data.vertices])
    manifest = {'outfit': name, 'base': f'{args.base}_Apose', 'bind_pose': bind, 'fit': fit, 'items': {}}
    for slot, objs in items.items():
        covered = covered_body_verts(rest_co, normals, objs)
        if len(seam_pts):
            # Keep skin visible wherever an opened sleeve seam could reveal it.
            from mathutils.kdtree import KDTree
            kd = KDTree(len(seam_pts))
            for i, p in enumerate(seam_pts):
                kd.insert(Vector(p), i)
            kd.balance()
            covered = [i for i in covered if kd.find(Vector(rest_co[i]))[2] > 0.05]
        vg = body.vertex_groups.get(f'hide_{slot}') or body.vertex_groups.new(name=f'hide_{slot}')
        vg.add(covered, 1.0, 'REPLACE')
        file_stem = f'{name}__{slot}'
        bpy.ops.object.select_all(action='DESELECT')
        for o in [arm, *objs]:
            o.select_set(True)
        bpy.context.view_layer.objects.active = arm
        bpy.ops.export_scene.gltf(filepath=str(out / f'{file_stem}.glb'), export_format='GLB', use_selection=True,
                                  export_skins=True, export_animations=False, export_morph=False)
        bpy.ops.export_scene.fbx(filepath=str(out / f'{file_stem}.fbx'), use_selection=True,
                                 object_types={'ARMATURE', 'MESH'}, add_leaf_bones=False, bake_anim=False,
                                 path_mode='COPY', embed_textures=True)
        manifest['items'][slot] = {
            'files': [f'{file_stem}.glb', f'{file_stem}.fbx'],
            'layer': SLOTS['slots'][slot]['layer'],
            'parts': [o.name for o in objs],
            'hidden_body_verts': covered,
            'excludes': SLOTS['slots'][slot]['excludes'],
            'fit_report': {k: report[k] for k in slot_of if slot_of[k] == slot},
        }
    # Hide covered skin as the game would (a Mask modifier on the body; delete it to see the full body).
    hide_all = body.vertex_groups.new(name='hide_all')
    for slot in items:
        g = body.vertex_groups[f'hide_{slot}']
        hide_all.add([v.index for v in body.data.vertices if any(ge.group == g.index for ge in v.groups)], 1.0, 'REPLACE')
    mask = body.modifiers.new('hide_covered_skin', 'MASK')
    mask.vertex_group = 'hide_all'
    mask.invert_vertex_group = True
    bpy.ops.wm.save_as_mainfile(filepath=str(out / f'{name}__{args.base}_Apose.blend'))

    # QA renders: bind pose all around and arm close-ups, then a T-pose and an action pose.
    shown = [body, *[o for objs in items.values() for o in objs]] + [m for m in base_meshes if m is not body]
    tops = [parts[k] for k in sleeved]
    checks = {}

    def sleeve_check(pose_name):
        if not tops:
            return
        top = tops[-1]
        me = top.evaluated_get(bpy.context.evaluated_depsgraph_get()).to_mesh()
        co, wid, _ = welded(me)
        rid = np.array([d.value for d in top.data.attributes['region_id'].data])
        lab_w = np.empty(len(co), object)
        lab_w[wid] = [REGION_IDS[r] for r in rid]
        bvhs = sleeve_bvhs(me, wid, lab_w, matrix=top.matrix_world)
        co_w = np.array([(top.matrix_world @ Vector(p))[:] for p in co])
        top.evaluated_get(bpy.context.evaluated_depsgraph_get()).to_mesh_clear()
        checks[pose_name] = arm_scores(arm, bvhs, cuff_centres(co_w, lab_w, arm))
        log(f'sleeve check ({pose_name}):', checks[pose_name])

    for i in range(8):
        render(out / f'qa_bind_{i * 45:03d}.png', shown, rotate=math.radians(i * 45), res=(400, 560))
    render(out / 'qa_bind_below.png', shown, elev=math.radians(-35), res=(400, 560))
    sleeve_check('bind')
    for region, side in ARM_SIDES.items():
        pts = np.array([joint(arm, f'{side}{b}') for b in ('Arm', 'ForeArm', 'Hand')] +
                       [arm.matrix_world @ arm.pose.bones[f'{side}Hand'].tail])
        box = (pts.min(0) - 0.09, pts.max(0) + 0.09)
        out_dir = 90 if side == 'Left' else -90
        for tag, rot, el in (('front', 0, 0), ('back', 180, 0), ('outside', out_dir, 0), ('inside', -out_dir, 0),
                             ('below', 0, -70)):
            render(out / f'qa_arm_{side[0]}_{tag}.png', shown, rotate=math.radians(rot), elev=math.radians(el),
                   focus=box, res=(360, 360))
        # Looking straight up the sleeve from beyond the hand, and across the cuff: the hand must leave through
        # the opening, never through the sleeve wall.
        e, w = np.array(joint(arm, f'{side}ForeArm')), np.array(joint(arm, f'{side}Hand'))
        up = (w - e) / np.linalg.norm(w - e)
        cuff_box = (w - 0.09, w + 0.09)
        render(out / f'qa_arm_{side[0]}_upsleeve.png', shown, rotate=math.atan2(up[0], -up[1]),
               elev=math.asin(max(-1.0, min(1.0, float(up[2])))), focus=cuff_box, res=(360, 360))
        render(out / f'qa_arm_{side[0]}_cuff.png', shown, rotate=math.radians(out_dir), focus=cuff_box, res=(360, 360))
    set_pose(arm, -bind['arm_deg'], -bind['leg_deg'])
    sleeve_check('tpose')
    for i, rot in enumerate((0, 90, 180, 270)):
        render(out / f'qa_tpose_{rot:03d}.png', shown, rotate=math.radians(rot), res=(400, 560))
    set_pose(arm, -25, 0)
    for side, sign in (('Left', 1), ('Right', -1)):
        rotate_bone_world(arm, f'{side}ForeArm', 'Z', sign * math.radians(40))
    rotate_bone_world(arm, 'LeftUpLeg', 'X', math.radians(-35))
    rotate_bone_world(arm, 'LeftLeg', 'X', math.radians(50))
    rotate_bone_world(arm, 'Spine1', 'Z', math.radians(15))
    sleeve_check('action')
    for rot in (0, 90, 180, 270):
        render(out / f'qa_action_{rot:03d}.png', shown, rotate=math.radians(rot), res=(400, 560))
    manifest['sleeve_check'] = checks
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    log('DONE', out)


if __name__ == '__main__':
    main()


def apply_look_pose(arm, look_dir):
    """Put the rig in a look's saved pose (06_fitted/manifest.json 'look_pose'): the pose in which every visible piece
    is shown exactly as generated. Rest (T-pose) for outfits/looks without one."""
    import json
    from pathlib import Path
    man = Path(look_dir) / '06_fitted' / 'manifest.json'
    pose = json.loads(man.read_text()).get('look_pose', {}) if man.exists() else {}
    for pb in arm.pose.bones:
        pb.matrix_basis = Matrix(pose[pb.name]) if pb.name in pose else Matrix.Identity(4)
    bpy.context.view_layer.update()
    return pose
