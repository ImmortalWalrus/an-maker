"""Step 6 - put every piece on the T-pose Genies rig and skin it. The generated meshes are NOT edited.

  * each piece is imported exactly as generated (04_meshes/<key>.glb) and gets the rigid transform measured in
    step 5 (rotation, one uniform scale, translation) - its shape never changes
  * skin weights copied from the body by body region (sleeve -> arm bones, panel -> torso bones...) for normal
    deformation; rigid pieces (shoes, bags, hats) follow one bone per part
  * per-piece skinned .glb/.fbx, manifest (with the body vertices each piece covers), .blend in which the skin
    under the clothes is hidden by a Mask modifier on the BODY (garment meshes are never edited)

Run: blender -b --factory-startup -P pipeline/tpose/s6_fit.py -- <outfit_dir> <base>
"""
import bpy, bmesh, sys, json, os
from pathlib import Path
import numpy as np
from mathutils import Matrix, Vector

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'pipeline'))
import fit_outfit as F  # noqa: E402  (shared helpers: region-aware weights, coverage, rig utils)
sys.path.insert(0, str(ROOT / 'pipeline' / 'tpose'))
import metrics as M  # noqa: E402

SLOTS = json.loads((ROOT / 'pipeline' / 'slots.json').read_text(encoding='utf-8'))['slots']


def import_piece(glb, name):
    """Import a generated mesh as-is (node transforms kept as the object's transform, mesh data untouched)."""
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(glb))
    new = [o for o in bpy.data.objects if o not in before]
    meshes = [o for o in new if o.type == 'MESH']
    if len(meshes) != 1:
        raise RuntimeError(f'{glb.name}: expected one mesh, got {len(meshes)}')
    obj = meshes[0]
    mw = obj.matrix_world.copy()
    obj.parent = None
    obj.matrix_world = mw
    for o in new:
        if o is not obj:
            bpy.data.objects.remove(o, do_unlink=True)
    obj.name = obj.data.name = name
    swap_textures(obj, glb.parent / f'{glb.stem}_tex')
    return obj


def swap_textures(obj, tex_dir):
    """Texture-only rework of a generated piece (decal_bake.py: a logo redrawn sharply in place): use the reworked
    colour / ORM / normal images instead of the generated ones. The mesh is untouched."""
    if not tex_dir.is_dir():
        return
    want = {'Color': 'Color_reworked.png', 'ORM': 'ORM_reworked.png', 'Normal': 'Normal_reworked.png'}  # names survive glTF
    done = []
    for mat in obj.data.materials:
        for node in (mat.node_tree.nodes if mat and mat.use_nodes else []):
            if node.type != 'TEX_IMAGE' or not node.image:
                continue
            for prefix, fname in want.items():
                if node.image.name.startswith(prefix) and (tex_dir / fname).exists():
                    cs = node.image.colorspace_settings.name
                    img = bpy.data.images.load(str(tex_dir / fname))
                    img.colorspace_settings.name = cs
                    img.pack()
                    node.image = img
                    done.append(fname)
                    break
    if len(done) != len([f for f in want.values() if (tex_dir / f).exists()]):
        raise RuntimeError(f'{obj.name}: reworked textures in {tex_dir} did not all find their slot ({done})')
    print(f'[fit] {obj.name}: textures from {tex_dir.name} ({", ".join(done)})', flush=True)


def place(obj, pl):
    """Apply the step-5 rigid transform: world = M_place @ (glb node transform) @ mesh. Then bake that rigid
    transform into the vertex positions so weights and exports work in rig space. Shape is unchanged."""
    M = Matrix(pl['matrix'])
    obj.matrix_world = M @ obj.matrix_world
    obj.data.transform(obj.matrix_world)
    obj.matrix_world = Matrix.Identity(4)


def rigid_skin(obj):
    """Rigid pieces follow one bone per connected part (each shoe its foot, a bag the spine): every vertex of a
    part gets weight 1 on the bone that dominates that part's copied weights. (Weights only.)"""
    me = obj.data
    co, wid, edges = F.welded(me)
    parent = list(range(len(co)))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a
    for a, b in edges:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb
    island = np.array([find(wid[i]) for i in range(len(me.vertices))])
    names = [g.name for g in obj.vertex_groups]
    W = np.zeros((len(me.vertices), len(names)))
    for v in me.vertices:
        for ge in v.groups:
            W[v.index, ge.group] = ge.weight
    chosen = {}
    for isl in np.unique(island):
        sel = island == isl
        if sel.sum() >= 30:
            chosen[int(isl)] = names[int(W[sel].sum(0).argmax())]
    big = max(chosen, key=lambda i: (island == i).sum()) if chosen else None
    obj.vertex_groups.clear()
    groups = {}
    for v in me.vertices:
        bone = chosen.get(int(island[v.index]), chosen.get(big))
        if bone is not None:
            g = groups.get(bone) or groups.setdefault(bone, obj.vertex_groups.new(name=bone))
            g.add([v.index], 1.0, 'REPLACE')
    return sorted(set(chosen.values()))


CONTAINS = {'footwear': ('LeftFoot', 'RightFoot', 'LeftToe', 'RightToe'), 'headwear': ('Head',)}


def inside_volume(bvh, p, up=Vector((0, 0, 1))):
    """Ray-parity test: is point p inside the closed mesh?"""
    n, o = 0, Vector(p)
    for _ in range(20):
        hit = bvh.ray_cast(o, up, 5.0)
        if hit[0] is None:
            break
        n += 1
        o = hit[0] + up * 1e-5
    return n % 2 == 1


def split_pair(obj):
    """A pair of shoes generated as one mesh -> a left and a right object (faces by which side of the body their
    centre is on). Nothing is reshaped; the two shoes just become separately placeable."""
    me = obj.data
    left = [p.index for p in me.polygons if (obj.matrix_world @ p.center).x > 0]
    if not left or len(left) == len(me.polygons):
        return [obj]
    right_obj = obj.copy()
    right_obj.data = me.copy()
    bpy.context.scene.collection.objects.link(right_obj)
    out = []
    for o, keep_left in ((obj, True), (right_obj, False)):
        bm = bmesh.new()
        bm.from_mesh(o.data)
        doomed = [f for f in bm.faces if ((o.matrix_world @ f.calc_center_median()).x > 0) != keep_left]
        bmesh.ops.delete(bm, geom=doomed, context='FACES')
        bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context='VERTS')
        bm.to_mesh(o.data)
        bm.free()
        o.name = o.data.name = obj.name.split('.')[0] + ('_L' if keep_left else '_R')
        out.append(o)
    return out


def fit_to_body(obj, body, names, W, slot, side=None):
    """Rigid fit for pieces that must contain a body part (a shoe contains its foot, a hat the head): the image gave
    orientation and size; here translation (coarse, then fine), yaw and uniform scale are searched so that as much
    of that body part as possible lies inside the piece. Footwear soles must stay at or below the foot sole.
    Moves the object as a whole - its mesh is not edited."""
    keys = CONTAINS[slot]
    if side:
        keys = tuple(k for k in keys if k.startswith(side))
    bone_of = np.array([names[i] for i in W.argmax(1)])
    sel = np.array([any(b.startswith(k) for k in keys) for b in bone_of])
    pts = np.array([body.matrix_world @ v.co for v in body.data.vertices])[sel]
    pts = pts[np.linspace(0, len(pts) - 1, min(len(pts), 120)).astype(int)]
    co = np.array([(obj.matrix_world @ v.co)[:] for v in obj.data.vertices])
    bvh = F.bvh_of(co, [tuple(p.vertices) for p in obj.data.polygons])
    centre = (co.min(0) + co.max(0)) / 2
    sole, foot_sole = co[:, 2].min(), pts[:, 2].min()

    def evaluate(s, yaw, t):
        new_sole = (sole - centre[2]) * s + centre[2] + t[2]
        if slot == 'footwear' and new_sole > foot_sole + 0.003:
            return None
        R = np.array(Matrix.Rotation(np.radians(yaw), 3, 'Z'))
        local = ((pts - centre - t) @ R) / s + centre  # body points in the piece's own frame
        inside = sum(inside_volume(bvh, p) for p in local)
        return inside - 0.3 * float(np.abs(t).sum()), inside

    best = None
    for dz in np.arange(-0.04, 0.121, 0.01):
        for dy in np.arange(-0.10, 0.101, 0.01):
            for dx in np.arange(-0.04, 0.041, 0.01):
                r = evaluate(1.0, 0, np.array([dx, dy, dz]))
                if r and (best is None or r[0] > best[0]):
                    best = (r[0], 1.0, 0, np.array([dx, dy, dz]), r[1])
    for s in (0.9, 0.95, 1.0, 1.05, 1.1, 1.15, 1.2):
        for yaw in range(-15, 16, 3):
            for d in [np.array(v) * 0.005 for v in np.ndindex(3, 3, 3)]:
                t = best[3] + d - 0.005
                r = evaluate(s, yaw, t)
                if r and r[0] > best[0]:
                    best = (r[0], s, yaw, t, r[1])
    _, s, yaw, t, inside = best
    R = Matrix.Rotation(np.radians(yaw), 4, 'Z')
    M = Matrix.Translation(Vector(centre) + Vector(t)) @ R @ Matrix.Scale(s, 4) @ Matrix.Translation(-Vector(centre))
    obj.matrix_world = M @ obj.matrix_world
    obj.data.transform(obj.matrix_world)
    obj.matrix_world = Matrix.Identity(4)
    return {'body_part_inside': round(inside / len(pts), 3), 'scale': s, 'yaw_deg': yaw,
            'move_m': [round(float(x), 3) for x in t]}


TORSO_SLOTS = {'top', 'outerwear', 'fullbody', 'bottom'}
SKIN_CLEAR = 0.003      # a garment's outer surface must lie at least this far above the skin
MAX_SCALE = 1.06        # torso clearance: largest uniform scale on top of the image placement
MAX_MOVE = 0.02         # ...and largest move per axis (m)
MAX_TILT = 8.0          # ...and largest forward/back tilt (deg)
SEAT_GAP = 0.006        # a top rests this far above the tops of the shoulders (outer surface over the skin)


def torso_clearance(g, base, body, names, W, slot):
    """RIGID clearance of a garment from the skin (shape untouched): uniform scale about the garment's covered-torso
    centre + translation, pattern-searched so that no skin pokes through its outer surface (outer surface >=
    SKIN_CLEAR above the skin at every torso/hip cage point it covers), with a small pull back to the image
    placement. Limbs are left to rig_fit. Returns the report; the transform is baked into the mesh."""
    cage = np.load(ROOT / 'Bases' / f'{base}_cage.npz')
    co, n = cage['co'], cage['n']
    bco, _ = F.world_verts(body, evaluated=True)
    bb = M.chain_bone_of(names, W)
    from mathutils.kdtree import KDTree
    kd = KDTree(len(bco))
    for i, q in enumerate(bco):
        kd.insert(Vector(q), i)
    kd.balance()
    cb = np.array([bb[kd.find(Vector(q))[1]] for q in co])
    region = (cb == '') | ((cb == 'LeftUpLeg') | (cb == 'RightUpLeg')) & (slot in ('bottom', 'fullbody'))
    bvh = F.bvh_of(*F.world_verts(g))
    B0 = M.outer_heights(bvh, co, n)
    sel = np.nonzero(region & ~np.isnan(B0))[0]
    if len(sel) < 40:
        return {'skipped': f'only {len(sel)} torso points covered'}
    pc, pn = co[sel], n[sel]
    pivot = pc.mean(0)
    # SEAT: a top hangs from the shoulders - the tops of the shoulders (upward-facing skin between the chest and the
    # neck) are where it rests, a few mm off. Without this the clearance happily lifts a top off the shoulders (and its
    # collar off the neck) to clear a tight spot elsewhere.
    lm = json.loads((ROOT / 'Bases' / f'{base}.json').read_text())['landmarks']
    shoulder = (pn[:, 2] > 0.4) & (pc[:, 2] > lm['Spine2'][2] + 0.05) & (pc[:, 2] < lm['Neck'][2] + 0.02)
    seat = slot in ('top', 'outerwear', 'fullbody') and shoulder.sum() >= 10
    # ...and its collar sits evenly a few mm off the base of the neck, front and back (sideways-facing neck skin)
    neck = (np.abs(pn[:, 2]) < 0.5) & (pc[:, 2] > lm['Neck'][2] - 0.04) & (pc[:, 2] < lm['Neck'][2] + 0.01)
    neck_f, neck_b = neck & (pn[:, 1] < -0.3), neck & (pn[:, 1] > 0.3)
    import shells as SH
    shell_bands = [(b['z'][0], b['z'][1], (b['bottom_max'] + SH.GAP_MM) / 1000) for b in SH.BANDS.values()]

    def unmove(x):
        """The cage seen in the garment's original frame, for scale x[0], move x[1:4], tilt x[4] (deg, about the
        left-right axis through the pivot: a top leaning forward or back on the body)."""
        s, t, rx = x[0], x[1:4], np.radians(x[4])
        c, sn = np.cos(-rx), np.sin(-rx)
        Rinv = np.array([[1, 0, 0], [0, c, -sn], [0, sn, c]])
        return pivot + ((pc - pivot - t) @ Rinv.T) / s, pn @ Rinv.T

    def cost(x):
        s, t = x[0], x[1:4]
        q, qn = unmove(x)
        B = M.outer_heights(bvh, q, qn) * s
        lost = np.isnan(B)
        poke = np.clip(SKIN_CLEAR - np.nan_to_num(B, nan=SKIN_CLEAR), 0, None)
        c = 50 * poke.mean() + 0.01 * lost.mean() + 0.002 * (s - 1) + 0.005 * np.linalg.norm(t) + 0.0002 * abs(x[4])
        if seat:
            Bs = B[shoulder]
            c += 0.5 * float(np.nanmean(np.clip(Bs - SEAT_GAP, 0, None))) if (~np.isnan(Bs)).any() else 0.01
            # the hem stays outside the bottoms' standard envelope while it seats (shells.BANDS): seating must never
            # lower or tilt a top onto whatever trousers it is worn over. (The collar itself is settled by the
            # customizer - user-approved, v38 - so the placement no longer pulls the collar in.)
            for zl, zh, need in shell_bands:
                mb = (pc[:, 2] - lm['Hips'][2] >= zl) & (pc[:, 2] - lm['Hips'][2] < zh) & ~np.isnan(B)
                if mb.sum() >= 5:
                    c += 5 * float(np.clip(need - B[mb], 0, None).mean())
        return float(c), int((np.nan_to_num(B, nan=1) < SKIN_CLEAR).sum())

    x = np.array([1.0, 0, 0, 0, 0.0])
    best, poke0 = cost(x)
    steps = np.array([0.02, 0.008, 0.008, 0.008, 2.0])
    lo = np.array([1 / MAX_SCALE, -MAX_MOVE, -MAX_MOVE, -MAX_MOVE, -MAX_TILT])
    hi = np.array([MAX_SCALE, MAX_MOVE, MAX_MOVE, MAX_MOVE, MAX_TILT])
    while steps[:4].max() > 0.001 or steps[4] > 0.25:
        improved = False
        for j in range(5):
            for sgn in (1, -1):
                y = x.copy()
                y[j] = np.clip(y[j] + sgn * steps[j], lo[j], hi[j])
                c, _ = cost(y)
                if c < best - 1e-8:
                    x, best, improved = y, c, True
        if not improved:
            steps /= 2
    _, poke1 = cost(x)
    T = (Matrix.Translation(Vector(pivot + x[1:4])) @ Matrix.Rotation(np.radians(x[4]), 4, 'X') @ Matrix.Scale(x[0], 4)
         @ Matrix.Translation(Vector(-pivot)))
    g.data.transform(T)
    g.data.update()
    rep = {'scale': round(float(x[0]), 3), 'move_cm': [round(float(v) * 100, 2) for v in x[1:4]],
           'tilt_deg': round(float(x[4]), 2),
           'skin_poke_points': [poke0, poke1], 'points': int(len(sel))}
    if seat:
        q, qn = unmove(x)
        Bs = (M.outer_heights(bvh, q, qn) * x[0])[shoulder]
        rep['shoulder_gap_mm'] = round(float(np.nanmedian(Bs)) * 1000, 1)
        Ball = M.outer_heights(bvh, q, qn) * x[0]
        for nm, m in (('neck_front_gap_mm', neck_f), ('neck_back_gap_mm', neck_b)):
            if m.sum() and (~np.isnan(Ball[m])).any():
                rep[nm] = round(float(np.nanmedian(Ball[m])) * 1000, 1)
    print(f'[fit]   torso clearance (rigid): {rep}', flush=True)
    return rep


def level_sole(obj):
    """RIGID: rotate a shoe about its centre so its sole (the area-weighted normal of its downward-facing faces) points
    straight down - a generated shoe is often pitched or rolled a degree or two."""
    me = obj.data
    acc = Vector((0, 0, 0))
    for f in me.polygons:
        if f.normal.z < -0.7:
            acc += f.normal * f.area
    if acc.length < 1e-9:
        return 0.0
    n = acc.normalized()
    q = n.rotation_difference(Vector((0, 0, -1)))
    c = Vector(np.array([v.co[:] for v in me.vertices]).mean(0))
    me.transform(Matrix.Translation(c) @ q.to_matrix().to_4x4() @ Matrix.Translation(-c))
    me.update()
    return float(np.degrees(q.angle))


def level_feet(arm):
    """Pose for the feet that keeps them in their rest orientation (flat) whatever the legs are posed to:
    {bone: matrix_basis}. The arm is left posed with them."""
    out = {}
    for name in ('LeftFoot', 'RightFoot'):
        pb = arm.pose.bones.get(name)
        if pb is None:
            continue
        m = pb.bone.matrix_local.to_3x3().to_4x4()
        m.translation = pb.matrix.translation
        pb.matrix = m
        bpy.context.view_layer.update()
        out[name] = [list(r) for r in pb.matrix_basis]
    return out


def joint_w(arm, bone):
    return arm.matrix_world @ arm.pose.bones[bone].head


# upper / lower segment of a limb; the lower one is sampled densely towards its opening, where a short tight cuff
# (an ankle or wrist band only ~1/10 of the bone long) must be found by more than one plane
SECTION_TS = {0: np.linspace(0.15, 0.95, 9), 1: np.r_[np.linspace(0.1, 0.6, 6), np.linspace(0.65, 1.1, 19)]}


# Every failure the inspection would report for this limb costs FAIL (5 cm): a pose is chosen first for the fewest
# failures, the section cost only decides between poses that fail equally (inspect_look.LIMITS)
FAIL = 0.05
JOINT_SPAN, JOINT_STEP = 12, 3         # parent turn tried when an end segment still fails from its joint (deg)
JOINT_PASSES = ((24, 6), (4, 2), (1, 1))
IN_LINING_MAX, OUTSIDE_SOLID_MAX, END_OFFSET_MAX, RIM_TOUCH_MAX = 0.1, 0.1, 0.008, 0.25


def violations(e, judged_solid=True):
    if e['cavity']:
        return int(e['in_material'] > IN_LINING_MAX) + int(e['offset'] > END_OFFSET_MAX and e.get('touch', 0) > RIM_TOUCH_MAX)
    return int(judged_solid and 1 - e['in_material'] > OUTSIDE_SOLID_MAX)


def section_cost(e):
    """Cost of one cross-section (metres). Hollow sleeve: the limb must be in the hole (not in the lining) and centred
    on it. Solid AI sleeve / trouser leg (the limb is embedded): the limb must stay inside it, loosely centred."""
    if e['cavity']:  # in the hole, centred, and clear of the wall all round (the RPG gap - no rubbing through it)
        return 0.05 * e['in_material'] + e['offset'] + 0.01 * e.get('touch', 0.0)
    # inside baggy fabric any position is fine: stay inside, only a weak pull to the middle
    return 0.05 * (1 - e['in_material']) + 0.05 * (e['offset'] or 0.0)


def rig_fit(arm, garment, slot, body, names, W, coarse=(24, 4), fine=(3, 1)):
    """Pose the rig INTO the garment, limb by limb, from the body outward (garment untouched).
    Each limb segment is judged on planar CROSS-SECTIONS of the garment (metrics.SectionField) - not rays, which
    double-walled AI sleeves fool - at fixed planes along the segment; the opening end (t >= 0.6 of the last
    segment) counts double. Searched over rotations about the two axes PERPENDICULAR to the bone (rotating about
    world X twists a horizontal arm and cannot move it), coarse then fine. Returns {bone: matrix_basis}, report."""
    limbs = M.SLOT_LIMBS.get(slot)
    if not limbs:
        return {}, {}
    gco, gtri = M.tri_mesh(garment)
    gbvh = F.bvh_of(gco, [tuple(t) for t in gtri])
    body_co, _ = F.world_verts(body, evaluated=True)  # rest pose
    ev_ = body.evaluated_get(bpy.context.evaluated_depsgraph_get()).to_mesh()
    R3_ = body.matrix_world.to_3x3()
    body_nrm = np.array([(R3_ @ v.normal).normalized()[:] for v in ev_.vertices])
    body.evaluated_get(bpy.context.evaluated_depsgraph_get()).to_mesh_clear()
    body_bone = M.chain_bone_of(names, W)
    report = {}

    def fit_segment(si, bone, child, last):
        """Fit one limb segment (bone -> child) by rotating its bone; returns handles to search it again."""
        pb = arm.pose.bones[bone]
        skin_rest = M.limb_skin(body_co, body_bone, bone, child)
        nrm_rest = M.limb_skin(body_nrm, body_bone, bone, child)
        # the same skin with its real blended weights (armpit skin is part torso, part arm): pokes are judged on
        # where the skin actually goes, not on a rigid copy of the bone
        sel_ = (body_bone == bone) | ((body_bone == child) if child in M.END_BONES else False)
        Wsel = np.asarray(W)[sel_]
        used = np.nonzero(Wsel.sum(0) > 0)[0]
        Wsel, used_names = Wsel[:, used], [names[k] for k in used]
        if len(skin_rest) < 40:
            raise RuntimeError(f'{bone}: only {len(skin_rest)} skin points - weight lookup broken, refusing to fit')

        def posed_skin(normals=False):
            if not normals:  # cross-sections: the limb's own outline, carried by its bone
                Ms = np.array(F.skin_matrices(arm, [bone])[0])
                return (np.c_[skin_rest, np.ones(len(skin_rest))] @ Ms.T)[:, :3]
            Mv = np.einsum('vb,bij->vij', Wsel / np.maximum(Wsel.sum(1, keepdims=True), 1e-9),
                           np.array(F.skin_matrices(arm, used_names)))
            pts = np.einsum('vij,vj->vi', Mv, np.c_[skin_rest, np.ones(len(skin_rest))])[:, :3]
            return pts, np.einsum('vij,vj->vi', Mv[:, :3, :3], nrm_rest)

        gco_np = np.asarray(gco)

        def threading():
            pts, _ = posed_skin(True)
            return M.thread_check(gbvh, gco_np, pts, np.array(joint_w(arm, bone)), np.array(joint_w(arm, child)))

        def pokes():
            """Skin points of this segment poking > 1 mm through the garment's surface in this pose (the armpit
            seam of a sleeve, a cuff lip): the cross-sections can be fine while a seam still cuts the skin."""
            pts, nr = posed_skin(True)
            k = 0
            for q, nn in zip(pts, nr):
                nv = Vector(nn).normalized()
                h = gbvh.ray_cast(Vector(q) - nv * M.POKE_TOL, -nv, 0.015)
                if h[0] is not None and h[1].dot(nv) > 0 and not M.inside_solid(gbvh, q):
                    k += 1
            return k
        a, b = np.array(joint_w(arm, bone)), np.array(joint_w(arm, child))
        n, u, v = M.plane_basis(b - a)
        sk = posed_skin()
        fields = []
        for t in SECTION_TS[si]:
            c = M.skin_centre(sk, a, b, float(t))
            if c is None:
                continue
            segs = M.plane_section(gco, gtri, c, n, u, v)
            if not len(segs):
                continue
            fields.append((c, M.SectionField(segs), 2.0 if last and t >= 0.6 else 1.0, float(t)))
        if not fields:
            return None  # no tube along this bone (short sleeve forearm, shorts shin)

        def score(active=None):
            pts = posed_skin()
            tot = wsum = 0.0
            det = []
            for c, sf, w, t in fields:
                ring2 = M.skin_ring_2d(pts, c, n, u, v)
                if ring2 is None:
                    continue
                e = sf.evaluate(ring2)
                if active is None:
                    if e['enclosed'] < 0.3 and not e['cavity']:
                        continue  # this slice is past the garment's hem (a short sleeve): nothing to fit
                elif t not in active:
                    continue  # judged once, in the starting pose: a pose cannot escape by leaving the garment
                # a hole the limb must pass through (cuff, sleeve opening) decides where the limb goes
                wk = w * (3.0 if e['cavity'] else 1.0)
                tot += wk * section_cost(e)
                wsum += wk
                det.append((t, e))
            base_cost = (tot / wsum if wsum else 1.0)
            hem = max([t for t, _ in det], default=0) - 0.1 if last else 9  # the hem itself may be thin (as inspect)
            cav_t = [t for t, e in det if e['cavity']]
            lo = -9
            if cav_t:  # a hollow sleeve: its armhole (before) and hem (after the hollow slices) are transitions
                hem, lo = min(hem, max(cav_t)), min(cav_t)
            fails = sum(violations(e, lo < t < hem) for t, e in det) + pokes()
            # the limb must come out through the garment's opening (judged from the garment's own end, so a
            # limb leaving through a wall cannot hide the cuff): a failure, plus a pull towards threading it
            th = threading()
            if os.environ.get('FIT_DEBUG_THREAD') and th is not None:
                print('[thr]', bone, np.round(np.array(joint_w(arm, child)), 3), th['offset_cm'], th['wall_exit_cm_before_opening'], flush=True)
            if th is not None:
                # a limb out through a wall is the most visible defect a fit can have: it outweighs the rest
                fails += 3 * int(not th['threaded'])
                miss = (th['offset_cm'] + th['limb_r_cm'] - th['ring_r_cm']) / 100 + 0.002
                base_cost += 2.0 * max(0.0, miss) + (0.05 if th['wall_exit_cm_before_opening'] is not None else 0)
            if os.environ.get('FIT_DEBUG_THREAD') and th is not None:
                print('[cost]', bone, round(base_cost, 4), fails, int(not th['threaded']), pokes(),
                      [(round(t, 2), violations(e, lo < t < hem)) for t, e in det if violations(e, lo < t < hem)], flush=True)
            return base_cost + FAIL * fails, det

        base = pb.matrix_basis.copy()
        first = score()
        # the same slices the inspection judges: up to the last one that still wraps the limb (past it is the
        # hand/foot beyond the cuff, whose wide outline says nothing about the opening)
        wraps = [t for t, e in first[1] if e.get('enclosed', 0) >= 0.5]
        active = {t for t, _ in first[1] if not wraps or t <= max(wraps)}

        def turn(ax, ay):
            pb.matrix_basis = base
            bpy.context.view_layer.update()
            F.rotate_bone_world(arm, bone, Vector(u), np.radians(ax))
            F.rotate_bone_world(arm, bone, Vector(v), np.radians(ay))

        def search(passes=(coarse, fine)):
            """Best rotation of this bone (the parent's pose as it is now); leaves the bone at it."""
            r0 = score(active)
            best = (r0[0], 0.0, 0.0, r0)
            for span, step in passes:
                cx, cy = best[1], best[2]
                for ax in np.arange(cx - span, cx + span + 1e-6, step):
                    for ay in np.arange(cy - span, cy + span + 1e-6, step):
                        turn(ax, ay)
                        r = score(active)
                        cost = r[0] + 0.0004 * np.hypot(ax, ay)
                        if cost < best[0]:
                            best = (cost, ax, ay, r)
            turn(best[1], best[2])
            return best

        def summary(det):
            cav = [e for _, e in det if e['cavity']]
            return {'cost_cm': None, 'hollow_slices': len(cav),
                    'max_in_lining': round(max([e['in_material'] for e in cav], default=0.0), 2),
                    'max_hole_offset_cm': round(100 * max([e['offset'] for e in cav], default=0.0), 1),
                    'max_touch': round(max([e.get('touch', 0.0) for e in cav], default=0.0), 2),
                    'min_inside_solid': round(min([e['in_material'] for _, e in det if not e['cavity']], default=1.0), 2)}

        def record(best, first):
            s0, s1 = summary(first[1]), summary(best[3][1])
            s1['pokes'] = pokes()  # the chosen pose is applied at this point
            s1['thread'] = threading()
            s0['cost_cm'], s1['cost_cm'] = round(first[0] * 100, 2), round(best[3][0] * 100, 2)
            report[bone] = {'rot_deg_about_perp_axes': [float(best[1]), float(best[2])], 'before': s0, 'after': s1}
            print(f'[fit]   {bone}: rot {report[bone]["rot_deg_about_perp_axes"]} deg, before {s0}, after {s1}', flush=True)

        first = score(active)
        best = search()
        record(best, first)
        return {'bone': bone, 'search': search, 'turn': turn, 'record': record, 'score': lambda: score(active),
                'threading': threading, 'pokes': pokes,
                'best': best, 'first': first, 'base': base}

    for limb in limbs:
        chain = M.LIMB_CHAINS[limb]
        segs = []
        for si, (bone, child) in enumerate(chain):
            segs.append(fit_segment(si, bone, child, si == len(chain) - 1))
        end, up = segs[-1], (segs[-2] if len(segs) > 1 else None)
        th = report.get(end['bone'], {}).get('after', {}).get('thread') if end else None
        # the end segment still fails from where its joint is: it misses its opening, or it runs through the sleeve's
        # lining (a cost at or over one failure) - a sleeve that bends at the elbow differently from the arm
        stuck = end and ((th is not None and not th['threaded']) or end['best'][0] >= FAIL)
        if end and up and stuck:
            # Turn the segment above it a little too, re-fitting the end each time,
            # and keep the pair with the lowest combined cost (still only posing the avatar).
            u0 = up['best']
            best = (u0[0] + end['best'][0], u0, end['best'])
            was_threaded, pokes0 = bool(th and th['threaded']), end['pokes']()
            for dx in np.arange(-JOINT_SPAN, JOINT_SPAN + 1e-6, JOINT_STEP):
                for dy in np.arange(-JOINT_SPAN, JOINT_SPAN + 1e-6, JOINT_STEP):
                    if not dx and not dy:
                        continue
                    ax, ay = u0[1] + dx, u0[2] + dy
                    up['turn'](ax, ay)
                    ru = up['score']()
                    cu = ru[0] + 0.0004 * np.hypot(ax, ay)
                    if cu >= best[0]:
                        continue
                    e = end['search'](JOINT_PASSES)
                    # never trade the opening or the skin for fewer lining slices: a limb out through the wall or
                    # skin through the fabric shows; a forearm crossing the sleeve's inner wall deep in its padding
                    # does not
                    th_e = end['threading']()
                    if (was_threaded and not (th_e and th_e['threaded'])) or end['pokes']() > pokes0:
                        continue
                    if cu + e[0] < best[0]:
                        best = (cu + e[0], (cu, ax, ay, ru), e)
            up['turn'](best[1][1], best[1][2])
            end['turn'](best[2][1], best[2][2])
            if best[1] is not u0:
                print(f"[fit]   {end['bone']}: not threaded from its joint - {up['bone']} turned as well", flush=True)
                up['record'](best[1], up['first'])
                end['record'](best[2], end['first'])
    pose = {b: [list(r) for r in arm.pose.bones[b].matrix_basis] for b in report}
    return pose, report


def skin_in_pose(garment, arm, body, pose, names, W):
    """Copy weights with the rig posed into the garment, then return the rig to its T-pose rest: the garment follows
    by ordinary linear-blend skinning (normal deformation - no cutting, pushing or sculpting)."""
    for pb in arm.pose.bones:
        pb.matrix_basis = Matrix.Identity(4)
    for bone, m in pose.items():
        arm.pose.bones[bone].matrix_basis = Matrix(m)
    bpy.context.view_layer.update()
    bco, bpolys = F.world_verts(body, evaluated=True)
    w, gnames = F.transfer_weights(garment, bco, bpolys, names, W, rig=arm)
    if pose:
        posed = F.skin_matrices(arm, gnames)
        rest = np.array([np.eye(4)] * len(gnames))
        before = np.array([v.co[:] for v in garment.data.vertices])
        repose(garment, w, posed, rest)
        moved = np.linalg.norm(np.array([v.co[:] for v in garment.data.vertices]) - before, axis=1)
        # stored in rest space only; it is SHOWN in its fit pose (equip poses the avatar), i.e. exactly as generated
        print(f'[fit]   rest-space copy differs from the generated mesh by up to {moved.max() * 1000:.1f} mm '
              f'(storage only - shown undeformed in its fit pose)', flush=True)
    moved_mm = round(float(moved.max()) * 1000, 2) if pose else 0.0
    for pb in arm.pose.bones:
        pb.matrix_basis = Matrix.Identity(4)
    bpy.context.view_layer.update()
    return moved_mm


def repose(garment, weights, mats_from, mats_to):
    me = garment.data
    co = np.array([v.co[:] + (1.0,) for v in me.vertices])
    b_from = np.einsum('vb,bij->vij', weights, mats_from)
    b_to = np.einsum('vb,bij->vij', weights, mats_to)
    new = np.einsum('vij,vj->vi', b_to, np.einsum('vij,vj->vi', np.linalg.inv(b_from), co))[:, :3]
    for v, p in zip(me.vertices, new):
        v.co = p
    me.update()


def body_covered(body, body_co, normals, garments, reach=0.15, erode=2):
    """Skin a set of garments covers: a ray straight out from the skin meets a garment within `reach`. The hidden
    region is then shrunk back from its edge by `erode` rings of body vertices, so skin at every garment boundary
    (ankles, wrists, neck) stays visible and can never show a see-through gap."""
    hidden = set(F.covered_body_verts(body_co, normals, garments, max_dist=reach))
    if not hidden:
        return []
    co, wid, edges = F.welded(body.data)
    h = np.zeros(len(co))
    for i in hidden:
        h[wid[i]] = 1
    a, b = edges[:, 0], edges[:, 1]
    for _ in range(erode):
        keep = h.copy()
        np.minimum.at(keep, a, h[b])
        np.minimum.at(keep, b, h[a])
        h = keep
    return [i for i, u in enumerate(wid) if h[u]]


def covered_by(inner, outer, body_bvh, near=0.04, erode=2):
    """Vertices of `inner` that `outer` covers: a ray from the body out through the vertex meets `outer` anywhere
    before the vertex (inner poking through) or within `near` metres beyond it. Hidden only while both
    are worn - the mesh is never changed. The hidden region is majority-smoothed, then shrunk back from its edge
    by `erode` rings so a hem boundary can never open a see-through gap."""
    o_co, o_polys = F.world_verts(outer)
    o_bvh = F.bvh_of(o_co, o_polys)
    co, wid, edges = F.welded(inner.data)
    hidden = np.zeros(len(co))
    for u, p in enumerate(co):
        p = Vector(p)
        hit, n, _, _ = body_bvh.find_nearest(p)
        if hit is None:
            continue
        d = p - hit
        r = d.length
        d = d.normalized() if r > 1e-6 else n
        # outer anywhere between the body and the vertex (inner poking through), or just outside it
        hidden[u] = o_bvh.ray_cast(hit + d * 1e-4, d, r + near)[0] is not None
    for _ in range(3):
        hidden = (F.smooth_on_edges(hidden[:, None], edges, 1)[:, 0] > 0.5).astype(float)
    a, b = edges[:, 0], edges[:, 1]
    for _ in range(erode):  # shrink: a vertex stays hidden only if all its neighbours are hidden
        keep = hidden.copy()
        np.minimum.at(keep, a, hidden[b])
        np.minimum.at(keep, b, hidden[a])
        hidden = keep
    return [i for i, u in enumerate(wid) if hidden[u]]


def main():
    d = Path(sys.argv[sys.argv.index('--') + 1]).resolve()
    base = sys.argv[sys.argv.index('--') + 2]
    out = d / '06_fitted'
    out.mkdir(exist_ok=True)
    placement = json.loads((d / '05_place' / 'placement.json').read_text())
    arm, body, base_meshes = F.load_base(base)
    for pb in arm.pose.bones:
        pb.matrix_basis = Matrix.Identity(4)
    bpy.context.view_layer.update()
    body_co, body_polys = F.world_verts(body, evaluated=True)
    names, W = F.body_weights(body)
    normals = np.array([body.matrix_world.to_3x3() @ v.normal for v in body.data.vertices])

    manifest = {'outfit': d.name, 'base': base, 'rest_pose': 'T-pose', 'meshes': 'as generated (rigid placement only)',
                'pieces': {}}
    pieces, info = {}, {}
    for key, pl in placement.items():
        if key.startswith('_'):
            continue
        slot = SLOTS[pl['slot']]
        g = import_piece(d / '04_meshes' / f'{key}.glb', key)
        place(g, pl)
        if pl['slot'] == 'footwear':
            parts = split_pair(g)
            pl['body_fit'] = {}
            for part, side in zip(parts, ('Left', 'Right') if len(parts) == 2 else (None,)):
                level_sole(part)  # rigid: the sole flat on the floor before the foot is fitted into it
                pl['body_fit'][part.name] = fit_to_body(part, body, names, W, 'footwear', side)
                print(f"[fit] {part.name}: fitted to the {side or ''} foot -> {pl['body_fit'][part.name]}", flush=True)
            floor = float(np.mean([min(v.co.z for v in pt.data.vertices) for pt in parts]))
            for pt in parts:  # both soles on the same floor (rigid move up/down)
                dz = floor - min(v.co.z for v in pt.data.vertices)
                pt.data.transform(Matrix.Translation((0, 0, dz)))
            pl['floor_z'] = round(floor, 4)
            if len(parts) == 2:  # keep the pair as one piece object for export
                with bpy.context.temp_override(active_object=parts[0], selected_editable_objects=parts):
                    bpy.ops.object.join()
                g = parts[0]
                g.name = g.data.name = key
        elif pl['slot'] in CONTAINS:
            pl['body_fit'] = fit_to_body(g, body, names, W, pl['slot'])
            print(f"[fit] {key}: fitted to the body -> {pl['body_fit']}", flush=True)
        if slot['rigid']:
            F.transfer_weights(g, body_co, body_polys, names, W, rig=arm)
            rigid_bones = rigid_skin(g)
        else:
            rigid_bones = None
            if pl['slot'] in TORSO_SLOTS:
                pl['torso_clearance'] = torso_clearance(g, base, body, names, W, pl['slot'])
            print(f'[fit] {key}: fitting the rig into its tubes', flush=True)
            pose, fitrep = rig_fit(arm, g, pl['slot'], body, names, W)
            if any(b in pose for b in ('LeftUpLeg', 'LeftLeg', 'RightUpLeg', 'RightLeg')):
                pose.update(level_feet(arm))  # legs posed into the trousers: the feet stay flat on the floor
            if pose:
                pl['rig_fit'] = fitrep
                pl['fit_pose'] = pose  # the avatar pose this piece is shown in UNDEFORMED (equip poses the avatar to it)
            pl['rest_copy_max_mm'] = skin_in_pose(g, arm, body, pose, names, W)
        F.attach(g, arm)
        covered = [] if pl['slot'] == 'accessory' else body_covered(body, body_co, normals, [g])
        pieces[key], info[key] = g, (pl, slot, rigid_bones, covered)

    # Inner layers: the part an outer layer covers is hidden while both are worn (vertex group + manifest; a Mask
    # modifier in this outfit's preview). The inner mesh itself stays whole and unedited.
    body_bvh = F.bvh_of(body_co, body_polys)
    under = {}
    pairs = [(k_in, k_out) for k_in in pieces for k_out in pieces
             if not info[k_in][1]['rigid'] and info[k_in][0]['slot'] != 'hair'
             and info[k_out][1]['layer'] > info[k_in][1]['layer'] and not info[k_out][1]['rigid']
             and info[k_out][0]['slot'] != 'hair']
    cover = {pr: covered_by(pieces[pr[0]], pieces[pr[1]], body_bvh) for pr in pairs}
    # Pass 1: a piece mostly covered by an outer one is hidden entirely while worn under it (no peeking hem).
    gone = set()
    for (k_in, k_out), idx in cover.items():
        if len(idx) >= 0.5 * len(pieces[k_in].data.vertices):
            gone.add(k_in)
            info[k_in][0].setdefault('hidden_entirely_under', []).append(k_out)
    # Pass 2: partial hiding, only by outer pieces that are themselves visible.
    for (k_in, k_out), idx in cover.items():
        g_in = pieces[k_in]
        if k_in in gone:
            idx = list(range(len(g_in.data.vertices))) if k_out in info[k_in][0]['hidden_entirely_under'] else []
        elif k_out in gone:
            continue
        if idx:
            g_in.vertex_groups.new(name=f'hidden_under__{k_out}').add(idx, 1.0, 'REPLACE')
            under.setdefault(k_in, {})[k_out] = idx
            print(f'[fit] {k_in}: {len(idx)} of {len(g_in.data.vertices)} verts hidden while under {k_out}', flush=True)
    for k_in, outs in under.items():
        g = pieces[k_in]
        allg = g.vertex_groups.new(name='hidden_under_this_outfit')
        allg.add(sorted({i for idx in outs.values() for i in idx}), 1.0, 'REPLACE')
        m = g.modifiers.new('hide_when_layered', 'MASK')
        m.vertex_group = allg.name
        m.invert_vertex_group = True

    for key, g in pieces.items():
        pl, slot, rigid_bones, covered = info[key]
        g.name = f'{d.name}__{pl["slot"]}__{key}'
        bpy.ops.object.select_all(action='DESELECT')
        for o in (arm, g):
            o.select_set(True)
        bpy.context.view_layer.objects.active = arm
        stem = f'{d.name}__{key}'
        bpy.ops.export_scene.gltf(filepath=str(out / f'{stem}.glb'), export_format='GLB', use_selection=True,
                                  export_skins=True, export_animations=False, export_morph=False)
        bpy.ops.export_scene.fbx(filepath=str(out / f'{stem}.fbx'), use_selection=True, object_types={'ARMATURE', 'MESH'},
                                 use_mesh_modifiers=False, add_leaf_bones=False, bake_anim=False, path_mode='COPY',
                                 embed_textures=True)
        manifest['pieces'][key] = {'slot': pl['slot'], 'layer': slot['layer'], 'rigid': slot['rigid'],
                                   'rigid_bones': rigid_bones, 'fit': {k: v for k, v in pl.items() if k != 'matrix'},
                                   'files': [f'{stem}.glb', f'{stem}.fbx'], 'body_verts_covered': covered,
                                   'hidden_verts_while_under': under.get(key, {})}
        print(f'[fit] {key}: placed as generated, skinned{" rigid " + str(rigid_bones) if rigid_bones else ""}', flush=True)
    # Skin under the clothes is hidden on the BODY (Mask modifier on the Genies body; garments untouched).
    # Only pieces that are actually visible in this outfit hide skin (a fully hidden inner tee must not, or the gap
    # it leaves would show through).
    hide_all = body.vertex_groups.new(name='hide_covered_by_outfit')
    for k, piece in manifest['pieces'].items():
        if not info[k][0].get('hidden_entirely_under'):
            hide_all.add(piece['body_verts_covered'], 1.0, 'REPLACE')
    mask = body.modifiers.new('hide_covered_skin', 'MASK')
    mask.vertex_group = hide_all.name
    mask.invert_vertex_group = True
    bpy.ops.wm.save_as_mainfile(filepath=str(out / f'{d.name}__{base}.blend'))
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print('[fit] DONE', out, flush=True)


if __name__ == '__main__':
    main()
