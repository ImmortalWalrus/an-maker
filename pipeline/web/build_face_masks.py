"""Exact masks for the customizer's lip and nose pictures (no guessing, no pixels).

  lips   Genies' own lip line: the lipstick shape painted in Clementine's face texture, which sits exactly on the lips
         of the shared UV layout. Baked as a signed distance field (4x the texture's resolution, inside > 0), so the
         shader cuts a sharp, anti-aliased edge at any zoom.
  nose   the part of the face that stands out more than NOSE_MM from the surface around it (Gaussian-weighted mean of
         the skin within NOSE_R, along its mean normal), grown from the nose tip across the mesh. Stored per vertex as
         that height minus NOSE_MM, so the edge is the exact zero line of a field that lives on the geometry.

Writes <out>/face_masks.json and <out>/lip_sdf.png.
Run: python pipeline/web/build_face_masks.py --out web/customizer/assets
"""
import argparse, base64, json, struct
from pathlib import Path
import numpy as np
from PIL import Image
from scipy import ndimage
from scipy.spatial import cKDTree

ROOT = Path(__file__).resolve().parents[2]
PACK = ROOT / 'GeniesStarterPack-main' / 'Assets' / 'Project' / '3D'
NOSE_MM, NOSE_R = 2.0, 0.02
LIP_UV = (0.2123, 0.9172)        # middle of the lips in the shared UV layout
LIP_WIN = (0.075, 0.055)         # half-size of the window baked around them (UV)
SDF_UP, SDF_RANGE = 8, 48        # supersampling, and distance range stored (in supersampled pixels)
LIP_SMOOTH = 1.6                 # texels
CT = {5126: np.float32, 5123: np.uint16, 5125: np.uint32}
NC = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3}


def read_web_body(out):
    man = json.loads((out / 'manifest.json').read_text(encoding='utf-8'))
    g = json.loads((out / man['body']).read_text(encoding='utf-8'))
    b = base64.b64decode((out / man['bodyBin']).read_text().strip())
    node = next(n for n in g['nodes'] if n.get('name') == 'Submesh_0')
    p = g['meshes'][node['mesh']]['primitives'][0]
    def acc(i):
        a = g['accessors'][i]; v = g['bufferViews'][a['bufferView']]; k = NC[a['type']]; dt = CT[a['componentType']]
        size = np.dtype(dt).itemsize * k; st = v.get('byteStride', size); o = v.get('byteOffset', 0) + a.get('byteOffset', 0)
        raw = np.frombuffer(b, np.uint8, count=st * (a['count'] - 1) + size, offset=o)
        return np.lib.stride_tricks.as_strided(raw, (a['count'], size), (st, 1)).copy().view(dt).reshape(a['count'], k).astype(np.float64)
    return acc(p['attributes']['POSITION']), acc(p['indices']).astype(int).reshape(-1, 3)


def lip_sdf(out):
    im = np.asarray(Image.open(PACK / 'Clementine' / 'Textures' / 'Submesh_0_Albedo.png').convert('RGB')).astype(np.float64) / 255
    h, w, _ = im.shape
    u0, v0 = LIP_UV[0] - LIP_WIN[0], LIP_UV[1] - LIP_WIN[1]
    u1, v1 = LIP_UV[0] + LIP_WIN[0], LIP_UV[1] + LIP_WIN[1]
    x0, x1, y0, y1 = int(u0 * w), int(np.ceil(u1 * w)), int(v0 * h), int(np.ceil(v1 * h))   # texture rows run with v
    crop = im[y0:y1, x0:x1]
    # the lipstick is one flat color; the lip line is halfway between it and the skin just around it
    ci, cj = (LIP_UV[1] * h - y0), (LIP_UV[0] * w - x0)
    lip = crop[int(ci) - 2:int(ci) + 3, int(cj) - 2:int(cj) + 3].reshape(-1, 3).mean(0)
    dist = np.linalg.norm(crop - lip, axis=-1)
    ring = dist[(dist > np.percentile(dist, 60))]
    half = 0.5 * np.median(ring)
    # the painted edge steps from texel to texel and carries brush noise; smoothing the field first turns the lip line
    # into one clean curve (it moves the line by well under a texel), then it is traced at sub-texel precision
    field = ndimage.gaussian_filter(half - dist, LIP_SMOOTH)
    up = ndimage.zoom(field, SDF_UP, order=3)                # inside > 0
    lab, nlab = ndimage.label(up > 0)
    keep = lab == (1 + np.argmax(ndimage.sum(np.ones_like(up), lab, range(1, nlab + 1))))   # the lips, nothing else
    keep = ndimage.binary_fill_holes(keep)
    d = ndimage.distance_transform_edt(keep) - ndimage.distance_transform_edt(~keep)
    d = ndimage.gaussian_filter(d, SDF_UP * 0.5)
    enc = np.clip(d / SDF_RANGE * 127.5 + 127.5, 0, 255).astype(np.uint8)
    Image.fromarray(enc).save(out / 'lip_sdf.png')
    ys, xs = np.nonzero(keep)
    print(f'[masks] lips: {keep.sum() / SDF_UP ** 2:.0f} texels, {np.ptp(xs) / SDF_UP:.0f} x {np.ptp(ys) / SDF_UP:.0f} texels', flush=True)
    return {'uv': [x0 / w, y0 / h, x1 / w, y1 / h], 'range': SDF_RANGE}


def nose_field(P, F):
    key = np.round(P / 1e-5).astype(np.int64)
    _, weld, inv = np.unique(key, axis=0, return_index=True, return_inverse=True)
    inv = inv.ravel(); W = P[weld]; Fw = inv[F]; m = len(W)
    nb = [set() for _ in range(m)]
    for a, b, c in Fw:
        nb[a] |= {b, c}; nb[b] |= {a, c}; nb[c] |= {a, b}
    N = np.zeros_like(W)
    fn = np.cross(W[Fw[:, 1]] - W[Fw[:, 0]], W[Fw[:, 2]] - W[Fw[:, 0]])
    for k in range(3):
        np.add.at(N, Fw[:, k], fn)
    N /= np.maximum(np.linalg.norm(N, axis=1, keepdims=True), 1e-12)
    head = W[:, 1] > W[:, 1].max() - 0.24
    tree = cKDTree(W); h = np.full(m, -1.0)
    for i in np.nonzero(head)[0]:
        js = tree.query_ball_point(W[i], NOSE_R)
        wgt = np.exp(-np.sum((W[js] - W[i]) ** 2, 1) / (2 * (NOSE_R / 2) ** 2))
        mu = (W[js] * wgt[:, None]).sum(0) / wgt.sum()
        nm = (N[js] * wgt[:, None]).sum(0); nm /= np.linalg.norm(nm)
        h[i] = (W[i] - mu) @ nm
    near = np.nonzero(head & (np.abs(W[:, 0]) < 0.01))[0]
    eyes_y = W[head, 1].max() - 0.15                              # stay below the brow ridge
    near = near[W[near, 1] < eyes_y]
    tip = near[np.argmax(W[near, 2])]
    t = NOSE_MM / 1000
    inside = np.zeros(m, bool); inside[tip] = True; stack = [tip]
    while stack:
        i = stack.pop()
        for j in nb[i]:
            if not inside[j] and h[j] > t:
                inside[j] = True; stack.append(j)
    # the edge is the zero line between the region and its direct neighbours; everything further out is firmly outside
    edge = np.zeros(m, bool)
    for i in np.nonzero(inside)[0]:
        edge[list(nb[i])] = True
    edge &= ~inside
    f = np.full(m, -0.01)
    f[inside] = h[inside] - t
    f[edge] = np.minimum(h[edge] - t, 0.0)
    f = np.clip(f, -0.01, 0.01)
    print(f'[masks] nose: {inside.sum()} vertices, {np.ptp(W[inside, 0]) * 100:.1f} cm wide, '
          f'{np.ptp(W[inside, 1]) * 100:.1f} cm tall, tip stands out {h[tip] * 1000:.1f} mm', flush=True)
    return f[inv]


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--out', required=True)
    out = Path(ap.parse_args().out).resolve()
    P, F = read_web_body(out)
    doc = {'lips': lip_sdf(out), 'nose': base64.b64encode(nose_field(P, F).astype(np.float32).tobytes()).decode(),
           'noseMM': NOSE_MM}
    (out / 'face_masks.json').write_text(json.dumps(doc), encoding='utf-8')
    print(f'[masks] wrote {out / "face_masks.json"}', flush=True)


if __name__ == '__main__':
    main()
