"""Texture kits and builds for skin-tight bottoms (legging_shell.py): leggings, capris, bike shorts, one system.

  make      Codex writes Outfits/legging-kits/<kit>/raw/: leg_print.png (the printed fabric for one leg of the LONGEST,
            highest cut; shorter cuts use less of it), normal_tile.png + roughness_tile.png (by code), spec.json
  prepare   checked and cleaned into <kit>/kit/ (print upscaled 2x, the normal tile checked, a procedural knit if not)
  build     legging_shell.py, equipped and inspected alone and under a fitted tee, then exported with the tees to
            web/customizer/assets-test (never published by this script)

Run: python pipeline/tpose/legging_kit.py --collection Outfits/legging-kits/collection.json [--only make,prepare,build]
"""
import argparse, json, subprocess, sys, zipfile
from pathlib import Path
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'pipeline' / 'tpose'))
from s2_images import codex  # noqa: E402
import tee_kit as TK  # noqa: E402

KITS = ROOT / 'Outfits' / 'legging-kits'
TEE_OVER = 'tee-groovy-sun-tee:groovy_sun_tee'   # a fitted tee worn over them for the layering check

PROMPT = """You are making a TEXTURE KIT for skin-tight stretch leggings worn by a stylised 3D game character (Bitmoji /
Genies style). You make the printed FABRIC, laid flat like printed yardage; the pipeline cuts each leg out of it, so
never draw leggings, legs, a body, folds, lighting or perspective. Theme: {theme}

Write these files into the current folder (and nothing anywhere else). Do not ask questions; make good choices.

1. leg_print.png - use your image generation tool, 1024x1024. The fabric for ONE leg, about 80 x 80 cm. The vertical
   CENTRE LINE of the image runs down the OUTSIDE of the leg (the side you see from the side); the LEFT half wraps to
   the front of the leg and the RIGHT half to the back. The TOP edge is the waistband, the BOTTOM edge the ankle. The
   leg narrows toward the ankle, so the part that shows is about 45 cm wide at the top and 22 cm wide at the bottom,
   centred - keep the important design within that, but run the print full-bleed to all four edges. The design may
   use the outside-leg centre line (a stripe or panel down the side looks great), and should read at a glance. Both
   legs are cut from this same fabric, mirrored. Flat print artwork only. No text, no logos.
2. normal_tile.png - make it with Python code, not image generation: 1024x1024, seamless, a tangent-space normal map
   of fine stretch-knit (spandex jersey) fabric (OpenGL convention, average colour close to #8080FF, very subtle).
3. roughness_tile.png - make it with Python code: 1024x1024, seamless, greyscale, around 0.5 (pixel value ~128) with a
   slight knit variation (stretch fabric has a soft sheen).
4. spec.json - exactly these keys:
   {{"name": "<short name>", "theme": "<one line>", "base_color": "#rrggbb" (the print's dominant colour),
     "trim_color": "#rrggbb" (the waistband: a solid colour that suits the print),
     "stitch_color": "#rrggbb", "roughness": 0.5, "normal_strength": 0.5}}
5. kit.zip - all of the above files.
"""


def make(d: Path, theme: str):
    raw = d / 'raw'
    raw.mkdir(parents=True, exist_ok=True)
    ok = codex(raw, PROMPT.format(theme=theme), [], raw / 'kit.zip', d / 'codex.log', tries=1)
    if (raw / 'kit.zip').exists() and not (raw / 'leg_print.png').exists():
        zipfile.ZipFile(raw / 'kit.zip').extractall(raw)
    missing = [f for f in ('spec.json', 'leg_print.png') if not (raw / f).exists()]
    if missing:
        sys.exit(f'[legs] Codex did not deliver {missing}; see {d / "codex.log"} (ok={ok})')
    print(f'[legs] made {d.name}: {sorted(p.name for p in raw.iterdir())}', flush=True)


def prepare(d: Path):
    raw, kit = d / 'raw', d / 'kit'
    kit.mkdir(exist_ok=True)
    spec = json.loads((raw / 'spec.json').read_text(encoding='utf-8'))
    fab = Image.open(raw / 'leg_print.png').convert('RGB')
    fab.resize((fab.width * 2, fab.height * 2), Image.LANCZOS).save(kit / 'leg_print.png')
    tile_px = 1100                                               # the knit tiles cover 24 cm (knit_tile_cm)
    nrm = None
    if (raw / 'normal_tile.png').exists():
        n = np.array(Image.open(raw / 'normal_tile.png').convert('RGB')).astype(float)
        mean = n.reshape(-1, 3).mean(0)
        if abs(mean[0] - 128) < 20 and abs(mean[1] - 128) < 20 and mean[2] > 200:
            nrm = n.astype(np.uint8)
        else:
            print(f'[legs] {d.name}: normal_tile is not a usable normal map (mean {mean.round()}): procedural knit', flush=True)
    Image.fromarray(nrm if nrm is not None else TK.knit_normal()).resize((tile_px, tile_px), Image.LANCZOS).save(kit / 'normal_tile.png')
    if (raw / 'roughness_tile.png').exists():
        Image.open(raw / 'roughness_tile.png').convert('L').resize((tile_px, tile_px), Image.LANCZOS).convert('RGB').save(kit / 'roughness_tile.png')
    spec['knit_tile_cm'] = 24
    for img in [d_['image'] for d_ in spec.get('decals', [])] + ([spec['waistband_text']['image']] if spec.get('waistband_text') else []):
        TK.key_graphic(Image.open(raw / img)).save(kit / img)     # printed logos / type, transparent, trimmed
    (kit / 'spec.json').write_text(json.dumps(spec, indent=2), encoding='utf-8')
    print(f'[legs] prepared {kit}', flush=True)


def build_one(c, tex):
    out = 'legs-' + c['key'].replace('_', '-')
    TK.blender('pipeline/tpose/legging_shell.py', '--', '--base', 'Xander', '--out', f'Outfits/{out}', '--key', c['key'],
               '--leg', str(c['leg']), '--rise-cm', str(c.get('rise_cm', 9.5)), '--kit', str(KITS / c['kit'] / 'kit'),
               '--tex', str(tex))
    fails = []
    for look, pieces in ((f'web-{c["key"]}', [f'{out}:{c["key"]}']), (f'combo-{c["key"]}-tee', [f'{out}:{c["key"]}', TEE_OVER])):
        TK.blender('pipeline/tpose/equip.py', '--', '--base', 'Xander', '--name', look, '--pieces', *pieces)
        TK.blender('pipeline/tpose/inspect_look.py', '--', f'Outfits/_looks/{look}', 'Xander')
        rep = json.loads((ROOT / 'Outfits/_looks' / look / '08_inspect/inspect.json').read_text(encoding='utf-8'))
        f = rep.get('fails') or []
        print(f'[legs] {look}: {"PASS" if not f else "FAIL " + "; ".join(f[:2])}', flush=True)
        fails += f
    return f'{out}:{c["key"]}', fails


def collection(path: Path, tex: int, steps):
    from concurrent.futures import ThreadPoolExecutor
    col = json.loads(path.read_text(encoding='utf-8'))['bottoms']
    if 'make' in steps:
        todo = [c for c in col if not (KITS / c['kit'] / 'raw' / 'spec.json').exists()]
        import legging_graphics                                   # brand-style kits: Codex draws only the mark
        with ThreadPoolExecutor(3) as pool:
            list(pool.map(lambda c: legging_graphics.make(c['kit']) if c.get('maker') == 'code'
                          else make(KITS / c['kit'], c['theme']), todo))
    if 'prepare' in steps:
        for c in col:
            prepare(KITS / c['kit'])
    if 'build' not in steps:
        return
    legs, fails = [], []
    for c in col:
        piece, f = build_one(c, tex)
        legs.append(piece)
        fails += f
    if fails:
        sys.exit('[legs] inspection failed; nothing exported')
    tees = json.loads((ROOT / 'Outfits/tee-kits/collection.json').read_text(encoding='utf-8'))['shirts']
    tees = ['tee-' + t['key'].replace('_', '-') + ':' + t['key'] for t in tees]
    TK.export()   # the whole wardrobe from the catalog (catalog.py)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--collection', default=str(KITS / 'collection.json'))
    ap.add_argument('--tex', type=int, default=2048)
    ap.add_argument('--only', default='make,prepare,build')
    a = ap.parse_args()
    collection(Path(a.collection).resolve(), a.tex, a.only.split(','))
