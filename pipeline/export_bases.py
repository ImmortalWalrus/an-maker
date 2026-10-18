"""Export the unclothed Genies avatars as .blend + .glb fitting bases with a landmark JSON.
Run: blender -b --factory-startup -P pipeline/export_bases.py -- Clementine Xander
"""
import bpy, sys, json
from pathlib import Path
from mathutils import Vector

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / 'Unclothed-staging'
OUT = ROOT / 'Bases'
LANDMARK_BONES = ['Hips', 'Spine', 'Spine2', 'Neck', 'Head', 'LeftShoulder', 'LeftArm', 'LeftForeArm', 'LeftHand',
                  'RightShoulder', 'RightArm', 'RightForeArm', 'RightHand', 'LeftUpLeg', 'LeftLeg', 'LeftFoot',
                  'LeftToeBase', 'RightUpLeg', 'RightLeg', 'RightFoot', 'RightToeBase']

avatars = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else ['Clementine', 'Xander']
for avatar in avatars:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.fbx(filepath=str(SRC / f'{avatar}.fbx'))
    arm = next(o for o in bpy.context.scene.objects if o.type == 'ARMATURE')
    meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']
    body = max(meshes, key=lambda o: len(o.data.vertices))
    corners = [o.matrix_world @ Vector(c) for o in meshes for c in o.bound_box]
    landmarks = {b: list(arm.matrix_world @ arm.data.bones[b].head_local) for b in LANDMARK_BONES if b in arm.data.bones}
    info = {
        'avatar': avatar,
        'body_mesh': body.name,
        'height': max(c.z for c in corners) - min(c.z for c in corners),
        'bounds_min': [min(c[i] for c in corners) for i in range(3)],
        'bounds_max': [max(c[i] for c in corners) for i in range(3)],
        'landmarks': landmarks,
    }
    (OUT / f'{avatar}.json').write_text(json.dumps(info, indent=2), encoding='utf-8')
    bpy.ops.wm.save_as_mainfile(filepath=str(OUT / f'{avatar}.blend'))
    bpy.ops.export_scene.gltf(filepath=str(OUT / f'{avatar}.glb'), export_format='GLB', export_morph=False, export_animations=False)
    print('BASE', avatar, round(info['height'], 3), body.name, flush=True)
