"""Steps 2-3 - image work through the local Codex CLI (image generation billed to the ChatGPT subscription).

  2a  read the concept and list the wearable pieces            -> outfit.json
  2b  dress the step-1 mannequin render in the concept outfit  -> 02_dressed/{front,back}.png
  3   one image per piece, alone, at the same place on canvas  -> 03_garments/{front,back}_<key>.png

Run: python pipeline/tpose/s2_images.py <outfit_dir> [--only 2a,2b,3] [--keys hoodie,shoes]
Every call is skipped when its output already exists, so a rerun only redoes what is missing.
"""
import argparse, json, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

SLOTS = ['hair', 'top', 'outerwear', 'bottom', 'fullbody', 'legwear', 'footwear', 'headwear', 'hands', 'accessory']
CANVAS = 'the same 1024x1536 portrait canvas'


def codex(cwd: Path, prompt: str, images, expect: Path, log: Path, tries=2):
    """Run one non-interactive Codex session; succeed only if `expect` was written."""
    if expect.exists():
        return True
    for attempt in range(1, tries + 1):
        cmd = ['codex', 'exec', '--skip-git-repo-check', '--sandbox', 'workspace-write']
        for im in images:
            cmd += ['-i', str(im)]
        cmd += ['-']
        t0 = time.time()
        with open(log, 'a', encoding='utf-8') as fh:
            fh.write(f'\n===== {expect.name} attempt {attempt}\n')
            fh.flush()
            subprocess.run(cmd, input=prompt, text=True, cwd=cwd, stdout=fh, stderr=subprocess.STDOUT,
                           encoding='utf-8', timeout=900, shell=sys.platform == 'win32')
        ok = expect.exists()
        print(f'[codex] {expect.relative_to(cwd)}: {"ok" if ok else "MISSING"} ({time.time() - t0:.0f}s)', flush=True)
        if ok:
            return True
    return False


def list_pieces(d: Path, log: Path):
    out = d / 'outfit.json'
    prompt = f"""Image 1 is a concept of a character's outfit. Do NOT generate any image.
List the separate wearable pieces a game character customiser would need, including the hairstyle if hair is
visible. Treat a pair of shoes as ONE item. Write the list to ./outfit.json (UTF-8), exactly this JSON shape:
{{"pieces": [{{"key": "snake_case_name", "slot": "<one of {', '.join(SLOTS)}>",
  "description": "one sentence: colours, materials, cut, prints, length"}}]}}
Order them from the innermost layer to the outermost. Reply with only the path."""
    codex(d, prompt, [d / 'concept.png'], out, log)
    return json.loads(out.read_text(encoding='utf-8'))['pieces']


def dress(d: Path, pieces, log: Path):
    outfit = '; '.join(f"{p['key']}: {p['description']}" for p in pieces)
    rules = f"""Keep EVERYTHING about the character from the mannequin image: same face, same body, same proportions,
same T-pose with both arms straight out horizontally, same camera and framing, same position and size in the frame,
{CANVAS}, plain pure white background, same 3D render style. Do not move, scale, rotate or crop the character.
The clothes must be worn by THIS body in THIS T-pose: each sleeve is its own tube around a horizontal arm with clear
white space between sleeve and torso under the arm; hands stay visible coming out of the sleeves; trouser legs
follow the legs with a gap between them; shoes on the feet. Outfit pieces: {outfit}."""
    (d / '02_dressed').mkdir(exist_ok=True)
    front = d / '02_dressed' / 'front.png'
    codex(d, f"""Use your image generation tool. Image 1 is the mannequin (front view). Image 2 is the outfit concept.
Generate ONE image: image 1 wearing the outfit and hairstyle from image 2. {rules}
Save the image as ./02_dressed/front.png. Reply with only the saved path.""",
          [d / '01_mannequin' / 'front.png', d / 'concept.png'], front, log)
    side = (" The arms are in a T-pose, so from this side they point STRAIGHT AT THE CAMERA: they appear only as "
            "short foreshortened shapes at the shoulders exactly as in image 1 (one arm hidden behind the body) - "
            "never reaching forward or sideways across the image.")
    seen = {'back': 'from BEHIND',
            'left': "from the character's LEFT side (the character faces the LEFT edge of the image)." + side,
            'right': "from the character's RIGHT side (the character faces the RIGHT edge of the image)." + side}
    jobs = []
    for view, how in seen.items():
        out = d / '02_dressed' / f'{view}.png'
        jobs.append((f"""Use your image generation tool. Image 1 is the mannequin seen {how}. Image 2 is the same character
dressed, seen from the front. Image 3 is the outfit concept.
Generate ONE image: image 1 ({view} view, exactly this camera and framing) wearing exactly the outfit and hairstyle of
image 2, as it looks {how}. Every piece must match image 2 in shape, length, colours and details.
{rules}
Save the image as ./02_dressed/{view}.png. Reply with only the saved path.""",
                     [d / '01_mannequin' / f'{view}.png', front, d / 'concept.png'], out))
    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(lambda j: codex(d, j[0], j[1], j[2], log), jobs))


def in_place(piece_png: Path, dressed_png: Path, need_inside=0.85, height_tol=0.25, slot=None):
    """A piece image must stay where it was in the dressed image:
      inside - share of its pixels inside the dressed figure's outline (dilated a few px)
      height - for side/back views, its height must match its FRONT-view height within height_tol (all cameras are
               orthographic at one scale, so an enlarged or shrunk piece shows up here even when hidden parts were
               completed differently)"""
    import numpy as np
    from PIL import Image, ImageFilter
    sys.path.insert(0, str(Path(__file__).parent))
    from s5_place import background_mask
    piece, _ = background_mask(piece_png)
    dressed, _ = background_mask(dressed_png)
    dil = np.asarray(Image.fromarray(dressed.astype(np.uint8) * 255).filter(ImageFilter.MaxFilter(9))) > 127
    inside = float((piece & dil).sum() / max(piece.sum(), 1))
    ratio = 1.0
    front_png = piece_png.with_name('front_' + piece_png.name.split('_', 1)[1])
    # Hair is exempt: from the front the head hides the hair behind it, so its front outline is legitimately shorter.
    if slot not in ('hair', 'headwear') and not piece_png.name.startswith('front_') and front_png.exists():
        fm, _ = background_mask(front_png)
        h = lambda m: np.ptp(np.nonzero(m.any(1))[0]) + 1
        ratio = float(h(piece) / h(fm))
    ok = inside >= need_inside and abs(ratio - 1) <= height_tol
    return ok, (round(inside, 3), round(ratio, 3))


def split(d: Path, pieces, log: Path, keys=None, views=('front', 'left', 'back', 'right')):
    (d / '03_garments').mkdir(exist_ok=True)
    jobs = []
    for view in views:
        for p in pieces:
            if keys and p['key'] not in keys:
                continue
            out = d / '03_garments' / f"{view}_{p['key']}.png"
            prompt = f"""Use your image generation tool. Image 1 is a dressed character ({view} view) on a white background.
Generate ONE image that shows ONLY this piece: {p['key']} - {p['description']}.
It must stay exactly where it is in image 1: same pixel position, same size, same shape, same T-pose drape, as if
worn by an invisible body ("ghost mannequin"). Generate it with a TRANSPARENT background (alpha channel): remove
everything else - skin, head, face, hands and every other piece of clothing - so it is fully transparent, including
any gaps enclosed by the piece (for example inside a strap loop). Where the body or other pieces hid part of this
piece, complete it naturally (for example the inside of a collar or the part of a waistband under a top).
{CANVAS}, same 3D render style, no shadows. Save a PNG with alpha.
Save the image as ./03_garments/{out.name}. Reply with only the saved path."""
            jobs.append((prompt, [d / '02_dressed' / f'{view}.png'], out, p['slot']))

    def run(job, tries=3):
        prompt, images, out, slot = job
        for attempt in range(tries):
            if not codex(d, prompt, images, out, log):
                return
            ok, (inside, height) = in_place(out, images[0], slot=slot)
            print(f'[check] {out.name}: {inside:.0%} inside the dressed outline, height x{height:.2f} of front '
                  f'-> {"ok" if ok else "REDO"}', flush=True)
            if ok:
                return
            out.rename(out.with_name(f'_rejected_{attempt}_{out.name}'))
            prompt += ("\nIMPORTANT: a previous attempt moved or enlarged the piece. Keep it at EXACTLY the same pixel "
                       "position and size as in image 1 - do not zoom, centre or enlarge it.")
    # Front views first: the other views are checked against them.
    for phase in (lambda j: j[2].name.startswith('front_'), lambda j: not j[2].name.startswith('front_')):
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(run, [j for j in jobs if phase(j)]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('outfit_dir')
    ap.add_argument('--only', default='2a,2b,3')
    ap.add_argument('--keys', default='')
    a = ap.parse_args()
    d = Path(a.outfit_dir).resolve()
    log = d / 'codex.log'
    steps = set(a.only.split(','))
    pieces = list_pieces(d, log)
    print('[pieces]', json.dumps(pieces, indent=1), flush=True)
    if '2b' in steps:
        dress(d, pieces, log)
    if '3' in steps:
        split(d, pieces, log, set(filter(None, a.keys.split(','))))


if __name__ == '__main__':
    main()
