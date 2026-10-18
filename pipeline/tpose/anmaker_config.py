"""Where this machine keeps the tools the pipeline runs (Blender above all), so the same code works on every
teammate's computer. Saved by `python pipeline/garment.py setup` in .anmaker/config.json (not in git); the env var
AN_BLENDER wins over it. Without either, the usual install folders on Windows and macOS are searched.
"""
import glob, json, os, shutil, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / '.anmaker' / 'config.json'


def load():
    try:
        return json.loads(CONFIG.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def save(cfg):
    CONFIG.parent.mkdir(exist_ok=True)
    CONFIG.write_text(json.dumps(cfg, indent=2), encoding='utf-8')


def find_blender():
    """Newest Blender 5.x found on this machine, or None."""
    cand = []
    if sys.platform == 'win32':
        for base in (os.environ.get('ProgramFiles', r'C:\Program Files'), os.environ.get('ProgramFiles(x86)', '')):
            cand += glob.glob(os.path.join(base, 'Blender Foundation', 'Blender *', 'blender.exe'))
        cand += glob.glob(os.path.expandvars(r'%LOCALAPPDATA%\Programs\Blender Foundation\Blender *\blender.exe'))
        cand += glob.glob(os.path.expanduser(r'~\an-maker-tools\blender-5.*-windows-x64\blender.exe'))  # setup's portable copy
    elif sys.platform == 'darwin':
        cand += glob.glob('/Applications/Blender*.app/Contents/MacOS/Blender')
        cand += glob.glob(os.path.expanduser('~/Applications/Blender*.app/Contents/MacOS/Blender'))
    on_path = shutil.which('blender')
    if on_path:
        cand.append(on_path)
    cand = [c for c in cand if os.path.isfile(c)]
    return sorted(cand)[-1] if cand else None


def blender():
    return os.environ.get('AN_BLENDER') or load().get('blender') or find_blender() or 'blender'


BLENDER = blender()
