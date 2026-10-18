"""Redraw the makeup Genies painted into the Starter Pack face textures as clean layers with real transparency.

Nothing is "skin subtracted" any more. Each element is selected the way a magic wand would: its own colour, inside
the part of the face it belongs to. Then it is rebuilt:

  shape   liner, shadow, gems, stickers: a clean anti-aliased edge (supersampled and smoothed, so no texel steps),
          coloured from its own inside, carried out to the edge so no skin colour fringes it on other skin tones
  soft    blush and glows: a smooth gradient of how strongly that colour is painted, with freckles and specks left out
  lips    the exact lip outline (the same lip line as the customizer's lip mask), coloured from the painted lips

Every layer is plain colour plus alpha, so it sits the same on any skin tone and either body.
Writes <out>/makeup.json and <out>/makeup_<look>.png (RGBA, the face window at 2x the texture's resolution).
Run: python pipeline/web/build_makeup.py --out web/customizer/assets
"""
import argparse, json
from pathlib import Path
import numpy as np
from PIL import Image
from scipy import ndimage

ROOT = Path(__file__).resolve().parents[2]
PACK = ROOT / 'GeniesStarterPack-main' / 'Assets' / 'Project' / '3D'
WIN = (0.03, 0.66, 0.40, 1.0)          # u0, v0, u1, v1: the face (texture rows run with v)
LIP_U = 0.2123                         # the face's middle line, in U
UP = 2                                 # output resolution, x the texture's

# areas of the face, in UV (u0, v0, u1, v1)
EYES = (0.04, 0.808, 0.39, 0.865)   # below the brows
CHEEKS = (0.06, 0.83, 0.37, 0.905)
NOSE = (0.16, 0.842, 0.265, 0.897)
STICKER_AT = (0.2123, 0.862)            # the middle of Sticker's nose bandage (UV)
EYES_TIGHT = (0.04, 0.815, 0.39, 0.86)   # just around the eye openings

# Each element: (kind, key colour sRGB, tolerance, area). The key colours are the flat paint colours in the textures.
LOOKS = {
    'clementine': {'label': 'Winged', 'from': 'Clementine', 'lips': None, 'elements': [
        ('blush', (0.70, 0.36, 0.30), 0.16, CHEEKS),     # blush
        ('soft-shape', (0.56, 0.52, 0.52), 0.11, EYES),  # silver shadow: crisp outside, soft inside
        ('shape', (0.213, 0.199, 0.233), 0.075, EYES),   # navy winged liner
    ]},
    'alex': {'label': 'Gems', 'from': 'Alex', 'lips': ((0.467, 0.18, 0.196), 0.09), 'elements': [
        ('soft', (0.83, 0.72, 0.77), 0.14, EYES),        # pale glow under the eyes
        ('shape', (0.609, 0.384, 0.402), 0.075, EYES_TIGHT),   # mauve liner ring
        ('dots', (0.985, 0.407, 0.402), 0.22, EYES),     # red gems
        ('dots', (0.977, 0.972, 0.972), 0.16, EYES),     # white gems
    ]},
    'sticker': {'label': 'Sweet', 'from': 'Sticker', 'lips': ((0.62, 0.294, 0.333), 0.075), 'elements': [
        ('blush', (0.92, 0.60, 0.66), 0.13, CHEEKS),     # blush
        ('soft', (0.93, 0.84, 0.88), 0.07, EYES),        # white glow
        ('shape', (0.663, 0.389, 0.436), 0.07, EYES),    # mauve winged shadow
        ('shape', (0.831, 0.677, 0.80), 0.06, EYES),     # lavender lid
        ('decal', None, None, NOSE),                     # the heart bandage sticker
    ]},
}


def win_px(w, h):
    return int(WIN[0] * w), int(WIN[1] * h), int(WIN[2] * w), int(WIN[3] * h)


def area_mask(shape, w, h, area):
    x0, y0, _, _ = win_px(w, h)
    m = np.zeros(shape, bool)
    a0, b0 = int(area[0] * w) - x0, int(area[1] * h) - y0
    a1, b1 = int(area[2] * w) - x0, int(area[3] * h) - y0
    m[max(0, b0):max(0, b1), max(0, a0):max(0, a1)] = True
    return ndimage.gaussian_filter(m.astype(float), 6) > 0.5


def up(a, order=1):
    return ndimage.zoom(a, UP, order=order)


def clean_edge(mask, sigma=0.9):
    """A binary shape -> a smooth anti-aliased alpha at UP x: blur, supersample, then a one-pixel ramp at the 0.5 line."""
    f = up(ndimage.gaussian_filter(mask.astype(float), sigma), 3)
    return np.clip((f - 0.5) * 2.2 + 0.5, 0, 1)


def defringe(col, inside):
    """Colour each texel from the nearest texel well inside the shape, so edges carry no skin colour."""
    if not inside.any():
        return col
    idx = ndimage.distance_transform_edt(~inside, return_distances=False, return_indices=True)
    return col[idx[0], idx[1]]


def skin_under(A, paint):
    w = (~paint).astype(float)
    num = np.dstack([ndimage.gaussian_filter(A[..., c] * w, 18) for c in range(3)])
    return num / np.maximum(ndimage.gaussian_filter(w, 18)[..., None], 1e-4)


def lip_shape(out, w, h, shape):
    """The customizer's exact lip outline (face_masks.json + lip_sdf.png), resampled into this window at UP x."""
    fm = json.loads((out / 'face_masks.json').read_text(encoding='utf-8'))
    sdf = np.asarray(Image.open(out / 'lip_sdf.png')).astype(float)
    sdf = (sdf / 255 - 0.5) * 2 * fm['lips']['range']                   # supersampled pixels, inside > 0
    lu0, lv0, lu1, lv1 = fm['lips']['uv']
    x0, y0, _, _ = win_px(w, h)
    H, W = shape[0] * UP, shape[1] * UP
    yy, xx = np.mgrid[0:H, 0:W]
    u = (x0 + (xx + 0.5) / UP) / w; v = (y0 + (yy + 0.5) / UP) / h
    qx = (u - lu0) / (lu1 - lu0) * (sdf.shape[1] - 1); qy = (v - lv0) / (lv1 - lv0) * (sdf.shape[0] - 1)
    d = ndimage.map_coordinates(sdf, [qy, qx], order=1, cval=-fm['lips']['range'])
    px_per = sdf.shape[1] / ((lu1 - lu0) * w * UP)                     # sdf pixels per output pixel
    return np.clip(d / px_per * 1.0 + 0.5, 0, 1)


def build(name, cfg, out):
    src = np.asarray(Image.open(PACK / cfg['from'] / 'Textures' / 'Submesh_0_Albedo.png').convert('RGB')).astype(float) / 255
    h, w, _ = src.shape
    x0, y0, x1, y1 = win_px(w, h)
    A = src[y0:y1, x0:x1]
    H, W = A.shape[0] * UP, A.shape[1] * UP
    rgb = np.zeros((H, W, 3)); alpha = np.zeros((H, W))
    Aup = np.dstack([up(A[..., c]) for c in range(3)])

    def over(col, a):                                                   # paint a layer over what is there
        nonlocal rgb, alpha
        a = np.clip(a, 0, 1)
        out_a = a + alpha * (1 - a)
        rgb = (col * a[..., None] + rgb * (alpha * (1 - a))[..., None]) / np.maximum(out_a, 1e-6)[..., None]
        alpha = out_a

    paint = np.zeros(A.shape[:2], bool)
    for kind, key, tol, area in cfg['elements']:
        if key is not None:
            paint |= (np.linalg.norm(A - np.array(key), axis=-1) < tol) & area_mask(A.shape[:2], w, h, area)
    skin = skin_under(A, ndimage.binary_dilation(paint, iterations=4))
    report = []
    for kind, key, tol, area in cfg['elements']:
        region = area_mask(A.shape[:2], w, h, area)
        if kind == 'decal':                                             # a sticker: everything that is not skin, kept whole
            # the sticker is lilac: bluer than the skin and the blush around it (blue - green well above theirs)
            tint = A[..., 2] - A[..., 1]                                # lilac: blue well above green (skin here has blue <= green)
            m = ndimage.binary_fill_holes(ndimage.binary_closing((tint > 0.05) & (A[..., 0] < 0.9) & region, iterations=2))
            m = ndimage.binary_opening(m, iterations=1)
            lab, n = ndimage.label(m)
            cy, cx = int(STICKER_AT[1] * h) - y0, int(STICKER_AT[0] * w) - x0
            near = lab[max(0, cy - 20):cy + 21, max(0, cx - 20):cx + 21]           # the shape at the bandage's middle
            ids = near[near > 0]
            m = ndimage.binary_fill_holes(lab == np.bincount(ids).argmax()) if ids.size else np.zeros_like(m)
            a = clean_edge(m)
            inner = ndimage.binary_erosion(m, iterations=2)
            col = np.dstack([up(defringe(A, inner)[..., c]) for c in range(3)])
            over(col, a); report.append(f'decal {m.sum()} texels'); continue
        k = np.array(key)
        dist = np.linalg.norm(A - k, axis=-1)
        if kind == 'blush':                                             # one smooth oval per cheek, fitted to the paint
            s = skin
            amt = np.clip(np.sum((A - s) * (k - s), -1) / np.maximum(np.sum((k - s) ** 2, -1), 1e-4), 0, 1)
            amt *= np.clip(1 - dist / (tol * 2.2), 0, 1) * region
            amt *= ~ndimage.binary_dilation(paint & (dist >= tol), iterations=3)    # not the shapes painted over it
            yy, xx = np.mgrid[0:A.shape[0], 0:A.shape[1]]
            mid = LIP_U * w - x0
            field = np.zeros(A.shape[:2]); peaks = []
            for side in (xx < mid, xx >= mid):
                m = amt * side
                tot = m.sum()
                if tot < 50: continue
                cx, cy = (m * xx).sum() / tot, (m * yy).sum() / tot
                cov = np.array([[(m * (xx - cx) ** 2).sum(), (m * (xx - cx) * (yy - cy)).sum()],
                                [(m * (xx - cx) * (yy - cy)).sum(), (m * (yy - cy) ** 2).sum()]]) / tot
                ic = np.linalg.inv(cov)
                q = ic[0, 0] * (xx - cx) ** 2 + 2 * ic[0, 1] * (xx - cx) * (yy - cy) + ic[1, 1] * (yy - cy) ** 2
                peak = float(np.percentile(m[m > 0.05], 85)) if (m > 0.05).any() else 0
                field = np.maximum(field, peak * np.exp(-0.5 * q / 1.15)); peaks.append(round(peak, 2))
            over(np.broadcast_to(k, (H, W, 3)), up(field, 3)); report.append(f'blush ovals peak {peaks}'); continue
        if kind == 'soft':                                              # how strongly the colour is painted, smoothly
            s = skin
            amt = np.clip(np.sum((A - s) * (k - s), -1) / np.maximum(np.sum((k - s) ** 2, -1), 1e-4), 0, 1)
            amt *= np.clip(1 - dist / (tol * 2.2), 0, 1) * region
            speck = np.linalg.norm(A - s, axis=-1) > 0.05
            speck &= np.sum(A, -1) < np.sum(s, -1) - 0.06                # freckles: darker than the skin
            wgt = (~ndimage.binary_dilation(speck, iterations=1)).astype(float)
            sm = ndimage.gaussian_filter(amt * wgt, 4) / np.maximum(ndimage.gaussian_filter(wgt, 4), 1e-3)
            sm *= ndimage.gaussian_filter(region.astype(float), 4)
            over(np.broadcast_to(k, (H, W, 3)), up(sm, 3)); report.append(f'soft max {sm.max():.2f}'); continue
        m = (dist < tol) & region
        m = ndimage.binary_opening(m, iterations=1) if kind != 'dots' else m
        lab, n = ndimage.label(m)
        if n:
            idx = range(1, n + 1)
            size = ndimage.sum(np.ones_like(m), lab, idx)
            contrast = ndimage.mean(np.linalg.norm(A - skin, axis=-1), lab, idx)   # paint, not a patch of skin of a similar colour
            keep = 1 + np.nonzero((size >= (4 if kind == 'dots' else 30)) & (contrast > 0.07))[0]
            m = np.isin(lab, keep)
        m = ndimage.binary_closing(m, iterations=1)
        if kind == 'dots':                                              # gems: round them off
            m = ndimage.binary_dilation(m, iterations=1)
        a = clean_edge(m, 0.8 if kind == 'dots' else 1.0)
        if kind == 'soft-shape':                                        # crisp outer edge, the paint fading toward its inside
            graded = np.clip(1 - dist / tol, 0, 1) ** 0.6
            a = a * up(ndimage.gaussian_filter(graded, 1.5), 3)
        inner = ndimage.binary_erosion(m, iterations=1)
        col = np.dstack([up(defringe(A, inner if inner.any() else m)[..., c]) for c in range(3)])
        over(col, a); report.append(f'{kind} {m.sum()} texels')
    if cfg['lips'] is not False:
        la = lip_shape(out, w, h, A.shape[:2])
        inside = ndimage.zoom(la, 1 / UP, order=1) > 0.9
        if cfg['lips'] is not None:                                     # two-tone lips: the painted colour, fading toward the natural lip
            key, tol = cfg['lips']
            k = np.array(key)
            ring = ndimage.binary_dilation(inside, iterations=4) & ~ndimage.binary_dilation(inside, iterations=1)
            nat = np.median(A[inside & (np.linalg.norm(A - k, axis=-1) > tol * 2.5)], 0) if (inside & (np.linalg.norm(A - k, axis=-1) > tol * 2.5)).any() else np.median(A[ring], 0)
            amt = np.clip(np.sum((A - nat) * (k - nat), -1) / max(np.sum((k - nat) ** 2), 1e-4), 0, 1) * inside
            amt = ndimage.gaussian_filter(amt, 1.2)
            la = la * up(amt, 3)
            over(np.broadcast_to(k, (H, W, 3)), la); report.append('lips (two-tone)')
        else:                                                           # the whole lip is painted
            col = np.dstack([up(defringe(A, inside)[..., c]) for c in range(3)])
            over(col, la); report.append('lips')
    img = np.dstack([rgb, alpha])
    Image.fromarray((np.clip(img, 0, 1) * 255 + 0.5).astype(np.uint8), 'RGBA').save(out / f'makeup_{name}.png', optimize=True)
    print(f'[makeup] {name}: ' + ', '.join(report), flush=True)
    return {'id': name, 'label': cfg['label'], 'from': cfg['from'], 'file': f'makeup_{name}.png'}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--out', required=True)
    out = Path(ap.parse_args().out).resolve()
    w = h = 2048
    x0, y0, x1, y1 = win_px(w, h)
    doc = {'uv': [x0 / w, y0 / h, x1 / w, y1 / h], 'looks': [build(n, c, out) for n, c in LOOKS.items()]}
    (out / 'makeup.json').write_text(json.dumps(doc, indent=1), encoding='utf-8')


if __name__ == '__main__':
    main()
