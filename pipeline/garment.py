"""AN Maker garment maker: one entry point for the whole hardened clothing pipeline (docs/clothing-pipeline.md).

The AI agent (Claude Code or Codex, see CLAUDE.md / AGENTS.md / .claude/skills/new-garment) writes the creative
brief; this script runs every mechanical step, the same way each time, and stops on any failed check.

  setup     --name NAME --mesh assethub|higgsfield|none --max-credits N --publish yes|no   save this machine's answers
  doctor    check Blender, Python packages, Codex image generation, mesh credits, git and the data
  update    pull the latest pipeline (run first, every time; links a downloaded zip to git the first time)
  shell-top     --key K --label L --theme "..." [--sleeve 0.45] [--hem -2]            fitted tee / tank / crop top
  shell-bottom  --key K --label L --theme "..." [--leg 1.0] [--rise 9.5]             leggings / capris / bike shorts
  generated     --key K --label L --slot top|bottom|outerwear --description "..."   loose 3D garment (mesh credits)
                [--ref image.png] [--loft-mm N] [--tries 2] [--badge-art art.png --badge-place sleeve-left|logo]
  emblem    --key K --brief "..." [--ref img]   Codex draws a logo emblem (no letters) -> Outfits/badges/K/emblem.png
  badge     --key K --art art.png --place logo|sleeve-left|sleeve-right   (re)draw a generated piece's logo crisply
  export    rebuild the customizer's files (web/customizer/assets) from the catalog; lists what changed
  preview   serve web/customizer on http://localhost:8765 to look at the result
  save      --key K   commit the new piece and push it, so the other machine gets it

Run from anywhere: python pipeline/garment.py <command> ...
"""
import argparse, filecmp, http.server, json, os, shutil, socketserver, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
T = ROOT / 'pipeline' / 'tpose'
sys.path.insert(0, str(T))
import anmaker_config as CFG  # noqa: E402
import catalog  # noqa: E402

OUT = ROOT / 'Outfits'
WEB = ROOT / 'web' / 'customizer'
TEE = 'tee-groovy-sun-tee:groovy_sun_tee'                       # standard partners for combo checks
JOG = 'hoodie-boy-joggers5:olive_cargo_joggers'
SHORTS = 'legs-like-pro-shorts:like_pro_shorts'
HOODIE = 'hoodie-boy-hoodiebag2:black_graphic_hoodie_with_gray_crossbody_bag'
SHOES = 'hoodie-boy:multicolor_high_top_sneakers'
REPO_FILE = ROOT / 'tools' / 'repo.txt'                          # the GitHub repo this copy updates from


def say(msg):
    print(f'[garment] {msg}', flush=True)


def stop(msg):
    print(f'[garment] STOPPED: {msg}', flush=True)
    sys.exit(1)


def run(cmd, env=None, check=True, quiet=False):
    cmd = [str(c) for c in cmd]
    if not quiet:
        say('$ ' + ' '.join(c if ' ' not in c else f'"{c}"' for c in cmd[:8]) + (' ...' if len(cmd) > 8 else ''))
    r = subprocess.run(cmd, cwd=ROOT, env={**os.environ, **(env or {})}, text=True, encoding='utf-8',
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if check and r.returncode:
        print(r.stdout[-4000:])
        stop(f'{Path(cmd[0]).name} {" ".join(cmd[1:3])} failed (exit {r.returncode})')
    return r


def blender(script, *args, check=True):
    r = run([CFG.blender(), '-b', '--factory-startup', '-P', T / script, '--', *args], check=False)
    if check and (r.returncode or 'Traceback' in r.stdout):    # Blender exits 0 even when its script crashes
        print(r.stdout[-3000:])
        stop(f'Blender step {script} failed (above)')
    return r


def py(script, *args, env=None, check=True, stream=False):
    if stream:                                                  # long steps (gate, Codex): show progress live
        say(f'$ python {script} ...')
        r = subprocess.run([sys.executable, '-u', str(T / script), *map(str, args)], cwd=ROOT,
                           env={**os.environ, **(env or {})})
        if check and r.returncode:
            stop(f'{script} failed (exit {r.returncode})')
        return r
    return run([sys.executable, T / script, *args], env=env, check=check)


def cfg():
    c = CFG.load()
    if not c:
        stop('this copy is not set up yet: run  python pipeline/garment.py setup ...  (the agent asks you the questions)')
    return c


def inspect(look, pieces):
    blender('equip.py', '--base', 'Xander', '--name', look, '--pieces', *pieces)
    blender('inspect_look.py', f'Outfits/_looks/{look}', 'Xander', check=False)
    rep = json.loads((OUT / '_looks' / look / '08_inspect' / 'inspect.json').read_text(encoding='utf-8'))
    fails = rep.get('fails') or []
    say(f'{look}: ' + ('PASS' if not fails else 'FAIL\n    - ' + '\n    - '.join(fails)))
    return fails


def check_key(key):
    if not key.replace('_', '').isalnum() or key != key.lower():
        stop(f'key must be lower_snake_case letters and digits: {key!r}')
    if any(sp.endswith(':' + key) for sp in catalog.all_specs()):
        stop(f'{key} is already in the wardrobe - pick a new key')


# ---------------------------------------------------------------- setup / doctor / update
def cmd_setup(a):
    c = CFG.load()
    c.update({'name': a.name, 'mesh': a.mesh, 'max_credits': a.max_credits, 'publish': a.publish == 'yes'})
    c['blender'] = a.blender or c.get('blender') or CFG.find_blender()
    CFG.save(c)
    say(f'saved {CFG.CONFIG}')
    cmd_doctor(a)


def cmd_doctor(a):
    c, ok = CFG.load(), True

    def line(good, what, fix=''):
        nonlocal ok
        ok &= bool(good)
        print(f'  [{"ok" if good else "!!"}] {what}' + ('' if good else f'  ->  {fix}'), flush=True)

    print('AN Maker garment maker - checks')
    line(sys.version_info >= (3, 10), f'Python {sys.version.split()[0]}', 'install Python 3.10+ from python.org')
    for mod, pkg in (('numpy', 'numpy'), ('PIL', 'pillow')):
        try:
            __import__(mod); line(True, f'Python package {pkg}')
        except ImportError:
            line(False, f'Python package {pkg}', f'python -m pip install {pkg}')
    b = CFG.blender()
    v = subprocess.run([b, '--version'], capture_output=True, text=True).stdout.split('\n')[0] if shutil.which(b) or Path(b).exists() else ''
    line(v.startswith('Blender 5'), f'Blender: {v or "not found"} ({b})',
         'install Blender 5.2 from blender.org, then run setup again (or set AN_BLENDER to blender.exe)')
    cx = shutil.which('codex')
    line(cx, 'Codex CLI (image generation)', 'npm install -g @openai/codex   then   codex login  (ChatGPT plan)')
    if cx:
        st = subprocess.run('codex login status', shell=True, capture_output=True, text=True)
        line(st.returncode == 0 and 'not' not in (st.stdout + st.stderr).lower(), 'Codex signed in',
             'run  codex login  and sign in with the ChatGPT account')
    mesh = c.get('mesh', 'none')
    if mesh == 'none':
        print('  [--] 3D mesh provider: none (fitted tees, tanks, leggings and shorts only)')
    else:
        exe = 'assethub' if mesh == 'assethub' else 'higgsfield'
        line(shutil.which(exe), f'{exe} CLI', f'install the {exe} CLI and sign in with YOUR OWN account/API key')
        if shutil.which(exe):
            os.environ['MESH_PROVIDER'] = mesh
            import s4_meshes as S4
            S4.PROVIDER = mesh
            cr = S4.credits()
            line(cr is not None, f'{exe} credits: {cr}', f'sign in:  {exe} auth login  (never paste a password into chat)')
            if cr is not None and cr < S4.cost_per_mesh():
                print(f'  [!!] only {cr:g} credits: a 3D garment needs about {S4.cost_per_mesh()} per try - top up first')
    line(shutil.which('git'), 'git (for updates)', 'install Git for Windows: https://git-scm.com/download/win')
    line((ROOT / '.git').exists(), 'linked to GitHub for updates', 'python pipeline/garment.py update')
    line(len(str(ROOT)) <= 60, f'folder path is short enough ({len(str(ROOT))} characters)',
         'Windows limits paths to 260 characters: move this folder somewhere short, like C:\an-maker')
    need = [ROOT / 'Bases' / 'Xander.blend', ROOT / 'Bases' / 'Xander.json']
    need += [OUT / s.split(':')[0] / '06_fitted' / 'manifest.json' for s in catalog.all_specs()]
    miss = [str(p.relative_to(ROOT)) for p in need if not p.exists()]
    line(not miss, 'wardrobe data present', f'missing {miss[:3]} - re-download the zip')
    print('ALL GOOD' if ok else 'FIX THE !! LINES ABOVE, then run doctor again', flush=True)
    return ok


def git(*args, check=True):
    return run(['git', *args], check=check, quiet=True)


def cmd_update(a):
    if not shutil.which('git'):
        stop('git is not installed (https://git-scm.com/download/win) - needed for updates')
    url = REPO_FILE.read_text(encoding='utf-8').strip() if REPO_FILE.exists() else ''
    if not (ROOT / '.git').exists():                            # a downloaded zip: turn it into a clone, keep the files
        if not url:
            stop('tools/repo.txt is missing - ask the owner for the repo address')
        say(f'linking this folder to {url} (one time; GitHub may open a browser to sign in)')
        git('init', '-q'); git('remote', 'add', 'origin', url)
        git('fetch', '-q', 'origin', 'main')
        git('reset', '-q', 'origin/main')                        # history from GitHub, your files untouched
    before = git('rev-parse', 'HEAD', check=False).stdout.strip()
    dirty = git('status', '--porcelain', '--untracked-files=no').stdout.strip()
    if dirty:
        git('stash', '-q')
    r = git('pull', '-q', '--rebase', 'origin', 'main', check=False)
    if dirty:
        git('stash', 'pop', '-q', check=False)
    if r.returncode:
        stop('could not pull the update: ' + r.stdout[-500:])
    after = git('rev-parse', 'HEAD').stdout.strip()
    if before == after:
        say('already up to date')
    else:
        say('updated. What is new:')
        print(git('log', '--format=  - %s', f'{before}..{after}', check=False).stdout if before else '  (first link)')


# ---------------------------------------------------------------- shell garments (no mesh credits)
def cmd_shell_top(a):
    check_key(a.key); c = cfg()
    import tee_kit as TK
    d = OUT / 'tee-kits' / a.key
    TK.make(d, a.theme, 24, 'fabric')
    TK.prepare(d, 2048)
    spec, fails = TK.build_shirt(d, a.key, a.sleeve, a.hem, 2048)
    if fails:
        stop('the shirt failed inspection (see above) - change the theme or cut and run again')
    catalog.add(spec, 'shell-top', a.label, 20, c.get('name', ''))
    say(f'DONE: {a.label} built and inspected ({spec}). Next: export, preview, then save.')


def cmd_shell_bottom(a):
    check_key(a.key); c = cfg()
    import legging_kit as LK
    d = LK.KITS / a.key
    LK.make(d, a.theme)
    LK.prepare(d)
    spec, fails = LK.build_one({'key': a.key, 'kit': a.key, 'leg': a.leg, 'rise_cm': a.rise}, 2048)
    if fails:
        stop('the bottoms failed inspection (see above) - change the theme or cut and run again')
    catalog.add(spec, 'shell-bottom', a.label, 30, c.get('name', ''))
    say(f'DONE: {a.label} built and inspected ({spec}). Next: export, preview, then save.')


# ---------------------------------------------------------------- generated garments (mesh credits)
CONCEPT = """Use your image generation tool. Image 1 is a 3D render of a stylised game avatar (Genies / Bitmoji style) in a
T-pose, front view, on a plain white background. Generate ONE image: the same character, same pose, camera, framing,
render style and white background, now wearing: {desc}
{ref}Keep the face, hair and body exactly as in image 1. Save the image as ./concept.png. Reply with only the saved path."""


def combos(slot, spec):
    if slot == 'bottom':
        return 'gate', [spec], {'tee': [TEE, spec], 'bundle': [spec, HOODIE], 'shoes': [spec, SHOES]}
    if slot == 'top':
        return 'gate', [JOG, spec], {'alone': [spec], 'shorts': [SHORTS, spec]}
    return 'gate', [TEE, JOG, spec], {'alone': [spec], 'shorts': [TEE, SHORTS, spec]}


def cmd_generated(a):
    check_key(a.key); c = cfg()
    mesh = c.get('mesh', 'none')
    if mesh == 'none' and not a.draw_only:
        stop('3D garments need a mesh provider (setup --mesh assethub|higgsfield). Fitted pieces: shell-top / shell-bottom.')
    env = {'MESH_PROVIDER': mesh}
    os.environ.update(env)
    import s4_meshes as S4
    S4.PROVIDER = mesh
    cost, have = S4.cost_per_mesh() * a.tries, (None if a.draw_only else S4.credits())
    say(f'budget: up to {a.tries} mesh tries x {S4.cost_per_mesh()} = {cost} credits ({mesh}, {have} available)')
    if cost > c.get('max_credits', 50) and not a.allow and not a.draw_only:
        stop(f'that is over your limit of {c.get("max_credits")} credits per garment - lower --tries or pass --allow')
    if have is not None and have < S4.cost_per_mesh():
        stop(f'only {have} {mesh} credits left - top up first')
    src, out = OUT / f'src-{a.key}', OUT / f'gen-{a.key.replace("_", "-")}'
    src.mkdir(parents=True, exist_ok=True)
    piece = {'key': a.key, 'slot': a.slot, 'description': a.description}
    if a.loft_mm:
        piece['loft_mm'] = a.loft_mm
    (src / 'outfit.json').write_text(json.dumps({'pieces': [piece]}, indent=2), encoding='utf-8')
    if not (src / '01_mannequin' / 'front.png').exists():
        blender('s1_render_mannequin.py', src, 'Xander')
    if not (src / 'concept.png').exists():
        from s2_images import codex
        imgs = [src / '01_mannequin' / 'front.png']
        ref = ''
        if a.ref:
            shutil.copy(a.ref, src / 'reference.png'); imgs.append(src / 'reference.png')
            ref = 'Image 2 is a reference for the design: take it as inspiration (shape, colours, details), not a copy.\n'
        if not codex(src, CONCEPT.format(desc=a.description, ref=ref), imgs, src / 'concept.png', src / 'codex.log'):
            stop('Codex did not draw the concept - is Codex signed in? (doctor)')
    # the layers underneath, rendered (a bottom is drawn straight on the avatar)
    under = OUT / '_looks' / f'under-{a.slot}'
    if a.slot != 'bottom' and not (under / '06_fitted').exists():
        blender('equip.py', '--base', 'Xander', '--name', f'under-{a.slot}',
                '--pieces', *([JOG] if a.slot == 'top' else [TEE, JOG]))
    py('s2_over.py', '--look', under if a.slot != 'bottom' else src, '--base', 'Xander', '--from', src, '--key', a.key,
       '--out', out, *(['--under-mannequin'] if a.slot == 'bottom' else []), stream=True)
    chk = json.loads((out / 'image_checks.json').read_text(encoding='utf-8'))
    if not chk.get('pass'):
        stop(f'the drawings did not pass the 2D checks after the free redraws: {chk.get("failing_views")} - '
             'adjust the description (see the REDO reasons above) and run again')
    if a.draw_only:
        say(f'drawings done and checked (free): {(out / "03_garments").relative_to(ROOT)}. Run again without --draw-only '
            'to build it in 3D (it reuses these drawings).')
        return
    spec = f'{out.name}:{a.key}'
    gate_look, pieces, extra = combos(a.slot, spec)
    gate_args = ['--outfit', out, '--key', a.key, '--base', 'Xander', '--look', f'{gate_look}-{a.key}', '--pieces', *pieces]
    for n, p in extra.items():
        gate_args += ['--combo', f'combo-{a.key}-{n}=' + ','.join(p)]
    gate_args += ['--tries', a.tries]
    if (out / '04_meshes' / f'{a.key}.glb').exists():
        gate_args.append('--redo-first')                         # a mesh from an earlier run already failed
    py('gate.py', *gate_args, env=env, stream=True)
    if a.badge_art:
        bake_badge(a.key, out, a.badge_art, a.badge_place)
    looks = [(f'web-{a.key}', [spec]), (f'{gate_look}-{a.key}', pieces)] + [(f'combo-{a.key}-{n}', p) for n, p in extra.items()]
    fails = [f for look, p in looks for f in inspect(look, p)]
    catalog.add(spec, 'generated', a.label, 55, c.get('name', ''))
    if fails:
        say(f'{a.label} is built but has {len(fails)} inspection notes (listed above). Look at it in the preview; '
            'the agent explains each one. To drop it: python pipeline/garment.py remove --key ' + a.key)
    else:
        say(f'DONE: {a.label} passed every check.')
    say('Next: export, preview, then save.')


def bake_badge(key, out, art, place):
    py('decal_bake.py', '--outfit', out.relative_to(ROOT), '--key', key, '--decal', art, '--place', place)
    blender('s6_fit.py', out, 'Xander')


def cmd_badge(a):
    e = next((e for e in catalog.entries() if e['spec'].endswith(':' + a.key)), None)
    if not e or e.get('kind') != 'generated':
        stop(f'{a.key} is not a generated piece in the catalog')
    out = OUT / e['spec'].split(':')[0]
    bake_badge(a.key, out, a.art, a.place)
    inspect(f'web-{a.key}', [e['spec']])
    say('badge baked. Next: export, preview, then save.')


EMBLEM = """Use your image generation tool to make emblem.png in the current folder (and nothing else anywhere).
A crisp, flat, vector-style PARODY emblem for an invented brand: {brief}
{ref}Flat colours, crisp edges, no gradient, no texture, no shadow, no perspective. NO text, no letters, no numbers.
Centred, filling about 80% of a 1024x1024 canvas, on a fully transparent background (RGBA PNG). If transparency is
impossible, use a flat pure #00FF00 background."""


def cmd_emblem(a):
    from s2_images import codex
    d = OUT / 'badges' / a.key
    d.mkdir(parents=True, exist_ok=True)
    imgs, ref = [], ''
    if a.ref:
        shutil.copy(a.ref, d / 'reference.png'); imgs.append(d / 'reference.png')
        ref = 'Image 1 is a reference for the idea only: make an ORIGINAL parody, never a copy of a real logo.\n'
    (d / 'emblem.png').unlink(missing_ok=True)
    if not codex(d, EMBLEM.format(brief=a.brief, ref=ref), imgs, d / 'emblem.png', d / 'codex.log'):
        stop('Codex did not draw the emblem - is Codex signed in? (doctor)')
    say(f'emblem: {(d / "emblem.png").relative_to(ROOT)}  - next: pipeline/tpose/badge_art.py to add the name')


def cmd_remove(a):
    f = catalog.PIECES / f'{a.key}.json'
    if f.exists():
        f.unlink(); say(f'{a.key} taken out of the wardrobe (its files stay in Outfits/)')


# ---------------------------------------------------------------- export / preview / save
WEB_OWNED = ('manifest.json', 'body.', 'body_img', 'piece_')               # what the clothing export writes; the rest is the page's


def cmd_export(a):
    import tee_kit as TK
    specs = catalog.all_specs()
    for s in specs:                                             # the body's skin masks come from each piece's own look
        key = s.split(':')[1]
        if not list((OUT / '_looks' / f'web-{key}' / '06_fitted').glob('*.blend')):
            blender('equip.py', '--base', 'Xander', '--name', f'web-{key}', '--pieces', s)
    TK.export(specs)
    test, live = WEB / 'assets-test', WEB / 'assets'
    changed = []
    for f in sorted(test.rglob('*')):
        if f.is_dir() or f.suffix == '.glb' or not f.name.startswith(WEB_OWNED):
            continue
        rel = f.relative_to(test)
        dst = live / rel
        if not dst.exists() or not filecmp.cmp(f, dst, shallow=False):
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, dst)
            changed.append(str(rel).replace('\\', '/'))
    (ROOT / '.anmaker').mkdir(exist_ok=True)
    (ROOT / '.anmaker' / 'publish_list.json').write_text(json.dumps(changed, indent=2), encoding='utf-8')
    say(f'export done: {len(changed)} files changed in web/customizer/assets (list: .anmaker/publish_list.json)')
    for c_ in changed:
        print('   ', c_)


def cmd_preview(a):
    os.chdir(WEB)

    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *x):
            pass
    say('preview on http://localhost:8765  (Ctrl+C to stop). Pick the new piece under Outfit.')
    with socketserver.TCPServer(('127.0.0.1', 8765), Quiet) as s:
        s.serve_forever()


def cmd_save(a):
    c = cfg()
    if not (ROOT / '.git').exists():
        stop('not linked to GitHub yet: python pipeline/garment.py update')
    e = next((e for e in catalog.entries() if e['spec'].endswith(':' + a.key)), None)
    if not e:
        stop(f'{a.key} is not in the catalog')
    outfit = e['spec'].split(':')[0]
    paths = [f'catalog/pieces/{a.key}.json', f'Outfits/{outfit}/06_fitted', f'Outfits/{outfit}/outfit.json',
             f'Outfits/{outfit}/04_meshes/{a.key}_tex', f'Outfits/src-{a.key}/outfit.json', f'Outfits/src-{a.key}/concept.png',
             f'Outfits/tee-kits/{a.key}/raw', f'Outfits/legging-kits/{a.key}/raw']
    for p in paths:
        if (ROOT / p).exists():
            git('add', '-f', p)
    git('commit', '-q', '-m', f'Add {e["label"]} ({a.key}) by {c.get("name", "?")}')
    r = git('pull', '-q', '--rebase', 'origin', 'main', check=False)
    if r.returncode:
        stop('could not merge with the latest version: ' + r.stdout[-400:])
    git('push', '-q', 'origin', 'HEAD:main')
    say(f'saved and pushed {e["label"]} - the other machine gets it on its next update')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    s = sub.add_parser('setup')
    s.add_argument('--name', required=True)
    s.add_argument('--mesh', choices=['assethub', 'higgsfield', 'none'], required=True)
    s.add_argument('--max-credits', type=int, default=50)
    s.add_argument('--publish', choices=['yes', 'no'], default='no')
    s.add_argument('--blender', default='')
    sub.add_parser('doctor'); sub.add_parser('update'); sub.add_parser('export'); sub.add_parser('preview')
    s = sub.add_parser('shell-top')
    s.add_argument('--key', required=True); s.add_argument('--label', required=True); s.add_argument('--theme', required=True)
    s.add_argument('--sleeve', type=float, default=0.45); s.add_argument('--hem', type=float, default=-2)
    s = sub.add_parser('shell-bottom')
    s.add_argument('--key', required=True); s.add_argument('--label', required=True); s.add_argument('--theme', required=True)
    s.add_argument('--leg', type=float, default=1.0); s.add_argument('--rise', type=float, default=9.5)
    s = sub.add_parser('generated')
    s.add_argument('--key', required=True); s.add_argument('--label', required=True)
    s.add_argument('--slot', choices=['top', 'bottom', 'outerwear'], required=True)
    s.add_argument('--description', required=True); s.add_argument('--ref', default='')
    s.add_argument('--loft-mm', type=float, default=0); s.add_argument('--tries', type=int, default=2)
    s.add_argument('--allow', action='store_true', help='allow spending over max_credits')
    s.add_argument('--draw-only', action='store_true', help='stop after the (free) drawings and their checks')
    s.add_argument('--badge-art', default=''); s.add_argument('--badge-place', default='sleeve-left',
                                                               choices=['logo', 'sleeve-left', 'sleeve-right'])
    s = sub.add_parser('emblem')
    s.add_argument('--key', required=True); s.add_argument('--brief', required=True); s.add_argument('--ref', default='')
    s = sub.add_parser('badge')
    s.add_argument('--key', required=True); s.add_argument('--art', required=True)
    s.add_argument('--place', choices=['logo', 'sleeve-left', 'sleeve-right'], default='logo')
    s = sub.add_parser('remove'); s.add_argument('--key', required=True)
    s = sub.add_parser('save'); s.add_argument('--key', required=True)
    a = ap.parse_args()
    {'setup': cmd_setup, 'doctor': cmd_doctor, 'update': cmd_update, 'shell-top': cmd_shell_top,
     'shell-bottom': cmd_shell_bottom, 'generated': cmd_generated, 'emblem': cmd_emblem, 'badge': cmd_badge, 'remove': cmd_remove,
     'export': cmd_export, 'preview': cmd_preview, 'save': cmd_save}[a.cmd](a)


if __name__ == '__main__':
    main()
