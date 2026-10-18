"""Re-rest a Genies base avatar in the wardrobe's canonical A-pose (slots.json "bind_pose").
Every mesh is baked into the pose, all shape keys included, and the armature's rest pose becomes that pose,
so wardrobe pieces generated in an A-pose bind without being bent back into a T-pose.

Run: blender -b --factory-startup -P pipeline/export_apose_bases.py -- Clementine Xander
Writes Bases/<avatar>_Apose.blend / .fbx / .glb
"""
import bpy, sys, json, math
from pathlib import Path
from mathutils import Matrix

ROOT = Path(__file__).resolve().parent.parent
POSE = json.loads((ROOT / 'pipeline' / 'slots.json').read_text(encoding='utf-8'))['bind_pose']


def rotate_bone_world(arm, bone_name, axis, angle):
    pb = arm.pose.bones[bone_name]
    A = arm.matrix_world
    head_w = A @ pb.head
    T = Matrix.Translation(head_w) @ Matrix.Rotation(angle, 4, axis) @ Matrix.Translation(-head_w)
    pb.matrix = A.inverted() @ T @ A @ pb.matrix
    bpy.context.view_layer.update()


def bake_pose(obj):
    """Replace mesh + shape keys with their posed versions and drop the armature modifier."""
    dg = bpy.context.evaluated_depsgraph_get()
    keys = obj.data.shape_keys.key_blocks if obj.data.shape_keys else []
    saved = [(k.value, k.mute) for k in keys]
    for k in keys:
        k.value = 0.0
    if keys:
        obj.show_only_shape_key = False
    posed = {}
    for i, k in enumerate(keys):
        if i == 0:
            continue
        k.value = 1.0
        bpy.context.view_layer.update()
        ev = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
        posed[k.name] = [v.co.copy() for v in ev.to_mesh().vertices]
        ev.to_mesh_clear()
        k.value = 0.0
    bpy.context.view_layer.update()
    ev = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    basis = [v.co.copy() for v in ev.to_mesh().vertices]
    ev.to_mesh_clear()
    for mod in [m for m in obj.modifiers if m.type == 'ARMATURE']:
        obj.modifiers.remove(mod)
    for i, k in enumerate(keys):
        target = basis if i == 0 else posed[k.name]
        for p, co in zip(k.data, target):
            p.co = co
        k.value, k.mute = saved[i]
    for v, co in zip(obj.data.vertices, basis):
        v.co = co
    obj.data.update()


for avatar in sys.argv[sys.argv.index('--') + 1:]:
    bpy.ops.wm.open_mainfile(filepath=str(ROOT / 'Bases' / f'{avatar}.blend'))
    arm = next(o for o in bpy.data.objects if o.type == 'ARMATURE')
    meshes = [o for o in bpy.data.objects if o.type == 'MESH']
    rotate_bone_world(arm, 'LeftArm', 'Y', math.radians(POSE['arm_deg']))
    rotate_bone_world(arm, 'RightArm', 'Y', -math.radians(POSE['arm_deg']))
    rotate_bone_world(arm, 'LeftUpLeg', 'Y', -math.radians(POSE['leg_deg']))
    rotate_bone_world(arm, 'RightUpLeg', 'Y', math.radians(POSE['leg_deg']))
    for m in meshes:
        bake_pose(m)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode='POSE')
    bpy.ops.pose.select_all(action='SELECT')
    bpy.ops.pose.armature_apply(selected=False)
    bpy.ops.object.mode_set(mode='OBJECT')
    for m in meshes:
        mod = m.modifiers.new('Armature', 'ARMATURE')
        mod.object = arm
    out = ROOT / 'Bases' / f'{avatar}_Apose'
    bpy.ops.wm.save_as_mainfile(filepath=str(out.with_suffix('.blend')))
    bpy.ops.export_scene.fbx(filepath=str(out.with_suffix('.fbx')), object_types={'ARMATURE', 'MESH'},
                             add_leaf_bones=False, bake_anim=False, path_mode='COPY', embed_textures=True)
    bpy.ops.export_scene.gltf(filepath=str(out.with_suffix('.glb')), export_format='GLB', export_animations=False)
    print('APOSE', avatar, POSE, flush=True)
