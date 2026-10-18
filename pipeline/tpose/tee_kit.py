"""Texture kits for the fitted tee: one Codex run makes the artwork, the pipeline lays it onto the tee's shared
true-scale sewing pattern (tee_layout.py), so all six variants (sleeveless / short / elbow x standard / crop) come out
of one kit, always aligned, at 2048 px or more.

  1 make      Codex (image generation for the art, code for the fabric maps) writes Outfits/tee-kits/<name>/raw/:
              torso_print.png + sleeve_print.png (the printed fabric for the LONGEST shirt - elbow sleeves, full
              length - which every shorter variant cuts back from; --mode tile: one small repeating pattern_tile.png),
              chest_graphic.png, back_graphic.png (optional), normal_tile.png, roughness_tile.png, spec.json, kit.zip
  2 prepare   checked and cleaned into Outfits/tee-kits/<name>/kit/: the print tile made seamless if its edges do not
              meet, graphics keyed to transparency if they came on a flat background and trimmed, the normal tile
              checked (a procedural knit if it is not a usable normal map), everything resized to true scale
  3 build     shell_garment.py --kit for all six variants, each equipped and inspected alone and over the joggers,
              then exported to web/customizer/assets-test (never published by this script)

Run: python pipeline/tpose/tee_kit.py <name> --theme "funky 70s ..." [--only make,prepare,build|export] [--tex 2048]
     python pipeline/tpose/tee_kit.py --collection Outfits/tee-kits/collection.json   (one design per shirt)
"""
import argparse, json, shutil, subprocess, sys, zipfile
from pathlib import Path
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'pipeline' / 'tpose'))
import tee_layout as TL  # noqa: E402
from s2_images import codex  # noqa: E402

from anmaker_config import BLENDER  # noqa: E402  (this machine's Blender: .anmaker/config.json or a search)
VARIANTS = [(s, h) for s in ('000', '045', '090') for h in ('-2', '6')]
# Every generated (track B) piece in the live wardrobe: a kit export without one would drop it from the customizer.
OTHER_PIECES = ['hoodie-boy:navy_teal_tousled_hair', 'hoodie-boy-tee4:white_crew_neck_tshirt',
                'spoof-sweats:champignon_sweatpants', 'spoof-puffer:monchill_puffer_jacket', 'hoodie-boy-joggers5:olive_cargo_joggers',
                'hoodie-boy-hoodiebag2:black_graphic_hoodie_with_gray_crossbody_bag', 'hoodie-boy:multicolor_high_top_sneakers']
JOGGERS = 'hoodie-boy-joggers5:olive_cargo_joggers'

PROMPT = """You are making a TEXTURE KIT for a fitted crew-neck t-shirt worn by a stylised 3D game character
(Bitmoji / Genies style). The pipeline lays your files onto the shirt's sewing pattern itself, so you only make the
artwork. Theme: {theme}

Write these files into the current folder (and nothing anywhere else). Do not ask questions; make good choices.

1. pattern_tile.png - use your image generation tool. 1024x1024, a SEAMLESS, TILEABLE all-over fabric print that
   covers the whole shirt (front, back and sleeves). It must repeat perfectly left-right and top-bottom with no visible
   seam. Flat print artwork only: no shirt shape, no folds, no lighting or shading, no perspective, no borders, no
   text. Fill the whole square. One repeat covers about {tile_cm} cm of fabric, so keep the motifs bold and readable.
2. chest_graphic.png - use your image generation tool. One bold chest graphic in the same style, centred, on a fully
   transparent background (RGBA PNG). If transparency is impossible, put it on a flat pure #00FF00 background with no
   shadow or glow. No shirt, no mockup, no text unless the theme asks for it.
3. back_graphic.png - optional, the same rules: a large print for the upper back. Skip it if the theme does not need one.
4. normal_tile.png - make it with Python code, not image generation: 1024x1024, seamless, a tangent-space normal map
   of fine cotton jersey knit (OpenGL convention, average colour close to #8080FF, subtle).
5. roughness_tile.png - make it with Python code: 1024x1024, seamless, greyscale, around 0.85 (pixel value ~217)
   with a slight knit variation.
6. spec.json - exactly these keys:
   {{"name": "<short name>", "theme": "<one line>", "base_color": "#rrggbb" (the print's dominant colour),
     "trim_color": "#rrggbb" (collar band: a colour that suits the print), "stitch_color": "#rrggbb",
     "pattern_tile_cm": {tile_cm}, "chest_graphic_width_cm": 16, "back_graphic_width_cm": <number, or null if skipped>,
     "roughness": 0.85, "normal_strength": 0.6}}
7. kit.zip - all of the above files.
"""


FABRIC_PROMPT = """You are making a TEXTURE KIT for a fitted crew-neck t-shirt worn by a stylised 3D game character
(Bitmoji / Genies style). You make the printed FABRIC, laid flat like printed yardage; the pipeline cuts the shirt out
of it, so never draw a shirt, its outline, folds, lighting or perspective. Theme: {theme}

Write these files into the current folder (and nothing anywhere else). Do not ask questions; make good choices.

1. torso_print.png - use your image generation tool, 1536x1024. The fabric for the whole body of the shirt, wrapping
   round it: about 90 cm of fabric wide and 50 cm tall. The CENTRE of the image is the centre front; the LEFT and RIGHT
   edges are the centre back and must join seamlessly (the design continues across that join). Bottom = the hem, top =
   the shoulders. Full-bleed: the design runs off all four edges. A bold, large-scale design with real variety: do NOT
   mirror it, do NOT make a kaleidoscope, and do not repeat a small tile. A separate chest graphic is printed at the
   upper centre and a back graphic at the upper back, so do not put another big focal motif there. No text.
2. sleeve_print.png - use your image generation tool, 1536x1024. The fabric of one sleeve unrolled: about 35 cm round
   the arm and 20 cm down it. The centre is the top of the arm; the LEFT and RIGHT edges meet under the arm and must
   join seamlessly. Top = the shoulder, bottom = the cuff. Same style and colours as the torso, full-bleed, no text.
3. chest_graphic.png - use your image generation tool. One bold chest graphic in the same style, centred, on a fully
   transparent background (RGBA PNG). If transparency is impossible, put it on a flat pure #00FF00 background with no
   shadow or glow. No shirt, no mockup, no text unless the theme asks for it.
4. back_graphic.png - optional, the same rules: a large print for the upper back. Skip it if the theme does not need one.
5. normal_tile.png - make it with Python code, not image generation: 1024x1024, seamless, a tangent-space normal map
   of fine cotton jersey knit (OpenGL convention, average colour close to #8080FF, subtle).
6. roughness_tile.png - make it with Python code: 1024x1024, seamless, greyscale, around 0.85 (pixel value ~217)
   with a slight knit variation.
7. spec.json - exactly these keys:
   {{"name": "<short name>", "theme": "<one line>", "base_color": "#rrggbb" (the print's dominant colour),
     "trim_color": "#rrggbb" (collar band: a colour that suits the print), "stitch_color": "#rrggbb",
     "pattern_tile_cm": 24, "chest_graphic_width_cm": 16, "back_graphic_width_cm": <number, or null if skipped>,
     "roughness": 0.85, "normal_strength": 0.6}}
8. kit.zip - all of the above files.
"""


def make(d: Path, theme: str, tile_cm: float, mode='fabric'):
    raw = d / 'raw'
    raw.mkdir(parents=True, exist_ok=True)
    prompt = FABRIC_PROMPT.format(theme=theme) if mode == 'fabric' else PROMPT.format(theme=theme, tile_cm=tile_cm)
    ok = codex(raw, prompt, [], raw / 'kit.zip', d / 'codex.log', tries=1)
    if not ok and (raw / 'spec.json').exists():
        ok = True                                    # the files are there, only the zip is missing
    if (raw / 'kit.zip').exists() and not (raw / 'chest_graphic.png').exists():
        zipfile.ZipFile(raw / 'kit.zip').extractall(raw)
    need = ('torso_print.png', 'sleeve_print.png') if mode == 'fabric' else ('pattern_tile.png',)
    missing = [f for f in ('spec.json', 'chest_graphic.png', *need) if not (raw / f).exists()]
    if missing:
        sys.exit(f'[kit] Codex did not deliver {missing}; see {d / "codex.log"}')
    print(f'[kit] made: {sorted(p.name for p in raw.iterdir())}', flush=True)


def seam_error(a):
    a = a.astype(float)
    inner_x = np.abs(np.diff(a, axis=1)).mean()
    inner_y = np.abs(np.diff(a, axis=0)).mean()
    return max(np.abs(a[:, 0] - a[:, -1]).mean() / max(inner_x, 1e-6), np.abs(a[0] - a[-1]).mean() / max(inner_y, 1e-6))


def make_seamless(a):
    """Cross-fade the tile with itself shifted by half a repeat, weighted so the shifted copy covers the edges."""
    h, w = a.shape[:2]
    sh = np.roll(np.roll(a, h // 2, 0), w // 2, 1).astype(float)
    yy, xx = np.mgrid[0:h, 0:w]
    dx = np.minimum(xx, w - 1 - xx) / (w / 2)
    dy = np.minimum(yy, h - 1 - yy) / (h / 2)
    wt = np.clip(np.minimum(dx, dy) * 4, 0, 1)[..., None]     # 0 at the edges, 1 from 1/8 of the way in
    return (a.astype(float) * wt + sh * (1 - wt)).astype(np.uint8)


def wrap_error(a):
    a = a.astype(float)
    inner = np.abs(np.diff(a, axis=1)).mean()
    return np.abs(a[:, 0] - a[:, -1]).mean() / max(inner, 1e-6)


def make_wrap(a):
    """Make the left and right edges meet: within 5% of each edge, cross-fade toward the image rolled by half its width
    (whose edges are the image's own neighbouring middle columns, so they continue across the join)."""
    h, w = a.shape[:2]
    sh = np.roll(a, w // 2, 1).astype(float)
    xx = np.arange(w)
    t = np.clip(np.minimum(xx, w - 1 - xx) / (0.05 * w), 0, 1)
    wt = (t * t * (3 - 2 * t))[None, :, None]
    return (a.astype(float) * wt + sh * (1 - wt)).astype(np.uint8)


def knit_normal(n=512):
    """A procedural cotton-jersey normal tile (rows of small V stitches), seamless by construction."""
    yy, xx = np.mgrid[0:n, 0:n] / n
    cols, rows = 48, 64
    u = (xx * cols) % 1.0
    v = (yy * rows + 0.5 * np.abs(u - 0.5)) % 1.0
    hgt = np.sin(np.pi * u) ** 2 * (0.6 + 0.4 * np.cos(2 * np.pi * v))
    gx = (np.roll(hgt, -1, 1) - np.roll(hgt, 1, 1)) * 0.5
    gy = (np.roll(hgt, -1, 0) - np.roll(hgt, 1, 0)) * 0.5
    nrm = np.stack([-gx * 3, gy * 3, np.ones_like(hgt)], -1)
    nrm /= np.linalg.norm(nrm, axis=-1, keepdims=True)
    return ((nrm * 0.5 + 0.5) * 255).astype(np.uint8)


def key_graphic(im: Image.Image):
    """RGBA with real transparency: keep a usable alpha, otherwise key out the flat background colour, then trim."""
    a = np.array(im.convert('RGBA')).astype(float)
    if (a[..., 3] < 250).mean() < 0.02:                         # no usable alpha: key the border colour
        border = np.concatenate([a[0, :, :3], a[-1, :, :3], a[:, 0, :3], a[:, -1, :3]])
        bg = np.median(border, 0)
        dist = np.linalg.norm(a[..., :3] - bg, axis=-1)
        a[..., 3] = np.clip((dist - 30) / 40, 0, 1) * 255
        if np.linalg.norm(bg - [0, 255, 0]) < 80:                # despill a green screen
            g = a[..., 1]
            a[..., 1] = np.minimum(g, np.maximum(a[..., 0], a[..., 2]) + 10)
    ys, xs = np.nonzero(a[..., 3] > 8)
    if len(xs) == 0:
        raise SystemExit('[kit] graphic is empty after keying')
    a = a[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    return Image.fromarray(a.clip(0, 255).astype(np.uint8), 'RGBA')


def prepare(d: Path, tex: int, tile_cm=None):
    raw, kit = d / 'raw', d / 'kit'
    kit.mkdir(exist_ok=True)
    spec = json.loads((raw / 'spec.json').read_text(encoding='utf-8'))
    if tile_cm:                                                   # art direction: the print's scale on the shirt
        spec['pattern_tile_cm'] = tile_cm
    ppm = TL.px_per_m(tex)
    tile_m = float(spec.get('pattern_tile_cm') or 12) / 100
    tile_px = max(64, int(round(tile_m * ppm * 2)))              # 2x the texture's density: sharp after sampling
    if (raw / 'pattern_tile.png').exists() and not (raw / 'torso_print.png').exists():
        pat = np.array(Image.open(raw / 'pattern_tile.png').convert('RGB'))
        err = seam_error(pat)
        if err > 1.6:
            pat = make_seamless(pat)
            print(f'[kit] pattern tile edges did not meet (seam {err:.1f}x its own detail): blended seamless', flush=True)
        Image.fromarray(pat).resize((tile_px, tile_px), Image.LANCZOS).save(kit / 'pattern_tile.png')
    for nm in ('torso_print', 'sleeve_print'):  # full-size fabric for the longest shirt: wraps left-right only
        if (raw / f'{nm}.png').exists():
            fab = np.array(Image.open(raw / f'{nm}.png').convert('RGB'))
            err = wrap_error(fab)
            if err > 1.6:
                fab = make_wrap(fab)
                print(f'[kit] {nm}: left and right edges did not meet (seam {err:.1f}x its own detail): blended across the join', flush=True)
            Image.fromarray(fab).resize((fab.shape[1] * 2, fab.shape[0] * 2), Image.LANCZOS).save(kit / f'{nm}.png')
    nrm = None
    if (raw / 'normal_tile.png').exists():
        n = np.array(Image.open(raw / 'normal_tile.png').convert('RGB')).astype(float)
        mean = n.reshape(-1, 3).mean(0)
        if abs(mean[0] - 128) < 20 and abs(mean[1] - 128) < 20 and mean[2] > 200:
            nrm = n.astype(np.uint8)
        else:
            print(f'[kit] normal_tile is not a usable normal map (mean {mean.round()}): procedural knit instead', flush=True)
    if nrm is None:
        nrm = knit_normal()
    Image.fromarray(nrm).resize((tile_px, tile_px), Image.LANCZOS).save(kit / 'normal_tile.png')
    if (raw / 'roughness_tile.png').exists():
        Image.open(raw / 'roughness_tile.png').convert('L').resize((tile_px, tile_px), Image.LANCZOS).convert('RGB').save(kit / 'roughness_tile.png')
    # graphics are projected flat onto the chest / upper back: no wider than those areas (about 18 / 22 cm on Xander)
    for wkey, cap in (('chest_graphic_width_cm', 18), ('back_graphic_width_cm', 22)):
        if spec.get(wkey) and float(spec[wkey]) > cap:
            print(f'[kit] {wkey} {spec[wkey]} -> {cap} (wider would run off the panel)', flush=True)
            spec[wkey] = cap
    for g, wkey in (('chest_graphic', 'chest_graphic_width_cm'), ('back_graphic', 'back_graphic_width_cm')):
        if (raw / f'{g}.png').exists() and spec.get(wkey):
            im = key_graphic(Image.open(raw / f'{g}.png'))
            wpx = int(round(float(spec[wkey]) / 100 * ppm * 2))
            im.resize((wpx, max(1, int(round(wpx * im.height / im.width)))), Image.LANCZOS).save(kit / f'{g}.png')
        elif g == 'back_graphic':
            spec[wkey] = None
    (kit / 'spec.json').write_text(json.dumps(spec, indent=2), encoding='utf-8')
    print(f'[kit] prepared {kit}: tile {tile_px}px for {tile_m * 100:.0f} cm, {sorted(p.name for p in kit.iterdir())}', flush=True)


def blender(*args):
    r = subprocess.run([BLENDER, '-b', '--factory-startup', '-P', *args], cwd=ROOT, capture_output=True, text=True,
                       encoding='utf-8', errors='replace')
    if 'Traceback' in r.stdout + r.stderr or r.returncode:
        sys.exit(f'[kit] blender failed: {args[0]}\n' + (r.stdout + r.stderr)[-3000:])
    return r.stdout


def build(d: Path, tex: int):
    fails = []
    for s, h in VARIANTS:
        key, out = f'template_tee_s{s}_h{h}', f'template-tee-s{s}-h{h}'
        blender('pipeline/tpose/shell_garment.py', '--', '--base', 'Xander', '--out', f'Outfits/{out}', '--key', key,
                '--sleeve', str(int(s) / 100), '--hem-cm', h, '--kit', str(d / 'kit'), '--tex', str(tex))
        for look, pieces in ((f'web-{key}', [f'{out}:{key}']), (f'combo-{key}-jog', [f'{out}:{key}', JOGGERS])):
            blender('pipeline/tpose/equip.py', '--', '--base', 'Xander', '--name', look, '--pieces', *pieces)
            blender('pipeline/tpose/inspect_look.py', '--', f'Outfits/_looks/{look}', 'Xander')
            rep = json.loads((ROOT / 'Outfits/_looks' / look / '08_inspect/inspect.json').read_text(encoding='utf-8'))
            f = rep.get('fails') or []
            print(f'[kit] {look}: {"PASS" if not f else "FAIL " + "; ".join(f[:2])}', flush=True)
            fails += f
    if fails:
        sys.exit('[kit] inspection failed; nothing exported')
    export()


def build_shirt(d: Path, key: str, sleeve: float, hem_cm: float, tex: int):
    """One shirt of a collection: its own key and outfit folder (Outfits/tee-<key>), built and inspected alone and
    over the joggers. Returns the inspection failures."""
    out = 'tee-' + key.replace('_', '-')
    blender('pipeline/tpose/shell_garment.py', '--', '--base', 'Xander', '--out', f'Outfits/{out}', '--key', key,
            '--sleeve', str(sleeve), '--hem-cm', str(hem_cm), '--kit', str(d / 'kit'), '--tex', str(tex))
    fails = []
    for look, pieces in ((f'web-{key}', [f'{out}:{key}']), (f'combo-{key}-jog', [f'{out}:{key}', JOGGERS])):
        blender('pipeline/tpose/equip.py', '--', '--base', 'Xander', '--name', look, '--pieces', *pieces)
        blender('pipeline/tpose/inspect_look.py', '--', f'Outfits/_looks/{look}', 'Xander')
        rep = json.loads((ROOT / 'Outfits/_looks' / look / '08_inspect/inspect.json').read_text(encoding='utf-8'))
        f = rep.get('fails') or []
        print(f'[kit] {look}: {"PASS" if not f else "FAIL " + "; ".join(f[:2])}', flush=True)
        fails += f
    return f'{out}:{key}', fails


def collection(path: Path, tex: int):
    """A collection of shirts, one design each (each its own customizer tile): make the missing kits (Codex, three at
    a time), prepare them, build and inspect every shirt, then export them all together."""
    from concurrent.futures import ThreadPoolExecutor
    col = json.loads(path.read_text(encoding='utf-8'))['shirts']
    kits = ROOT / 'Outfits' / 'tee-kits'
    todo = [c for c in col if not (kits / c['kit'] / 'raw' / 'spec.json').exists()]
    import tee_graphics                                            # exact logos / set type: drawn by code, not Codex
    for c in [c for c in todo if c.get('maker') == 'code']:
        tee_graphics.make(c['kit'])
    with ThreadPoolExecutor(3) as pool:
        list(pool.map(lambda c: make(kits / c['kit'], c['theme'], 24, 'fabric'), [c for c in todo if c.get('maker') != 'code']))
    for c in col:
        prepare(kits / c['kit'], tex)
    tees, fails = [], []
    for c in col:
        piece, f = build_shirt(kits / c['kit'], c['key'], c['sleeve'], c['hem_cm'], tex)
        tees.append(piece)
        fails += f
    if fails:
        sys.exit('[kit] inspection failed; nothing exported')
    export()  # the whole wardrobe from the catalog (the collection's tees included)


def export(specs=None):
    """Export the whole wardrobe (catalog.py: every published piece, in tile order) to assets-test."""
    import catalog
    specs = specs or catalog.all_specs()
    out = ROOT / 'web/customizer/assets-test'
    blender('pipeline/web/export_web.py', '--', '--base', 'Xander', '--out', str(out), '--pieces', *specs)
    cmds = [['pipeline/web/glb_to_gltf.py', str(out)]]
    if (ROOT / 'GeniesStarterPack-main').exists():   # face masks and the feminine body come from the Genies pack: they
        cmds += [['pipeline/web/build_face_masks.py', '--out', str(out)],          # only change with the body, so a
                 ['pipeline/web/build_feminine.py', '--out', str(out)]]            # machine without the pack keeps them
    for cmd in cmds:
        subprocess.run([sys.executable, *cmd], cwd=ROOT, check=True, capture_output=True)
    print(f'[kit] exported {len(specs)} pieces to {out} (not published)', flush=True)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('name', nargs='?')
    ap.add_argument('--collection', default='', help='a collection file (Outfits/tee-kits/collection.json): one design per shirt')
    ap.add_argument('--theme', default='')
    ap.add_argument('--tile-cm', type=float, default=None, help='print repeat size on the shirt (default 24 cm)')
    ap.add_argument('--tex', type=int, default=2048)
    ap.add_argument('--only', default='make,prepare,build')
    ap.add_argument('--mode', default='fabric', choices=['fabric', 'tile'],
                    help='fabric: full-size printed fabric for the longest shirt (default); tile: a small repeating tile')
    a = ap.parse_args()
    if a.collection:
        collection(Path(a.collection).resolve(), a.tex)
        sys.exit(0)
    d = ROOT / 'Outfits' / 'tee-kits' / a.name
    steps = a.only.split(',')
    if 'make' in steps:
        if not a.theme and not (d / 'raw' / 'spec.json').exists():
            sys.exit('--theme is needed to make a kit')
        make(d, a.theme, a.tile_cm or 24, a.mode)
    if 'prepare' in steps:
        prepare(d, a.tex, a.tile_cm)
    if 'build' in steps:
        build(d, a.tex)
    elif 'export' in steps:
        export()
