"""Step 4 - one 3D mesh per piece with Tripo H3.1 multi-view (front, left, back, right) on Higgsfield, from the
step-3 images of that piece. Depth comes from the side views instead of being guessed.

Inputs per view are transparent cut-outs (background removed with the same border flood-fill step 5 uses) cropped
with ONE shared square size and vertical frame across the four views, so the piece has the same scale in every
image. Tripo is asked for a game budget (face_limit) so the mesh needs no processing afterwards.

Run: python pipeline/tpose/s4_meshes.py <outfit_dir> [--estimate] [--keys a,b] [--quality standard|detailed] [--redo a,b]
Writes 04_meshes/<key>.glb, <key>.json (job record) and <key>_<view>_input.png. Existing meshes are never redone.
"""
import argparse, json, os, re, shutil, subprocess, sys, urllib.request, uuid
from pathlib import Path
import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
from s5_place import background_mask, registered  # noqa: E402

MODEL = 'tripo_h3_1_multiview_to_3d'
VIEWS = ['front', 'left', 'back', 'right']  # Tripo multi-view order


def hf(args):
    r = subprocess.run(['higgsfield', *args], capture_output=True, text=True, encoding='utf-8',
                       shell=sys.platform == 'win32', timeout=1800)
    return r.returncode, r.stdout + r.stderr


PROVIDER = os.environ.get('MESH_PROVIDER', 'higgsfield')   # higgsfield | assethub
AH_MODEL = 'meshGen.tripo_3_1'
# Tripo 3.1 bills its cheapest plan (meshGen.tripo_3_1, 25 credits) ONLY when both qualities are sent as standard
AH_PARAMS = {'textureQuality': 'standard', 'geometryQuality': 'standard'}
AH_COST = 25


def ah(args, timeout=1800):
    r = subprocess.run(['assethub', *args], capture_output=True, text=True, encoding='utf-8',
                       shell=sys.platform == 'win32', timeout=timeout)
    return r.returncode, r.stdout + r.stderr


def ah_json(args, timeout=1800):
    code, txt = ah(args, timeout)
    try:
        return code, json.loads(txt[txt.index('{'):]), txt
    except Exception:
        return code, None, txt


def ah_generate(imgs, key, glb_out: Path, log: Path):
    """Multiview (front, left, back, right - Tripo's order) image-to-mesh on AssetHub; True if glb_out was written."""
    ids = []
    for im in imgs:
        code, j, txt = ah_json(['files', 'upload', str(im), '--media-type', 'image'], 300)
        if not j or 'uploadId' not in j:
            log.write_text(txt, encoding='utf-8')
            return False
        ids.append(j['uploadId'])
    req = {'modelId': AH_MODEL, 'inputMode': 'multiview', 'sources': [{'uploadId': i} for i in ids],
           'faceLimit': 40000, 'params': AH_PARAMS, 'strictOptions': True, 'name': key}
    reqf = glb_out.with_suffix('.request.json')
    reqf.write_text(json.dumps(req, indent=1), encoding='utf-8')
    op = str(uuid.uuid4())
    code, j, txt = ah_json(['api', 'call', 'POST /generate/mesh', '--input-json', '@' + str(reqf), '--operation-id', op])
    job = None
    if j:
        job = j.get('jobId') or (j.get('data') or {}).get('jobId') or (j.get('job') or {}).get('id')
    if not job:
        log.write_text(txt, encoding='utf-8')
        return False
    tmp = glb_out.parent / f'_dl_{key}'
    shutil.rmtree(tmp, ignore_errors=True)
    code, txt2 = ah(['jobs', 'watch', job, '--timeout-ms', str(25 * 60 * 1000), '--download', '--out-dir', str(tmp)],
                    timeout=1800)
    log.write_text(txt + '\n' + txt2, encoding='utf-8')
    got = sorted(tmp.rglob('*.glb')) if tmp.exists() else []
    if not got:
        return False
    shutil.move(str(got[0]), glb_out)
    shutil.rmtree(tmp, ignore_errors=True)
    return True


def credits():
    """Credits left with the active mesh provider (None if it cannot be read)."""
    if PROVIDER == 'assethub':
        code, j, _ = ah_json(['api', 'call', 'GET /account'], 120)
        try:
            return float(j['data']['availableBalance'])
        except Exception:
            return None
    code, txt = hf(['account', 'status', '--json'])
    try:
        return float(json.loads(txt)['credits'])
    except Exception:
        return None


def cost_per_mesh():
    return AH_COST if PROVIDER == 'assethub' else 18


def multiview_inputs(d: Path, key: str, slot: str, out: Path, margin=0.1):
    masks, rgbs = {}, {}
    for v in VIEWS:
        m, rgb = registered(d, v, d / '03_garments' / f'{v}_{key}.png', slot)
        # trim 1 px so no background-coloured fringe reaches Tripo's texture
        from PIL import ImageFilter
        m = np.asarray(Image.fromarray(m.astype(np.uint8) * 255).filter(ImageFilter.MinFilter(3))) > 127
        masks[v], rgbs[v] = m, rgb
    rows = np.concatenate([np.nonzero(m.any(1))[0] for m in masks.values()])
    y0, y1 = rows.min(), rows.max()
    widths = [np.ptp(np.nonzero(m.any(0))[0]) for m in masks.values()]
    side = int(max(y1 - y0, max(widths)) * (1 + 2 * margin))
    cy = (y0 + y1) / 2
    paths = []
    for v in VIEWS:
        xs = np.nonzero(masks[v].any(0))[0]
        cx = (xs.min() + xs.max()) / 2
        rgba = np.dstack([rgbs[v].astype(np.uint8), (masks[v] * 255).astype(np.uint8)])
        img = Image.fromarray(rgba, 'RGBA')
        box = (int(cx - side / 2), int(cy - side / 2), int(cx - side / 2) + side, int(cy - side / 2) + side)
        canvas = Image.new('RGBA', (side, side), (0, 0, 0, 0))
        canvas.paste(img.crop(box), (0, 0))
        p = out / f'{key}_{v}_input.png'
        canvas.resize((1024, 1024), Image.LANCZOS).save(p)
        paths.append(p)
    return paths


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('outfit_dir')
    ap.add_argument('--estimate', action='store_true')
    ap.add_argument('--keys', default='')
    ap.add_argument('--quality', default='detailed')
    ap.add_argument('--from-file', default='', help='use this already-generated .glb (e.g. a kept gate try) for --keys')
    ap.add_argument('--redo', default='', help='keys whose mesh failed inspection: archive it (and its steps 5-6 '
                    'outputs) to _rejected/ and generate a fresh one - the generator gives a different result per run')
    a = ap.parse_args()
    d = Path(a.outfit_dir).resolve()
    pieces = json.loads((d / 'outfit.json').read_text(encoding='utf-8'))['pieces']
    keys = set(filter(None, a.keys.split(',')))
    out = d / '04_meshes'
    out.mkdir(exist_ok=True)
    import time
    redo = set(filter(None, a.redo.split(',')))

    def archive(key):
        """Move a mesh that failed inspection (and its steps 5-6 outputs) to _rejected/ - only once its replacement
        is safely on disk, so a failed generation (no credits, expired login) never loses the mesh we had."""
        stamp = time.strftime('%Y%m%d-%H%M%S')
        rej = d / '_rejected' / f'{key}_{stamp}'
        rej.mkdir(parents=True, exist_ok=True)
        for f in list(out.glob(f'{key}.*')) + list((d / '05_place').glob(f'{key}*')) + list((d / '06_fitted').glob(f'*{key}*')):
            if f.name.endswith('.new.glb'):
                continue
            shutil.move(str(f), rej / f.name)
        pl = d / '05_place' / 'placement.json'
        if pl.exists():
            data = json.loads(pl.read_text())
            data.pop(key, None)
            pl.write_text(json.dumps(data, indent=2))
        print(f'[mesh] {key}: previous mesh archived to {rej}', flush=True)
    params = ['--orientation', 'align_image', '--geometry_quality', a.quality, '--texture_quality', a.quality,
              '--face_limit', '40000']
    total = 0
    for p in pieces:
        if keys and p['key'] not in keys:
            continue
        glb = out / f"{p['key']}.glb"
        if a.from_file:
            if p['key'] in redo and glb.exists():
                archive(p['key'])
            if not glb.exists():
                shutil.copy(a.from_file, glb)
                print(f"[mesh] {p['key']}: restored from {a.from_file}", flush=True)
            continue
        if glb.exists() and not a.estimate and p['key'] not in redo:
            print(f"[mesh] {p['key']}: exists", flush=True)
            continue
        imgs = multiview_inputs(d, p['key'], p['slot'], out)
        img_args = [x for im in imgs for x in ('--image-references', str(im))]
        if PROVIDER == 'assethub':
            cost = float(AH_COST)
        else:
            code, txt = hf(['generate', 'cost', MODEL, *img_args, *params])
            m = re.search(r'(\d+(?:\.\d+)?)\s*credits', txt)
            cost = float(m.group(1)) if m else None
        if a.estimate:
            total += cost or 0
            print(f"[estimate] {p['key']}: {cost} credits ({PROVIDER})", flush=True)
            continue
        have = credits()
        if have is not None and cost is not None and have < cost:
            print(f"[mesh] {p['key']}: NOT ENOUGH CREDITS - {have:g} left, this mesh costs {cost:g}. Nothing was "
                  f"changed; top up and run again.", flush=True)
            sys.exit(4)
        new = out / f"{p['key']}.new.glb"
        if PROVIDER == 'assethub':
            ok = ah_generate(imgs, p['key'], new, out / f"{p['key']}.json")
            txt = (out / f"{p['key']}.json").read_text(encoding='utf-8') if (out / f"{p['key']}.json").exists() else ''
            if not ok:
                print(f"[mesh] {p['key']}: FAILED on AssetHub - the previous mesh, if any, is kept\n{txt[-800:]}", flush=True)
                continue
        else:
            code, txt = hf(['generate', 'create', MODEL, *img_args, *params, '--wait', '--wait-timeout', '25m', '--json'])
            urls = re.findall(r'https://[^\s"\']+\.glb[^\s"\']*', txt)
            if code != 0 or not urls:
                (out / f"{p['key']}.failed.json").write_text(txt, encoding='utf-8')
                print(f"[mesh] {p['key']}: FAILED (exit {code}) - the previous mesh, if any, is kept\n{txt[-800:]}", flush=True)
                continue
            urllib.request.urlretrieve(urls[0], new)
        if p['key'] in redo and glb.exists():
            archive(p['key'])
        new.replace(glb)
        (out / f"{p['key']}.json").write_text(txt, encoding='utf-8')
        (out / f"{p['key']}.provider").write_text(f'{PROVIDER} {AH_MODEL if PROVIDER == "assethub" else MODEL}', encoding='utf-8')
        print(f"[mesh] {p['key']}: {glb.stat().st_size // 1024} KB", flush=True)
    if a.estimate:
        print(f'[estimate] total {total} credits ({PROVIDER})', flush=True)


if __name__ == '__main__':
    main()
