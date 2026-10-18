"""Make an exported .glb smaller without changing what it renders (pure python + numpy, so it runs inside Blender too).

  morph targets   Blender writes every blend shape's NORMAL deltas densely: one row per vertex, although ~90% of the
                  rows are float noise below 1e-6 (the normal recomputed on unmoved skin). On Xander's body that was
                  8.8 of 10.7 MB. Rows whose largest normal delta is under NORMAL_EPS become 0 and the target is
                  stored as a standard glTF sparse accessor (only the rows that move). Shading changes by < 1e-5,
                  far below one 8-bit step (0.004). POSITION and TANGENT deltas keep every non-zero row exactly.
  images          byte-identical images (Genies reuses one emission or normal map on several face meshes) are
                  stored once and every texture points to that one, so the page downloads it once.

GLTFLoader reads sparse accessors natively, so the page needs no change. Run alone: python slim_glb.py <file.glb>...
"""
import json, struct, sys
from pathlib import Path
import numpy as np

NORMAL_EPS = 1e-5
EXACT = 0.0
COMP = {5120: np.int8, 5121: np.uint8, 5122: np.int16, 5123: np.uint16, 5125: np.uint32, 5126: np.float32}
NCOMP = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4, 'MAT2': 4, 'MAT3': 9, 'MAT4': 16}


def read_glb(b):
    assert b[:4] == b'glTF'
    jlen = struct.unpack('<I', b[12:16])[0]
    j = json.loads(b[20:20 + jlen])
    off = 20 + jlen
    binc = b[off + 8:off + 8 + struct.unpack('<I', b[off:off + 4])[0]] if off < len(b) else b''
    return j, binc


def write_glb(j, binc):
    jb = json.dumps(j, separators=(',', ':')).encode()
    jb += b' ' * (-len(jb) % 4)
    binc = bytes(binc) + b'\0' * (-len(binc) % 4)
    total = 12 + 8 + len(jb) + 8 + len(binc)
    return (struct.pack('<4sII', b'glTF', 2, total) + struct.pack('<I4s', len(jb), b'JSON') + jb
            + struct.pack('<I4s', len(binc), b'BIN\0') + binc)


def view_bytes(j, binc, vi):
    v = j['bufferViews'][vi]
    return binc[v.get('byteOffset', 0):v.get('byteOffset', 0) + v['byteLength']]


def dense(j, binc, ai):
    """The accessor's full array (sparse substitutions applied), shape (count, ncomp)."""
    a = j['accessors'][ai]
    dt, nc = COMP[a['componentType']], NCOMP[a['type']]
    if 'bufferView' in a:
        v = j['bufferViews'][a['bufferView']]
        assert not v.get('byteStride') or v['byteStride'] == nc * np.dtype(dt).itemsize, 'interleaved view'
        out = np.frombuffer(binc, dt, a['count'] * nc, v.get('byteOffset', 0) + a.get('byteOffset', 0)).reshape(-1, nc).copy()
    else:
        out = np.zeros((a['count'], nc), dt)
    sp = a.get('sparse')
    if sp:
        iv, vv = sp['indices'], sp['values']
        idx = np.frombuffer(view_bytes(j, binc, iv['bufferView']), COMP[iv['componentType']], sp['count'], iv.get('byteOffset', 0))
        val = np.frombuffer(view_bytes(j, binc, vv['bufferView']), dt, sp['count'] * nc, vv.get('byteOffset', 0)).reshape(-1, nc)
        out[idx] = val
    return out


def slim(b):
    j, binc = read_glb(b)
    views = j.get('bufferViews', [])
    pieces = []          # (key, bytes) for the rebuilt binary: ('view', old index) or ('new', bytes)
    new_views = []

    def add(data):
        new_views.append({'buffer': 0, 'byteLength': len(data)})
        pieces.append(data)
        return len(new_views) - 1

    # ---- morph targets -> sparse
    acc_eps = {}
    for me in j.get('meshes', []):
        for p in me['primitives']:
            for t in p.get('targets', []):
                for k, ai in t.items():
                    acc_eps[ai] = NORMAL_EPS if k == 'NORMAL' else EXACT
    replaced = {}
    for ai, eps in acc_eps.items():
        a = j['accessors'][ai]
        if a['componentType'] != 5126:
            continue
        d = dense(j, binc, ai)
        keep = np.abs(d).max(1) > eps
        n = int(keep.sum())
        idx_t, idx_np = (5123, np.uint16) if a['count'] < 65536 else (5125, np.uint32)
        sparse_size = n * (np.dtype(idx_np).itemsize + d.shape[1] * 4)
        if sparse_size >= d.nbytes:
            continue
        rows = np.nonzero(keep)[0]
        d[~keep] = 0
        replaced[ai] = (rows.astype(idx_np), d[keep].astype(np.float32), idx_t)
        if 'min' in a:      # spec: POSITION accessors carry bounds; recompute them for the values that remain
            a['min'] = d.min(0).tolist()
            a['max'] = d.max(0).tolist()

    # ---- identical images -> one
    img_hash, img_map = {}, {}
    for i, im in enumerate(j.get('images', [])):
        key = bytes(view_bytes(j, binc, im['bufferView'])) if 'bufferView' in im else im.get('uri')
        img_map[i] = img_hash.setdefault(key, i)
    for t in j.get('textures', []):
        if 'source' in t:
            t['source'] = img_map[t['source']]
    kept_imgs = sorted(set(img_map.values()))
    if len(kept_imgs) < len(j.get('images', [])):
        renum = {old: new for new, old in enumerate(kept_imgs)}
        j['images'] = [j['images'][i] for i in kept_imgs]
        for t in j.get('textures', []):
            if 'source' in t:
                t['source'] = renum[t['source']]

    # ---- rebuild the binary from the views still in use
    used = set()
    for ai, a in enumerate(j.get('accessors', [])):
        if ai in replaced:
            continue
        if 'bufferView' in a:
            used.add(a['bufferView'])
        if 'sparse' in a:
            used |= {a['sparse']['indices']['bufferView'], a['sparse']['values']['bufferView']}
    used |= {im['bufferView'] for im in j.get('images', []) if 'bufferView' in im}
    remap = {}
    for vi in sorted(used):
        v = dict(views[vi])
        nv = add(bytes(view_bytes(j, binc, vi)))
        for k in ('byteStride', 'target'):
            if k in v:
                new_views[nv][k] = v[k]
        remap[vi] = nv
    for ai, a in enumerate(j.get('accessors', [])):
        if ai in replaced:
            rows, vals, idx_t = replaced[ai]
            a.pop('bufferView', None)
            a.pop('byteOffset', None)
            a['sparse'] = {'count': len(rows), 'indices': {'bufferView': add(rows.tobytes()), 'componentType': idx_t},
                           'values': {'bufferView': add(vals.tobytes())}}
            continue
        if 'bufferView' in a:
            a['bufferView'] = remap[a['bufferView']]
        if 'sparse' in a:
            a['sparse']['indices']['bufferView'] = remap[a['sparse']['indices']['bufferView']]
            a['sparse']['values']['bufferView'] = remap[a['sparse']['values']['bufferView']]
    for im in j.get('images', []):
        if 'bufferView' in im:
            im['bufferView'] = remap[im['bufferView']]
    out = bytearray()
    for v, data in zip(new_views, pieces):
        out += b'\0' * (-len(out) % 4)
        v['byteOffset'] = len(out)
        out += data
    j['bufferViews'] = new_views
    j['buffers'] = [{'byteLength': len(out)}]
    return write_glb(j, out)


def slim_file(path):
    path = Path(path)
    before = path.stat().st_size
    path.write_bytes(slim(path.read_bytes()))
    print(f'[slim] {path.name}: {before / 1e6:.2f} -> {path.stat().st_size / 1e6:.2f} MB', flush=True)


if __name__ == '__main__':
    for f in sys.argv[1:]:
        slim_file(f)
