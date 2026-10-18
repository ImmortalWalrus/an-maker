"""Split .glb files for hosts that only serve JSON, text and images (and block data: URLs): textures become separate
image files, the glTF JSON goes to <name>.gltf.json (its buffer has no uri) and the remaining binary (geometry,
skin, morph targets) to <name>.bin.txt as base64. The page rebuilds the .glb in memory (header + JSON chunk + BIN
chunk) and hands it to GLTFLoader.parse - lossless, the same model stored differently.

Images: a PNG is stored as lossless WebP when that is smaller (about half) and decodes to the very same pixels
(checked here, RGB under transparent pixels included), else it stays PNG. JPEGs are copied as they are.

Phones: every piece whose textures are larger than LITE_PX also gets <name>.lite.gltf.json, the same model whose
images are copies downscaled to LITE_PX (<name>_img<i>_lite.*; the geometry file is shared). The manifest lists it
as the piece's "liteFile"; the page uses it on touch devices only, so desktop keeps the full-size textures.

Run: python pipeline/web/glb_to_gltf.py <dir with .glb files>
"""
import base64, io, json, re, struct, sys
from pathlib import Path
import numpy as np
from PIL import Image

LITE_PX = 1024   # phone texture cap (long side)


def web_image(data, ext):
    """(bytes, ext) to write for an image: a PNG becomes lossless WebP when smaller and pixel-identical."""
    if ext != '.png':
        return data, ext
    im = Image.open(io.BytesIO(data))
    buf = io.BytesIO()
    im.save(buf, 'WEBP', lossless=True, quality=100, method=5, exact=True)   # exact: keep RGB under alpha 0
    if buf.tell() >= len(data):
        return data, ext
    a = np.asarray(im.convert('RGBA'))
    b = np.asarray(Image.open(io.BytesIO(buf.getvalue())).convert('RGBA'))
    if a.shape != b.shape or (a != b).any():
        print(f'  lossless WebP decoded differently: kept PNG', flush=True)
        return data, ext
    return buf.getvalue(), '.webp'


def lite_image(data, ext):
    """A copy for phones with the long side at LITE_PX, or None when the image is already that small."""
    im = Image.open(io.BytesIO(data))
    w, h = im.size
    if max(w, h) <= LITE_PX:
        return None
    k = LITE_PX / max(w, h)
    im = im.resize((max(1, round(w * k)), max(1, round(h * k))), Image.LANCZOS)
    buf = io.BytesIO()
    if ext == '.jpg':
        im.save(buf, 'JPEG', quality=90)
    else:
        im.save(buf, 'WEBP', lossless=True, quality=100, method=5, exact=True)
        ext = '.webp'
    return buf.getvalue(), ext


def convert(glb: Path, lite=False):
    b = glb.read_bytes()
    assert b[:4] == b'glTF'
    jlen = struct.unpack('<I', b[12:16])[0]
    j = json.loads(b[20:20 + jlen])
    off = 20 + jlen
    blen = struct.unpack('<I', b[off:off + 4])[0]
    binc = b[off + 8:off + 8 + blen]
    views = j.get('bufferViews', [])
    # images from an earlier conversion (another format or count) must not linger and get published
    old = re.compile(re.escape(glb.stem) + r'_img\d+(_lite)?\.(png|jpg|webp)$')
    for f in glb.parent.glob(f'{glb.stem}_img*'):
        if old.match(f.name):
            f.unlink()
    image_views, lite_uris = set(), {}
    for i, im in enumerate(j.get('images', [])):
        if 'bufferView' not in im:
            continue
        v = views[im['bufferView']]
        data = binc[v.get('byteOffset', 0):v.get('byteOffset', 0) + v['byteLength']]
        data, ext = web_image(data, '.png' if im.get('mimeType') == 'image/png' else '.jpg')
        name = f'{glb.stem}_img{i}{ext}'
        (glb.parent / name).write_bytes(data)
        image_views.add(im.pop('bufferView'))
        im.pop('mimeType', None)
        im['uri'] = name
        small = lite and lite_image(data, ext)
        if small:
            lite_uris[i] = f'{glb.stem}_img{i}_lite{small[1]}'
            (glb.parent / lite_uris[i]).write_bytes(small[0])
    # compact the binary: keep every bufferView except the images, re-aligned to 4 bytes
    new_bin, remap, new_views = bytearray(), {}, []
    for i, v in enumerate(views):
        if i in image_views:
            continue
        while len(new_bin) % 4:
            new_bin.append(0)
        start = v.get('byteOffset', 0)
        new_bin += binc[start:start + v['byteLength']]
        nv = dict(v)
        nv['byteOffset'] = len(new_bin) - v['byteLength']
        remap[i] = len(new_views)
        new_views.append(nv)
    j['bufferViews'] = new_views
    for a in j.get('accessors', []):
        if 'bufferView' in a:
            a['bufferView'] = remap[a['bufferView']]
        sp = a.get('sparse')
        if sp:
            sp['indices']['bufferView'] = remap[sp['indices']['bufferView']]
            sp['values']['bufferView'] = remap[sp['values']['bufferView']]
    j['buffers'] = [{'byteLength': len(new_bin)}]
    out = glb.parent / f'{glb.stem}.gltf.json'
    out.write_text(json.dumps(j, separators=(',', ':')), encoding='utf-8')
    lite_out = glb.parent / f'{glb.stem}.lite.gltf.json'
    lite_out.unlink(missing_ok=True)
    if lite_uris:
        for i, uri in lite_uris.items():
            j['images'][i]['uri'] = uri
        lite_out.write_text(json.dumps(j, separators=(',', ':')), encoding='utf-8')
    binf = glb.parent / f'{glb.stem}.bin.txt'
    binf.write_text(base64.b64encode(bytes(new_bin)).decode(), encoding='ascii')
    print(f'{glb.name}: {out.name} + {binf.name} {binf.stat().st_size / 1e6:.1f} MB + '
          f'{len(j.get("images", []))} images' + (f' ({len(lite_uris)} with a phone copy)' if lite_uris else ''), flush=True)
    return out.name, binf.name, (lite_out.name if lite_uris else None)


if __name__ == '__main__':
    d = Path(sys.argv[1])
    man = d / 'manifest.json'
    m = json.loads(man.read_text()) if man.exists() else None
    as_glb = lambda f: f.replace('.gltf.json', '.glb')  # a manifest already converted once
    body = m.get('bodyGlb', as_glb(m['body'])) if m else None
    names = {g.name: convert(g, lite=g.name != body) for g in sorted(d.glob('*.glb'))}
    if m:
        m['bodyGlb'] = body
        m['body'], m['bodyBin'], _ = names[body]
        for p in m['pieces']:
            p['glb'] = p.get('glb', as_glb(p['file']))
            p['file'], p['bin'], lite = names[p['glb']]
            p.pop('liteFile', None)
            if lite:
                p['liteFile'] = lite
        man.write_text(json.dumps(m, indent=1))
        print('manifest updated', flush=True)
