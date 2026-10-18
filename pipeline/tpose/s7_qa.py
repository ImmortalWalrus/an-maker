"""Step 7 - test animation + automatic QA on the fitted outfit.

A test action is keyed on the rig covering the range real clips use (T-pose, A-pose, walk, wave, arms raised past
horizontal, squat) and saved into the outfit .blend. For every pose: renders from 4 sides (rest pose from 8 +
below) and per-piece numbers - edge stretch versus rest (p99 / max ratio; capes and tears show up as big ratios)
and how many piece vertices sink inside the body. Results -> 07_qa/qa.json + qa_sheet.png.
(The Genies Unity clips Idle/Walk/Run/Jump/Wave/Peace are humanoid-muscle clips; they play on these pieces in
Unity directly, since the pieces are skinned to the same humanoid rig.)

Run: blender -b --factory-startup -P pipeline/tpose/s7_qa.py -- <outfit_dir> <base>
"""
import bpy, sys, json, math
from pathlib import Path
import numpy as np
from mathutils import Vector, Matrix

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'pipeline'))
import fit_outfit as F  # noqa: E402

POSES = {  # name: list of (bone, world axis, degrees) applied from the T-pose rest
    'tpose': [],
    'apose': [('LeftArm', 'Y', 65), ('RightArm', 'Y', -65)],
    'walk_a': [('LeftArm', 'Y', 65), ('RightArm', 'Y', -65), ('LeftArm', 'X', 25), ('RightArm', 'X', -25),
               ('LeftUpLeg', 'X', -30), ('RightUpLeg', 'X', 20), ('RightLeg', 'X', 35)],
    'walk_b': [('LeftArm', 'Y', 65), ('RightArm', 'Y', -65), ('LeftArm', 'X', -25), ('RightArm', 'X', 25),
               ('RightUpLeg', 'X', -30), ('LeftUpLeg', 'X', 20), ('LeftLeg', 'X', 35)],
    'wave': [('LeftArm', 'Y', 65), ('RightArm', 'Y', 45), ('RightForeArm', 'Y', 50), ('Spine1', 'Z', 10)],
    'arms_up': [('LeftArm', 'Y', -60), ('RightArm', 'Y', 60)],
    'squat': [('LeftArm', 'X', -60), ('RightArm', 'X', -60), ('LeftUpLeg', 'X', -75), ('RightUpLeg', 'X', -75),
              ('LeftLeg', 'X', 95), ('RightLeg', 'X', 95), ('Spine', 'X', -15)],
}
KEYED = ['Hips', 'Spine', 'Spine1', 'Spine2', 'LeftArm', 'RightArm', 'LeftForeArm', 'RightForeArm',
         'LeftUpLeg', 'RightUpLeg', 'LeftLeg', 'RightLeg']


LOOK_POSE = {}  # set in main: test motions start from the look's pose (visible pieces undeformed there)


def pose(arm, moves):
    for pb in arm.pose.bones:
        pb.matrix_basis = Matrix(LOOK_POSE[pb.name]) if pb.name in LOOK_POSE else Matrix.Identity(4)
    bpy.context.view_layer.update()
    for bone, axis, deg in moves:
        F.rotate_bone_world(arm, bone, axis, math.radians(deg))


def edges_of(obj):
    return np.array([e.vertices[:] for e in obj.data.edges], int)


def stretch(rest, now, edges):
    l0 = np.linalg.norm(rest[edges[:, 0]] - rest[edges[:, 1]], axis=1)
    l1 = np.linalg.norm(now[edges[:, 0]] - now[edges[:, 1]], axis=1)
    r = l1[l0 > 1e-5] / l0[l0 > 1e-5]
    return round(float(np.percentile(r, 99)), 2), round(float(r.max()), 2)


def sunk(piece_co, body_bvh, sample=4):
    n = 0
    pts = piece_co[::sample]
    for p in pts:
        hit, nrm, _, _ = body_bvh.find_nearest(Vector(p))
        if hit is not None and (Vector(p) - hit).dot(nrm) < -0.003:
            n += 1
    return round(n / max(len(pts), 1), 4)


def main():
    d = Path(sys.argv[sys.argv.index('--') + 1]).resolve()
    base = sys.argv[sys.argv.index('--') + 2]
    qa = d / '07_qa'
    qa.mkdir(exist_ok=True)
    blend = d / '06_fitted' / f'{d.name}__{base}.blend'
    bpy.ops.wm.open_mainfile(filepath=str(blend))
    scene = bpy.context.scene
    arm = next(o for o in bpy.data.objects if o.type == 'ARMATURE')
    LOOK_POSE.update(F.apply_look_pose(arm, d))
    meshes = [o for o in bpy.data.objects if o.type == 'MESH']
    body = max((o for o in meshes if o.parent == arm and not o.name.startswith(d.name)), key=lambda o: len(o.data.vertices))
    pieces = [o for o in meshes if o.name.startswith(d.name + '__')]

    # Test action, keyed every 12 frames, saved in the file.
    for i, (name, moves) in enumerate(POSES.items()):
        pose(arm, moves)
        for b in KEYED:
            pb = arm.pose.bones[b]
            pb.keyframe_insert('rotation_quaternion' if pb.rotation_mode == 'QUATERNION' else 'rotation_euler', frame=1 + 12 * i)
    pose(arm, [])
    for b in KEYED:
        pb = arm.pose.bones[b]
        pb.keyframe_insert('rotation_quaternion' if pb.rotation_mode == 'QUATERNION' else 'rotation_euler', frame=1 + 12 * len(POSES))
    scene.frame_start, scene.frame_end = 1, 1 + 12 * len(POSES)
    if arm.animation_data and arm.animation_data.action:
        arm.animation_data.action.name = 'qa_test_motion'
    scene.frame_set(1)
    bpy.ops.wm.save_as_mainfile(filepath=str(blend))

    masks = [m for o in [body, *pieces] for m in o.modifiers if m.type == 'MASK']

    def measuring(on):
        for m in masks:  # measure whole meshes; masks only affect what renders show
            m.show_viewport = not on
        bpy.context.view_layer.update()

    measuring(True)
    rest = {o.name: F.world_verts(o, evaluated=True)[0] for o in pieces}
    measuring(False)
    edges = {o.name: edges_of(o) for o in pieces}
    shown = [o for o in meshes if o.visible_get()]
    report = {}
    for i, name in enumerate(POSES):
        scene.frame_set(1 + 12 * i)
        measuring(True)
        bco, bpolys = F.world_verts(body, evaluated=True)
        bvh = F.bvh_of(bco, bpolys)
        report[name] = {}
        for o in pieces:
            now = F.world_verts(o, evaluated=True)[0]
            p99, mx = stretch(rest[o.name], now, edges[o.name])
            report[name][o.name.split('__')[-1]] = {'stretch_p99': p99, 'stretch_max': mx, 'sunk_in_body': sunk(now, bvh)}
        measuring(False)
        angles = range(0, 360, 45) if name == 'tpose' else (0, 90, 180, 270)
        for a in angles:
            F.render(qa / f'{name}_{a:03d}.png', shown, rotate=math.radians(a), res=(360, 480))
        if name == 'tpose':
            F.render(qa / 'tpose_below.png', shown, elev=math.radians(-40), res=(360, 480))
        print(f'[qa] {name}: ' + ', '.join(f"{k} p99 {v['stretch_p99']} max {v['stretch_max']} sunk {v['sunk_in_body']}"
                                          for k, v in report[name].items()), flush=True)
    (qa / 'qa.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print('[qa] DONE', qa, flush=True)


if __name__ == '__main__':
    main()
