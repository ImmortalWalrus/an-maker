"""Texture finish for a generated (3D) piece: the generator's colour map at full resolution, slightly sharpened.

The 3D generator (Tripo) paints a 2048 px atlas, but the web export cuts piece textures to 1024. A reworked colour map
(Color_reworked.png, the name decal_bake.py uses) keeps 2048 in export_web.py, so the finish:
  1. starts from Color_reworked.png when a logo was already redrawn (decal_bake.py), else from the mesh's own map;
  2. brings it to at least 2048 px (Lanczos) and sharpens it gently (unsharp mask: fabric weave and print edges read
     crisper; flat areas are left alone by the threshold);
  3. saves it as <outfit>/04_meshes/<key>_tex/Color_reworked.png. s6_fit.py swaps it in on the next fit.
Free (no image generation), the mesh untouched. Never sharpens the same map twice (finish.json keeps the hash of what
it wrote; a later logo bake writes a new map, which then gets finished again).

Run: python pipeline/tpose/texture_finish.py --outfit Outfits/gen-x --key x [--amount 60]
"""
import argparse, hashlib, json
from pathlib import Path
from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parents[2]
SIZE = 2048


def sha(p: Path):
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16]


def finish(outfit: Path, key: str, amount=60):
    import decal_bake as D
    tex = outfit / '04_meshes' / f'{key}_tex'
    tex.mkdir(parents=True, exist_ok=True)
    out, log = tex / 'Color_reworked.png', tex / 'finish.json'
    done = json.loads(log.read_text(encoding='utf-8')) if log.exists() else {}
    if out.exists() and done.get('sha') == sha(out):
        print(f'[finish] {key}: already finished', flush=True)
        return False
    src = Image.open(out).convert('RGB') if out.exists() else D.glb_images(outfit / '04_meshes' / f'{key}.glb')['color']
    w0 = src.size[0]
    if w0 < SIZE:
        src = src.resize((SIZE, SIZE * src.size[1] // src.size[0]), Image.LANCZOS)
    src = src.filter(ImageFilter.UnsharpMask(radius=1.2, percent=amount, threshold=3))
    src.save(out)
    log.write_text(json.dumps({'sha': sha(out), 'from_px': w0, 'px': src.size[0], 'amount': amount}), encoding='utf-8')
    print(f'[finish] {key}: colour map {w0} -> {src.size[0]} px, sharpened ({amount}%)', flush=True)
    return True


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--outfit', required=True)
    ap.add_argument('--key', required=True)
    ap.add_argument('--amount', type=int, default=60)
    a = ap.parse_args()
    finish((ROOT / a.outfit).resolve(), a.key, a.amount)


if __name__ == '__main__':
    main()
