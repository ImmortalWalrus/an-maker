"""T-pose-first outfit pipeline - one command, resumable (every step skips work whose output already exists).

  1 render the Genies base in its T-pose from a fixed ortho camera          (local, free)
  2 Codex: list the pieces, dress the mannequin front/back                   (ChatGPT subscription)
  3 Codex: each piece alone, in place, on the same canvas                   (ChatGPT subscription)
  4 Tripo H3.1 image-to-3D per piece on Higgsfield                           (PAID: ~9-18 credits per piece)
  5 place each mesh by silhouette maths against the known camera            (local)
  6 depth, layering, push-out, region skin weights, per-piece exports       (local, Blender)
  7 test motion + renders + stretch/sink numbers                            (local, Blender)

Usage:
  python pipeline/tpose/run_outfit.py --concept path/to/concept.png --name my-outfit [--base Xander]
                                      [--until 3] [--yes-spend]
Without --yes-spend the run stops before step 4 and prints the Higgsfield estimate.
"""
import argparse, shutil, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
from anmaker_config import BLENDER  # noqa: E402  (this machine's Blender: .anmaker/config.json or a search)
HERE = ROOT / 'pipeline' / 'tpose'


def run(cmd):
    print('>>', ' '.join(str(c) for c in cmd), flush=True)
    subprocess.run([str(c) for c in cmd], check=True)


def blender(script, *args):
    run([BLENDER, '-b', '--factory-startup', '-P', HERE / script, '--', *args])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--concept', required=True)
    ap.add_argument('--name', required=True)
    ap.add_argument('--base', default='Xander')
    ap.add_argument('--until', type=int, default=7)
    ap.add_argument('--yes-spend', action='store_true')
    a = ap.parse_args()
    d = ROOT / 'Outfits' / a.name
    d.mkdir(parents=True, exist_ok=True)
    if not (d / 'concept.png').exists():
        shutil.copy(a.concept, d / 'concept.png')
    py = sys.executable
    if not (d / '01_mannequin' / 'camera.json').exists():
        blender('s1_render_mannequin.py', d, a.base)
    if a.until >= 2:
        run([py, HERE / 's2_images.py', d, '--only', '2a,2b' + (',3' if a.until >= 3 else '')])
    if a.until >= 4:
        if not a.yes_spend:
            run([py, HERE / 's4_meshes.py', d, '--estimate'])
            print('Stopping before the paid mesh step. Re-run with --yes-spend to generate meshes.')
            return
        run([py, HERE / 's4_meshes.py', d])
    if a.until >= 5:
        run([py, HERE / 's5_place.py', d])
    if a.until >= 6:
        blender('s6_fit.py', d, a.base)
    if a.until >= 7:
        blender('s7_qa.py', d, a.base)
        run([py, HERE / 'qa_sheet.py', d])


if __name__ == '__main__':
    main()
