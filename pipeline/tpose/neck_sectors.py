"""Per-sector neckline measurement of a top's exported glb (as the customizer draws it, rest/fit pose).

Sectors: 16 x 22.5 deg around the neck centre, 0 = +X side, 4 = front, 8 = -X side, 12 = back (the customizer
session's convention). Per sector:
  r    the collar opening's inner radius (the nearest garment vertex to the neck axis in that sector, collar zone)
  z    that point's height vs the Neck joint (cm)
  gap  r minus the neck skin's radius in that direction at that height (horizontal stand-off)
  near that point's true distance to the nearest body surface
Neck centre: x = 0, y midway between the front and back neck skin at the Neck joint height.

Run: blender -b --factory-startup -P pipeline/tpose/neck_sectors.py -- <piece.glb> [<piece.glb> ...]
"""
import bpy, sys, json, math
from pathlib import Path
import numpy as np
from mathutils import Vector
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'pipeline'))
sys.path.insert(0, str(ROOT / 'pipeline' / 'tpose'))
import fit_outfit as F  # noqa: E402

lm = json.loads((ROOT / 'Bases' / 'Xander.json').read_text())['landmarks']
arm, body, _ = F.load_base('Xander')
for pb in arm.pose.bones:
    pb.matrix_basis.identity()
bpy.context.view_layer.update()
bb = F.bvh_of(*F.world_verts(body, evaluated=True))
nz = lm['Neck'][2]


def ray(cy, z, ang):  # ang: 0 = +X, 90 = front (-Y in Blender)
    d = Vector((math.cos(math.radians(ang)), -math.sin(math.radians(ang)), 0))
    h = bb.ray_cast(Vector((0, cy, z)), d, 0.3)
    return h[3] if h[0] is not None else float('nan')


cy = lm['Neck'][1]
for _ in range(4):
    cy += (ray(cy, nz, 270) - ray(cy, nz, 90)) / 2
neck_r = (ray(cy, nz, 90) + ray(cy, nz, 270)) / 2
for path in sys.argv[sys.argv.index('--') + 1:]:
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(Path(path).resolve()))
    g = np.concatenate([F.world_verts(o)[0] for o in set(bpy.data.objects) - before if o.type == 'MESH'])
    for o in set(bpy.data.objects) - before:
        bpy.data.objects.remove(o, do_unlink=True)
    c = g[(g[:, 2] > nz - 0.07) & (np.hypot(g[:, 0], g[:, 1] - cy) < 0.15)]
    ang = np.degrees(np.arctan2(-(c[:, 1] - cy), c[:, 0])) % 360
    rad = np.hypot(c[:, 0], c[:, 1] - cy)
    R, Z, G, N = [], [], [], []
    for s in range(16):
        m = np.abs(((ang - s * 22.5 + 180) % 360) - 180) < 11.25
        k = np.argmin(np.where(m, rad, 9))
        R.append(round(rad[k] * 1000)); Z.append(round((c[k, 2] - nz) * 100, 1))
        G.append(round((rad[k] - ray(cy, c[k, 2], s * 22.5)) * 1000))
        N.append(round(bb.find_nearest(Vector(c[k]))[3] * 1000))
    print(f'SECTORS {Path(path).name}: neck radius at the joint {neck_r*1000:.0f} mm, centre y {cy:.3f}\n'
          f'  r   {R}\n  gap {G}\n  near {N}\n  z   {Z}\n'
          f'  front dip vs back {Z[12] - Z[4]:.1f} cm, L/R asym max {max(abs(R[s] - R[(8 - s) % 16]) for s in range(16))} mm',
          flush=True)
