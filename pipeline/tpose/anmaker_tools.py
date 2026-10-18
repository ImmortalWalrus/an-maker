"""Installs what the garment maker needs, by itself, on a fresh Windows PC (run by `garment.py setup`).

Everything comes from its official source and needs no admin rights where possible:
  Python packages   pip install -r requirements.txt
  Blender 5.2 LTS   the portable zip from download.blender.org, unpacked to %USERPROFILE%\an-maker-tools
  Git               winget (Git.Git); Windows may ask once to allow it
  Node.js           winget (OpenJS.NodeJS.LTS), only when a command-line tool below needs it
  Codex CLI         npm install -g @openai/codex   (image generation with a ChatGPT plan)
  AssetHub CLI      npm install -g @assethub/cli    (3D meshes, paid images)
  Higgsfield CLI    npm install -g @higgsfield/cli  (3D meshes, paid images)
Sign-ins are never done here: they are the person's own, in their own browser.
"""
import glob, os, re, shutil, subprocess, sys, urllib.request, zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOLS = Path.home() / 'an-maker-tools'
BLENDER_LINE = '5.2'                                             # the LTS line the pipeline is tested on
NPM = {'codex': '@openai/codex', 'assethub': '@assethub/cli', 'higgsfield': '@higgsfield/cli'}


def say(msg):
    print(f'[install] {msg}', flush=True)


def fix_path():
    """Tools installed a moment ago are not on this shell's PATH yet: add their usual folders."""
    extra = [r'C:\Program Files\Git\cmd', r'C:\Program Files\nodejs', os.path.expandvars(r'%APPDATA%\npm'),
             os.path.expandvars(r'%LOCALAPPDATA%\Programs\Git\cmd')]
    have = os.environ.get('PATH', '').split(os.pathsep)
    os.environ['PATH'] = os.pathsep.join(have + [p for p in extra if os.path.isdir(p) and p not in have])


def winget(pkg):
    if not shutil.which('winget'):
        say(f'winget is missing, so {pkg} cannot be installed automatically')
        return False
    say(f'installing {pkg} (Windows may ask you to allow it: click Yes)')
    r = subprocess.run(['winget', 'install', '-e', '--id', pkg, '--silent', '--accept-package-agreements',
                        '--accept-source-agreements'], text=True, capture_output=True)
    fix_path()
    ok = r.returncode == 0 or 'already installed' in (r.stdout + r.stderr).lower()
    say(f'{pkg}: {"ok" if ok else "FAILED " + (r.stdout + r.stderr)[-300:]}')
    return ok


def pip_packages():
    try:
        import numpy, PIL  # noqa: F401
        return True
    except ImportError:
        say('installing the Python packages (numpy, pillow)')
        return subprocess.run([sys.executable, '-m', 'pip', 'install', '-q', '-r', str(ROOT / 'requirements.txt')]).returncode == 0


UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) an-maker-setup'}   # blender.org refuses Python's default


def fetch(url, dest=None):
    r = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120)
    if dest is None:
        return r.read().decode('utf-8', 'replace')
    with open(dest, 'wb') as f:
        shutil.copyfileobj(r, f, 1 << 20)


def portable_blender():
    """blender.exe from an earlier portable install, if any."""
    found = sorted(glob.glob(str(TOOLS / f'blender-{BLENDER_LINE}.*-windows-x64' / 'blender.exe')))
    return found[-1] if found else None


def blender():
    """Blender 5.2 LTS, portable (no admin rights): the newest 5.2.x zip from download.blender.org."""
    import anmaker_config as CFG
    have = CFG.find_blender() or portable_blender()
    if have:
        return have
    base = f'https://download.blender.org/release/Blender{BLENDER_LINE}/'
    page = fetch(base)
    zips = sorted(set(re.findall(rf'blender-{re.escape(BLENDER_LINE)}\.(\d+)-windows-x64\.zip', page)), key=int)
    if not zips:
        say(f'no Blender {BLENDER_LINE} download found at {base}')
        return None
    name = f'blender-{BLENDER_LINE}.{zips[-1]}-windows-x64.zip'
    TOOLS.mkdir(exist_ok=True)
    z = TOOLS / name
    say(f'downloading {name} from blender.org (about 400 MB, a few minutes)')
    fetch(base + name, z)
    say('unpacking Blender')
    with zipfile.ZipFile(z) as f:
        f.extractall(TOOLS)
    z.unlink()
    exe = portable_blender()
    say(f'Blender ready: {exe}')
    return exe


def git():
    fix_path()
    return shutil.which('git') or (winget('Git.Git') and shutil.which('git'))


def npm_tool(exe):
    """A command-line tool from npm (installs Node.js first if needed)."""
    fix_path()
    if shutil.which(exe):
        return True
    if not shutil.which('npm') and not winget('OpenJS.NodeJS.LTS'):
        return False
    say(f'installing the {exe} command-line tool')
    subprocess.run(f'npm install -g {NPM[exe]}', shell=True)
    fix_path()
    return bool(shutil.which(exe))


def ensure(cfg):
    """Install everything this machine's choices need. Returns what is still missing (for doctor)."""
    missing = []
    fix_path()
    if not pip_packages():
        missing.append('Python packages')
    exe = blender()
    if exe:
        cfg['blender'] = exe
    else:
        missing.append('Blender')
    if not git():
        missing.append('Git')
    for tool in {cfg.get('images'), cfg.get('mesh')} & set(NPM):
        if not npm_tool(tool):
            missing.append(f'{tool} CLI')
    return missing
