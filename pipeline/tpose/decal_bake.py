"""Redraw a generated piece's logo sharply, in place: the mesh is untouched, only its textures change.

A generated mesh's logo is usually smeared and split over several UV islands, so it cannot be repainted in the flat
texture. Instead:
  1. find the old logo: the saturated / bright texels of the base colour, as one cluster on the 3D surface;
  2. fit a decal frame to it: centre, the surface normal there, world up, and the logo's radius;
  3. project the new artwork (an RGBA image, drawn by image generation) straight along that normal onto every texel of
     the surface facing it - nearest surface only - and bake it into the atlas;
  4. fill any old-logo texels the new art does not cover with the fabric round them, make the badge matte (ORM) and
     flatten the old logo's relief in the normal map under it.
The results go to <outfit>/04_meshes/<key>_tex/ (Color_reworked.png, ORM_reworked.png, Normal_reworked.png: the names survive glTF export); s6_fit.py swaps them in when it
imports the piece, so every later fit, look and export uses them.

Run: python pipeline/tpose/decal_bake.py --outfit Outfits/spoof-puffer --key monchill_puffer_jacket --decal badge.png
"""
import argparse, io, json, struct, subprocess, sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
from anmaker_config import BLENDER  # noqa: E402  (this machine's Blender: .anmaker/config.json or a search)


def glb_images(glb: Path):
    """{'color'|'orm'|'normal': PIL image} from a glTF binary's one material."""
    b = glb.read_bytes()
    jl = struct.unpack('<I', b[12:16])[0]
    J = json.loads(b[20:20 + jl])
    b0 = 20 + jl + 8
    mat = J['materials'][0]
    idx = {'color': mat['pbrMetallicRoughness']['baseColorTexture']['index'],
           'orm': mat['pbrMetallicRoughness']['metallicRoughnessTexture']['index'],
           'normal': mat['normalTexture']['index']}
    out = {}
    for k, ti in idx.items():
        bv = J['bufferViews'][J['images'][J['textures'][ti]['source']]['bufferView']]
        o = b0 + bv.get('byteOffset', 0)
        out[k] = Image.open(io.BytesIO(b[o:o + bv['byteLength']])).convert('RGB')
    return out


def rasterise(tri_p, tri_uv, n):
    """Per texel of an n x n atlas: its 3D point and its triangle's normal (NaN where no triangle)."""
    P = np.full((n, n, 3), np.nan, np.float32)
    N = np.full((n, n, 3), np.nan, np.float32)
    px = np.stack([tri_uv[..., 0] * n - 0.5, (1 - tri_uv[..., 1]) * n - 0.5], -1)   # Blender flips glTF v
    fn = np.cross(tri_p[:, 1] - tri_p[:, 0], tri_p[:, 2] - tri_p[:, 0])
    fn /= np.maximum(np.linalg.norm(fn, axis=1, keepdims=True), 1e-12)
    for t in range(len(tri_p)):
        a, b, c = px[t]
        x0, y0 = np.floor(np.minimum(np.minimum(a, b), c)).astype(int)
        x1, y1 = np.ceil(np.maximum(np.maximum(a, b), c)).astype(int)
        x0, y0, x1, y1 = max(x0, 0), max(y0, 0), min(x1, n - 1), min(y1, n - 1)
        if x1 < x0 or y1 < y0:
            continue
        xs, ys = np.meshgrid(np.arange(x0, x1 + 1), np.arange(y0, y1 + 1))
        q = np.stack([xs, ys], -1).astype(np.float64)
        v0, v1, v2 = b - a, c - a, q - a
        d = v0[0] * v1[1] - v1[0] * v0[1]
        if abs(d) < 1e-12:
            continue
        w1 = (v2[..., 0] * v1[1] - v1[0] * v2[..., 1]) / d
        w2 = (v0[0] * v2[..., 1] - v2[..., 0] * v0[1]) / d
        w0 = 1 - w1 - w2
        m = (w0 >= -0.02) & (w1 >= -0.02) & (w2 >= -0.02)     # a hair over the edge: no gaps between triangles
        if not m.any():
            continue
        p = w0[m, None] * tri_p[t, 0] + w1[m, None] * tri_p[t, 1] + w2[m, None] * tri_p[t, 2]
        P[ys[m], xs[m]] = p
        N[ys[m], xs[m]] = fn[t]
    return P, N


def sample(img, s, t):
    """Bilinear RGBA sample of img (float array h x w x 4) at s, t in [-1, 1] (t up)."""
    h, w = img.shape[:2]
    x = (s + 1) / 2 * (w - 1)
    y = (1 - (t + 1) / 2) * (h - 1)
    x0, y0 = np.clip(np.floor(x).astype(int), 0, w - 2), np.clip(np.floor(y).astype(int), 0, h - 2)
    fx, fy = (x - x0)[:, None], (y - y0)[:, None]
    return (img[y0, x0] * (1 - fx) * (1 - fy) + img[y0, x0 + 1] * fx * (1 - fy)
            + img[y0 + 1, x0] * (1 - fx) * fy + img[y0 + 1, x0 + 1] * fx * fy)


def fill(rgb, hole, iters=200):
    """Fill hole texels from their neighbours (diffusion), so leftover old-logo texels take the fabric round them."""
    a = rgb.astype(np.float64).copy()
    known = ~hole
    a[hole] = 0
    for _ in range(iters):
        s = np.zeros_like(a)
        c = np.zeros(hole.shape)
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            s += np.roll(np.roll(a * known[..., None], dy, 0), dx, 1)
            c += np.roll(np.roll(known, dy, 0), dx, 1)
        new = hole & (c > 0)
        a[new] = s[new] / c[new, None]
        known = known | new
        if known.all():
            break
    return a


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--outfit', required=True)
    ap.add_argument('--key', required=True)
    ap.add_argument('--decal', required=True, help='RGBA artwork, square, the badge filling it')
    ap.add_argument('--cover', type=float, default=1.06, help="new art radius / the old logo's radius")
    ap.add_argument('--roughness', type=float, default=0.85, help='badge roughness (felt / embroidery is matte)')
    ap.add_argument('--place', default='logo', choices=['logo', 'sleeve-left', 'sleeve-right'],
                    help="logo: redraw the generated logo where it is; sleeve-*: a new badge on that upper arm's outer side")
    ap.add_argument('--base', default='Xander')
    ap.add_argument('--along', type=float, default=0.42, help='sleeve-*: how far from shoulder (0) to elbow (1)')
    ap.add_argument('--toward-front-deg', type=float, default=30.0, help='sleeve-*: turn from the outer side toward the front')
    ap.add_argument('--radius-cm', type=float, default=4.0, help='sleeve-*: badge radius')
    a = ap.parse_args()
    d = (ROOT / a.outfit).resolve()
    glb = d / '04_meshes' / f'{a.key}.glb'
    out = d / '04_meshes' / f'{a.key}_tex'
    out.mkdir(exist_ok=True)
    npz = out / '_uv.npz'
    subprocess.run([BLENDER, '-b', '--factory-startup', '-P', str(ROOT / 'pipeline/tpose/uv_dump.py'), '--', str(glb), str(npz)],
                   check=True, capture_output=True)
    with np.load(npz) as z_:
        D = {k: z_[k] for k in z_.files}
    tex = glb_images(glb)
    n = tex['color'].size[0]
    P, N = rasterise(D['tri_p'].astype(np.float64), D['tri_uv'].astype(np.float64), n)
    col = np.asarray(tex['color']).astype(int)
    on = ~np.isnan(P[..., 0])

    if a.place == 'logo':
        # 1. the old logo: coloured or bright texels on the surface, the biggest cluster in 3D
        # brighter than almost all of the fabric (its 99th percentile + 10), so the logo's pale grey anti-aliased rim counts
        fab = np.percentile(col.mean(2)[on], 99) + 10
        logo = on & (((col.max(2) - col.min(2)) > 60) | (col.mean(2) > fab))
        pts = P[logo]
        c = np.median(pts, 0)
        for _ in range(3):
            near = np.linalg.norm(pts - c, axis=1) < 0.08
            c = np.median(pts[near], 0)
        keep = np.zeros_like(logo)
        keep[logo] = np.linalg.norm(P[logo] - c, axis=1) < 0.08
        logo = keep
        nrm = np.nanmean(N[logo], 0)
        nrm /= np.linalg.norm(nrm)
        up = np.array([0, 0, 1.0]) - nrm[2] * nrm
        up /= np.linalg.norm(up)
        right = np.cross(up, nrm)                              # seen from outside, looking along -normal
        rel = P[logo] - c
        plane = np.c_[rel @ right, rel @ up]
        centre2 = (plane.max(0) + plane.min(0)) / 2            # centre the frame on the logo's extent, not its mass
        c = c + centre2[0] * right + centre2[1] * up
        rel = P[logo] - c
        r_old = float(np.percentile(np.abs(np.c_[rel @ right, rel @ up]), 99))
        R = r_old * a.cover
        print(f'[decal] old logo: {int(logo.sum())} texels, centre {np.round(c, 3)}, normal {np.round(nrm, 2)}, '
              f'radius {r_old * 100:.1f} cm', flush=True)
    else:
        # a new spot: the outer side of one upper arm (Moncler's sleeve badge), worked out in rig space (step-5
        # placement) from the base's arm joints. In the T-pose fit the arm's outer side when it hangs is its top,
        # turned a little toward the front so it reads from the front three-quarter view as well
        side = a.place.split('-')[1].capitalize()
        pl = json.loads((d / '05_place' / 'placement.json').read_text())[a.key]
        Mx = np.array(pl['matrix'])
        Rm = Mx[:3, :3] / np.cbrt(np.linalg.det(Mx[:3, :3]))
        P = P @ Mx[:3, :3].T + Mx[:3, 3]
        N = N @ Rm.T
        lm = json.loads((ROOT / 'Bases' / f'{a.base}.json').read_text())['landmarks']
        sh, el = np.array(lm[side + 'Arm']), np.array(lm[side + 'ForeArm'])
        axis_pt = sh + a.along * (el - sh)
        down = np.array([0, 0, 1.0])                            # top of the T-pose arm = outside of the hanging arm
        fwd = np.array([0, -1.0, 0])                            # rig front is -y
        tilt = np.radians(a.toward_front_deg)
        nrm = np.cos(tilt) * down + np.sin(tilt) * fwd
        rel = P - axis_pt
        along_n = rel @ nrm
        perp = np.linalg.norm(rel - along_n[..., None] * nrm, axis=-1)
        cand = on & (perp < 0.01) & ((N @ nrm) > 0.3) & (along_n > 0)
        if cand.sum() < 5:
            raise SystemExit(f'[decal] found no sleeve surface over the {side} upper arm')
        c = P[cand][np.argmax(along_n[cand])]                   # the outermost surface there
        up = (sh - el) - ((sh - el) @ nrm) * nrm                # toward the shoulder: up when the arm hangs
        up /= np.linalg.norm(up)
        right = np.cross(up, nrm)
        logo = np.zeros_like(on)
        R = a.radius_cm / 100
        print(f'[decal] {side} upper arm, outer side: centre {np.round(c, 3)} (rig), normal {np.round(nrm, 2)}, '
              f'radius {R * 100:.1f} cm', flush=True)

    # 2. texels the new art lands on: facing it, inside its square, nearest surface along the normal
    rel = P - c
    s, t, z = rel @ right / R, rel @ up / R, rel @ nrm
    facing = on & ((N @ nrm) > 0.15) & (np.abs(s) <= 1) & (np.abs(t) <= 1) & (np.abs(z) < R)
    g = 160
    gi = np.clip(((s[facing] + 1) / 2 * (g - 1)).round().astype(int), 0, g - 1)
    gj = np.clip(((t[facing] + 1) / 2 * (g - 1)).round().astype(int), 0, g - 1)
    front = np.full((g, g), -np.inf)
    np.maximum.at(front, (gj, gi), z[facing])
    vis = np.zeros_like(facing)
    vis[facing] = z[facing] > front[gj, gi] - 0.006

    art = np.asarray(Image.open(a.decal).convert('RGBA').resize((1024, 1024), Image.LANCZOS)).astype(np.float64) / 255
    rgba = np.zeros((n, n, 4))
    rgba[vis] = sample(art, s[vis], t[vis])
    al = rgba[..., 3:4]

    # 3. bake: old logo texels the new art misses take the fabric round them, then the art goes on top
    base = col.astype(np.float64)
    hole_grow = logo.copy()
    for _ in range(4):                                     # and the soft fringe next to the old logo
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            hole_grow |= np.roll(np.roll(hole_grow, dy, 0), dx, 1) & on
    ys, xs = np.nonzero(hole_grow)
    cells = set(zip(ys // 64, xs // 64))
    for cy, cx in cells:                                   # fill window by window (the logo spans a few islands)
        y0, x0 = max(cy * 64 - 48, 0), max(cx * 64 - 48, 0)
        y1, x1 = min(cy * 64 + 112, n), min(cx * 64 + 112, n)
        base[y0:y1, x0:x1] = fill(base[y0:y1, x0:x1], hole_grow[y0:y1, x0:x1])
        hole_grow[y0 + 16:y1 - 16, x0 + 16:x1 - 16] = False  # done (its border band is redone by the neighbour)
    hole_grow = logo
    lin = (base / 255) ** 2.2
    art_lin = rgba[..., :3] ** 2.2
    color = ((lin * (1 - al) + art_lin * al) ** (1 / 2.2) * 255).clip(0, 255).astype(np.uint8)

    orm = np.asarray(tex['orm']).astype(np.float64)
    badge = np.maximum(al[..., 0], logo.astype(float))
    orm[..., 1] = orm[..., 1] * (1 - badge) + a.roughness * 255 * badge    # glTF: G roughness, B metallic
    orm[..., 2] = orm[..., 2] * (1 - badge)
    nm = np.asarray(tex['normal']).astype(np.float64)
    flat = np.array([128.0, 128.0, 255.0])
    nm = nm * (1 - 0.8 * badge[..., None]) + flat * 0.8 * badge[..., None]  # the old logo's relief, mostly gone

    Image.fromarray(color).save(out / 'Color_reworked.png')
    Image.fromarray(orm.clip(0, 255).astype(np.uint8)).save(out / 'ORM_reworked.png')
    Image.fromarray(nm.clip(0, 255).astype(np.uint8)).save(out / 'Normal_reworked.png')
    (out / 'decal.json').write_text(json.dumps({
        'source': str(glb.relative_to(ROOT)), 'decal': str(Path(a.decal).resolve().relative_to(ROOT)),
        'centre': np.round(c, 4).tolist(), 'normal': np.round(nrm, 4).tolist(), 'radius_cm': round(R * 100, 2),
        'old_logo_texels': int(logo.sum()), 'art_texels': int((al[..., 0] > 0.5).sum()),
        'leftover_filled': int(hole_grow.sum())}, indent=2), encoding='utf-8')
    npz.unlink()
    print(f'[decal] baked into {out}: {int((al[..., 0] > 0.5).sum())} art texels, {int(hole_grow.sum())} old texels filled',
          flush=True)


if __name__ == '__main__':
    main()
