"""Combine 08_inspect renders into one sheet: one labelled row per feature (6 views each), with the pass/fail list.
Run: python pipeline/tpose/inspect_sheet.py <look_or_outfit_dir>"""
import json, sys
from pathlib import Path
from PIL import Image, ImageDraw

d = Path(sys.argv[1]) / '08_inspect'
rep = json.loads((d / 'inspect.json').read_text()) if (d / 'inspect.json').exists() else {}
order = ['cuff_L', 'cuff_R', 'armpit_L', 'armpit_R', 'collar', 'hood_back', 'waist', 'ankle_L', 'ankle_R',
         'chest_front', 'chest_back']
S, LH = 220, 20
rows = []
for f in order:
    ims = sorted(d.glob(f'{f}_*.png'))
    if not ims:
        continue
    row = Image.new('RGB', (S * len(ims), S + LH), 'white')
    ImageDraw.Draw(row).text((4, 3), f + ':  ' + '  |  '.join(p.stem[len(f) + 1:] for p in ims), fill=(0, 0, 0))
    for i, p in enumerate(ims):
        row.paste(Image.open(p).convert('RGB').resize((S, S)), (S * i, LH))
    rows.append(row)
head = Image.new('RGB', (S * 6, 20 + 16 * max(1, len(rep.get('fails', [])))), 'white')
dr = ImageDraw.Draw(head)
dr.text((4, 3), 'PASS' if rep.get('pass') else 'FAIL', fill=(0, 140, 0) if rep.get('pass') else (200, 0, 0))
for i, f in enumerate(rep.get('fails', [])):
    dr.text((60, 3 + 16 * i), f, fill=(0, 0, 0))
W = max(r.width for r in rows + [head])
sheet = Image.new('RGB', (W, head.height + sum(r.height for r in rows)), 'white')
sheet.paste(head, (0, 0))
y = head.height
for r in rows:
    sheet.paste(r, (0, y))
    y += r.height
sheet.save(d / 'sheet.png')
print('sheet', d / 'sheet.png', sheet.size)
