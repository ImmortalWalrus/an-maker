"""Shared fit measurements (run inside Blender). Used by step 6 to fit, by equip to clear layers, and by the
inspection step to pass/fail a look - one set of maths everywhere.

  tube_profile    - along a bone segment: where the garment closes a ring around it, and how far the bone axis is
                    from the ring's centre at each slice (the cuff/ankle opening is the last closed slice)
  inside_solid    - is a point inside a closed mesh (AI meshes are closed solids): majority of 3 ray-parity tests
  enclosed        - is a skin point covered by a tube garment (ring of rays all hit it; works solid or hollow)
  limb_poke       - skin of a limb, within a garment tube's length, that is not enclosed by it = poke-through
  piece_poke      - vertices of a piece that are inside another (lower) piece = clipping between layers
"""
import math
import numpy as np
from mathutils import Vector

LIMB_CHAINS = {  # limb: [(bone, child joint bone)] from the body outward
    'arm_L': [('LeftArm', 'LeftForeArm'), ('LeftForeArm', 'LeftHand')],
    'arm_R': [('RightArm', 'RightForeArm'), ('RightForeArm', 'RightHand')],
    'leg_L': [('LeftUpLeg', 'LeftLeg'), ('LeftLeg', 'LeftFoot')],
    'leg_R': [('RightUpLeg', 'RightLeg'), ('RightLeg', 'RightFoot')],
}
SLOT_LIMBS = {'top': ['arm_L', 'arm_R'], 'outerwear': ['arm_L', 'arm_R'], 'fullbody': list(LIMB_CHAINS),
              'bottom': ['leg_L', 'leg_R']}
DIRS = 12


def joint(arm, bone):
    return arm.matrix_world @ arm.pose.bones[bone].head


def ring(bvh, o, axis, reach=0.3, dirs=DIRS):
    """Cast a ring of rays around the axis at point o. Returns (closed fraction, centre offset vector)."""
    u = axis.orthogonal().normalized()
    v = axis.cross(u)
    acc, hits = Vector((0, 0, 0)), 0
    for k in range(dirs):
        th = 2 * math.pi * k / dirs
        d = u * math.cos(th) + v * math.sin(th)
        h = bvh.ray_cast(o, d, reach)
        if h[0] is not None:
            acc += d * h[3]
            hits += 1
    return hits / dirs, (acc / hits if hits else Vector((0, 0, 0)))


def tube_profile(bvh, a, b, ts):
    """[(t, closed_fraction, offset_m)] along segment a->b."""
    a, b = Vector(a), Vector(b)
    axis = (b - a).normalized()
    out = []
    for t in ts:
        c, off = ring(bvh, a.lerp(b, float(t)), axis)
        out.append((float(t), c, off.length))
    return out


def segment_score(bvh, a, b, ts):
    """Mean centre offset over the closed slices of a segment, the offset at its far end, and how many closed."""
    prof = tube_profile(bvh, a, b, ts)
    closed = [(t, o) for t, c, o in prof if c >= 0.75]
    if not closed:
        return None
    return {'mean_offset': float(np.mean([o for _, o in closed])), 'end_offset': closed[-1][1],
            'end_t': closed[-1][0], 'closed': len(closed), 'slices': len(prof)}


def inside_solid(bvh, p):
    votes = 0
    for d in (Vector((0, 0, 1)), Vector((0.577, 0.577, 0.577)), Vector((-0.6, 0.0, -0.8))):
        n, o = 0, Vector(p)
        for _ in range(40):
            h = bvh.ray_cast(o, d, 10.0)
            if h[0] is None:
                break
            n += 1
            o = h[0] + d * 1e-5
        votes += n % 2
    return votes >= 2


CHAIN_BONES = [b for chain in LIMB_CHAINS.values() for b, _ in chain]
END_BONES = ['LeftHand', 'RightHand', 'LeftFoot', 'RightFoot']  # hands/feet: where cuffs and ankle openings end


def chain_bone_of(names, W):
    """Per body vertex: which limb-chain bone it belongs to. Genies skin is weighted to helper bones
    (LeftArmTwist1Bind, LeftForeArmTwist2Bind...), so map each weight bone to the chain bone it starts with."""
    canon = []
    for n in names:
        match = [b for b in CHAIN_BONES + END_BONES if n.startswith(b)]
        canon.append(max(match, key=len) if match else '')
    canon = np.array(canon)
    return canon[W.argmax(1)]


def enclosed(bvh, p, axis, need=0.9, reach=0.25):
    """Is skin point p covered by a tube garment? A ring of rays around the limb axis from p must (nearly) all hit
    the garment. True inside a solid sleeve AND inside a hollow one; False when the skin pokes through a wall."""
    c, _ = ring(bvh, Vector(p), Vector(axis).normalized(), reach=reach)
    return c >= need


HEM_MARGIN = 0.015


def limb_poke(arm, body_co, body_bone, garment_bvh, limb, step=1, all_bone=None, where=False):
    """Skin points of a limb that lie within the garment tube's length but OUTSIDE the garment (poke-through).
    The tube's length is found with rings cast from the skin's own centre (all_bone: chain bone of EVERY body
    vertex, used for the centres; body_bone may be restricted to visible skin)."""
    pokes, checked, at = 0, 0, []
    all_bone = body_bone if all_bone is None else all_bone
    for bone, child in LIMB_CHAINS[limb]:
        a, b = np.array(joint(arm, bone)), np.array(joint(arm, child))
        prof = skin_tube_profile(garment_bvh, body_co[all_bone == bone], a, b, np.linspace(0.0, 1.0, 21))
        closed_t = [t for t, c, _, _ in prof if c >= 0.75]
        if not closed_t:
            continue
        t0, t1 = min(closed_t), max(closed_t)
        ab = b - a
        # the rings are 1/20 of the bone apart, so a hem (often slanted or gathered) ends somewhere within one
        # step of the last closed ring: skin within HEM_MARGIN of the tube's ends is the opening, not a poke
        m = HEM_MARGIN / float(np.linalg.norm(ab))
        t0, t1 = t0 + m, t1 - m
        pts = body_co[body_bone == bone][::step]
        tt = (pts - a) @ ab / (ab @ ab)
        axis = Vector(ab).normalized()
        for p in pts[(tt >= t0) & (tt <= t1)]:
            checked += 1
            near = garment_bvh.find_nearest(Vector(p))
            if near[0] is not None and near[3] < POKE_TOL:
                continue  # resting on the garment's surface (within 1 mm): contact, not a visible poke
            if not enclosed(garment_bvh, p, axis):
                pokes += 1
                at.append(p)
    return (pokes, checked, at) if where else (pokes, checked)


POKE_TOL = 0.001   # contact shallower than 1 mm (a seam crease resting on the skin) cannot be seen at any distance


def skin_poke(body_co, body_n, garment_bvh, depth=0.015, tol=POKE_TOL):
    """Body vertices that poke through a garment (any region): looking a little way INTO the body from the skin,
    the garment's outer surface is found there - more than `tol` under the skin."""
    out = []
    for i, (p, n) in enumerate(zip(body_co, body_n)):
        nv = Vector(n)
        h = garment_bvh.ray_cast(Vector(p) - nv * tol, -nv, depth)
        # a garment's outer surface just under the skin, and the skin point is not inside the garment's volume
        # (for solid AI garments the body sits inside the solid - that is covered, not poking)
        if h[0] is not None and h[1].dot(nv) > 0 and not inside_solid(garment_bvh, p):
            out.append(i)
    return out


def piece_poke(piece_co, other_bvh, step=1):
    idx = [i for i in range(0, len(piece_co), step) if inside_solid(other_bvh, piece_co[i])]
    return idx


# ---------------------------------------------------------------- openings measured against the SKIN, not the bone
# The Genies bones are not in the middle of the limb (the wrist bone sits high in the wrist), so a sleeve centred on
# the bone can still have the hand resting on its rim. Every ring is cast from the skin's own centre at that slice.

def limb_skin(body_co, body_bone, bone, child):
    """Skin points of a limb segment; the last segment also takes the hand/foot, so an opening past the wrist/ankle
    is measured too."""
    sel = body_bone == bone
    if child in END_BONES:
        sel |= body_bone == child
    return body_co[sel]


def skin_centre(pts, a, b, t, slab=0.015):
    a, b = np.asarray(a, float), np.asarray(b, float)
    ab = b - a
    L = float(np.linalg.norm(ab))
    u = ab / L
    tt = (pts - a) @ u
    sel = np.abs(tt - t * L) < slab
    if sel.sum() < 6:  # low-poly limbs: vertex rings ~3 cm apart - take the nearest rings either side
        sel = np.abs(tt - t * L) < 2 * slab
        if sel.sum() < 6:
            return None
    c = pts[sel].mean(0)
    return c - u * ((c - a) @ u - t * L)


def thread_check(gbvh, gco, skin, a, b, reach=0.15, lateral=0.10, band=0.02, margin=0.001):
    """Does the limb come out of the garment THROUGH ITS OPENING? Judged from the garment itself, never from where
    the limb happens to be (a limb that exits through a wall must not make the cuff look "past the hem").
      opening   the garment's farthest extent along the limb (garment points within `lateral` of the limb line,
                bone start .. child + reach); the cuff ring = the garment's outline in the last `band` before it
      threaded  at the cuff, the limb's outline lies inside the ring (its far side + `margin` within the ring's edge)
      wall exit the limb's centre line leaves the garment (a ring of rays from it no longer all hits) before the cuff
    Returns None when the garment's tube does not end along this segment (it ends on the next one, or not at all)."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    L = float(np.linalg.norm(b - a))
    ax = (b - a) / L
    n, u, v = plane_basis(ax)
    def split(pts):
        s = (pts - a) @ ax
        lat = pts - a - np.outer(s, ax)
        return s, np.stack([lat @ u, lat @ v], -1)
    gs, g2 = split(gco)
    near = (gs > 0.05 * L) & (gs < L + reach) & (np.linalg.norm(g2, axis=1) < lateral)
    if near.sum() < 30:
        return None
    s_end = float(gs[near].max())
    if s_end < 0.35 * L or s_end > L + reach - 0.01:
        return None  # the tube ends on another segment (or runs on past the hand/foot)
    ring_pts = g2[near & (gs > s_end - band)]
    ks, k2 = split(skin)
    # the body's vertex rings are a few cm apart: take the skin ring nearest the opening (within 5 cm of it)
    cand = np.nonzero((ks > s_end - 0.05) & (ks < s_end + 0.02))[0]
    if len(ring_pts) < 8 or not len(cand):
        return None
    s_ring = ks[cand[np.argmin(np.abs(ks[cand] - (s_end - band / 2)))]]
    lim = k2[np.abs(ks - s_ring) < 0.006]
    if len(lim) < 4:
        return None
    rc = ring_pts.mean(0)
    rr = float(np.percentile(np.linalg.norm(ring_pts - rc, axis=1), 90))
    lc = lim.mean(0)
    lr = float(np.percentile(np.linalg.norm(lim - lc, axis=1), 90))
    off = float(np.linalg.norm(lc - rc))
    threaded = off + lr + margin <= rr
    # the limb's centre line inside the garment from where the tube starts on this segment to the cuff
    wall = None
    axv = Vector(ax)
    for sv in np.arange(max(0.1 * L, float(gs[near].min()) + 0.02), s_end - band, 0.01):
        sl = (ks > sv - 0.012) & (ks < sv + 0.012)
        if sl.sum() < 4:
            continue
        c = skin[sl].mean(0)
        frac, _ = ring(gbvh, Vector(c), axv, reach=0.25)
        if frac < 0.75:
            wall = round(float(s_end - sv), 3)  # metres before the opening
            break
    return {'end_t': round(s_end / L, 3), 'ring_r_cm': round(rr * 100, 1), 'limb_r_cm': round(lr * 100, 1),
            'offset_cm': round(off * 100, 1), 'threaded': bool(threaded and wall is None),
            'through_opening': bool(threaded), 'wall_exit_cm_before_opening': None if wall is None else round(wall * 100, 1)}


def skin_tube_profile(bvh, pts, a, b, ts):
    """[(t, closed_fraction, offset_m, centre)] - garment ring centre relative to the skin centre at each slice."""
    axis = Vector(np.asarray(b, float) - np.asarray(a, float)).normalized()
    out = []
    for t in ts:
        c = skin_centre(pts, a, b, float(t))
        if c is None:
            continue
        cl, off = ring(bvh, Vector(c), axis)
        out.append((float(t), cl, off.length, c))
    return out


def skin_segment_score(bvh, pts, a, b, ts):
    prof = skin_tube_profile(bvh, pts, a, b, ts)
    closed = [(t, o, c) for t, cl, o, c in prof if cl >= 0.75]
    if not closed:
        return None
    return {'mean_offset': float(np.mean([o for _, o, _ in closed])), 'end_offset': closed[-1][1],
            'end_t': closed[-1][0], 'end_centre': closed[-1][2], 'closed': len(closed), 'slices': len(prof)}


def segment_ts(si, last, limb=''):
    """Slices along a limb segment, from just off the torso / the joint (thighs from mid-thigh: near the crotch the
    rings run into the other leg / the seat of the trousers)."""
    if si == 0:
        return np.linspace(0.4, 0.95, 7) if limb.startswith('leg') else np.linspace(0.15, 0.95, 9)
    return np.linspace(0.1, 1.0, 10)


def ring_dirs(axis, dirs=16):
    axis = Vector(axis).normalized()
    u = axis.orthogonal().normalized()
    v = axis.cross(u)
    return [u * math.cos(2 * math.pi * k / dirs) + v * math.sin(2 * math.pi * k / dirs) for k in range(dirs)]


def opening_rim(bvh, pts, a, b, t0, t1=1.3, step=0.02, dirs=16, reach=0.15):
    """The opening as it really is. Cuffs are often slanted or ragged, so 'the last fully closed slice' is not the
    opening. From a slice inside the tube, walk outward along the limb; per direction around it, the rim is the last
    slice where that side of the garment still exists. Opening offset = centre of those rim points relative to the
    skin's own centre there (bones are off-centre in Genies limbs). Runs past the joint into the hand / foot.
    Returns {'offset', 'vec', 'rim_t', 'centre', 'axis', 'rim'} or None."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    axis = Vector(b - a).normalized()
    D = ring_dirs(axis, dirs)
    last = [None] * dirs
    alive = [True] * dirs
    for t in np.arange(t0, t1 + 1e-6, step):
        c = skin_centre(pts, a, b, float(t))
        if c is None:
            continue
        for k, d in enumerate(D):
            if not alive[k]:
                continue
            h = bvh.ray_cast(Vector(c), d, reach)
            if h[0] is not None:
                last[k] = (float(t), np.array(h[0]))
            elif last[k] is not None:
                alive[k] = False
    rim = [r for r in last if r is not None]
    if len(rim) < dirs * 0.6:
        return None
    tbar = float(np.mean([t for t, _ in rim]))
    c = skin_centre(pts, a, b, tbar)
    if c is None:
        return None
    ax = np.array(axis)
    rel = np.array([p - c for _, p in rim])
    rel -= np.outer(rel @ ax, ax)
    vec = rel.mean(0)
    return {'offset': float(np.linalg.norm(vec)), 'vec': vec, 'rim_t': tbar, 'centre': c, 'axis': ax,
            'rim': rim, 'rim_t_range': (min(t for t, _ in rim), max(t for t, _ in rim))}


def limb_openings(bvh, body_co, body_bone, joint_of, limb):
    """Per segment of a limb: mean skin-centred tube offset, and - where the tube ends (the last segment, or a short
    sleeve ending inside a segment) - the real opening rim."""
    chain = LIMB_CHAINS[limb]
    out = {}
    for si, (bone, child) in enumerate(chain):
        a, b = np.array(joint_of(bone)), np.array(joint_of(child))
        pts = limb_skin(body_co, body_bone, bone, child)
        s = skin_segment_score(bvh, pts, a, b, segment_ts(si, si == len(chain) - 1, limb))
        if s is None:
            continue
        r = {'mean_offset': s['mean_offset']}
        if si == len(chain) - 1 or s['end_t'] < 0.85:
            rim = opening_rim(bvh, pts, a, b, t0=max(0.1, s['end_t'] - 0.15),
                              t1=1.3 if si == len(chain) - 1 else 1.0)
            if rim:
                r['opening'] = rim
        out[bone] = r
    return out


def opening_clearance(body_bvh, rim, reach=0.15):
    """Per rim point: gap between the skin and the rim, measured in the rim's plane from the skin centre (m).
    Negative = the skin is outside the rim (pokes through / rests on it)."""
    gaps = []
    ax = rim['axis']
    for t, p in rim['rim']:
        rel = p - rim['centre']
        rel -= (rel @ ax) * ax
        dist = float(np.linalg.norm(rel))
        if dist < 1e-6:
            continue
        base = p - rel
        h = body_bvh.ray_cast(Vector(base), Vector(rel / dist), reach)
        if h[0] is not None:
            gaps.append(dist - h[3])
    return gaps


# ---------------------------------------------------------------- masks may only remove what nobody can see

def cone_dirs(n, rings=((0.0, 1), (30.0, 8), (55.0, 8))):
    n = Vector(n).normalized()
    u = n.orthogonal().normalized()
    w = n.cross(u)
    out = []
    for ang, k in rings:
        a = math.radians(ang)
        for j in range(k):
            t = 2 * math.pi * j / k
            out.append((n * math.cos(a) + (u * math.cos(t) + w * math.sin(t)) * math.sin(a)).normalized())
    return out


# How deep behind a hidden surface the revealed garment may lie. Looking THROUGH a limb (an ankle ~5 cm across) at up
# to 55 deg from the skin normal travels >= 2 * 2.5 cm * cos 55 = 2.9 cm, so 2.5 cm separates "the garment the skin
# was poking through" from "a hole through the leg to the far wall of a shoe".
BEHIND = 0.025


def reveals_ok(hit, d, p, behind, body_bvh, n=None):
    """What a camera sees once surface point p is hidden: OK only if it is a garment's FRONT face either right behind
    p (within `behind` along the view ray; or, for a slanted view, at most 2x that along the ray but no deeper than
    `behind` under p along its normal - a far wall seen THROUGH a limb is a limb's thickness deep - the same garment surface the skin pokes through, reached at a slant) or buried
    inside the body (the garment the skin was poking through). Anything else - nothing, a back face, or a surface
    beyond the body after looking THROUGH the limb (the far wall of a shoe) - is a hole."""
    if hit[0] is None or hit[1].dot(-d) > 0:
        return False
    run = (hit[0] - p).length
    if run <= behind:
        return True
    if n is not None and run <= 2 * behind and (p - hit[0]).dot(Vector(n)) <= behind:
        return True
    return body_bvh is not None and inside_solid(body_bvh, hit[0])


def seen(nude_bvh, p, d, own, far=1.5, tol=0.002):
    """Is surface point p (on the mesh whose polygons are nude_bvh indices own=(lo, hi)) what a camera looking
    along -d sees? The first hit must be p itself on its own mesh - a garment lying within mm of the skin is a
    different surface and means p is covered."""
    h = nude_bvh.ray_cast(p + d * far, -d, far + 0.01)
    return h[0] is not None and (h[0] - p).length < tol and own[0] <= h[2] < own[1]


def overreach(samples, normals, nude_bvh, shown_bvh, far=1.5, tol=0.002, behind=BEHIND, body_bvh=None, own=(0, 1 << 62)):
    """See-through holes made by masks: a masked-out surface point that a camera CAN see in the unmasked look (from any
    direction within 55 deg of its normal) where the masked look then shows something not allowed by reveals_ok().
    Returns [(point, view_dir)]."""
    out = []
    for p, n in zip(samples, normals):
        p = Vector(p)
        for d in cone_dirs(n):
            if not seen(nude_bvh, p, d, own, far, tol):
                continue  # not visible from here
            if not reveals_ok(shown_bvh.ray_cast(p + d * far, -d, far + 1.0), d, p, behind, body_bvh, n):
                out.append((np.array(p), np.array(d)))
                break
    return out


# ---------------------------------------------------------------- cross-sections: the ground truth for openings
# Rays from inside a limb are fooled by double-walled AI sleeves (inner lining + puffy outer shell): an arm running
# THROUGH the lining still "looks" enclosed and centred. A planar cross-section is not fooled: the garment's material
# is the area between its outlines (even-odd), the sleeve's hole is the empty area its outlines enclose, and the limb
# must lie in that hole, centred on it.

def tri_mesh(obj):
    import bpy
    dg = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(dg)
    me = ev.to_mesh()
    me.calc_loop_triangles()
    Mw = np.array(obj.matrix_world)
    co = np.array([v.co[:] for v in me.vertices])
    co = co @ Mw[:3, :3].T + Mw[:3, 3]
    tri = np.array([t.vertices[:] for t in me.loop_triangles], int).reshape(-1, 3)
    ev.to_mesh_clear()
    return co, tri


def plane_basis(axis):
    ax = np.asarray(axis, float) / np.linalg.norm(axis)
    up = np.array([0, 0, 1.0]) - ax * ax[2]
    if np.linalg.norm(up) < 1e-3:
        up = np.array([0, 1.0, 0]) - ax * ax[1]
    up /= np.linalg.norm(up)
    return ax, np.cross(up, ax), up  # normal, right, up


def plane_section(co, tri, o, n, u, v):
    """2D segments (in the plane's u/v coordinates, metres) where a triangle mesh crosses the plane."""
    d = (co - o) @ n
    dt = d[tri]
    m = (dt.min(1) < 0) & (dt.max(1) > 0)
    T, D = tri[m], dt[m]
    if not len(T):
        return np.zeros((0, 2, 2))
    C, P = [], []
    for i0, i1 in ((0, 1), (1, 2), (2, 0)):
        a, b = D[:, i0], D[:, i1]
        C.append(a * b < 0)
        t = a / np.where(a - b == 0, 1e-30, a - b)
        P.append(co[T[:, i0]] + (co[T[:, i1]] - co[T[:, i0]]) * t[:, None])
    C, P = np.stack(C, 1), np.stack(P, 1)
    ok = C.sum(1) == 2
    idx = np.argsort(~C[ok], 1, kind='stable')[:, :2]
    S = np.take_along_axis(P[ok], idx[:, :, None], 1) - o
    return np.stack([S @ u, S @ v], -1)


def crossings(segs, pts, direction=0, sign=1):
    """How many outline segments a ray from each 2D point crosses (along +/- u or v)."""
    if not len(segs):
        return np.zeros(len(pts), int)
    a, b = (0, 1) if direction == 0 else (1, 0)
    x1, y1 = segs[:, 0, a] * sign, segs[:, 0, b]
    x2, y2 = segs[:, 1, a] * sign, segs[:, 1, b]
    px, py = pts[:, a][:, None] * sign, pts[:, b][:, None]
    cond = (y1 > py) != (y2 > py)
    dy = np.where(y2 - y1 == 0, 1e-30, y2 - y1)
    xi = x1 + (py - y1) * (x2 - x1) / dy
    return (cond & (xi > px)).sum(1)


def _components(mask):
    """4-connected component labels of a boolean grid (-1 = not in mask)."""
    n0, n1 = mask.shape
    lab = np.full(mask.shape, -1, int)
    k = 0
    for y0, x0 in zip(*np.nonzero(mask)):
        if lab[y0, x0] >= 0:
            continue
        stack = [(y0, x0)]
        lab[y0, x0] = k
        while stack:
            y, x = stack.pop()
            for yy, xx in ((y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)):
                if 0 <= yy < n0 and 0 <= xx < n1 and mask[yy, xx] and lab[yy, xx] < 0:
                    lab[yy, xx] = k
                    stack.append((yy, xx))
        k += 1
    return lab, k


class SectionField:
    """One garment cross-section, rasterised once (2 mm grid around the plane origin): where its material is, the
    empty holes it encloses and the area inside its outline. Limb outlines are then evaluated against it cheaply -
    the rig fit tries hundreds of poses against fixed sections."""

    def __init__(self, segs, half=0.10, step=0.002):
        self.step, self.half, self.n_segs = step, half, len(segs)
        g = np.arange(-half, half + 1e-9, step)
        self.g = g
        X, Y = np.meshgrid(g, g)
        G = np.c_[X.ravel(), Y.ravel()]
        n = len(g)
        cr = [crossings(segs, G, 0, 1), crossings(segs, G, 0, -1), crossings(segs, G, 1, 1), crossings(segs, G, 1, -1)]
        self.material = (cr[0] % 2 == 1).reshape(n, n)
        self.enclosed = np.all([x > 0 for x in cr], 0).reshape(n, n)
        hole = self.enclosed & ~self.material
        self.hole_lab, k = _components(hole)
        self.holes = []
        for i in range(k):
            ys, xs = np.nonzero(self.hole_lab == i)
            edge = ys.min() == 0 or xs.min() == 0 or ys.max() == n - 1 or xs.max() == n - 1
            self.holes.append({'centre': np.array([g[xs].mean(), g[ys].mean()]), 'area': len(ys) * step * step, 'edge': edge})
        self.encl_lab, k2 = _components(self.enclosed)
        self.encl = [np.array([g[np.nonzero(self.encl_lab == i)[1]].mean(), g[np.nonzero(self.encl_lab == i)[0]].mean()])
                     for i in range(k2)]

    def cell(self, p):
        i = np.clip(np.round((np.asarray(p)[..., 1] + self.half) / self.step).astype(int), 0, len(self.g) - 1)
        j = np.clip(np.round((np.asarray(p)[..., 0] + self.half) / self.step).astype(int), 0, len(self.g) - 1)
        return i, j

    def evaluate(self, skin2d, shrink=0.003, gap=0.003):
        c = skin2d.mean(0)
        r = np.linalg.norm(skin2d - c, axis=1, keepdims=True)
        sk = c + (skin2d - c) * np.maximum(0, 1 - shrink / np.maximum(r, 1e-9))
        i, j = self.cell(sk)
        in_mat = float(self.material[i, j].mean()) if self.n_segs else 0.0
        area = 0.5 * abs(np.sum(skin2d[:, 0] * np.roll(skin2d[:, 1], 1) - np.roll(skin2d[:, 0], 1) * skin2d[:, 1]))
        out = {'in_material': in_mat, 'cavity': False, 'offset': None, 'vec': None, 'segments': self.n_segs,
               # share of the limb outline inside the garment's outline at all (0 past a short sleeve's hem)
               'enclosed': float(self.enclosed[i, j].mean()) if self.n_segs else 0.0}
        # RPG gap: share of the limb outline that, pushed out by `gap`, lands in the garment's material or outside
        # it - the limb resting on (or through) the sleeve wall instead of keeping a gap all round
        so = c + (skin2d - c) * (1 + gap / np.maximum(r, 1e-9))
        io, jo = self.cell(so)
        out['touch'] = float((self.material[io, jo] | ~self.enclosed[io, jo]).mean()) if self.n_segs else 1.0
        # the hole the limb is in (or the nearest one within 3 cm), if it is a real enclosed hole of limb size
        ci, cj = self.cell(c)
        cand = []
        lab = self.hole_lab[ci, cj]
        if lab >= 0:
            cand = [lab]
        else:
            ys, xs = np.nonzero(self.hole_lab >= 0)
            if len(ys):
                d = np.hypot(ys - ci, xs - cj)
                k = int(np.argmin(d))
                if d[k] * self.step < 0.03:
                    cand = [self.hole_lab[ys[k], xs[k]]]
        for lab in cand:
            h = self.holes[lab]
            if not h['edge'] and h['area'] > 0.25 * max(area, 1e-6):
                v = h['centre'] - c
                out.update(cavity=True, offset=float(np.linalg.norm(v)), vec=v.tolist(), hole_area=h['area'], skin_area=area)
        if not out['cavity'] and self.n_segs:
            lab = self.encl_lab[ci, cj]
            if lab >= 0:
                v = self.encl[lab] - c
                out.update(offset=float(np.linalg.norm(v)), vec=v.tolist())
        return out


def section_fit(segs, skin2d):
    return SectionField(segs).evaluate(skin2d)


def skin_ring_2d(skin3d, o, n, u, v, slab=0.012):
    """Limb outline at a plane: skin vertices within a slab, projected, ordered by angle around their centre."""
    d = (skin3d - o) @ n
    s = skin3d[np.abs(d) < slab]
    if len(s) < 6:
        s = skin3d[np.abs(d) < 2 * slab]
        if len(s) < 6:
            return None
    p = np.stack([(s - o) @ u, (s - o) @ v], -1)
    c = p.mean(0)
    return p[np.argsort(np.arctan2(p[:, 1] - c[1], p[:, 0] - c[0]))]


def limb_sections(gco, gtri, skin3d, a, b, ts):
    """Section fits along a limb segment (planes perpendicular to it, through the skin centre at each t)."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    n, u, v = plane_basis(b - a)
    out = []
    for t in ts:
        c = skin_centre(skin3d, a, b, float(t))
        if c is None:
            continue
        segs = plane_section(gco, gtri, c, n, u, v)
        ring2 = skin_ring_2d(skin3d, c, n, u, v)
        if ring2 is None or not len(segs):
            out.append({'t': float(t), 'garment': bool(len(segs))})
            continue
        f = section_fit(segs, ring2)
        f['t'] = float(t)
        f['garment'] = True
        out.append(f)
    return out


def hideable(samples, normals, nude_bvh, garment_bvh, far=1.5, tol=0.002, behind=BEHIND, body_bvh=None, own=(0, 1 << 62)):
    """Per surface sample: may it be hidden? Only if, from every direction it can be seen in the unmasked look
    (within 55 deg of its normal), what shows instead passes reveals_ok() - so hiding never opens a hole. The exact
    counterpart of overreach(): equip hides only what this allows, the inspection then cannot find a hole."""
    ok = np.ones(len(samples), bool)
    for i, (p, n) in enumerate(zip(samples, normals)):
        p = Vector(p)
        for d in cone_dirs(n):
            if not seen(nude_bvh, p, d, own, far, tol):
                continue  # not visible from here
            if not reveals_ok(garment_bvh.ray_cast(p + d * 1e-4, -d, 0.5), d, p, behind, body_bvh, n):
                ok[i] = False
                break
    return ok


def outer_heights(bvh, co, n, back=0.03, reach=0.10, solid_thickness=0.006):  # noqa: ARG001
    """Height of a piece's OUTER surface above each skin/cage point along its normal (NaN = not covered). Starting
    `back` inside the skin: if the ray starts inside a solid piece the first hit is its outer surface, else the
    surface after entering it. Same convention as equip.heights."""
    out = np.full(len(co), np.nan)
    for i, (p, nn) in enumerate(zip(co, n)):
        nv = Vector(nn)
        o = Vector(p) - nv * back
        h = bvh.ray_cast(o, nv, reach + back)
        if h[0] is None:
            continue
        t0 = h[3] - back
        if h[1].dot(nv) < 0:  # entering: the outer surface is where it leaves again
            h2 = bvh.ray_cast(h[0] + nv * 1e-4, nv, 0.04)
            out[i] = t0 + h2[3] if h2[0] is not None and h2[1].dot(nv) > 0 else t0 + 0.002
        else:
            out[i] = t0
    return out



# ---------------------------------------------------------------- torso: waistband, hem and side seams
TORSO_SLOTS = ('top', 'outerwear', 'fullbody', 'bottom')
ARM_PREFIX = ('LeftArm', 'RightArm', 'LeftForeArm', 'RightForeArm', 'LeftHand', 'RightHand')


def torso_sections(gco, gtri, bco, btri, z_lo, z_hi, axis_xy, step=0.01, reach=0.25):
    """Horizontal cross-sections of a garment through the torso, from z_lo to z_hi: at each height, the share of the
    torso's SKIN OUTLINE (a section of the body as shown - hidden skin removed, so only visible skin counts) that
    lies outside everything the garment encloses (material or hole) = skin poking out through a waistband, a hem or
    a side seam. Arms are excluded by `reach` around the body axis. Returns [(z, share_outside, n_points)]."""
    n, u, v = np.array([0.0, 0.0, 1.0]), np.array([1.0, 0.0, 0.0]), np.array([0.0, 1.0, 0.0])
    out = []
    for z in np.arange(z_lo, z_hi + 1e-9, step):
        o = np.array([axis_xy[0], axis_xy[1], z])
        bseg = plane_section(bco, btri, o, n, u, v)
        if not len(bseg):
            continue
        pts = bseg.reshape(-1, 2)
        pts = pts[np.linalg.norm(pts, axis=1) < reach * 0.95]
        if len(pts) < 8:
            continue
        segs = plane_section(gco, gtri, o, n, u, v)
        if not len(segs):
            out.append((float(z), 1.0, int(len(pts))))
            continue
        sf = SectionField(segs, half=reach)
        i, j = sf.cell(pts)
        out.append((float(z), float((~sf.enclosed[i, j]).mean()), int(len(pts))))
    return out
