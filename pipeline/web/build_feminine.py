"""Build the Feminine body type for the customizer from the Genies Starter Pack's Clementine.

Clementine is Xander's avatar with different settings: the same skeleton (1.6 cm lower), the same meshes and UV layout,
her body = Xander + his 'bodyOnly_geo_blendShape.female' blend shape at full strength (checked here, vertex by vertex,
against the shape baked into the pack's Clementine.gltf), the same face geometry, and her own skin, eye and brow
textures (from Bases/Clementine.glb, her FBX). So the customizer needs no new geometry: Feminine sets that blend shape
to 1 (garments already follow it, followBodyShape) and swaps in her textures. Her skeleton's 1.6 cm drop is left out,
so she stands where he does (she is his height).

Writes <out>/feminine.json (the blend-shape weights and texture files) + feminine_*.png.

Run: python pipeline/web/build_feminine.py --out web/customizer/assets
"""
import argparse, base64, hashlib, json, struct, sys
from pathlib import Path
import numpy as np
from scipy.spatial import cKDTree
from glb_to_gltf import web_image

ROOT = Path(__file__).resolve().parents[2]
PACK = ROOT / 'GeniesStarterPack-main' / 'Assets' / 'Project' / '3D'
CT = {5126: np.float32, 5123: np.uint16, 5125: np.uint32, 5121: np.uint8}
NC = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4}


def read_glb(p):
    b = Path(p).read_bytes()
    n = struct.unpack('<I', b[12:16])[0]
    off = 20 + n
    return json.loads(b[20:off]), b[off + 8:off + 8 + struct.unpack('<I', b[off:off + 4])[0]]


def read_gltf(p, bin_path=None):
    g = json.loads(Path(p).read_text(encoding='utf-8'))
    raw = Path(bin_path or Path(p).parent / g['buffers'][0]['uri']).read_bytes()
    if str(bin_path).endswith('.txt'):
        raw = base64.b64decode(raw.strip())
    return g, raw


def acc(g, b, i):
    a = g['accessors'][i]
    n, k, dt = a['count'], NC[a['type']], CT[a['componentType']]
    size = np.dtype(dt).itemsize * k
    v = g['bufferViews'][a['bufferView']]
    o = v.get('byteOffset', 0) + a.get('byteOffset', 0)
    st = v.get('byteStride', size)
    raw = np.frombuffer(b, np.uint8, count=st * (n - 1) + size, offset=o)
    return np.lib.stride_tricks.as_strided(raw, (n, size), (st, 1)).copy().view(dt).reshape(n, k).astype(np.float64)


def meshes(g, b):
    out = {}
    for n in g['nodes']:
        if 'mesh' in n:
            p = g['meshes'][n['mesh']]['primitives'][0]
            out[n['name']] = dict(pos=acc(g, b, p['attributes']['POSITION']), uv=acc(g, b, p['attributes']['TEXCOORD_0']))
    return out


def images(g, b):
    out = {}
    for im in g.get('images', []):
        v = g['bufferViews'][im['bufferView']]
        out[im['name']] = (b[v.get('byteOffset', 0):v.get('byteOffset', 0) + v['byteLength']], im.get('mimeType', 'image/png'))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    out = Path(a.out).resolve()
    man = json.loads((out / 'manifest.json').read_text(encoding='utf-8'))
    web = meshes(*read_gltf(out / man['body'], out / man['bodyBin']))
    clem = meshes(*read_gltf(PACK / 'Clementine' / 'Clementine.gltf'))
    X = web['Submesh_0']['pos']

    # 1. body: her baked shape, matched vertex by vertex
    # every vertex has an exact UV twin; seams share a UV between a few vertices, so the nearest of those wins
    c = clem['Submesh_0']
    du, ju = cKDTree(c['uv']).query(web['Submesh_0']['uv'], k=4)
    assert du[:, 0].max() < 1e-5, 'Clementine and Xander no longer share a UV layout'
    j = np.array([cand[np.argmin(np.linalg.norm(c['pos'][cand] - X[i], axis=1))]
                  for i, cand in enumerate(ju[r][du[r] < du[r, 0] + 1e-5] for r in range(len(X)))])
    d = np.linalg.norm(c['pos'][j] - X, axis=1)
    D = c['pos'][j] - X
    feet = X[:, 1] < 0.08
    drop = np.array([0, np.median(D[feet, 1]), 0])
    D -= drop
    print(f'[fem] body: matched {len(X)} vertices (worst match {d.max() * 1000:.1f} mm), dropped {drop[1] * 1000:.1f} mm, '
          f'shape up to {np.linalg.norm(D, axis=1).max() * 1000:.1f} mm', flush=True)

    # 2. her body is Xander's female blend shape at full strength, and nothing else moves
    gw, bw = read_gltf(out / man['body'], out / man['bodyBin'])
    node = next(n for n in gw['nodes'] if n.get('name') == 'Submesh_0')
    mdef = gw['meshes'][node['mesh']]
    names = mdef['extras']['targetNames']
    tgt = mdef['primitives'][0]['targets']
    F = np.zeros_like(X)
    a0 = gw['accessors'][tgt[names.index('bodyOnly_geo_blendShape.female')]['POSITION']]
    if 'sparse' in a0:                                # sparse target: zeros + the listed vertices
        sp = a0['sparse']
        iv, vv = gw['bufferViews'][sp['indices']['bufferView']], gw['bufferViews'][sp['values']['bufferView']]
        idx = np.frombuffer(bw, CT[sp['indices']['componentType']], sp['count'], iv.get('byteOffset', 0) + sp['indices'].get('byteOffset', 0)).astype(int)
        F[idx] = np.frombuffer(bw, np.float32, sp['count'] * 3, vv.get('byteOffset', 0) + sp['values'].get('byteOffset', 0)).reshape(-1, 3)
    if 'bufferView' in a0:
        F += acc(gw, bw, tgt[names.index('bodyOnly_geo_blendShape.female')]['POSITION'])
    w = float((F * D).sum() / (F * F).sum())
    left = np.linalg.norm(D - w * F, axis=1)
    print(f'[fem] Clementine = Xander + female body shape x{w:.3f}; left over max {left.max() * 1000:.1f} mm, mean {left.mean() * 1000:.2f} mm', flush=True)
    assert abs(w - 1) < 0.02 and left.max() < 0.005, 'Clementine is no longer Xander + the female body shape'
    for name in ['Submesh_1', 'Submesh_2', 'Submesh_3', 'Submesh_4']:
        if name in clem and len(clem[name]['pos']) == len(web[name]['pos']):
            mv = np.abs(np.sort(clem[name]['pos'] - drop, 0) - np.sort(web[name]['pos'], 0)).max()
            print(f'[fem] {name}: same as Xander within {mv * 1000:.1f} mm', flush=True)

    # 3. textures that differ from Xander's (both from the FBX bases)
    ix, ic = images(*read_glb(ROOT / 'Bases' / 'Xander.glb')), images(*read_glb(ROOT / 'Bases' / 'Clementine.glb'))
    tex = {}
    for name, (data, mime) in ic.items():
        if name in ix and hashlib.md5(ix[name][0]).digest() == hashlib.md5(data).digest():
            continue
        mesh, slot = name.rsplit('_', 1)                # Submesh_0_Albedo -> (Submesh_0, Albedo)
        data, ext = web_image(data, '.png' if 'png' in mime else '.jpg')   # PNG -> lossless WebP, same pixels
        file = f'feminine_{name}{ext}'
        for old in out.glob(f'feminine_{name}.*'):
            old.unlink()
        (out / file).write_bytes(data)
        tex.setdefault(mesh, {})[{'Albedo': 'map', 'Emission': 'emissiveMap', 'Normal': 'normalMap'}[slot]] = file
        print(f'[fem] texture {name} -> {file}', flush=True)

    doc = {'name': 'Clementine', 'from': 'GeniesStarterPack Clementine.gltf (shape check) + Bases/Clementine.glb (textures)',
           'morphs': {'bodyOnly_geo_blendShape.female': 1}, 'textures': tex}
    (out / 'feminine.json').write_text(json.dumps(doc, indent=1), encoding='utf-8')
    print(f'[fem] wrote {out / "feminine.json"}', flush=True)


if __name__ == '__main__':
    sys.exit(main())
