"""RPG layer shells: a fixed envelope per clothing layer where layers overlap AND stay visible, so ANY bottoms fit
under ANY top or outerwear - a piece is checked against the standard, never against one particular neighbour, and
swapping one piece never forces another to be regenerated.

Where layers overlap visibly: the WAISTBAND BAND (Hips joint .. +10 cm). Bottoms show below a top's hem and the
top's hem lies over the bottoms' waistband, so both are seen together there. (A top under outerwear is hidden
entirely by equip's occlusion rule, so tops vs outerwear never show together over the torso; garments also hang
off the shoulders at ~0 mm, so a torso-wide band would be meaningless - measured on the hoodie-boy pieces.)

  bottoms           outer surface within each sub-band's max off the skin (95th percentile: hips/seat 24 mm,
                    elastic waistband 17 mm - a tab, loop or baggy seat sticking out is what pushes through the
                    layer above), and nothing above the band (RISE_MAX)
  tops, outerwear   wherever they cover the band, outer surface >= that max + GAP_MM (5th percentile), so they
                    always clear any in-spec bottoms. The exact pairwise spacing check (inspect_look) stays the
                    backstop for each real combination.

Measured on dense samples of the body surface (4 per face), along the skin normal (metrics.outer_heights). The same
shell is drawn in 2D (shell_rows) so step 2 rejects an image that breaks it before any 3D credits are spent.

Run (report only): blender -b --factory-startup -P pipeline/tpose/shells.py -- <look_dir> [<look_dir> ...]
"""
import sys
from pathlib import Path
import numpy as np

GAP_MM = 3
# Two sub-bands, metres above the Hips joint: the hips/seat (cargo cuts sit looser there) and the elastic waistband.
# bottoms: 95th percentile of the outer surface off the skin <= max; tops/outerwear: 5th percentile >= max + GAP_MM.
# Calibrated 2026-10-15 on every generated piece: Tripo 3.1 standard joggers 25-26 / 15-20 mm (6 meshes), Higgsfield
# H3.1 joggers 23/15, plain hoodie 31/30, bundle 29/21.
BANDS = {
    'hips':      {'z': (0.0, 0.05), 'bottom_max': 26},
    'waistband': {'z': (0.05, 0.10), 'bottom_max': 17},
}
BAND = (0.0, 0.10)            # the whole band
# Below the hip joint a hip-length hem ENDS, so percentiles there measure where it stops, not a clearance: hems over
# the thighs are judged on the real pairs instead (gate.py --combo: every new piece against the existing pieces)
RISE_MAX = 0.11               # bottoms may not cover skin higher than this above the Hips joint
EDGE = 0.012                  # a piece's own hem edge (within this of its lowest/highest cover) is not judged
MIN_POINTS = 40
LO_PCT, HI_PCT = 5, 95
BOTTOM_MAX_MM = max(b['bottom_max'] for b in BANDS.values())   # loosest bound (2D check, all rows of the band)
UPPER_MIN_MM = min(b['bottom_max'] for b in BANDS.values()) + GAP_MM
SLOTS = {'bottom': 'bottom', 'top': 'upper', 'outerwear': 'upper', 'fullbody': 'upper'}


def band_samples(body_co, tris, body_bone, hips_z):
    """Dense skin samples on the trunk around the waistband band: (points, normals, z_rel)."""
    bb = np.array([str(b) for b in body_bone])
    trunk_v = np.isin(bb, ['', 'LeftUpLeg', 'RightUpLeg'])
    a, b, c = body_co[tris[:, 0]], body_co[tris[:, 1]], body_co[tris[:, 2]]
    cen = (a + b + c) / 3
    keep = trunk_v[tris].all(1) & (cen[:, 2] > hips_z + BAND[0] - 0.02) & (cen[:, 2] < hips_z + RISE_MAX + 0.04)
    a, b, c, cen = a[keep], b[keep], c[keep], cen[keep]
    n = np.cross(b - a, c - a)
    n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-12
    # below the hip joint the inner thighs face each other: no top's hem lies there (it spans the legs outside)
    inner = (cen[:, 2] < hips_z) & (n[:, 0] * np.sign(cen[:, 0]) < -0.3)
    a, b, c, cen, n = a[~inner], b[~inner], c[~inner], cen[~inner], n[~inner]
    pts = np.concatenate([cen] + [cen + 0.5 * (v - cen) for v in (a, b, c)])
    nrm = np.concatenate([n] * 4)
    return pts, nrm, pts[:, 2] - hips_z


def measure(outer, z_rel):
    """outer: outer-surface height (m, NaN = not covered) per sample -> per sub-band stats in mm (the piece's own
    hem edges excluded) and how high the piece reaches."""
    cov = ~np.isnan(outer)
    if not cov.any():
        return {'n': 0}
    lo_z, hi_z = z_rel[cov].min(), z_rel[cov].max()
    out = {'n': 0, 'top_rel_m': round(float(hi_z), 3)}
    for name, b in BANDS.items():
        m = cov & (z_rel >= b['z'][0]) & (z_rel < b['z'][1]) & (z_rel > lo_z + EDGE) & (z_rel < hi_z - EDGE)
        h = outer[m] * 1000
        out['n'] += int(m.sum())
        if len(h) >= MIN_POINTS:
            out[name] = {'n': int(len(h)), f'p{LO_PCT}': round(float(np.percentile(h, LO_PCT)), 1),
                         'median': round(float(np.median(h)), 1), f'p{HI_PCT}': round(float(np.percentile(h, HI_PCT)), 1)}
    return out


def check(slot, s):
    kind = SLOTS.get(slot)
    if kind is None:
        return []
    fails = []
    for name, b in BANDS.items():
        st = s.get(name)
        if not st:
            continue
        if kind == 'bottom' and st[f'p{HI_PCT}'] > b['bottom_max']:
            fails.append(f'outside the bottoms shell at the {name}: {st[f"p{HI_PCT}"]:.0f} mm off the skin '
                         f'({HI_PCT}th pct; max {b["bottom_max"]} mm - tabs, loops, pockets or a baggy seat there '
                         f'push through tops)')
        if kind == 'upper' and st[f'p{LO_PCT}'] < b['bottom_max'] + GAP_MM:
            fails.append(f'inside the bottoms shell at the {name}: {st[f"p{LO_PCT}"]:.0f} mm off the skin '
                         f'({LO_PCT}th pct; {"an" if slot[0] in "aeiou" else "a"} {slot} must stay >= '
                         f'{b["bottom_max"] + GAP_MM} mm out to clear any bottoms)')
    if kind == 'bottom' and s.get('top_rel_m', 0) > RISE_MAX + EDGE:
        fails.append(f'rises above the bottoms shell: covers skin {s["top_rel_m"] * 100:.0f} cm above the hips '
                     f'(max {RISE_MAX * 100:.0f} cm)')
    return fails


def shell_rows(cam, hips_z):
    """Image rows (top, bottom) of the waistband band for a step-1 camera (camera.json: orthographic)."""
    mpp, cz, h = cam['metres_per_pixel'], cam['center'][2], cam['res'][1]
    row = lambda z: int(round(h / 2 - (z - cz) / mpp))
    return row(hips_z + BAND[1]), row(hips_z + BAND[0])


def look_report(look):
    """In Blender: shell stats + fails for every garment in a look, each measured in the look pose with masks off."""
    import bpy
    import fit_outfit as F  # noqa: E402
    import metrics as M  # noqa: E402
    arm = next(o for o in bpy.data.objects if o.type == 'ARMATURE')
    body = bpy.data.objects['Submesh_0']
    names, W = F.body_weights(body)
    bco, btri = M.tri_mesh(body)
    hips_z = float(M.joint(arm, 'Hips')[2])
    pts, nrm, z_rel = band_samples(bco, btri, M.chain_bone_of(names, W), hips_z)
    rep = {}
    for o in bpy.data.objects:
        if o.type != 'MESH' or '__' not in o.name:
            continue
        slot, key = o.name.split('__')[1], o.name.split('__')[-1]
        if slot not in SLOTS:
            continue
        outer = M.outer_heights(F.bvh_of(*F.world_verts(o, evaluated=True)), pts, nrm, reach=0.15)
        s = measure(outer, z_rel)
        rep[key] = {'slot': slot, 'stats': s, 'fails': check(slot, s)}
    return rep, hips_z


if __name__ == '__main__' and '--' in sys.argv:
    import bpy, json
    ROOT = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(ROOT / 'pipeline'))
    sys.path.insert(0, str(ROOT / 'pipeline' / 'tpose'))
    import fit_outfit as F  # noqa: E402
    for look in sys.argv[sys.argv.index('--') + 1:]:
        look = Path(look).resolve()
        man = json.loads((look / '06_fitted' / 'manifest.json').read_text())
        bpy.ops.wm.open_mainfile(filepath=str(look / '06_fitted' / f'{look.name}__{man["base"]}.blend'))
        F.apply_look_pose(next(o for o in bpy.data.objects if o.type == 'ARMATURE'), look)
        for o in bpy.data.objects:
            for m in getattr(o, 'modifiers', []):
                if m.type == 'MASK':
                    m.show_viewport = False
        bpy.context.view_layer.update()
        rep, hz = look_report(look)
        for k, r in rep.items():
            print('SHELL', look.name, k, r['slot'], json.dumps(r['stats']), '|', '; '.join(r['fails']) or 'IN SPEC',
                  flush=True)
