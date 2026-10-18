"""Write a small static body GLB for AssetHub's base-body input (no rig, textures downscaled).
Run: blender -b --factory-startup -P pipeline/export_upload_body.py -- Xander [max_tex_px]
"""
import bpy, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
args = sys.argv[sys.argv.index('--') + 1:]
avatar, max_px = args[0], int(args[1]) if len(args) > 1 else 512
bpy.ops.wm.open_mainfile(filepath=str(ROOT / 'Bases' / f'{avatar}.blend'))
for obj in [o for o in bpy.data.objects if o.type == 'MESH']:
    for mod in list(obj.modifiers):
        if mod.type == 'ARMATURE':
            obj.modifiers.remove(mod)
    if obj.data.shape_keys:
        obj.shape_key_clear()
for obj in [o for o in bpy.data.objects if o.type != 'MESH']:
    bpy.data.objects.remove(obj, do_unlink=True)
for image in bpy.data.images:
    if image.size[0] > max_px:
        image.scale(max_px, max(1, int(image.size[1] * max_px / image.size[0])))
out = ROOT / 'Bases' / f'{avatar}-upload.glb'
bpy.ops.export_scene.gltf(filepath=str(out), export_format='GLB', export_image_format='JPEG',
                          export_jpeg_quality=80, export_morph=False, export_skins=False, export_animations=False)
print('UPLOAD_BODY', out, out.stat().st_size, flush=True)
