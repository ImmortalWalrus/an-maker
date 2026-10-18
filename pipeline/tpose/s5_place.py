"""Step 5 - place each mesh on the mannequin by camera maths (rigid only: rotation, one uniform scale, translation).

Every step-3 image of a piece was drawn on a step-1 canvas whose orthographic camera is known (camera.json), so its
outline is the piece's true silhouette from that side, in metres. The mannequin body is used as an occluder when
scoring, because in the images it hides whatever is behind it (e.g. the back half of a strap in the front view). For each mesh we search the 24 axis-aligned
orientations, then refine scale, x/y/z and small rotations so its silhouettes match the piece's outlines in the
front, left, back and right views at once (mean IoU, plus front colour agreement). Front/back fix x and z, the
sides fix y - nothing is guessed. Each view is first registered onto its mannequin canvas (silhouette overlap
search), in case the image model drifted the framing.

Run: python pipeline/tpose/s5_place.py <outfit_dir> [--keys a,b]
Writes 05_place/placement.json (4x4 matrix per piece + per-view IoU) and <key>_fit.png (top: image outlines,
bottom: placed mesh, per view).
"""
import itertools, json, math, subprocess, sys
from collections import deque
from pathlib import Path
import numpy as np
from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parents[2]
from anmaker_config import BLENDER  # noqa: E402  (this machine's Blender: .anmaker/config.json or a search)
VIEWS = ['front', 'left', 'back', 'right']


# ------------------------------------------------------------------ image side

def background_mask(png, tol=6):
    """Background = colour connected to the image border within tol of the border colour (works for white garments
    on white). Piece = the rest, minus specks smaller than 2% of the largest blob."""
    img = Image.open(png)
    if img.mode in ('RGBA', 'LA', 'P') and 'A' in img.convert('RGBA').getbands():
        rgba = np.asarray(img.convert('RGBA'))
        if (rgba[..., 3] < 255).any():  # real transparency: the alpha channel IS the mask
            return rgba[..., 3] > 127, rgba[..., :3].astype(int)
    a = np.asarray(img.convert('RGB')).astype(int)
    h, w, _ = a.shape
    bg_col = np.median(np.concatenate([a[0], a[-1], a[:, 0], a[:, -1]]), 0)
    near = np.abs(a - bg_col).max(2) <= tol
    bg = np.zeros((h, w), bool)
    q = deque([(y, x) for y in range(h) for x in (0, w - 1)] + [(y, x) for x in range(w) for y in (0, h - 1)])
    while q:
        y, x = q.popleft()
        if bg[y, x] or not near[y, x]:
            continue
        bg[y, x] = True
        if y > 0: q.append((y - 1, x))
        if y < h - 1: q.append((y + 1, x))
        if x > 0: q.append((y, x - 1))
        if x < w - 1: q.append((y, x + 1))
    piece = ~bg
    # Chroma-key background (step 3 draws pieces on solid magenta): every magenta pixel is background, including
    # enclosed gaps such as the inside of a strap loop. White backgrounds keep border-connected removal only, since
    # white cloth cannot be told apart from white background by colour.
    if bg_col[0] > 200 and bg_col[2] > 200 and bg_col[1] < 80:
        piece &= ~(np.abs(a - bg_col).max(2) <= 60)
    piece = np.asarray(Image.fromarray(piece.astype(np.uint8) * 255).filter(ImageFilter.MedianFilter(5))) > 127
    lab, sizes = components(piece)
    if sizes:
        keep = [i for i, s in sizes.items() if s >= 0.02 * max(sizes.values())]
        piece = np.isin(lab, keep)
    return piece, a


def components(mask):
    lab = np.zeros(mask.shape, int)
    sizes, n = {}, 0
    for y, x in zip(*np.nonzero(mask)):
        if lab[y, x]:
            continue
        n += 1
        q, cnt = deque([(y, x)]), 0
        lab[y, x] = n
        while q:
            cy, cx = q.popleft()
            cnt += 1
            for ny, nx in ((cy - 1, cx), (cy + 1, cx), (cy, cx - 1), (cy, cx + 1)):
                if 0 <= ny < mask.shape[0] and 0 <= nx < mask.shape[1] and mask[ny, nx] and not lab[ny, nx]:
                    lab[ny, nx] = n
                    q.append((ny, nx))
        sizes[n] = cnt
    return lab, sizes


def warp(arr, s, t, resample):
    img = Image.fromarray(arr)
    return np.asarray(img.transform(img.size, Image.AFFINE, (1 / s, 0, -t[0] / s, 0, 1 / s, -t[1] / s), resample=resample))


def fingertips(mask):
    ys, xs = np.nonzero(mask)
    return np.array([(float(u), float(ys[np.abs(xs - u) <= 2].mean())) for u in (xs.min(), xs.max())])


def view_registration(d, view):
    """Similarity (scale s, shift t px) taking the dressed image of a view onto its mannequin canvas.
    front/back: from the fingertip span and arm line (bare skin in both images, unaffected by clothes).
    sides: the image model keeps the framing (verified on front/back), so identity - then CHECKED: the bare
    mannequin must lie inside the dressed outline (coverage >= 0.95), otherwise the view is flagged.
    Cached in 05_place/registration.json."""
    cache = d / '05_place' / 'registration.json'
    reg = json.loads(cache.read_text()) if cache.exists() else {}
    if view in reg:
        return reg[view]['scale'], np.array(reg[view]['shift_px'])
    man = np.asarray(Image.open(d / '01_mannequin' / f'{view}_mask.png').convert('L')) > 127
    dressed, _ = background_mask(d / '02_dressed' / f'{view}.png')
    if view in ('front', 'back'):
        m, g = fingertips(man), fingertips(dressed)
        s = float(np.linalg.norm(m[1] - m[0]) / np.linalg.norm(g[1] - g[0]))
        t = m.mean(0) - s * g.mean(0)
    else:
        s, t = 1.0, np.zeros(2)
    w = warp(dressed.astype(np.uint8) * 255, s, t, Image.NEAREST) > 127
    coverage = float((man & w).sum() / man.sum())
    reg[view] = {'scale': s, 'shift_px': t.tolist(), 'mannequin_inside_dressed': round(coverage, 4),
                 'ok': coverage >= 0.95}
    cache.parent.mkdir(exist_ok=True)
    cache.write_text(json.dumps(reg, indent=2))
    return s, t


UPPER_SLOTS = {'hair', 'headwear', 'top', 'outerwear', 'fullbody', 'accessory', 'hands'}


def registered(d, view, png, slot=None):
    """A piece image's mask and colours, moved onto the view's mannequin canvas. With `slot`, side/back views are
    also lined up vertically with the piece's FRONT view (the pixel-exact master): the image model draws each view
    at a slightly different height, so upper-body pieces are matched on their top edge, lower-body pieces on their
    bottom edge (the edge that is reliably visible in every view)."""
    s, t = view_registration(d, view)
    m, rgb = background_mask(png)
    m = warp(m.astype(np.uint8) * 255, s, t, Image.NEAREST) > 127
    rgb = warp(rgb.astype(np.uint8), s, t, Image.BILINEAR)
    if slot is not None and view != 'front':
        fs, ft = view_registration(d, 'front')
        fm, _ = background_mask(png.with_name(png.name.replace(f'{view}_', 'front_', 1)))
        fm = warp(fm.astype(np.uint8) * 255, fs, ft, Image.NEAREST) > 127
        rows, frows = np.nonzero(m.any(1))[0], np.nonzero(fm.any(1))[0]
        dy = int(frows.min() - rows.min()) if slot in UPPER_SLOTS else int(frows.max() - rows.max())
        m = np.roll(m, dy, 0)
        rgb = np.roll(rgb, dy, 0)
    return m, rgb


# ------------------------------------------------------------------ mesh side

def rotations():
    out = []
    for perm in itertools.permutations(range(3)):
        for signs in itertools.product((1, -1), repeat=3):
            R = np.zeros((3, 3))
            for i, (j, s) in enumerate(zip(perm, signs)):
                R[i, j] = s
            if np.isclose(np.linalg.det(R), 1):
                out.append(R)
    return out


def rot(axis, deg):
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return {'x': np.array([[1, 0, 0], [0, c, -s], [0, s, c]]), 'y': np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]]),
            'z': np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])}[axis]


class Views:
    def __init__(self, cam, targets, down, occluder=None):
        self.cam, self.down = cam, down
        self.occluder = occluder
        W, H = cam['res']
        self.w, self.h = W // down, H // down
        self.mpp = cam['metres_per_pixel'] * down
        self.c = np.array(cam['center'])
        self.up = np.array(cam['up'], float)
        self.tg = {}
        for v, (m, rgb) in targets.items():
            self.tg[v] = (np.asarray(Image.fromarray(m).resize((self.w, self.h), Image.NEAREST)),
                          np.asarray(Image.fromarray(rgb).resize((self.w, self.h), Image.BILINEAR)) / 255.0)

    def body_front(self, view):
        """Per pixel, the depth (toward the camera) of the frontmost mannequin surface; -inf where no body."""
        if not hasattr(self, '_front'):
            self._front = {}
        if view not in self._front:
            front = np.full((self.h, self.w), -np.inf)
            if self.occluder is not None:
                vw = self.cam['views'][view]
                right, to_cam = np.array(vw['right']), np.array(vw['to_camera'])
                q = self.occluder - self.c
                u = np.round(q @ right / self.mpp + self.w / 2).astype(int)
                v = np.round(-(q @ self.up) / self.mpp + self.h / 2).astype(int)
                dep = q @ to_cam
                ok = (u >= 0) & (u < self.w) & (v >= 0) & (v < self.h)
                np.maximum.at(front, (v[ok], u[ok]), dep[ok])
                img = Image.fromarray(np.where(np.isfinite(front), front, -10).astype(np.float32), 'F')
                front = np.asarray(img.filter(ImageFilter.MaxFilter(3)))
                front = np.where(front <= -9.9, -np.inf, front)
            self._front[view] = front
        return self._front[view]

    def splat(self, P, C, view):
        vw = self.cam['views'][view]
        right, to_cam = np.array(vw['right']), np.array(vw['to_camera'])
        q = P - self.c
        u = np.round(q @ right / self.mpp + self.w / 2).astype(int)
        v = np.round(-(q @ self.up) / self.mpp + self.h / 2).astype(int)
        depth = q @ to_cam
        ok = (u >= 0) & (u < self.w) & (v >= 0) & (v < self.h)
        # the mannequin hides whatever is behind it, exactly as in the images
        ok[ok] &= depth[ok] >= self.body_front(view)[v[ok], u[ok]] - 0.004
        u, v, depth, c = u[ok], v[ok], depth[ok], C[ok]
        order = np.argsort(depth)  # far first, nearest to the camera written last
        img = np.full((self.h, self.w, 3), -1.0)
        img[v[order], u[order]] = c[order]
        sil = img[..., 0] >= 0
        sil = np.asarray(Image.fromarray(sil.astype(np.uint8) * 255).filter(ImageFilter.MaxFilter(5)).filter(ImageFilter.MinFilter(3))) > 127
        return sil, img

    def score(self, P, C):
        """Outline overlap (IoU) + front colour agreement - mean outline distance in mm (chamfer). The distance term
        matters for thin parts (straps, laces): a 1 cm miss and a 10 cm miss have the same IoU but not the same
        distance."""
        from scipy.ndimage import distance_transform_edt
        if not hasattr(self, '_dt'):
            self._dt = {v: distance_transform_edt(~t) for v, (t, _) in self.tg.items()}
        ious, colour, cham = {}, 0.0, {}
        for view, (tgt, rgb) in self.tg.items():
            sil, img = self.splat(P, C, view)
            ious[view] = (sil & tgt).sum() / max((sil | tgt).sum(), 1)
            if sil.any() and tgt.any():
                d_sil = distance_transform_edt(~sil)
                cham[view] = 0.5 * (self._dt[view][sil].mean() + d_sil[tgt].mean()) * self.mpp * 1000
            else:
                cham[view] = 100.0
            if view == 'front':
                both = sil & tgt & (img[..., 0] >= 0)
                colour = 1 - np.abs(img[both] - rgb[both]).mean() if both.any() else 0.0
        mean = float(np.mean(list(ious.values())))
        self.last_chamfer = cham
        return mean + 0.3 * colour * mean - 0.01 * float(np.mean(list(cham.values()))), ious, colour


def initial_transform(V, R, views):
    """Uniform scale from the outline height; translation from outline centres (front/back -> x,z; sides -> y)."""
    P = V @ R.T
    lo, hi = P.min(0), P.max(0)
    tg = {v: np.nonzero(views.tg[v][0]) for v in views.tg}
    ys, xs = tg['front']
    s = (ys.max() - ys.min()) * views.mpp / (hi[2] - lo[2])
    cu_f, cv_f = (xs.max() + xs.min()) / 2, (ys.max() + ys.min()) / 2
    ys_l, xs_l = tg['left']
    cu_l = (xs_l.max() + xs_l.min()) / 2
    world = views.c.copy()
    world[0] += (cu_f - views.w / 2) * views.mpp * views.cam['views']['front']['right'][0]
    world[2] += -(cv_f - views.h / 2) * views.mpp
    world[1] += (cu_l - views.w / 2) * views.mpp * views.cam['views']['left']['right'][1]
    t = world - s * (lo + hi) / 2
    return s, t


def refine(V, C, R, s, t, views, rounds=3, px=1.0):
    """Coordinate descent over uniform scale, x/z (front+back), y (sides) and small rotations."""
    step = views.mpp * px
    best = views.score(s * (V @ R.T) + t, C)[0]
    for _ in range(rounds):
        for k in np.arange(-6, 7):
            s2 = s * (1 + 0.005 * k)
            sc = views.score(s2 * (V @ R.T) + t, C)[0]
            if sc > best:
                best, s = sc, s2
        for axis in (0, 2, 1):
            for k in np.arange(-6, 7):
                t2 = t.copy()
                t2[axis] += k * step
                sc = views.score(s * (V @ R.T) + t2, C)[0]
                if sc > best:
                    best, t = sc, t2
        for ax in 'zxy':
            for deg in (-4, -3, -2, -1, 1, 2, 3, 4):
                Rn = rot(ax, deg) @ R
                # rotate about the piece's own centre so the translation stays meaningful
                ctr = s * (V @ R.T).mean(0) + t
                t2 = ctr - s * (V @ Rn.T).mean(0)
                sc = views.score(s * (V @ Rn.T) + t2, C)[0]
                if sc > best:
                    best, R, t = sc, Rn, t2
    return R, s, t, best


def main():
    d = Path(sys.argv[1]).resolve()
    only = set(sys.argv[sys.argv.index('--keys') + 1].split(',')) if '--keys' in sys.argv else None
    cam = json.loads((d / '01_mannequin' / 'camera.json').read_text())
    pieces = json.loads((d / 'outfit.json').read_text(encoding='utf-8'))['pieces']
    (d / '05_place').mkdir(exist_ok=True)
    subprocess.run([BLENDER, '-b', '--factory-startup', '-P', str(ROOT / 'pipeline' / 'tpose' / 's5_dump_meshes.py'), '--', str(d)],
                   check=True, capture_output=True)
    for v in VIEWS:
        s, t = view_registration(d, v)
        print(f'[place] registration {v}: scale {s:.3f}, shift {np.round(t, 1)} px', flush=True)
    pj = d / '05_place' / 'placement.json'
    placement = json.loads(pj.read_text()) if (only and pj.exists()) else {}
    R24 = rotations()
    for p in pieces:
        key = p['key']
        npz = d / '05_place' / f'{key}_mesh.npz'
        if not npz.exists() or (only and key not in only):
            continue
        data = np.load(npz)
        V = np.concatenate([data['verts'], data['verts'][data['tris']].mean(1)])
        C = np.concatenate([data['colors'], data['colors'][data['tris']].mean(1)])
        targets = {v: registered(d, v, d / '03_garments' / f'{v}_{key}.png', p['slot']) for v in VIEWS}
        occ = None
        if (d / '05_place' / '_body_mesh.npz').exists():
            bd = np.load(d / '05_place' / '_body_mesh.npz')
            occ = np.concatenate([bd['verts'], bd['verts'][bd['tris']].mean(1)])
        coarse, fine = Views(cam, targets, 4, occ), Views(cam, targets, 2, occ)
        trials = []
        for ri, R in enumerate(R24):
            s, t = initial_transform(V, R, coarse)
            trials.append((coarse.score(s * (V @ R.T) + t, C)[0], ri))
        trials.sort(reverse=True)
        best = None
        for _, ri in trials[:3]:
            s, t = initial_transform(V, R24[ri], fine)
            R, s, t, sc = refine(V, C, R24[ri], s, t, fine)
            if best is None or sc > best[3]:
                best = (R, s, t, sc)
        R, s, t, _ = best
        full = Views(cam, targets, 1, occ)
        R, s, t, _ = refine(V, C, R, s, t, full, rounds=1)
        total, ious, colour = full.score(s * (V @ R.T) + t, C)
        cham = {v: round(float(x), 1) for v, x in full.last_chamfer.items()}
        M = np.eye(4)
        M[:3, :3] = s * R
        M[:3, 3] = t
        placement[key] = {'slot': p['slot'], 'matrix': M.tolist(), 'scale': float(s),
                          'iou': {v: round(float(x), 3) for v, x in ious.items()},
                          'iou_mean': round(float(np.mean(list(ious.values()))), 3), 'colour_front': round(float(colour), 3),
                          'outline_distance_mm': cham}
        # Visual check: image outline (top) vs placed mesh (bottom) for each view.
        rows = []
        for v in VIEWS:
            tgt, rgb = full.tg[v]
            sil, img = full.splat(s * (V @ R.T) + t, C, v)
            a = np.where(tgt[..., None], (rgb * 255).astype(np.uint8), 255)
            b = np.where(sil[..., None], np.clip(img * 255, 0, 255).astype(np.uint8), 255)
            rows.append(np.concatenate([a, b], 0))
        Image.fromarray(np.concatenate(rows, 1).astype(np.uint8)).resize((1024, 768)).save(d / '05_place' / f'{key}_fit.png')
        print(f"[place] {key}: IoU {placement[key]['iou']} (mean {placement[key]['iou_mean']}), colour {colour:.3f}, "
              f"scale {s:.4f}, outline distance mm {cham}", flush=True)
    pj.write_text(json.dumps(placement, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
