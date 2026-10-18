"""Brand-style kits for the skin-tight bottoms (legging_shell.py): a plain performance fabric plus printed logos.
Codex draws only the logo MARK (an icon, no letters); wordmarks and taglines are set in type by code (image generation
garbles letters); the fabric is a solid knit with a faint heather, normal / roughness tiles from a spandex kit.

Writes Outfits/legging-kits/<kit>/raw/ like a Codex kit, plus the logo images and a spec with "decals" /
"waistband_text" (legging_kit.py prepare keys the mark to transparency and copies everything to kit/).

Run: python pipeline/tpose/legging_graphics.py lululemur|like-pro
"""
import json, shutil, sys
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'pipeline' / 'tpose'))
from s2_images import codex  # noqa: E402
import tee_kit as TK  # noqa: E402

KITS = ROOT / 'Outfits' / 'legging-kits'
FONTS = Path('C:/Windows/Fonts')
SPANDEX = KITS / 'volt' / 'raw'          # a Codex-made stretch-knit normal / roughness pair

MARK_PROMPT = """Use your image generation tool to make mark.png in the current folder (and nothing else anywhere):
a minimal, flat LOGO MARK for {brief}
Rules: one bold, clean, simple shape that reads at thumbnail size, like a premium sportswear logo; a single solid colour,
pure white #FFFFFF; NO text, no letters, no gradient, no shadow, no glow, no outline, no background shapes. Centred,
filling about 80% of a 1024x1024 canvas, on a fully transparent background (RGBA PNG). If transparency is impossible,
use a flat pure #00FF00 background."""


def hexrgb(h):
    h = h.lstrip('#')
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def heather(base, n=1024, amt=4, seed=0):
    rng = np.random.default_rng(seed)
    a = np.empty((n, n, 3))
    a[:] = hexrgb(base)
    a += rng.normal(0, amt, (n, n, 1))
    return Image.fromarray(a.clip(0, 255).astype(np.uint8))


def type_line(text, font, width_px, colour, variation=None, skew=0.0, ss=3):
    """One line of type, fitted to width_px, RGBA, trimmed; skew > 0 leans it like an italic."""
    f = ImageFont.truetype(str(FONTS / font), 400)
    if variation:
        f.set_variation_by_name(variation)
    w = f.getlength(text)
    size = int(400 * width_px * ss / w)
    f = ImageFont.truetype(str(FONTS / font), size)
    if variation:
        f.set_variation_by_name(variation)
    asc, desc = f.getmetrics()
    img = Image.new('RGBA', (int(width_px * ss * 1.3), asc + desc), (0, 0, 0, 0))
    ImageDraw.Draw(img).text((int(width_px * ss * 0.15), 0), text, font=f, fill=hexrgb(colour) + (255,))
    if skew:
        img = img.transform(img.size, Image.AFFINE, (1, skew, -skew * img.height, 0, 1, 0), Image.BICUBIC)
    img = img.crop(img.getbbox())
    return img.resize((max(1, img.width // ss), max(1, img.height // ss)), Image.LANCZOS)


def stack(parts, gap_frac=0.25):
    """Stack RGBA images vertically, centred."""
    g = int(gap_frac * min(p.height for p in parts))
    W = max(p.width for p in parts)
    out = Image.new('RGBA', (W, sum(p.height for p in parts) + g * (len(parts) - 1)), (0, 0, 0, 0))
    y = 0
    for p in parts:
        out.alpha_composite(p, ((W - p.width) // 2, y))
        y += p.height + g
    return out


def tinted_mark(raw, colour):
    """The Codex mark keyed to transparency, recoloured to one ink colour."""
    m = TK.key_graphic(Image.open(raw / 'mark.png'))
    a = np.array(m).astype(float)
    a[..., :3] = hexrgb(colour)
    return Image.fromarray(a.astype(np.uint8), 'RGBA')


def knit_tiles(raw, rough_mean):
    shutil.copy(SPANDEX / 'normal_tile.png', raw / 'normal_tile.png')
    r = np.array(Image.open(SPANDEX / 'roughness_tile.png').convert('L')).astype(float)
    r = (r - r.mean()) * 0.6 + rough_mean * 255
    Image.fromarray(r.clip(0, 255).astype(np.uint8)).save(raw / 'roughness_tile.png')


BRANDS = {
    'lululemur': {
        'mark': "'lululemur', a parody of a premium yoga-wear brand: a ringed lemur's tail curling up into one elegant "
                "loop, drawn as a single bold smooth shape with three or four ring stripes cut out of it as gaps.",
    },
    'like-pro': {
        'mark': "'LIKE PRO', a parody of a big athletic brand's compression wear: a fast, sporty swoop - a thick "
                "tapered curved stroke sweeping left to right - whose raised end turns into a simple thumbs-up hand "
                "silhouette.",
    },
}


def lululemur(raw):
    fab, silver = '#2F4A43', '#D8DEE2'
    heather(fab, seed=3).save(raw / 'leg_print.png')
    knit_tiles(raw, 0.78)                                        # buttery matte
    tinted_mark(raw, silver).save(raw / 'logo_mark.png')
    type_line('lululemur', 'segoeuib.ttf', 1400, silver).save(raw / 'logo_word.png')
    return {'name': 'lululemur', 'theme': 'parody yoga leggings: buttery matte spruce, reflective silver lemur-tail mark',
            'base_color': fab, 'trim_color': fab, 'stitch_color': '#3B5952', 'roughness': 0.78, 'normal_strength': 0.35,
            'ink_roughness': 0.28, 'graphic_metallic': 0.85, 'ink_height_mm': 0.2,
            'decals': [{'image': 'logo_mark.png', 'side': 'left_front', 'z': 'waist', 'dz_cm': -6.5, 'width_cm': 4.0},
                       {'image': 'logo_word.png', 'side': 'back', 'z': 'waist', 'dz_cm': 0, 'width_cm': 9.0}]}


def like_pro(raw):
    fab, white = '#0B0B0C', '#F4F4F4'
    heather(fab, amt=3, seed=5).save(raw / 'leg_print.png')
    knit_tiles(raw, 0.62)                                        # compression knit: a soft, diffuse sheen (0.45 read as plastic on black)
    tinted_mark(raw, white).save(raw / 'logo_mark.png')
    stack([type_line('JUST LIKE IT.', 'bahnschrift.ttf', 1200, white, 'Bold Condensed', skew=0.18)]).save(raw / 'logo_tag.png')
    type_line('LIKE PRO', 'bahnschrift.ttf', 1600, white, 'Bold Condensed', skew=0.18).save(raw / 'waist_text.png')
    return {'name': 'LIKE PRO', 'theme': 'parody compression shorts: black, LIKE PRO round the waistband, thumbs-up swoop',
            'base_color': fab, 'trim_color': fab, 'stitch_color': '#2A2A2C', 'roughness': 0.62, 'normal_strength': 0.5,
            'ink_roughness': 0.40, 'graphic_metallic': 0, 'ink_height_mm': 0.25,
            'waistband_text': {'image': 'waist_text.png', 'height_cm': 2.0, 'gap_cm': 4.0},
            'decals': [{'image': 'logo_mark.png', 'side': 'left_front', 'z': 'hem', 'dz_cm': 6.0, 'width_cm': 6.5},
                       {'image': 'logo_tag.png', 'side': 'left_front', 'z': 'hem', 'dz_cm': 2.6, 'width_cm': 5.5}]}


MAKERS = {'lululemur': lululemur, 'like-pro': like_pro}


def make(kit):
    raw = KITS / kit / 'raw'
    raw.mkdir(parents=True, exist_ok=True)
    if not (raw / 'mark.png').exists():
        codex(raw, MARK_PROMPT.format(brief=BRANDS[kit]['mark']), [], raw / 'mark.png', KITS / kit / 'codex.log', tries=1)
    if not (raw / 'mark.png').exists():
        sys.exit(f'[graphics] Codex did not deliver the mark for {kit}')
    spec = MAKERS[kit](raw)
    (raw / 'spec.json').write_text(json.dumps(spec, indent=2), encoding='utf-8')
    print(f'[graphics] made {raw}: {sorted(p.name for p in raw.iterdir())}', flush=True)


if __name__ == '__main__':
    make(sys.argv[1])
