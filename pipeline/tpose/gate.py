"""Creation-time fit gate: generate a piece's mesh, place it, fit it, equip it into a look and inspect it; if the
inspection finds a STRUCTURAL defect in that piece (a sleeve that is open or has its hole off the arm, a limb leaving
a solid sleeve, a mask hole) the mesh is archived and generated again - the 3D generator gives a different result per
run - up to --tries times. Layer-order residuals between pieces are reported, not regenerated.

Run: python pipeline/tpose/gate.py --outfit Outfits/hoodie-boy-hoodiebag --key <piece key> --base Xander
         --look full-look --pieces <outfit:key> ... [--tries 3] [--redo-first]
Each try costs one mesh generation (Higgsfield, ~18 credits). The best try is kept.
"""
import argparse, hashlib, json, shutil, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
from anmaker_config import BLENDER  # noqa: E402  (this machine's Blender: .anmaker/config.json or a search)
T = Path(__file__).parent
sys.path.insert(0, str(T))
import s4_meshes as S4  # noqa: E402
COST = S4.cost_per_mesh()  # credits per mesh with the active provider (MESH_PROVIDER)
STRUCTURAL = ('runs through the sleeve lining', 'off-centre in the sleeve hole', 'leaves the solid sleeve',
              'skin points poke through', 'see-through holes',
              'pokes out of it at the waist/torso', 'layer spacing over', 'floats over', 'floats off the body',
              'layer order wrong', 'does not come out through its opening',
              'thin flap past the', 'sleeve opening too wide')


def run(cmd):
    print('[gate] $', ' '.join(str(c) for c in cmd[-6:]), flush=True)
    r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True)
    tail = (r.stdout + r.stderr).strip().splitlines()[-3:]
    for line in tail:
        print('[gate]   ', line, flush=True)
    if r.returncode != 0:
        raise SystemExit(f'[gate] step failed: {cmd}')


def blender(script, *args):
    run([BLENDER, '-b', '--factory-startup', '-P', T / script, '--', *args])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--outfit', required=True)
    ap.add_argument('--key', required=True)
    ap.add_argument('--base', required=True)
    ap.add_argument('--look', required=True)
    ap.add_argument('--pieces', nargs='+', required=True)
    ap.add_argument('--tries', type=int, default=3)
    ap.add_argument('--redo-first', action='store_true', help='the current mesh already failed: start with a new one')
    ap.add_argument('--combo', action='append', default=[], metavar='LOOK=PIECE,PIECE,...',
                    help='also equip + inspect the new piece together with existing pieces in this look (repeatable): '
                         'a newcomer must not clash with what it is worn with - any failure naming it counts')
    a = ap.parse_args()
    d = Path(a.outfit).resolve()
    look = ROOT / 'Outfits' / '_looks' / a.look
    def after_mesh():
        blender('s5_dump_meshes.py', d)
        run([sys.executable, T / 's5_place.py', d])
        blender('s6_fit.py', d, a.base)
        mine = []
        for name, pieces in [(a.look, a.pieces)] + [(c.split('=')[0], c.split('=')[1].split(',')) for c in a.combo]:
            blender('equip.py', '--base', a.base, '--name', name, '--pieces', *pieces)
            lk = ROOT / 'Outfits' / '_looks' / name
            blender('inspect_look.py', lk, a.base)
            rep = json.loads((lk / '08_inspect' / 'inspect.json').read_text())
            # its own failures, and every clash that names it (another piece covered by it / spaced over it)
            mine += [f'[{name}] {f}' for f in rep['fails'] if f.startswith(a.key + ':') or f' {a.key}' in f]
        structural = [f for f in mine if any(s in f for s in STRUCTURAL)]
        return structural, [f for f in mine if f not in structural]

    mesh = d / '04_meshes' / f'{a.key}.glb'
    keep = d / '_gate_tries'
    keep.mkdir(exist_ok=True)
    history = []
    digest = lambda: hashlib.md5(mesh.read_bytes()).hexdigest() if mesh.exists() else None
    stopped = None
    ic = d / 'image_checks.json'  # written by s2_over: the drawings must pass every 2D check before credits are spent
    if ic.exists() and not json.loads(ic.read_text()).get('pass', True):
        raise SystemExit(f'[gate] STOPPED: the drawings fail the image checks {json.loads(ic.read_text())["failing_views"]}'
                         f' - redraw them (rerun s2_over) before generating a mesh; nothing was spent')
    for t in range(a.tries):
        redo = t > 0 or a.redo_first or not mesh.exists()
        if redo:  # a new mesh costs credits: check first, never start a try that cannot finish
            have = S4.credits()
            if have is not None and have < COST:
                stopped = f'only {have:g} credits left (a mesh costs ~{COST}) - top up and rerun'
                break
        before = digest()
        r = subprocess.run([sys.executable, str(T / 's4_meshes.py'), str(d), '--keys', a.key]
                           + (['--redo', a.key] if redo and before else []), capture_output=True, text=True)
        print('[gate]   ', (r.stdout + r.stderr).strip().splitlines()[-1:] or '', flush=True)
        if r.returncode != 0 or (redo and digest() == before) or not mesh.exists():
            # generation failed (credits, login, service): the previous mesh is still in place, untouched
            stopped = 'mesh generation failed: ' + ' '.join((r.stdout + r.stderr).strip().splitlines()[-2:])[:300]
            break
        shutil.copy(mesh, keep / f'{a.key}_try{t + 1}.glb')
        structural, other = after_mesh()
        history.append({'try': t + 1, 'structural': structural, 'other': other,
                        'score': [len(structural), len(other)]})
        print(f'[gate] try {t + 1}: {len(structural)} structural defects in {a.key}', flush=True)
        for f in structural:
            print('[gate]    -', f, flush=True)
        if not structural:
            break
    if stopped:
        print(f'[gate] STOPPED: {stopped}', flush=True)
    if not history:
        raise SystemExit('[gate] no try completed - nothing changed')
    best = min(history, key=lambda h: h['score'])
    if best is not history[-1] or digest() != hashlib.md5((keep / f'{a.key}_try{best["try"]}.glb').read_bytes()).hexdigest():  # keep the BEST try, not the last one
        print(f'[gate] keeping try {best["try"]} (fewest defects)', flush=True)
        run([sys.executable, T / 's4_meshes.py', d, '--keys', a.key, '--redo', a.key, '--from-file',
             keep / f'{a.key}_try{best["try"]}.glb'])
        after_mesh()
    (d / 'gate.json').write_text(json.dumps({'key': a.key, 'tries': history, 'kept': best['try']}, indent=2),
                                 encoding='utf-8')
    print('[gate] DONE', f'kept try {best["try"]} of {len(history)}:', 'PASS' if not best['structural'] else 'still failing', flush=True)


if __name__ == '__main__':
    main()
