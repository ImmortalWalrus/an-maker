"""Surface-quality numbers for a body-made top (shell_garment.py output), measured on its glb in the fit pose (rest).

  relief   per vertex of the OUTER fabric surface: its offset from the mean of its neighbours, along its normal (mm).
           Reported as p90 of |relief| for: the armhole band (within 1.5 cm of the sleeve/body join, shoulder to
           underarm), the sleeve tube, the sleeve end (last 1.5 cm: flare + rolled rim), and the torso panels.
  back     depth below the convex outline of the back profile, between the shoulder-blade line and the waist, in
           vertical slices 1 cm wide at x = -8, -5, 0, 5, 8 cm (mm; 0 = straight or convex), with the slice's sideways
           slope removed (raw_slice_mm: without that correction; it reads ~2 mm on a straight back where it curves round)

Run: blender -b --factory-startup -P pipeline/tpose/tee_quality.py -- <piece.glb> [<piece.glb> ...]
"""
import bpy, bmesh, sys, json
from pathlib import Path
import numpy as np
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'pipeline'))
sys.path.insert(0, str(ROOT / 'pipeline' / 'tpose'))
import fit_outfit as F  # noqa: E402

lm = json.loads((ROOT / 'Bases' / 'Xander.json').read_text())['landmarks']
J = {k: np.array(v) for k, v in lm.items()}
arm, body, _ = F.load_base('Xander')
for pb in arm.pose.bones:
    pb.matrix_basis.identity()
bpy.context.view_layer.update()
bb = F.bvh_of(*F.world_verts(body, evaluated=True))
SPLIT = J['LeftArm'][0] + 0.015          # where shell_garment.py splits sleeve from body
ARMPIT_Z = J['LeftArm'][2] - 0.07


def upper_hull_depth(z, y):  # depth of each point below the upper convex hull of (z, y), y = outward
    o = np.argsort(z)
    z, y = z[o], y[o]
    hull = []
    for p in zip(z, y):
        while len(hull) >= 2 and (hull[-1][0] - hull[-2][0]) * (p[1] - hull[-2][1]) - (hull[-1][1] - hull[-2][1]) * (p[0] - hull[-2][0]) >= 0:
            hull.pop()
        hull.append(p)
    hz, hy = np.array(hull).T
    return np.interp(z, hz, hy) - y, z


for path in sys.argv[sys.argv.index('--') + 1:]:
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(Path(path).resolve()))
    obs = [o for o in set(bpy.data.objects) - before if o.type == 'MESH']
    o = max(obs, key=lambda m: len(m.data.vertices))
    bm = bmesh.new()
    bm.from_mesh(o.data)
    bm.transform(o.matrix_world)
    bm.normal_update()
    bm.verts.ensure_lookup_table()
    co = np.array([v.co[:] for v in bm.verts])
    no = np.array([v.normal[:] for v in bm.verts])
    outer = np.zeros(len(co), bool)
    for i, v in enumerate(bm.verts):
        loc, nrm, _, d = bb.find_nearest(v.co)
        outer[i] = loc is not None and (v.co - loc).dot(v.normal) > 0 and not v.is_boundary
    rel = np.zeros(len(co))
    for i, v in enumerate(bm.verts):
        nb = [e.other_vert(v).index for e in v.link_edges]
        if outer[i] and nb and all(outer[j] or bm.verts[j].is_boundary for j in nb):
            rel[i] = (co[i] - co[nb].mean(0)) @ no[i]
        else:
            outer[i] = False
    ax = np.abs(co[:, 0])
    # along each arm axis; the sleeve's last 1.5 cm (the flare and the rolled rim) is not the tube
    along = np.zeros(len(co))
    for sgn, side in ((1, 'Left'), (-1, 'Right')):
        a0, a1 = J[f'{side}Arm'], J[f'{side}ForeArm']
        d_ = (a1 - a0) / np.linalg.norm(a1 - a0)
        m_ = np.sign(co[:, 0]) == sgn
        along[m_] = (co[m_] - a0) @ d_
    s_end = along[ax > SPLIT + 0.02].max() if (ax > SPLIT + 0.02).any() else 0
    zone = {
        'armhole': outer & (np.abs(ax - SPLIT) < 0.015) & (co[:, 2] > ARMPIT_Z - 0.02),
        'sleeve': outer & (ax > SPLIT + 0.02) & (along < s_end - 0.015),
        'sleeve_end': outer & (ax > SPLIT + 0.02) & (along >= s_end - 0.015),
        'torso': outer & (ax < 0.08) & (co[:, 2] > J['Hips'][2] + 0.06) & (co[:, 2] < J['Spine2'][2]),
    }
    rep = {k: {'n': int(m.sum()), 'p90_mm': round(float(np.percentile(np.abs(rel[m]), 90)) * 1000, 2) if m.any() else None,
               'max_mm': round(float(np.abs(rel[m]).max()) * 1000, 2) if m.any() else None} for k, m in zone.items()}
    cy = (J['Neck'][1] + J['Spine2'][1]) / 2
    z_top, z_low = J['Spine2'][2] + 0.08, J['Spine'][2] - 0.02   # shoulder-blade line .. waist
    back = {}
    for x0 in (-0.08, -0.05, 0.0, 0.05, 0.08):
        m = outer & (np.abs(co[:, 0] - x0) < 0.005) & (co[:, 1] > cy) & (co[:, 2] > z_low) & (co[:, 2] < z_top)
        if m.sum() < 8:
            back[f'{x0*100:+.0f}cm'] = None
            continue
        z_, y_, x_ = co[m, 2], co[m, 1], co[m, 0]
        d_raw, _ = upper_hull_depth(z_, y_)
        # the back slopes sideways, so across a 1 cm slice the outer points sit lower whatever their height: remove the
        # slice's own sideways slope (pooled within 1 cm height bins) before taking the profile
        zb = np.floor(z_ / 0.01)
        sxx = sxy = 0.0
        for b_ in np.unique(zb):
            q = zb == b_
            if q.sum() >= 2:
                dx_, dy_ = x_[q] - x_[q].mean(), y_[q] - y_[q].mean()
                sxx += dx_ @ dx_
                sxy += dx_ @ dy_
        slope = sxy / sxx if sxx > 0 else 0.0
        d, zz = upper_hull_depth(z_, y_ - slope * (x_ - x0))
        k = int(np.argmax(d))
        back[f'{x0*100:+.0f}cm'] = {'max_mm': round(float(d[k]) * 1000, 1), 'at_z_cm': round(float(zz[k]) * 100, 1),
                                    'raw_slice_mm': round(float(d_raw.max()) * 1000, 1)}
    print('QUALITY', Path(path).name, json.dumps({'relief': rep, 'back_concavity': back}), flush=True)
    bm.free()
    for ob in set(bpy.data.objects) - before:
        bpy.data.objects.remove(ob, do_unlink=True)
