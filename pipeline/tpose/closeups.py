"""Close-up renders of one region of a look, from 6 directions, as shown (look pose, masks on).

Run: blender -b --factory-startup -P pipeline/tpose/closeups.py -- <look_dir> <base> <region> <out_dir>
regions: waist, shoulder, cuffs, ankles, collar, back, full, at:x,y,z (a 10 cm box around one point, e.g. a defect)
"""
import bpy, sys, math
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'pipeline'))
sys.path.insert(0, str(ROOT / 'pipeline' / 'tpose'))
import fit_outfit as F  # noqa: E402
import metrics as M  # noqa: E402

look, base, region, out = sys.argv[sys.argv.index('--') + 1:][:4]
look, out = Path(look).resolve(), Path(out).resolve()
out.mkdir(parents=True, exist_ok=True)
bpy.ops.wm.open_mainfile(filepath=str(look / '06_fitted' / f'{look.name}__{base}.blend'))
arm = next(o for o in bpy.data.objects if o.type == 'ARMATURE')
F.apply_look_pose(arm, look)
shown = [o for o in bpy.data.objects if o.type == 'MESH' and not o.hide_render and not o.name.startswith(('Icosphere', 'Sphere'))]
J = lambda b: np.array(M.joint(arm, b))
VIEWS = {
    'waist': (J('Hips') + [0, 0, 0.06], 0.17, [('front', 0, 0), ('side', 90, 0), ('back', 180, 0), ('low', 30, -30), ('side2', -90, 0), ('lowback', 200, -30)]),
    'shoulder': (J('LeftShoulder') + [0.03, 0, 0.03], 0.11, [('front', 0, 15), ('frontside', 45, 35), ('side', 90, 20), ('backside', 135, 35), ('back', 180, 20), ('above', 0, 75)]),
    'ankles': ((J('LeftFoot') + J('RightFoot')) / 2 + [0, 0, 0.02], 0.16, [('front', 0, 0), ('side', 90, 0), ('back', 180, 0), ('low', 30, -15), ('side2', -90, 0), ('above', 0, 60)]),
    'cuffs': (J('LeftHand'), 0.1, [('front', 0, 0), ('end_on', 90, 0), ('below', 0, -80), ('back', 180, 0), ('above', 0, 80), ('inner', 30, -30)]),
    'full': (None, None, [(f'turn{a:03d}', a, 0) for a in (0, 60, 120, 180, 240, 300)]),
    'back': (J('Spine2') + [0, 0, -0.03], 0.17, [('back', 180, 5), ('backleft', 140, 5), ('backright', 220, 5),
                                               ('left', 90, 5), ('right', 270, 5), ('back_low', 180, -20)]),
    'collar': (J('Neck') + [0, 0, -0.03], 0.13, [('front', 0, 10), ('above', 0, 80), ('frontside', 45, 25), ('side', 90, 10),
                                                ('backside', 135, 25), ('back', 180, 10)]),
}
if region.startswith('at:'):
    c = np.array([float(x) for x in region[3:].split(',')])
    VIEWS[region] = (c, 0.05, [('front', 0, 0), ('left', -45, 0), ('right', 45, 0), ('high', 0, 40), ('low', 0, -40),
                               ('side', 90, 0), ('side2', -90, 0), ('back', 180, 0),
                               ('below', 0, -80), ('below_back', 180, -80), ('below_side', 90, -75)])
    region = 'at'
    VIEWS['at'] = VIEWS.pop(next(k for k in VIEWS if k.startswith('at:')))
c, half, views = VIEWS[region]
for name, rot, el in views:
    focus = None if c is None else (c - half, c + half)
    F.render(out / f'{region}_{name}.png', shown, rotate=math.radians(rot), elev=math.radians(el), focus=focus,
             res=(400, 400) if c is not None else (360, 520), clip=False)
print('CLOSEUPS', out, flush=True)
