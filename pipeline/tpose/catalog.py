"""The AN Maker wardrobe: every piece the customizer ships, in tile order.

Two sources, so two people can add garments at the same time without editing the same file:
  - the shell collections (Outfits/tee-kits/collection.json, Outfits/legging-kits/collection.json), and
  - one file per piece in catalog/pieces/<key>.json:
      {"spec": "<outfit>:<key>", "kind": "hair|shell-top|shell-bottom|generated|shoes",
       "label": "Shown name", "order": 50, "by": "who made it"}
Order: hair, shell tops, shell bottoms, then the catalog pieces by "order" (generated garments 40-89, shoes 90+).
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PIECES = ROOT / 'catalog' / 'pieces'


def entries():
    out = []
    for f in sorted(PIECES.glob('*.json')):
        e = json.loads(f.read_text(encoding='utf-8'))
        e.setdefault('order', 50)
        out.append(e)
    return sorted(out, key=lambda e: (e['order'], e['spec']))


def shell_specs():
    tees = json.loads((ROOT / 'Outfits/tee-kits/collection.json').read_text(encoding='utf-8'))['shirts']
    legs = json.loads((ROOT / 'Outfits/legging-kits/collection.json').read_text(encoding='utf-8'))['bottoms']
    out = ['tee-' + t['key'].replace('_', '-') + ':' + t['key'] for t in tees]
    out += [e['spec'] for e in entries() if e.get('kind') == 'shell-top']
    out += ['legs-' + t['key'].replace('_', '-') + ':' + t['key'] for t in legs]
    out += [e['spec'] for e in entries() if e.get('kind') == 'shell-bottom']
    return out


def all_specs():
    """Every published piece, in tile order."""
    es = entries()
    hair = [e['spec'] for e in es if e.get('kind') == 'hair']
    rest = [e['spec'] for e in es if e.get('kind') not in ('hair', 'shell-top', 'shell-bottom')]
    return hair + shell_specs() + rest


def labels():
    return {e['spec'].split(':')[1]: e['label'] for e in entries() if e.get('label')}


def add(spec, kind, label, order=50, by=''):
    PIECES.mkdir(parents=True, exist_ok=True)
    key = spec.split(':')[1]
    f = PIECES / f'{key}.json'
    f.write_text(json.dumps({'spec': spec, 'kind': kind, 'label': label, 'order': order, 'by': by}, indent=2),
                 encoding='utf-8')
    return f
