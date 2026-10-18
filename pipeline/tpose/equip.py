"""Equip ANY set of wardrobe pieces on a Genies base - shells + region masks. Pieces are NEVER deformed.

Every piece is shown exactly as generated (it only ever looks its best that way): the only changes allowed are rigid
placement (rotation, one uniform scale, translation), normal skinning, and hiding with masks.

Rules (the same for every combination; nothing is computed pair-by-pair):
  1. CAGE: the base body (welded, ~5k points) is the shared cage. For each piece, rays straight out from every cage
     point give its inner/outer surface height above the skin there; the cage points a piece covers (shrunk back
     ERODE rings from its edges) are its coverage.
  2. SHELL PRIORITY: every slot has a layer (slots.json). A garment mostly (OCCLUDED) under higher layers is hidden
     ENTIRELY (a tee under a hoodie never peeks out); otherwise it is shown whole - garments are never partially
     masked, because AI meshes are long sliver triangles and any mask edge is a visible sawtooth.
  3. SKIN (the Genies body has clean quads): hidden only where it is covered or pokes through a garment AND hiding
     it cannot open a hole from any angle (safe_hide / metrics.hideable).
  4. OVER-ITEMS (bags, belts, hats): never hidden, never bent; one rigid seat (uniform scale + rotation + move,
     within SEAT_MAX_*). An over-item that has to wrap a specific garment closely (a crossbody strap over a puffy
     hoodie) is not a separate piece: it is generated TOGETHER with that garment as one BUNDLE piece
     (s2_over.py --bundle-with), equipped and removed as one model, so the strap is built onto that exact surface.
  Remaining problems are reported by the inspection step (inspect_look.py) and fixed by refitting (rigid) or
  regenerating the piece.

Run: blender -b --factory-startup -P pipeline/tpose/equip.py -- --base Xander --name my-look
         --pieces hoodie-boy:black_graphic_hoodie hoodie-boy:olive_cargo_joggers ...
Writes Outfits/_looks/<name>/06_fitted/<name>__<base>.blend + manifest.json
"""
import bpy, sys, json, argparse
from pathlib import Path
import numpy as np
from mathutils import Vector, Matrix
from mathutils.kdtree import KDTree

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'pipeline'))
sys.path.insert(0, str(ROOT / 'pipeline' / 'tpose'))
import fit_outfit as F  # noqa: E402
import metrics as M  # noqa: E402

SLOTS = json.loads((ROOT / 'pipeline' / 'slots.json').read_text(encoding='utf-8'))['slots']
NEVER_HIDE = {'accessory'}            # over-items: never hidden, never hide anything
SOLID_THICKNESS = 0.006               # AI meshes are closed solids: assumed cloth thickness under their outer surface
SEAT_MAX_SCALE = 1.12                 # over-items: largest uniform scale of the rigid seat
SEAT_MAX_MOVE = 0.03                  # ...and largest move per axis (m)
SEAT_MAX_ROT = 15.0                   # ...and largest rotation per axis (deg)
SEAT_REGEN_SHARE = 0.3                # more than this share of an over-item still inside worn pieces -> regenerate
                                      # (shallow contact is resolved by hiding the garment surface under it)
OVER_GAP = 0.004                      # over-items want this clearance above what is worn beneath them
MAX_SHAPE_CHANGE = 0.001              # a visible piece may differ from its generated shape by this much (m), rigid aside
ERODE = 2                             # coverage is shrunk this many cage rings from its edge before it hides anything
SKIN_HIDE = 0.003                     # skin is hidden wherever a garment surface is at/under it (+3 mm)
OCCLUDED = 0.7                        # a piece with this share of its footprint under higher layers is hidden entirely


def ctx(o):
    return bpy.context.temp_override(object=o, active_object=o, selected_objects=[o], selected_editable_objects=[o])


def cage_template(base, body, cache=True):
    path = ROOT / 'Bases' / f'{base}_cage.npz'
    if cache and path.exists():
        d = np.load(path)
        return d['co'], d['n'], d['edges']
    # The Genies body is already low-poly (~5k verts) with clean normals: it IS the cage (welded by position).
    ev = body.evaluated_get(bpy.context.evaluated_depsgraph_get())
    me = ev.to_mesh()
    M, R = body.matrix_world, body.matrix_world.to_3x3()
    raw = np.array([(M @ v.co)[:] for v in me.vertices])
    rawn = np.array([(R @ v.normal).normalized()[:] for v in me.vertices])
    e_raw = np.array([e.vertices[:] for e in me.edges], int)
    ev.to_mesh_clear()
    co, wid = np.unique(np.round(raw, 5), axis=0, return_inverse=True)
    wid = wid.ravel()
    n = np.zeros_like(co)
    np.add.at(n, wid, rawn)
    n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-9)
    edges = np.sort(wid[e_raw], 1)
    edges = np.unique(edges[edges[:, 0] != edges[:, 1]], axis=0)
    if cache:
        np.savez(path, co=co, n=n, edges=edges)
    print(f'[equip] cage for {base}{"" if cache else " (look pose)"}: {len(co)} points', flush=True)
    return co, n, edges


def piece_weights(obj, arm):
    """Skin weights of an imported piece (vertex groups named after bones), normalised."""
    names = [g.name for g in obj.vertex_groups if g.name in arm.data.bones]
    idx = {obj.vertex_groups[n].index: i for i, n in enumerate(names)}
    W = np.zeros((len(obj.data.vertices), len(names)))
    for v in obj.data.vertices:
        for ge in v.groups:
            if ge.group in idx:
                W[v.index, idx[ge.group]] = ge.weight
    s = W.sum(1, keepdims=True)
    return names, W / np.where(s > 0, s, 1)


def blend_mats(W, mats):
    """Per-vertex skinning matrix; vertices without weights stay where they are (identity)."""
    Mv = np.einsum('vb,bij->vij', W, mats) if W.shape[1] else np.zeros((len(W), 4, 4))
    return Mv + (1 - W.sum(1))[:, None, None] * np.eye(4)


def lbs(co, W, mats):
    """Linear blend skinning of rest-space points with per-bone 4x4 matrices."""
    return np.einsum('vij,vj->vi', blend_mats(W, mats), np.c_[co, np.ones(len(co))])[:, :3]


def pose_mats(arm, names, pose):
    """Skinning matrices of `names` with the rig in `pose` ({bone: matrix_basis}); the rig is left in that pose."""
    for pb in arm.pose.bones:
        pb.matrix_basis = Matrix(pose[pb.name]) if pb.name in pose else Matrix.Identity(4)
    bpy.context.view_layer.update()
    return np.array(F.skin_matrices(arm, names)).reshape(-1, 4, 4)


def look_pose(loaded):
    """The avatar pose of this look: each limb takes the fit pose of the outermost piece fitted along it (the sleeve
    you see decides where the arm goes), so every visible garment is shown exactly as generated."""
    pose = {}
    for limb, chain in M.LIMB_CHAINS.items():
        bones = [b for b, _ in chain] + ([chain[-1][1]] if limb.startswith('leg') else [])  # + the (levelled) foot
        best = None
        for k, info, _ in loaded:
            fp = info.get('fit', {}).get('fit_pose') or {}
            if any(b in fp for b in bones) and (best is None or SLOTS[info['slot']]['layer'] > best[0]):
                best = (SLOTS[info['slot']]['layer'], k, fp)
        if best:
            for b in bones:
                if b in best[2]:
                    pose[b] = best[2][b]
            print(f'[equip] {limb}: avatar posed to fit {best[1]}', flush=True)
    return pose


def load_piece(spec):
    outfit, key = spec.split(':')
    man = json.loads((ROOT / 'Outfits' / outfit / '06_fitted' / 'manifest.json').read_text())
    info = man['pieces'][key]
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(ROOT / 'Outfits' / outfit / '06_fitted' / info['files'][0]))
    new = [o for o in bpy.data.objects if o not in before]
    # only the garment itself (the glTF export also carries the rig's bone display shapes, e.g. an Icosphere)
    meshes = [o for o in new if o.type == 'MESH' and o.name.endswith(key)]
    for m in meshes:
        for mod in list(m.modifiers):
            m.modifiers.remove(mod)
        mw = m.matrix_world.copy()
        m.parent = None
        m.data.transform(mw)
        m.matrix_world = Matrix.Identity(4)
    for o in new:
        if o.type != 'MESH':
            bpy.data.objects.remove(o, do_unlink=True)
    if len(meshes) > 1:
        with bpy.context.temp_override(active_object=meshes[0], selected_editable_objects=meshes):
            bpy.ops.object.join()
    obj = meshes[0]
    obj.name = obj.data.name = key
    return key, info, obj


def free_space(co, n, body):
    """How far each cage point can look outward before its ray re-enters the body (e.g. an armpit ray hitting the
    arm, or a point whose normal points inward). Garment hits beyond this belong to another body part."""
    bco, bpolys = F.world_verts(body, evaluated=True)
    bvh = F.bvh_of(bco, bpolys)
    out = np.full(len(co), np.inf)
    for i, (p, nn) in enumerate(zip(co, n)):
        h = bvh.ray_cast(Vector(p) + Vector(nn) * 0.002, Vector(nn), 0.5)
        if h[0] is not None:
            out[i] = h[3] + 0.002
    return out


def heights(obj, co, n, back=0.03, reach=0.10, limit=None):
    """Inner (a) and outer (b) surface height of a piece above each cage point; NaN where it does not cover.
    a = where the ray first enters the piece, b = where it first leaves it again (the local cloth thickness) -
    later hits belong to other parts of the same piece (far side of a sleeve, the hood) and are ignored."""
    gco, gp = F.world_verts(obj)
    bvh = F.bvh_of(gco, gp)
    a = np.full(len(co), np.nan)
    b = np.full(len(co), np.nan)
    for i, (p, nn) in enumerate(zip(co, n)):
        nv = Vector(nn)
        o = Vector(p) - nv * back
        travelled, hits = 0.0, []
        while travelled < reach + back and len(hits) < 2:
            h = bvh.ray_cast(o, nv, reach + back - travelled)
            if h[0] is None:
                break
            travelled += h[3]
            hits.append((travelled - back, h[1].dot(nv) < 0))  # (height, entering the piece?)
            o = h[0] + nv * 1e-4
            travelled += 1e-4
        if limit is not None:
            hits = [h for h in hits if h[0] < limit[i]]
        if not hits:
            continue
        (t0, enter0) = hits[0]
        if enter0:            # inner surface, then the outer surface where the ray leaves again
            a[i] = t0
            b[i] = hits[1][0] if len(hits) > 1 and not hits[1][1] and hits[1][0] - t0 < 0.04 else t0 + 0.002
        else:                 # started inside a solid piece: this hit is its outer surface
            b[i] = t0
            a[i] = t0 - SOLID_THICKNESS
    return a, b


def covered_from_all_sides(co, n, objs, half_angle=50, rays=8, reach=0.25):
    bvhs = [F.bvh_of(*F.world_verts(o)) for o in objs]
    if not bvhs:
        return np.zeros(len(co), bool)
    out = np.ones(len(co), bool)
    ca, sa = np.cos(np.radians(half_angle)), np.sin(np.radians(half_angle))
    for i, (p, nn) in enumerate(zip(co, n)):
        nv = Vector(nn)
        u = nv.orthogonal().normalized()
        w = nv.cross(u)
        o = Vector(p) + nv * 0.001
        dirs = [nv] + [(nv * ca + (u * np.cos(t) + w * np.sin(t)) * sa).normalized()
                       for t in np.linspace(0, 2 * np.pi, rays, endpoint=False)]
        for d in dirs:
            if not any(b.ray_cast(o, d, reach)[0] is not None for b in bvhs):
                out[i] = False
                break
    return out


def erode(mask, edges, rings):
    m = mask.astype(float)
    a, b = edges[:, 0], edges[:, 1]
    for _ in range(rings):
        k = m.copy()
        np.minimum.at(k, a, m[b])
        np.minimum.at(k, b, m[a])
        m = k
    return m > 0.5


def nearest_cage(co_cage, pts):
    kd = KDTree(len(co_cage))
    for i, p in enumerate(co_cage):
        kd.insert(Vector(p), i)
    kd.balance()
    return np.array([kd.find(Vector(p))[1] for p in pts])


def safe_hide(target, cand, others, reveal, body, corners=False):
    """Masks remove whole FACES (any face touching a hidden vertex), and Genies body faces are ~2 cm - hiding the
    vertices under a shoe collar removes skin above it too and opens a slit. So a candidate vertex is hidden only if
    every face around it may be hidden (metrics.hideable: wherever that face can be seen, what shows instead is a
    `reveal` garment's front face right behind it, or one buried in the body). Works for the skin and for a lower
    garment poking out of a higher one. Returns the vertices that are safe to hide (a subset of cand)."""
    def wv(o):
        return F.world_verts(o, evaluated=(o is body))
    co_t, polys = wv(target)
    R3 = target.matrix_world.to_3x3()
    allco, allp, off = [co_t], list(polys), len(co_t)
    for o in others:
        c, pl = wv(o)
        allco.append(c); allp += [tuple(i + off for i in q) for q in pl]; off += len(c)
    nude = F.bvh_of(np.concatenate(allco), allp)
    gco, gp, goff = [], [], 0
    for o in reveal:
        c, pl = wv(o)
        gco.append(c); gp += [tuple(i + goff for i in q) for q in pl]; goff += len(c)
    gbvh = F.bvh_of(np.concatenate(gco), gp)
    bco, bpolys = F.world_verts(body, evaluated=True)
    cand_faces = [f for f in target.data.polygons if cand[list(f.vertices)].any()]
    samples, normals, owner = [], [], []
    for f in cand_faces:
        vi = list(f.vertices)
        c = co_t[vi].mean(0)
        nn = np.array((R3 @ f.normal).normalized()[:])
        # corners: right out to each corner and along each edge (95% of the way), not just the middle - a ~2 cm face
        # whose tip sticks out past a hem (only its last few mm) would otherwise be hidden and leave a notch
        edge_pts = [c + 0.95 * ((co_t[vi[j]] + co_t[vi[(j + 1) % len(vi)]]) / 2 - c) for j in range(len(vi))]
        for q in [c] + ([c + 0.95 * (co_t[v] - c) for v in vi] + edge_pts if corners else []):
            samples.append(q); normals.append(nn); owner.append(f.index)
    ok = M.hideable(np.array(samples).reshape(-1, 3), np.array(normals).reshape(-1, 3), nude, gbvh,
                    body_bvh=F.bvh_of(bco, bpolys), own=(0, len(polys)))
    face_ok = np.zeros(len(target.data.polygons), bool)
    face_ok[[f.index for f in cand_faces]] = True
    for o_, k in zip(owner, ok):
        if not k:
            face_ok[o_] = False
    vert_ok = np.ones(len(co_t), bool)
    for f in target.data.polygons:
        if not face_ok[f.index]:
            vert_ok[list(f.vertices)] = False
    hide = cand & vert_ok
    print(f'[equip] {target.name}: {int(cand.sum())} candidate verts, {int(hide.sum())} safe to hide '
          f'({int((~ok).sum())} of {len(ok)} face samples would show a hole)', flush=True)
    return hide


def repair_holes(worn, body, rounds=4):
    """Final guarantee, with the inspection's own test (metrics.overreach on the masked look): any masked face that a
    camera can see and whose removal shows a hole is un-hidden, until none is left. Masks only ever shrink here."""
    def masks(o, on):
        for m in o.modifiers:
            if m.type == 'MASK':
                m.show_viewport = on
    for r in range(rounds):
        for o in worn:
            masks(o, False)
        bpy.context.view_layer.update()
        allco, allp, rng, off = [], [], {}, 0
        for o in worn:
            c, pl = F.world_verts(o, evaluated=True)
            rng[o] = (len(allp), len(allp) + len(pl))
            allco.append(c); allp += [tuple(i + off for i in q) for q in pl]; off += len(c)
        nude = F.bvh_of(np.concatenate(allco), allp)
        whole = {o: F.world_verts(o, evaluated=True)[0] for o in worn}
        bco, bpolys = F.world_verts(body, evaluated=True)
        body_bvh = F.bvh_of(bco, bpolys)
        for o in worn:
            masks(o, True)
        bpy.context.view_layer.update()
        allco, allp, off = [], [], 0
        for o in worn:
            c, pl = F.world_verts(o, evaluated=True)
            allco.append(c); allp += [tuple(i + off for i in q) for q in pl]; off += len(c)
        shown = F.bvh_of(np.concatenate(allco), allp)
        fixed = 0
        for o in worn:
            g = next((o.vertex_groups.get(n) for n in ('hidden_in_this_look', 'hide_covered_by_look')
                      if o.vertex_groups.get(n)), None)
            if g is None:
                continue
            hid = np.zeros(len(o.data.vertices), bool)
            for v in o.data.vertices:
                if any(e.group == g.index for e in v.groups):
                    hid[v.index] = True
            if not hid.any() or hid.all():
                continue
            co = whole[o]
            R3 = o.matrix_world.to_3x3()
            samples, normals, owner = [], [], []
            for f in o.data.polygons:
                vi = list(f.vertices)
                if not hid[vi].any():
                    continue
                c = co[vi].mean(0)
                nn = np.array((R3 @ f.normal).normalized()[:])
                for q in [c] + ([c + 0.7 * (co[v] - c) for v in vi] if o is body else []):
                    samples.append(q); normals.append(nn); owner.append(vi)
            if not samples:
                continue
            found = M.overreach(np.array(samples), np.array(normals), nude, shown, body_bvh=body_bvh, own=rng[o])
            bad = set()
            for p_, _ in found:
                k = int(np.argmin(np.linalg.norm(np.array(samples) - p_, axis=1)))
                bad.update(owner[k])
            if bad:
                g.remove(sorted(bad))
                fixed += len(bad)
                print(f'[equip] repair: {o.name}: un-hid {len(bad)} verts that opened a hole', flush=True)
        if not fixed:
            break


def rigid_seat(obj, under, arm, samples=3000, only=None):
    """One rigid placement for an over-item (bag, strap, belt) so it sits on what is worn beneath it: uniform scale
    about the torso axis (a strap loop grows around a bulkier layer) + rotation + translation, found by pattern search that
    minimises how deep its points sit inside the worn pieces (signed distance, OVER_GAP clearance wanted) with a
    small preference for staying where it was placed. The mesh shape is untouched."""
    if not under:
        return {'scale': 1.0, 'move_cm': [0, 0, 0], 'inside_before': 0, 'inside_after': 0, 'samples': 0,
                'needs_regen': False}
    me = obj.data
    co = np.array([v.co[:] for v in me.vertices])
    pool = co if only is None or not only.any() else co[only]
    pts = pool[np.linspace(0, len(pool) - 1, min(samples, len(pool))).astype(int)]
    bvhs = [F.bvh_of(*F.world_verts(o)) for o in under]
    spine = np.array(M.joint(arm, 'Spine1'))
    pivot = np.array([spine[0], spine[1], pts[:, 2].mean()])

    def sdist(q):
        out = np.full(len(q), np.inf)
        for b in bvhs:
            for i, p in enumerate(q):
                loc, nrm, _, dist = b.find_nearest(Vector(p), 0.1)
                if loc is None:
                    continue
                sd = dist if (Vector(p) - loc).dot(nrm) >= 0 else -dist
                out[i] = min(out[i], sd)
        return out

    def rot(x):
        return np.array(Matrix.Rotation(np.radians(x[6]), 3, 'Z') @ Matrix.Rotation(np.radians(x[5]), 3, 'Y')
                        @ Matrix.Rotation(np.radians(x[4]), 3, 'X'))

    def place(x):  # x = scale, move xyz (m), rotation xyz (deg) - all about the torso pivot
        return pivot + x[0] * (pts - pivot) @ rot(x).T + x[1:4]

    def cost(x):
        d = sdist(place(x))
        pen = np.clip(OVER_GAP - d, 0, None)
        return float(pen.sum() / len(d) + 0.002 * (x[0] - 1) + 0.01 * np.linalg.norm(x[1:4])
                     + 0.0001 * np.linalg.norm(x[4:])), int((d < 0).sum())

    lo = np.array([1.0] + [-SEAT_MAX_MOVE] * 3 + [-SEAT_MAX_ROT] * 3)
    hi = np.array([SEAT_MAX_SCALE] + [SEAT_MAX_MOVE] * 3 + [SEAT_MAX_ROT] * 3)
    x0 = np.zeros(7)
    x0[0] = 1.0
    best0, inside0 = cost(x0)
    # a few rotation starts (pattern search is local), then refine all 7 parameters
    starts = [x0] + [np.r_[1.0, 0, 0, 0, rx, ry, rz] for rx in (-8, 8) for ry in (-8, 8) for rz in (-8, 0, 8)]
    best, x = None, None
    for st in starts:
        c, _ = cost(st)
        if best is None or c < best:
            best, x = c, st.copy()
    steps = np.array([0.02, 0.01, 0.01, 0.01, 4.0, 4.0, 4.0])
    while (steps / np.array([0.02, 0.01, 0.01, 0.01, 4, 4, 4])).max() > 0.12:
        improved = False
        for j in range(7):
            for sgn in (1, -1):
                y = x.copy()
                y[j] = np.clip(y[j] + sgn * steps[j], lo[j], hi[j])
                c, _ = cost(y)
                if c < best - 1e-7:
                    x, best, improved = y, c, True
        if not improved:
            steps /= 2
    d1 = sdist(place(x))
    inside1 = int((d1 < 0).sum())
    deep1 = int((d1 < -0.003).sum())
    Rm = Matrix(rot(x).tolist()).to_4x4()
    Mx = Matrix.Translation(Vector(pivot + x[1:4])) @ Rm @ Matrix.Scale(x[0], 4) @ Matrix.Translation(Vector(-pivot))
    me.transform(Mx)
    me.update()
    return {'scale': round(float(x[0]), 3), 'move_cm': [round(float(v) * 100, 1) for v in x[1:4]],
            'rotate_deg': [round(float(v), 1) for v in x[4:]],
            'inside_before': inside0, 'inside_after': inside1, 'deeper_than_3mm_after': deep1, 'samples': len(pts),
            'needs_regen': inside1 > SEAT_REGEN_SHARE * len(pts)}


def mask_vertices(obj, idx, group, modifier):
    g = obj.vertex_groups.get(group) or obj.vertex_groups.new(name=group)
    if len(idx):
        g.add([int(i) for i in idx], 1.0, 'REPLACE')
    m = obj.modifiers.new(modifier, 'MASK')
    m.vertex_group, m.invert_vertex_group = g.name, True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--base', required=True)
    ap.add_argument('--name', required=True)
    ap.add_argument('--pieces', nargs='+', required=True)
    a = ap.parse_args(sys.argv[sys.argv.index('--') + 1:])
    out = ROOT / 'Outfits' / '_looks' / a.name / '06_fitted'
    out.mkdir(parents=True, exist_ok=True)

    arm, body, base_meshes = F.load_base(a.base)
    for pb in arm.pose.bones:
        pb.matrix_basis = Matrix.Identity(4)
    bpy.context.view_layer.update()

    loaded = [load_piece(s) for s in a.pieces]
    for k, info, _ in loaded:  # a piece fitted along its limbs must carry the pose it is shown undeformed in
        fit = info.get('fit', {})
        if fit.get('rig_fit') and not fit.get('fit_pose'):
            raise RuntimeError(f'{k}: fitted with rig_fit but no fit_pose stored (stale step 6) - rerun s6_fit.py')
        # the stored rest copy is only the generated mesh if it was skinned in the pose it is shown in
        if 'rest_copy_max_mm' not in fit and not info.get('rigid'):
            raise RuntimeError(f'{k}: step 6 predates the rest-copy record - rerun s6_fit.py')
        if fit.get('rest_copy_max_mm', 0) > MAX_SHAPE_CHANGE * 1000 and not fit.get('fit_pose'):
            raise RuntimeError(f'{k}: its stored copy is {fit["rest_copy_max_mm"]} mm off the generated mesh but no '
                               f'fit_pose was stored to show it in - rerun s6_fit.py')
    # Pieces arrive in rest (T-pose) space. Pose the avatar for this look and bring every piece into it by normal
    # skinning: a piece whose fit pose this is comes out EXACTLY as generated.
    P = look_pose(loaded)
    skin = {}
    for k, info, o in loaded:
        names_k, W_k = piece_weights(o, arm)
        rest = np.array([v.co[:] for v in o.data.vertices])
        own = lbs(rest, W_k, pose_mats(arm, names_k, (info.get('fit', {}).get('fit_pose') or {})))
        shown = lbs(rest, W_k, pose_mats(arm, names_k, P))
        for v, q in zip(o.data.vertices, shown):
            v.co = q
        o.data.update()
        skin[k] = (W_k, names_k, own)
    pose_mats(arm, [], P)  # leave the rig in the look pose
    co, n, edges = cage_template(a.base, body, cache=not P)
    limit = free_space(co, n, body)
    as_loaded = {k: skin[k][2] for k, _, _ in loaded}  # each piece as generated (in its own fit pose)
    loaded.sort(key=lambda t: SLOTS[t[1]['slot']]['layer'])
    layer = {k: SLOTS[i['slot']]['layer'] for k, i, _ in loaded}
    slot = {k: i['slot'] for k, i, _ in loaded}
    obj = {k: o for k, _, o in loaded}

    # 1. coverage of every piece on the cage (measured on the piece alone)
    A, B, cov, covE = {}, {}, {}, {}
    for k in obj:
        A[k], B[k] = heights(obj[k], co, n, limit=limit)
        cov[k] = ~np.isnan(A[k])
        covE[k] = erode(cov[k], edges, ERODE)

    # 2. shell priority: top garment layer per cage point (eroded coverage)
    garments = [k for k in obj if slot[k] not in NEVER_HIDE]
    top = np.full(len(co), -1)
    for k in garments:
        top = np.where(covE[k], np.maximum(top, layer[k]), top)
    report = {}
    vcage = {k: nearest_cage(co, F.world_verts(obj[k])[0]) for k in obj}
    # occlusion rule first: a piece mostly under higher layers is hidden ENTIRELY (no tee hem under a hoodie), and a
    # hidden piece takes no part in wrapping
    gone = {k for k in garments if cov[k].any() and (top[cov[k]] > layer[k]).mean() >= OCCLUDED}

    # 3. pieces stay EXACTLY as generated (no wrap, no bending). Over-items (bags, straps) get one rigid seat -
    # uniform scale about the torso + translation - so they clear what is worn beneath them; if no rigid seat
    # within limits does, the piece is reported as needing a regeneration for this layer.
    seats = {}
    for k in obj:
        if slot[k] in NEVER_HIDE:
            under = [obj[q] for q in garments if q not in gone and slot[q] not in ('hair', 'headwear')]
            seats[k] = rigid_seat(obj[k], under, arm)
            print(f'[equip] {k}: rigid seat scale {seats[k]["scale"]}, move cm {seats[k]["move_cm"]}, '
                  f'rotate deg {seats[k]["rotate_deg"]}, points inside worn pieces {seats[k]["inside_before"]} -> '
                  f'{seats[k]["inside_after"]} ({seats[k]["deeper_than_3mm_after"]} deeper than 3 mm) of '
                  f'{seats[k]["samples"]}' + ('  ** needs regeneration for this layer **'
                                              if seats[k]['needs_regen'] else ''), flush=True)
    over = [obj[k] for k in seats]
    for k in obj:
        seat = seats.get(k)
        # Garments are never PARTIALLY masked: AI meshes are made of long sliver triangles, so any mask edge is a
        # visible sawtooth (seen at a hoodie hem over joggers). A garment is shown whole, or hidden entirely when it is
        # mostly under higher layers (the occlusion rule below). Only the body skin is masked partially.
        hide = np.zeros(len(vcage[k]), bool)
        report[k] = {'slot': slot[k], 'layer': layer[k], 'cage_points_covered': int(cov[k].sum()),
                     'mesh': 'as generated (rigid only)', 'hidden_share': round(float(hide.mean()), 3)}
        if seat:
            report[k]['rigid_seat'] = seat
        print(f'[equip] {k}: layer {layer[k]}, hidden {hide.mean():.0%}', flush=True)
        if k in gone:
            hide[:] = True
            report[k]['hidden_entirely'] = True
            print(f'[equip] {k}: {(top[cov[k]] > layer[k]).mean():.0%} under higher layers -> hidden entirely', flush=True)
        mask_vertices(obj[k], np.nonzero(hide)[0], 'hidden_in_this_look', 'hide_when_layered')
        obj[k].name = f'{a.name}__{slot[k]}__{k}'

    # guard: every piece must still be its loaded mesh up to ONE rigid similarity (no bending, ever)
    # (a piece hidden entirely may be skinned into the look pose - it is not seen)
    for k in obj:
        now = np.array([v.co[:] for v in obj[k].data.vertices])
        # rigid pieces made of separate parts (a PAIR of shoes, each on its own foot) are checked part by part
        W_k = skin[k][0]
        parts = [np.arange(len(now))]
        if SLOTS[slot[k]]['rigid'] and W_k.shape[1] > 1:
            dom = W_k.argmax(1)
            parts = [np.nonzero(dom == b)[0] for b in np.unique(dom) if (dom == b).sum() >= 50]
        resid = 0.0
        for idx_ in parts:
            ref = as_loaded[k][idx_]
            R, sc, t = F.umeyama(ref, now[idx_])
            resid = max(resid, float(np.linalg.norm(ref @ (sc * R).T + t - now[idx_], axis=1).max()))
        report[k]['shape_change_mm'] = round(resid * 1000, 3)
        print(f'[equip] {k}: shown shape vs generated: {resid * 1000:.2f} mm', flush=True)
        # body-made pieces (shell_garment / legging_shell: _hem_band / _shell) carry the body's own skin weights and
        # follow the skin through any pose by design - a posed arm bends a tee sleeve exactly like the arm's skin
        body_made = any(at.name.lower() in ('_hem_band', '_shell') for at in obj[k].data.attributes)
        if resid > MAX_SHAPE_CHANGE and k not in gone and not body_made:
            raise RuntimeError(f'{k}: shown {resid * 1000:.1f} mm away from its generated shape - pieces may not be '
                               f'deformed (its fit pose conflicts with the look pose: refit or regenerate)')

    # skin under any (non over-item) piece is hidden - body vertices map 1:1 onto the welded cage
    # skin is hidden exactly where it cannot be seen: every ray in a cone around the skin normal hits worn
    # clothing. Covers clipping linings, keeps every visible gap (ankles, cuff edges) open.
    worn = [obj[k] for k in garments if k not in gone]
    body_cover = covered_from_all_sides(co, n, worn)
    # ...and where a worn garment's surface lies just under the skin (skin poking through): hiding it shows the
    # garment surface right there
    for o in worn:
        body_cover[M.skin_poke(co, n, F.bvh_of(*F.world_verts(o)), tol=1e-4)] = True  # mask even contact
    bco, _ = F.world_verts(body, evaluated=True)
    bc = nearest_cage(co, bco)
    hide_body = safe_hide(body, body_cover[bc], worn, worn, body, corners=True)
    mask_vertices(body, np.nonzero(hide_body)[0], 'hide_covered_by_look', 'hide_covered_skin')
    repair_holes([body] + [obj[k] for k in obj if k not in gone], body)

    # store pieces in rest space and attach: with the rig left in the look pose they display exactly as computed
    for k in obj:
        W_k, names_k = skin[k][0], skin[k][1]
        now = np.array([v.co[:] for v in obj[k].data.vertices])
        Mv = blend_mats(W_k, pose_mats(arm, names_k, P))
        rest = np.einsum('vij,vj->vi', np.linalg.inv(Mv), np.c_[now, np.ones(len(now))])[:, :3]
        for v, q in zip(obj[k].data.vertices, rest):
            v.co = q
        obj[k].data.update()
        F.attach(obj[k], arm)
    pose_mats(arm, [], P)

    bpy.ops.wm.save_as_mainfile(filepath=str(out / f'{a.name}__{a.base}.blend'))
    (out / 'manifest.json').write_text(json.dumps({'look': a.name, 'base': a.base, 'pieces': a.pieces,
                                                   'look_pose': {b: [list(r) for r in m] for b, m in P.items()},
                                                   'rules': {'meshes': 'as generated, rigid placement only',
                                                             'seat_max_scale': SEAT_MAX_SCALE, 'seat_max_move_m': SEAT_MAX_MOVE,
                                                             'erode_rings': ERODE},
                                                   'report': report}, indent=2), encoding='utf-8')
    print('[equip] DONE', out, flush=True)


if __name__ == '__main__':
    main()
