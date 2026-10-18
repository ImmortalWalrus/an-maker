"""Combine an outfit's step-7 renders into 07_qa/qa_sheet.png: one labelled row per pose (T-pose all around +
from below, then A-pose, walk, wave, arms up, squat from 4 sides), with each row's worst stretch number.
Run: python pipeline/tpose/qa_sheet.py <outfit_dir>"""
import json, sys
from pathlib import Path
from PIL import Image, ImageDraw

d = Path(sys.argv[1]) / '07_qa'
report = json.loads((d / 'qa.json').read_text()) if (d / 'qa.json').exists() else {}
rows = [('tpose', [f'tpose_{a:03d}.png' for a in range(0, 360, 45)] + ['tpose_below.png'])]
rows += [(p, [f'{p}_{a:03d}.png' for a in (0, 90, 180, 270)]) for p in ('apose', 'walk_a', 'walk_b', 'wave', 'arms_up', 'squat')]
H, LH = 300, 22
out = []
for pose, names in rows:
    ims = [Image.open(d / n).convert('RGB') for n in names if (d / n).exists()]
    if not ims:
        continue
    ims = [im.resize((int(im.width * H / im.height), H)) for im in ims]
    row = Image.new('RGB', (max(sum(i.width for i in ims), 900), H + LH), 'white')
    worst = report.get(pose, {})
    label = pose + '   ' + '  |  '.join(f"{k}: stretch p99 {v['stretch_p99']} max {v['stretch_max']}" for k, v in worst.items())
    ImageDraw.Draw(row).text((6, 4), label[:220], fill=(0, 0, 0))
    x = 0
    for im in ims:
        row.paste(im, (x, LH))
        x += im.width
    out.append(row)
sheet = Image.new('RGB', (max(r.width for r in out), sum(r.height for r in out)), 'white')
y = 0
for r in out:
    sheet.paste(r, (0, y))
    y += r.height
sheet.save(d / 'qa_sheet.png')
print('sheet', d / 'qa_sheet.png', sheet.size)
