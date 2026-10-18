"""Compose a crisp logo badge: an image-gen emblem (no letters) plus the brand name set in real type, because image
generation garbles letters. Feeds decal_bake.py.

  ring    navy felt ring, the name arched over the top, two stars, the emblem in the middle (a classic sleeve patch)
  banner  the emblem filling the badge, the name on a white banner across its lower part
  plain   the emblem alone (trimmed, centred)

Run: python pipeline/tpose/badge_art.py --emblem emblem.png --text MONCHILL --style ring --out badge.png
     [--rim "#14213D"] [--ink "#FAFAF8"] [--font C:/Windows/Fonts/ariblk.ttf]
"""
import argparse, math, sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).parent))
from tee_kit import key_graphic  # noqa: E402

S = 2048                                                       # drawn at 2x, saved at 1024


def font(path, size):
    for p in (path, r'C:/Windows/Fonts/ariblk.ttf', '/System/Library/Fonts/Supplemental/Arial Black.ttf'):
        if not p:
            continue
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            continue
    return ImageFont.load_default()


def ring(em, text, rim, ink, fpath):
    b = Image.new('RGBA', (S, S), (0, 0, 0, 0)); d = ImageDraw.Draw(b)
    d.ellipse((0, 0, S - 1, S - 1), fill=rim)
    D = int(S * 0.70); e = em.resize((D, D), Image.LANCZOS)
    b.alpha_composite(e, ((S - D) // 2, (S - D) // 2 + int(S * 0.02)))
    d.ellipse((S * 0.012, S * 0.012, S * 0.988, S * 0.988), outline=ink, width=int(S * 0.012))
    f = font(fpath, int(S * min(0.105, 0.84 / max(len(text), 1))))
    R, track = S * 0.405, S * 0.012
    widths = [d.textlength(ch, font=f) for ch in text]
    ang = -math.pi / 2 - (sum(widths) + track * (len(text) - 1)) / R / 2
    for ch, w in zip(text, widths):
        a = ang + (w / 2) / R
        tile = Image.new('RGBA', (int(S * 0.2), int(S * 0.2)), (0, 0, 0, 0)); td = ImageDraw.Draw(tile)
        l, t, r, bb = td.textbbox((0, 0), ch, font=f)
        td.text((tile.width / 2 - (l + r) / 2, tile.height / 2 - (t + bb) / 2), ch, font=f, fill=ink)
        tile = tile.rotate(-math.degrees(a + math.pi / 2), resample=Image.BICUBIC)
        b.alpha_composite(tile, (int(S / 2 + R * math.cos(a) - tile.width / 2), int(S / 2 + R * math.sin(a) - tile.height / 2)))
        ang += (w + track) / R
    for sx in (-1, 1):
        cx, cy, r0 = S / 2 + sx * S * 0.33, S / 2 + S * 0.24, S * 0.035
        d.polygon([(cx + (r0 if k % 2 == 0 else r0 * 0.42) * math.cos(-math.pi / 2 + k * math.pi / 5),
                    cy + (r0 if k % 2 == 0 else r0 * 0.42) * math.sin(-math.pi / 2 + k * math.pi / 5)) for k in range(10)], fill=ink)
    return b


def banner(em, text, rim, ink, fpath):
    b = Image.new('RGBA', (S, S), (0, 0, 0, 0)); b.alpha_composite(em.resize((S, S), Image.LANCZOS))
    d = ImageDraw.Draw(b)
    bw, bh = int(S * 0.84), int(S * 0.19); x0, y0 = (S - bw) // 2, int(S * 0.66); p = int(S * 0.013)
    d.rounded_rectangle((x0, y0, x0 + bw, y0 + bh), radius=bh // 2, fill=rim)
    d.rounded_rectangle((x0 + p, y0 + p, x0 + bw - p, y0 + bh - p), radius=bh // 2 - p, fill=ink)
    f = font(fpath, 300); l, t, r, bb = d.textbbox((0, 0), text, font=f)
    f = font(fpath, int(300 * min(bw * 0.78 / (r - l), bh * 0.6 / (bb - t))))
    l, t, r, bb = d.textbbox((0, 0), text, font=f)
    d.text((S / 2 - (l + r) / 2, y0 + bh / 2 - (t + bb) / 2), text, font=f, fill=rim)
    return b


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--emblem', required=True); ap.add_argument('--text', default='')
    ap.add_argument('--style', choices=['ring', 'banner', 'plain'], default='ring')
    ap.add_argument('--rim', default='#14213D'); ap.add_argument('--ink', default='#FAFAF8')
    ap.add_argument('--font', default=''); ap.add_argument('--out', required=True)
    a = ap.parse_args()
    em = key_graphic(Image.open(a.emblem))
    w, h = em.size; sq = Image.new('RGBA', (max(w, h),) * 2, (0, 0, 0, 0)); sq.alpha_composite(em, ((max(w, h) - w) // 2, (max(w, h) - h) // 2))
    out = {'ring': ring, 'banner': banner}.get(a.style, lambda e, *_: e.resize((S, S), Image.LANCZOS))(sq, a.text.upper(), a.rim, a.ink, a.font)
    out.resize((1024, 1024), Image.LANCZOS).save(a.out)
    print(f'[badge] {a.out}', flush=True)


if __name__ == '__main__':
    main()
