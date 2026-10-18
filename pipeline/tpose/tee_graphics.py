"""Code-made texture kits for brand and type tees: exact logos (vector paths) and set type never go through image
generation, which redraws letters. Writes the same raw/ files a Codex kit has (tee_kit.py prepare / build take over):
torso_print.png + sleeve_print.png (1536x1024, wrapping left-right), chest_graphic.png, back_graphic.png (optional),
normal_tile.png, roughness_tile.png, spec.json.

Run: python pipeline/tpose/tee_graphics.py sidequest|an-secret   (collection.json entries with "maker": "code")
"""
import json, re, shutil, sys
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
KITS = ROOT / 'Outfits' / 'tee-kits'
FONTS = Path('C:/Windows/Fonts')
SQ_WORDMARK = Path.home() / 'Documents/SideQuest/SideQuest-stable-4133-20261014/source/MapboxHighlights/Resources/Explore/SQWordmark.svgpath'
FW, FH = 1536, 1024                       # fabric size, same as a Codex kit's


def hexrgb(h):
    h = h.lstrip('#')
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def periodic_noise(h, w, seed, terms=14, fmax=6):
    """Smooth noise that wraps left-right exactly (integer frequencies across the width)."""
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:h, 0:w]
    u, v = xx / w * 2 * np.pi, yy / w * 2 * np.pi
    f = np.zeros((h, w))
    for _ in range(terms):
        kx = rng.integers(1, fmax + 1)
        ky = rng.uniform(0.3, fmax)
        amp = 1 / (kx * kx + ky * ky) ** 0.5
        f += amp * np.sin(kx * u * rng.choice([-1, 1]) + ky * v + rng.uniform(0, 2 * np.pi))
    return (f - f.mean()) / f.std()


def heather(base, h, w, seed, amt=5):
    """A plain jersey colour with a faint heather (fine fibre speckle), wrapping left-right."""
    rng = np.random.default_rng(seed)
    a = np.empty((h, w, 3))
    a[:] = hexrgb(base)
    a += rng.normal(0, amt, (h, w, 1)) + periodic_noise(h, w, seed + 1, 8, 10)[..., None] * amt * 0.4
    return a.clip(0, 255).astype(np.uint8)


def svg_polys(d, steps=16):
    """The M / L / C (absolute, with implicit repeats) subpaths of an SVG path as polygons."""
    toks = re.findall(r'[MLC]|-?\d*\.?\d+(?:e-?\d+)?', d)
    polys, cur, i, cmd, pt = [], [], 0, None, None
    while i < len(toks):
        if toks[i] in 'MLC':
            cmd = toks[i]
            i += 1
            if cmd == 'M':
                if cur:
                    polys.append(cur)
                cur = []
            continue
        if cmd in 'ML':
            pt = (float(toks[i]), float(toks[i + 1]))
            cur.append(pt)
            i += 2
            if cmd == 'M':
                cmd = 'L'
        else:
            p1, p2, p3 = [(float(toks[i + k]), float(toks[i + k + 1])) for k in (0, 2, 4)]
            for t in np.linspace(0, 1, steps + 1)[1:]:
                s = 1 - t
                cur.append((s ** 3 * pt[0] + 3 * s * s * t * p1[0] + 3 * s * t * t * p2[0] + t ** 3 * p3[0],
                            s ** 3 * pt[1] + 3 * s * s * t * p1[1] + 3 * s * t * t * p2[1] + t ** 3 * p3[1]))
            pt = p3
            i += 6
    if cur:
        polys.append(cur)
    return polys


def fill_evenodd(polys, width_px, colour, ss=4, pad=0.02):
    """Rasterise polygons with the even-odd rule (the wordmark's counters are same-wound inner contours)."""
    pts = np.concatenate([np.array(p) for p in polys])
    lo, hi = pts.min(0), pts.max(0)
    k = width_px * ss / (hi[0] - lo[0]) / (1 + 2 * pad)
    off = lo - (hi[0] - lo[0]) * pad
    W, H = int(width_px * ss), int(((hi[1] - lo[1]) + 2 * (hi[0] - lo[0]) * pad) * k)
    acc = np.zeros((H, W), bool)
    for p in polys:
        m = Image.new('1', (W, H), 0)
        ImageDraw.Draw(m).polygon([((x - off[0]) * k, (y - off[1]) * k) for x, y in p], fill=1)
        acc ^= np.array(m)
    alpha = Image.fromarray((acc * 255).astype(np.uint8)).resize((W // ss, H // ss), Image.LANCZOS)
    out = Image.new('RGBA', alpha.size, colour + (0,))
    out.putalpha(alpha)
    return out


def set_type(lines, width_px, ss=3, gap=0.18):
    """Lines of type, each [(text, font file, colour), ...] runs, centred, every line scaled to the same width
    unless it gives a 'scale' (fraction of the full width). Returns RGBA."""
    rendered = []
    for line in lines:
        runs, frac = line['runs'], line.get('scale', 1.0)
        probe = 400
        wsum = sum(ImageFont.truetype(str(FONTS / f), probe).getlength(t) for t, f, _ in runs)
        size = int(probe * width_px * ss * frac / wsum)
        fonts = [ImageFont.truetype(str(FONTS / f), size) for _, f, _ in runs]
        asc, desc = fonts[0].getmetrics()
        img = Image.new('RGBA', (int(width_px * ss), asc + desc), (0, 0, 0, 0))
        dr = ImageDraw.Draw(img)
        x = (width_px * ss - sum(fn.getlength(t) for (t, _, _), fn in zip(runs, fonts))) / 2
        for (t, _, c), fn in zip(runs, fonts):
            dr.text((x, 0), t, font=fn, fill=hexrgb(c) + (255,))
            x += fn.getlength(t)
        bb = img.getbbox()
        rendered.append(img.crop((0, bb[1], img.width, bb[3])))
    g = int(gap * rendered[0].height)
    H = sum(r.height for r in rendered) + g * (len(rendered) - 1)
    out = Image.new('RGBA', (int(width_px * ss), H), (0, 0, 0, 0))
    y = 0
    for r in rendered:
        out.alpha_composite(r, (0, y))
        y += r.height + g
    out = out.crop(out.getbbox())
    return out.resize((max(1, out.width // ss), max(1, out.height // ss)), Image.LANCZOS)


def knit_maps(raw):
    """The code-made jersey normal / roughness tiles, shared with the first fabric kit."""
    for f in ('normal_tile.png', 'roughness_tile.png'):
        shutil.copy(KITS / 'funky70s-fabric' / 'raw' / f, raw / f)


def sidequest(raw):
    """SideQuest merch tee: the brand ground colour with a faint topographic map (the app is a map), a few apricot
    quest markers, and the approved wordmark - its exact vector paths, never a redraw - on the chest in bone."""
    ground, line, line5, apricot = hexrgb('#101B21'), np.array(hexrgb('#1E2E37')), np.array(hexrgb('#2C4250')), hexrgb('#FFA36D')
    for name, seed in (('torso_print', 7), ('sleeve_print', 8)):
        f = periodic_noise(FH, FW, seed, 16, 4) * 1.0 + periodic_noise(FH, FW, seed + 10, 10, 9) * 0.25
        lv = f * 7                                               # contour levels
        frac = np.abs(lv - np.round(lv))
        gy, gx = np.gradient(lv)
        dist = frac / np.maximum(np.hypot(gx, gy), 1e-3)         # distance to the nearest contour, in px
        major = (np.round(lv) % 5 == 0)
        width = np.where(major, 1.9, 1.1)
        cov = np.clip(width - dist, 0, 1)[..., None]
        col = np.where(major[..., None], line5, line)
        a = np.array(ground, float) * (1 - cov) + col * cov
        a = a + np.random.default_rng(seed).normal(0, 2.5, (FH, FW, 1))
        img = Image.fromarray(a.clip(0, 255).astype(np.uint8))
        if name == 'torso_print':                                # a few quest markers, clear of the chest logo
            dr = ImageDraw.Draw(img)
            for x, y in ((0.12, 0.70), (0.30, 0.38), (0.71, 0.80), (0.86, 0.30), (0.58, 0.92)):
                cx, cy, r = x * FW, y * FH, 9
                dr.polygon([(cx, cy - r), (cx + r, cy), (cx, cy + r), (cx - r, cy)], outline=apricot, width=3)
                dr.ellipse((cx - 2.5, cy - 2.5, cx + 2.5, cy + 2.5), fill=apricot)
        img.save(raw / f'{name}.png')
    fill_evenodd(svg_polys(SQ_WORDMARK.read_text()), 1600, hexrgb('#F5EFE6')).save(raw / 'chest_graphic.png')
    knit_maps(raw)
    return {'name': 'SideQuest', 'theme': 'SideQuest merch: brand ground with a faint topographic map, apricot quest markers, the wordmark on the chest',
            'base_color': '#101B21', 'trim_color': '#1F2A31', 'stitch_color': '#FFA36D', 'pattern_tile_cm': 24,
            'chest_graphic_width_cm': 16, 'back_graphic_width_cm': None, 'roughness': 0.85, 'normal_strength': 0.6,
            'ink_roughness': 0.5}


def an_secret(raw):
    """The AN tee: what AN stands for is a secret. Front: a big AN and 'ask me what it stands for'. Back (the answer
    people read as you walk off): 'Absolutely Not telling.' with the A and N picked out."""
    tee, ink, hi = '#0E8C9E', '#FFFFFF', '#06303A'  # the A and N in deep ink: yellow washed out next to white under the page's lights
    for name, seed in (('torso_print', 21), ('sleeve_print', 22)):
        Image.fromarray(heather(tee, FH, FW, seed)).save(raw / f'{name}.png')
    bold, black = 'segoeuib.ttf', 'seguibl.ttf'
    set_type([{'runs': [('AN', black, ink)], 'scale': 0.55},
              {'runs': [('ask me what it stands for', bold, ink)]}], 1600, gap=0.16).save(raw / 'chest_graphic.png')
    set_type([{'runs': [('A', black, hi), ('bsolutely', black, ink)]},
              {'runs': [('N', black, hi), ('ot telling.', black, ink)], 'scale': 0.86}], 2000, gap=0.16).save(raw / 'back_graphic.png')
    knit_maps(raw)
    return {'name': 'AN (secret)', 'theme': 'AN slogan tee: front asks what AN stands for, back answers Absolutely Not telling',
            'base_color': tee, 'trim_color': '#0B7383', 'stitch_color': '#0B7383', 'pattern_tile_cm': 24,
            'chest_graphic_width_cm': 16, 'back_graphic_width_cm': 22, 'roughness': 0.85, 'normal_strength': 0.6,
            'ink_roughness': 0.45}


MAKERS = {'sidequest': sidequest, 'an-secret': an_secret}


def make(kit_name):
    raw = KITS / kit_name / 'raw'
    raw.mkdir(parents=True, exist_ok=True)
    spec = MAKERS[kit_name](raw)
    (raw / 'spec.json').write_text(json.dumps(spec, indent=2), encoding='utf-8')
    print(f'[graphics] made {raw}: {sorted(p.name for p in raw.iterdir())}', flush=True)


if __name__ == '__main__':
    make(sys.argv[1])
