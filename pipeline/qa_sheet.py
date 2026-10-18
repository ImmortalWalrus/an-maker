"""Combine a fitted outfit's QA renders into qa_sheet.png, one labelled row per check:
bind pose all around (8 views + from below), arm close-ups (each arm from front/back/outside/inside/below),
T-pose (4 sides) and action pose (4 sides).
Run: python pipeline/qa_sheet.py <outfit dir>"""
import sys
from pathlib import Path
from PIL import Image, ImageDraw

d = Path(sys.argv[1])
rows = [
    ('bind pose, all around', [f'qa_bind_{a:03d}.png' for a in range(0, 360, 45)] + ['qa_bind_below.png']),
    ('left arm: front / back / outside / inside / below / up the sleeve / cuff side', [f'qa_arm_L_{t}.png' for t in ('front', 'back', 'outside', 'inside', 'below', 'upsleeve', 'cuff')]),
    ('right arm: front / back / outside / inside / below / up the sleeve / cuff side', [f'qa_arm_R_{t}.png' for t in ('front', 'back', 'outside', 'inside', 'below', 'upsleeve', 'cuff')]),
    ('T-pose: front / side / back / side', [f'qa_tpose_{a:03d}.png' for a in (0, 90, 180, 270)]),
    ('action pose: front / side / back / side', [f'qa_action_{a:03d}.png' for a in (0, 90, 180, 270)]),
]
H, label_h = 300, 22
rendered = []
for title, names in rows:
    ims = [Image.open(d / n).convert('RGB') for n in names if (d / n).exists()]
    if not ims:
        continue
    ims = [im.resize((int(im.width * H / im.height), H)) for im in ims]
    row = Image.new('RGB', (sum(im.width for im in ims), H + label_h), 'white')
    ImageDraw.Draw(row).text((6, 4), title, fill=(0, 0, 0))
    x = 0
    for im in ims:
        row.paste(im, (x, label_h))
        x += im.width
    rendered.append(row)
sheet = Image.new('RGB', (max(r.width for r in rendered), sum(r.height for r in rendered)), 'white')
y = 0
for r in rendered:
    sheet.paste(r, (0, y))
    y += r.height
sheet.save(d / 'qa_sheet.png')
print('sheet', sheet.size)
