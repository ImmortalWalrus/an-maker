"""Image generation that works on any machine, whichever assistant (harness) runs the pipeline.

Every image step in the pipeline is a job: a prompt, input images, and the file it must produce. Who does it:
  codex       the Codex CLI (`codex exec`), billed to a ChatGPT plan: free per image. Used inside Codex, or anywhere
              the Codex CLI is installed and signed in.
  assethub    paid per image: GPT Image 2.5 on AssetHub (about 10 credits an image), with the person's own account.
  higgsfield  paid per image: a GPT Image / Nano Banana model on Higgsfield, with the person's own account.
Chosen by `garment.py setup --images ...` (.anmaker/config.json 'images'), or the AN_IMAGES env var.

For a paid provider the job is done here, without an agent: a one-image job becomes one call, with the input images
as references in the same order (portrait canvases are padded to 3:4 and cropped back, so the framing holds), and a
"texture kit" job (kit.zip: prints made by image generation, knit tiles and spec.json made by code) is assembled
item by item. A green #00FF00 background asked for in place of transparency is keyed out to real transparency.
"""
import json, os, re, shutil, subprocess, sys, uuid, zipfile
from pathlib import Path
import numpy as np
from PIL import Image

import anmaker_config as CFG

AH_MODEL = 'imageGen.gptImage25Sunburst.openrouter'   # precision image editing, up to 6 references
AH_COST = 10
RATIOS = {'1:1': 1.0, '4:3': 4 / 3, '3:4': 3 / 4, '16:9': 16 / 9, '9:16': 9 / 16}


def backend():
    return os.environ.get('AN_IMAGES') or CFG.load().get('images') or 'codex'


def cost_per_image(b=None):
    b = b or backend()
    return 0 if b == 'codex' else AH_COST if b == 'assethub' else 10


def say(msg):
    print(f'[image] {msg}', flush=True)


def _cli(exe, args, timeout=1800):
    r = subprocess.run([exe, *args], capture_output=True, text=True, encoding='utf-8', timeout=timeout,
                       shell=sys.platform == 'win32')
    txt = (r.stdout or '') + (r.stderr or '')
    j = None
    try:
        j = json.loads(r.stdout)
    except (ValueError, TypeError):
        m = re.search(r'\{.*\}', r.stdout or '', re.S)
        if m:
            try:
                j = json.loads(m.group(0))
            except ValueError:
                pass
    return r.returncode, j, txt


# ---------------------------------------------------------------- one paid image
def _ratio_for(w, h):
    return min(RATIOS, key=lambda k: abs(np.log(RATIOS[k] / (w / h))))


def _fit(img: Image.Image, ratio: float, fill=(255, 255, 255)):
    """Pad an image to the aspect ratio (centred). Returns the padded image and the box the original occupies."""
    w, h = img.size
    if abs(w / h - ratio) < 1e-3:
        return img, (0, 0, w, h)
    if w / h < ratio:
        W, H = round(h * ratio), h
    else:
        W, H = w, round(w / ratio)
    out = Image.new(img.mode, (W, H), fill if img.mode == 'RGB' else fill + (255,))
    x, y = (W - w) // 2, (H - h) // 2
    out.paste(img, (x, y))
    return out, (x, y, x + w, y + h)


def _key_green(img: Image.Image):
    a = np.asarray(img.convert('RGB')).astype(float)
    g = a[..., 1] - np.maximum(a[..., 0], a[..., 2])                       # how green, beyond the other channels
    alpha = np.clip(1 - (g - 40) / 80, 0, 1)                                # >120 green-dominant: gone
    a[..., 1] = np.minimum(a[..., 1], np.maximum(a[..., 0], a[..., 2]) + 10)  # despill the edges
    return Image.fromarray(np.dstack([a, alpha * 255]).astype(np.uint8), 'RGBA')


def _credits(b):
    if b == 'assethub':
        _, j, _ = _cli('assethub', ['api', 'call', 'GET /account'], 120)
        try:
            return float(j['data']['availableBalance'])
        except Exception:
            return None
    _, j, _ = _cli('higgsfield', ['account', 'status', '--json'], 120)
    try:
        return float(j['credits'])
    except Exception:
        return None


def _hf_model():
    _, j, txt = _cli('higgsfield', ['model', 'list', '--image', '--json'], 120)
    ids = re.findall(r'"(?:id|name|model)"\s*:\s*"([^"]+)"', json.dumps(j) if j else txt)
    for want in ('gpt_image', 'gpt-image', 'nano_banana', 'nano-banana', 'seedream'):
        for i in ids:
            if want in i.lower():
                return i
    return ids[0] if ids else None


def paid_image(prompt, refs, out: Path, size=None, transparent=False, log: Path = None):
    """One image from `prompt`, with `refs` as reference images (in order), saved as `out` at `size` (w, h)."""
    b = backend()
    work = out.parent / f'_img_{out.stem}'
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    refs = [Path(r) for r in refs]
    if size is None:
        size = Image.open(refs[0]).size if refs else (1024, 1024)
    ratio_key = _ratio_for(*size)
    up = []
    for i, r in enumerate(refs):                                            # pad references to the output ratio
        im = Image.open(r).convert('RGB')
        im, _ = _fit(im, RATIOS[ratio_key])
        p = work / f'ref{i + 1}.png'
        im.save(p)
        up.append(p)
    if transparent:
        prompt += ('\nThe background must be a flat, pure #00FF00 green, edge to edge, with no shadow, glow or '
                   'gradient; nothing in the design uses that green.')
    have, cost = _credits(b), cost_per_image(b)
    if have is not None and have < cost:
        say(f'NOT ENOUGH CREDITS on {b}: {have:g} left, an image costs about {cost}')
        return False
    say(f'{out.name}: {b} image generation (about {cost} credits)')
    got = None
    if b == 'assethub':
        ids = []
        for p in up:
            _, j, txt = _cli('assethub', ['files', 'upload', str(p), '--media-type', 'image'], 300)
            if not j or 'uploadId' not in j:
                (log or work / 'log.txt').write_text(txt, encoding='utf-8')
                return False
            ids.append(j['uploadId'])
        req = {'modelId': AH_MODEL, 'prompt': prompt, 'aspectRatio': ratio_key, 'batchSize': 1}
        if ids:
            req['sources'] = [{'uploadId': i} for i in ids]
        (work / 'request.json').write_text(json.dumps(req, indent=1), encoding='utf-8')
        _, j, txt = _cli('assethub', ['api', 'call', 'POST /image/generate', '--input-json', '@' + str(work / 'request.json'),
                                      '--operation-id', str(uuid.uuid4())])
        job = j and (j.get('jobId') or (j.get('data') or {}).get('jobId') or (j.get('job') or {}).get('id'))
        if not job:
            (log or work / 'log.txt').write_text(txt, encoding='utf-8')
            say(f'{out.name}: request refused - {txt[-300:]}')
            return False
        _, _, txt2 = _cli('assethub', ['jobs', 'watch', job, '--timeout-ms', str(15 * 60 * 1000), '--download',
                                       '--out-dir', str(work / 'dl')])
        pics = [p for p in (work / 'dl').rglob('*') if p.suffix.lower() in ('.png', '.jpg', '.jpeg', '.webp')]
        got = pics[0] if pics else None
        if log:
            log.write_text(txt + '\n' + txt2, encoding='utf-8')
    else:
        model = _hf_model()
        if not model:
            say('could not list Higgsfield image models (signed in?  higgsfield auth login)')
            return False
        args = ['generate', 'create', model, '--prompt', prompt, '--aspect_ratio', ratio_key]
        for p in up:
            args += ['--image-references', str(p)]
        code, _, txt = _cli('higgsfield', [*args, '--wait', '--wait-timeout', '15m', '--json'])
        urls = re.findall(r'https://[^\s"\']+\.(?:png|jpe?g|webp)[^\s"\']*', txt)
        if log:
            log.write_text(txt, encoding='utf-8')
        if urls:
            import urllib.request
            got = work / 'out.png'
            urllib.request.urlretrieve(urls[0], got)
    if not got:
        say(f'{out.name}: generation failed (see {log or work})')
        return False
    im = Image.open(got).convert('RGB')                                     # back to the asked size and framing
    W, H = im.size
    tw, th = size
    if abs(W / H - tw / th) > 1e-2:                                         # crop the padding added for the ratio
        if W / H > tw / th:
            nw = round(H * tw / th); im = im.crop(((W - nw) // 2, 0, (W - nw) // 2 + nw, H))
        else:
            nh = round(W * th / tw); im = im.crop((0, (H - nh) // 2, W, (H - nh) // 2 + nh))
    im = im.resize((tw, th), Image.LANCZOS)
    if transparent:
        im = _key_green(im)
    out.parent.mkdir(parents=True, exist_ok=True)
    im.save(out)
    shutil.rmtree(work, ignore_errors=True)
    say(f'{out.name}: ok')
    return True


# ---------------------------------------------------------------- whole jobs
TOOL_LINE = re.compile(r'Use your image generation tool[^.]*\.\s*', re.I)
SAVE_LINE = re.compile(r'(Save the image as|Reply with only)[^\n]*', re.I)


def _clean(prompt):
    p = TOOL_LINE.sub('', prompt)
    p = SAVE_LINE.sub('', p)
    p = re.sub(r'If transparency is impossible[^.]*\.', '', p)
    p = re.sub(r'(Write these files|Do not ask questions)[^.]*\.', '', p)
    return p.strip()


def _knit_normal(n=1024, strength=1.0, seed=0):
    rng = np.random.default_rng(seed)
    y, x = np.mgrid[0:n, 0:n] / n * 2 * np.pi
    h = 0.5 * np.sin(x * 96) * (0.6 + 0.4 * np.sin(y * 192)) + 0.3 * np.sin(y * 96 + np.sin(x * 96))
    f = np.fft.fft2(rng.normal(size=(n, n)))
    k = np.hypot(*np.meshgrid(np.fft.fftfreq(n), np.fft.fftfreq(n)))
    h += 0.4 * np.real(np.fft.ifft2(f * np.exp(-(k / 0.05) ** 2)))           # soft, seamless irregularity
    gx = (np.roll(h, -1, 1) - np.roll(h, 1, 1)) * strength
    gy = (np.roll(h, -1, 0) - np.roll(h, 1, 0)) * strength
    nrm = np.dstack([-gx, gy, np.ones_like(h) * 4])
    nrm /= np.linalg.norm(nrm, axis=2, keepdims=True)
    return Image.fromarray(((nrm * 0.5 + 0.5) * 255).astype(np.uint8), 'RGB')


def _rough(n=1024, value=217, seed=1):
    rng = np.random.default_rng(seed)
    f = np.fft.fft2(rng.normal(size=(n, n)))
    k = np.hypot(*np.meshgrid(np.fft.fftfreq(n), np.fft.fftfreq(n)))
    v = np.real(np.fft.ifft2(f * np.exp(-(k / 0.08) ** 2)))
    v = value + 8 * v / (np.abs(v).max() + 1e-9)
    return Image.fromarray(np.clip(v, 0, 255).astype(np.uint8), 'L')


def _palette(png: Path):
    im = Image.open(png).convert('RGB').resize((128, 128))
    q = im.quantize(6)
    raw = q.getpalette()
    pal = np.array(raw[:len(raw) // 3 * 3]).reshape(-1, 3)
    counts = np.bincount(np.asarray(q).ravel(), minlength=len(pal))[:len(pal)]
    order = np.argsort(-counts)
    return [pal[i] for i in order if counts[i]]


def _hex(c):
    return '#%02x%02x%02x' % tuple(int(v) for v in np.clip(c, 0, 255))


def kit_job(cwd: Path, prompt: str, log: Path):
    """A texture kit (tee_kit / legging_kit prompt): each numbered file in the prompt, made by paid image generation
    or by code, then spec.json and kit.zip."""
    header = prompt.split('\n1. ')[0]
    theme = (re.search(r'Theme:\s*(.*)', header) or re.search(r'theme[^:]*:\s*(.*)', header, re.I))
    theme = theme.group(1).strip() if theme else ''
    items = re.findall(r'^(\d+)\. (\S+) - (.*?)(?=^\d+\. |\Z)', prompt, re.M | re.S)
    made = []
    for _, name, text in items:
        text = ' '.join(text.split())
        f = cwd / name
        if f.exists():
            made.append(f)
            continue
        if 'image generation tool' in text:
            if text.lower().startswith('optional'):
                continue
            m = re.search(r'(\d{3,4})x(\d{3,4})', text)
            size = (int(m.group(1)), int(m.group(2))) if m else (1024, 1024)
            body = _clean(re.sub(r'use your image generation tool,?\s*(\d+x\d+\.)?', '', text, flags=re.I)).lstrip('. ')
            transparent = 'transparent' in text.lower()
            if not paid_image(f'{_clean(header)}\n\nMake this one image, {name.split(".")[0].replace("_", " ")}: {body}',
                              [], f, size, transparent, log.with_name(f'{f.stem}.log')):
                return False
            made.append(f)
        elif name.startswith('normal'):
            s = float((re.search(r'normal_strength":\s*([\d.]+)', prompt) or [0, 0.6])[1])
            _knit_normal(1024, 0.6 + s).save(f); made.append(f)
        elif name.startswith('roughness'):
            v = int((re.search(r'pixel value ~(\d+)', text) or [0, 217])[1])
            _rough(1024, v).save(f); made.append(f)
    tmpl = prompt[prompt.index('spec.json'):]
    tmpl = tmpl[tmpl.index('{'):tmpl.rindex('}') + 1]
    main = next((p for p in made if p.suffix == '.png' and 'tile' not in p.name and 'graphic' not in p.name), None)
    pal = _palette(main) if main else [np.array([128, 128, 128])]
    base = pal[0]
    trim = min(pal[1:] or [base * 0.5], key=lambda c: c.sum())               # the darkest other colour
    spec = {}
    keys = re.findall(r'"(\w+)":', tmpl)
    for i, k in enumerate(keys):
        after = tmpl[tmpl.index(f'"{k}":') + len(k) + 3:]
        if i + 1 < len(keys):
            after = after[:after.index(f'"{keys[i + 1]}":')]
        v = after.strip().rstrip(',}').strip()
        if k == 'name':
            spec[k] = ' '.join(theme.split()[:4]).title() or 'Kit'
        elif k == 'theme':
            spec[k] = theme
        elif k == 'base_color':
            spec[k] = _hex(base)
        elif k == 'trim_color':
            spec[k] = _hex(trim)
        elif k == 'stitch_color':
            spec[k] = _hex(np.clip(trim * 0.6 + 255 * 0.4, 0, 255))
        elif k == 'back_graphic_width_cm':
            spec[k] = 26 if (cwd / 'back_graphic.png').exists() else None
        else:
            num = re.match(r'-?\d+(\.\d+)?', v)
            spec[k] = json.loads(num.group(0)) if num else v.strip('"')
    (cwd / 'spec.json').write_text(json.dumps(spec, indent=2), encoding='utf-8')
    with zipfile.ZipFile(cwd / 'kit.zip', 'w') as z:
        for p in [*made, cwd / 'spec.json']:
            z.write(p, p.name)
    say(f'kit made: {sorted(p.name for p in made)} + spec.json')
    return True


def job(cwd: Path, prompt: str, images, expect: Path, log: Path):
    """Do one pipeline image job with a paid provider. True if `expect` was written."""
    if expect.name == 'kit.zip':
        return kit_job(cwd, prompt, log)
    if expect.suffix.lower() != '.png':
        say(f'{expect.name}: this step needs an assistant with image tools (Codex); not available with {backend()}')
        return False
    size = None
    m = re.search(r'(\d{3,4})x(\d{3,4})', prompt)
    if images:
        size = Image.open(images[0]).size
    elif m:
        size = (int(m.group(1)), int(m.group(2)))
    transparent = 'transparent' in prompt.lower()
    return paid_image(_clean(prompt), images, expect, size, transparent, log.with_name(f'{expect.stem}.log'))
