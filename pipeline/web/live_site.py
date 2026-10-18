"""The AN Maker site: a private GitHub repo that Cloudflare Pages serves for free. Every push to it goes live in about
a minute, so publishing is a git push. Anyone with write access to that repo can publish, from any assistant.

  repo   tools/site_repo.txt   (e.g. https://github.com/ImmortalWalrus/an-maker-site.git)
  url    tools/site_url.txt    (the live address, e.g. https://an-maker.pages.dev)
  copy   .anmaker/site         (a local clone, made on first use)

Layout of the site repo: index.html (the page, wrapped in a full HTML document) and assets/ (everything it loads).

  python pipeline/web/live_site.py publish --files assets/manifest.json assets/piece_x.gltf.json ... -m "message"
         copies those files from web/customizer/ into the site and pushes. Garments never send the page itself.
  python pipeline/web/live_site.py publish --page web/customizer/index.html -m "message"     (owner: a page change)
  python pipeline/web/live_site.py status     what is live (last commits) and the address
"""
import argparse, json, shutil, subprocess, sys, time, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / 'web' / 'customizer'
SITE = ROOT / '.anmaker' / 'site'
REPO_FILE = ROOT / 'tools' / 'site_repo.txt'
URL_FILE = ROOT / 'tools' / 'site_url.txt'

# what the page needs around it outside a Claude artifact: exactly the wrapper the artifact host added
HEAD = '<!doctype html><html><head><meta charset=utf8><meta name=viewport content="width=device-width,initial-scale=1,viewport-fit=cover"><style>:root{color-scheme:light;box-sizing:border-box;padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}html{scroll-padding-top:env(safe-area-inset-top,0px)}body{margin:0;padding:0;font:14px -apple-system,BlinkMacSystemFont,sans-serif;background:#fff;color:#000}img{max-width:100%}[hidden]:not([hidden=until-found i]){display:none!important}</style></head><body>\n'


def say(msg):
    print(f'[site] {msg}', flush=True)


def git(*args, cwd=SITE, check=True):
    r = subprocess.run(['git', *args], cwd=cwd, text=True, encoding='utf-8', stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if check and r.returncode:
        raise SystemExit(f'[site] git {" ".join(args[:2])} failed:\n{r.stdout[-1500:]}')
    return r.stdout.strip()


def repo_url():
    if not REPO_FILE.exists():
        raise SystemExit('[site] tools/site_repo.txt is missing - ask the owner for the site repo address')
    return REPO_FILE.read_text(encoding='utf-8').strip()


def live_url():
    return URL_FILE.read_text(encoding='utf-8').strip() if URL_FILE.exists() else ''


def checkout():
    """The local copy of the site, up to date with GitHub."""
    if not (SITE / '.git').exists():
        SITE.parent.mkdir(exist_ok=True)
        say(f'getting the site from {repo_url()} (one time, about 120 MB)')
        git('clone', '-q', repo_url(), str(SITE), cwd=ROOT)
        git('config', 'core.autocrlf', 'false')
    else:
        git('fetch', '-q', 'origin')
        git('reset', '-q', '--hard', 'origin/main')            # the site copy is never edited by hand
    return SITE


def wrap(page: str):
    return page if page.lstrip().lower().startswith('<!doctype') else HEAD + page.lstrip()


def publish(files=(), page=None, message='update', who=''):
    """Copy files (paths relative to web/customizer, e.g. assets/manifest.json) and optionally the page into the site,
    commit and push. Returns the commit id, or None if nothing changed."""
    checkout()
    for rel in files:
        src, dst = WEB / rel, SITE / rel
        if not src.exists():
            raise SystemExit(f'[site] missing {src}')
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
    if page:
        (SITE / 'index.html').write_text(wrap(Path(page).read_text(encoding='utf-8')), encoding='utf-8', newline='')
    git('add', '-A')
    if not git('status', '--porcelain'):
        say('nothing changed: the site already has these files')
        return None
    git('-c', f'user.name={who or "AN Maker"}', '-c', 'user.email=an-maker@users.noreply.github.com',
        'commit', '-q', '-m', message)
    for attempt in range(3):                                   # someone else may have published meanwhile
        if subprocess.run(['git', 'push', '-q', 'origin', 'HEAD:main'], cwd=SITE).returncode == 0:
            break
        git('pull', '-q', '--rebase', 'origin', 'main')
    else:
        raise SystemExit('[site] could not push to the site repo (write access? network?)')
    sha = git('rev-parse', '--short', 'HEAD')
    say(f'pushed {sha}: Cloudflare puts it live in about a minute' + (f' at {live_url()}' if live_url() else ''))
    return sha


def wait_live(rel, local, timeout=300):
    """Poll the live site until `rel` matches the local file (Cloudflare finished deploying)."""
    url = live_url()
    if not url:
        return False
    want = Path(local).read_bytes()
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            got = urllib.request.urlopen(urllib.request.Request(f'{url}/{rel}?t={int(time.time())}', headers={
                'Cache-Control': 'no-cache', 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) an-maker'}),  # Cloudflare blocks Python's default
                timeout=30).read()
            if got == want:
                say(f'live: {url}')
                return True
        except Exception:
            pass
        time.sleep(10)
    say(f'not live after {timeout // 60} min - check the Cloudflare Pages dashboard')
    return False


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('publish')
    p.add_argument('--files', nargs='*', default=[])
    p.add_argument('--page', default='')
    p.add_argument('-m', '--message', default='update')
    p.add_argument('--wait', action='store_true', help='wait until the change is live')
    sub.add_parser('status')
    a = ap.parse_args()
    if a.cmd == 'status':
        checkout()
        print(git('log', '--format=  %h %ad %an: %s', '--date=short', '-8'))
        print(f'  live at {live_url() or "(tools/site_url.txt not set)"}')
        return
    sha = publish(a.files, a.page or None, a.message)
    if sha and a.wait:
        rel = a.files[0] if a.files else 'index.html'
        wait_live(rel, SITE / rel)


if __name__ == '__main__':
    main()
