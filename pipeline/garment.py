"""AN Maker garment maker: one entry point for the whole hardened clothing pipeline (docs/clothing-pipeline.md).

The AI agent (Claude Code or Codex, see CLAUDE.md / AGENTS.md / .claude/skills/new-garment) writes the creative
brief; this script runs every mechanical step, the same way each time, and stops on any failed check.

  setup     --name NAME --mesh assethub|higgsfield|none --max-credits N --publish yes|no   install (a dropped zip goes to
            ~/an-maker), save this machine's answers, link to GitHub, run the doctor
  doctor    check Blender, Python packages, Codex image generation, mesh credits, git and the data
  update    pull the latest pipeline (run first, every time; links a downloaded zip to git the first time)
  shell-top     --key K --label L --theme "..." [--sleeve 0.45] [--hem -2]            fitted tee / tank / crop top
  shell-bottom  --key K --label L --theme "..." [--leg 1.0] [--rise 9.5]             leggings / capris / bike shorts
  generated     --key K --label L --slot top|bottom|outerwear --description "..."   loose 3D garment (mesh credits)
                [--ref image.png] [--loft-mm N] [--tries 2] [--badge-art art.png --badge-place sleeve-left|logo]
  image     --prompt "..." --out file.png [--ref img]... [--size WxH] [--transparent]   one image, any provider
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
import anmaker_tools  # noqa: E402
import catalog  # noqa: E402
anmaker_tools.fix_path()                                        # tools setup installed, before this shell knew them
os.environ.setdefault('AN_PYTHON', sys.executable)              # Blender steps draw their pictures with this Python

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


def replace(key):
    """A requested change: take the piece out of the wardrobe and set its old build aside (kept in Outfits/_replaced),
    so the same key is built again from scratch. Free; the rebuild costs what a new piece costs."""
    import time
    (catalog.PIECES / f'{key}.json').unlink(missing_ok=True)
    keep = OUT / '_replaced' / f'{key}-{time.strftime("%Y%m%d-%H%M%S")}'
    for d in (OUT / 'tee-kits' / key, OUT / 'legging-kits' / key, OUT / f'src-{key}', OUT / f'gen-{key.replace("_", "-")}',
              OUT / f'tee-{key.replace("_", "-")}', OUT / f'legs-{key.replace("_", "-")}'):
        if d.exists():
            keep.mkdir(parents=True, exist_ok=True)
            shutil.move(str(d), str(keep / d.name))
    say(f'{key}: old version set aside, building it again')


def check_key(key):
    if not key.replace('_', '').isalnum() or key != key.lower():
        stop(f'key must be lower_snake_case letters and digits: {key!r}')
    if any(sp.endswith(':' + key) for sp in catalog.all_specs()):
        stop(f'{key} is already in the wardrobe - pick a new key')


# ---------------------------------------------------------------- image generation
IMAGES_PER = {'generated': 8, 'shell-top': 3, 'shell-bottom': 1, 'emblem': 1}   # typical images per command


def images_note(kind='generated'):
    import imagegen
    b = imagegen.backend()
    if b == 'codex':
        say('images: Codex (ChatGPT plan), no credits')
    else:
        say(f'images: {b}, about {imagegen.cost_per_image(b)} credits each, typically {IMAGES_PER[kind]} for this '
            f'(about {imagegen.cost_per_image(b) * IMAGES_PER[kind]} credits)')


def codex_ready():
    if not shutil.which('codex'):
        return False
    st = subprocess.run('codex login status', shell=True, capture_output=True, text=True)
    return st.returncode == 0 and 'not' not in (st.stdout + st.stderr).lower()


def pick_images(choice, mesh):
    """auto: Codex when it is (or can be) signed in on this PC - inside Codex it always is - else the paid image
    generation of the 3D account they already have."""
    if choice != 'auto':
        return choice
    if codex_ready() or (Path.home() / '.codex' / 'auth.json').exists():
        return 'codex'
    return mesh if mesh in ('assethub', 'higgsfield') else 'codex'


def cmd_image(a):
    """One image, for the assistant to use directly (e.g. to try an idea), with this machine's provider."""
    import imagegen
    out = Path(a.out).resolve()
    size = tuple(int(v) for v in a.size.lower().split('x')) if a.size else None
    if imagegen.backend() == 'codex':
        from s2_images import codex
        ok = codex(out.parent, f'Use your image generation tool. {a.prompt}\nSave the image as ./{out.name}. Reply with '
                   'only the saved path.', [Path(r).resolve() for r in a.ref], out, out.parent / 'codex.log')
    else:
        ok = imagegen.paid_image(a.prompt, a.ref, out, size, a.transparent)
    if not ok:
        stop('image generation failed (doctor)')
    say(f'saved {out}')


# ---------------------------------------------------------------- setup / doctor / update
HOME = Path.home() / 'an-maker'                                 # where a teammate's copy lives (short path for Windows)
POINTER = """AN Maker garment maker is installed at {home}.
When the person asks to make, change or publish a top, bottoms or outerwear for AN Maker (or says "set me up",
"run the doctor" or "publish it"), work in that folder: read {home}/docs/garment-agent.md and follow it exactly,
starting with its step 0, and run every command from {home}. If you can switch this session's folder to {home},
do. Only garments: never change the AN Maker site, renderer or pipeline. Always ask "Is it good to publish, or would
you like any changes?" and never publish without an explicit "publish"."""


def install_home(a):
    """Setup run from a downloaded zip unpacked anywhere (a Downloads or chat-attachment folder): copy it to the short
    home folder once, and carry on there. If it's already installed, use that copy."""
    home = Path(a.home).expanduser() if a.home else HOME
    if ROOT.resolve() == home.resolve():
        return
    if not (home / 'pipeline' / 'garment.py').exists():
        if home.exists() and any(home.iterdir()):
            stop(f'{home} exists but is not AN Maker: pass --home with another empty folder')
        say(f'installing to {home} (a short path, so Windows file-name limits never bite)')
        shutil.copytree(ROOT, home, dirs_exist_ok=True, ignore=shutil.ignore_patterns('.anmaker'))
    else:
        say(f'already installed at {home}: using that copy')
    say(f'the downloaded copy in {ROOT} is not needed any more')
    sys.exit(subprocess.run([sys.executable, str(home / 'pipeline' / 'garment.py'), *sys.argv[1:]], cwd=home).returncode)


def install_pointers():
    """So that later chats work from any folder: a Claude Code skill and a Codex AGENTS.md note that point here."""
    text = POINTER.format(home=ROOT.as_posix())
    skill = Path.home() / '.claude' / 'skills' / 'an-maker' / 'SKILL.md'
    skill.parent.mkdir(parents=True, exist_ok=True)
    skill.write_text('---\nname: an-maker\ndescription: Make, change or publish an AN Maker garment (a top, bottoms or '
                     'outerwear such as a tee, leggings, hoodie or puffer), set up the AN Maker garment maker, or run '
                     'its doctor.\n---\n\n' + text + '\n', encoding='utf-8')
    agents = Path.home() / '.codex' / 'AGENTS.md'
    start, end = '<!-- an-maker -->', '<!-- /an-maker -->'
    cur = agents.read_text(encoding='utf-8') if agents.exists() else ''
    if start in cur and end in cur:
        cur = cur[:cur.index(start)] + cur[cur.index(end) + len(end):]
    agents.parent.mkdir(parents=True, exist_ok=True)
    agents.write_text(cur.rstrip() + ('\n\n' if cur.strip() else '') + f'{start}\n## AN Maker\n\n{text}\n{end}\n',
                      encoding='utf-8')
    say(f'later chats find it from any folder (Claude Code skill "an-maker", and {agents})')


def cmd_setup(a):
    if a.role == 'teammate':
        install_home(a)
    c = CFG.load()
    c.update({'name': a.name, 'mesh': a.mesh, 'max_credits': a.max_credits, 'publish': a.publish == 'yes',
              'role': a.role, 'images': pick_images(a.images, a.mesh)})
    say(f'image generation: {c["images"]}')
    missing = anmaker_tools.ensure(c)                           # install whatever is missing (Blender, Git, CLIs)
    c['blender'] = a.blender or c.get('blender') or CFG.find_blender()
    CFG.save(c)
    say(f'saved {CFG.CONFIG}' + (f'; still missing: {", ".join(missing)}' if missing else ''))
    if a.role == 'teammate':                                    # this machine may make garments, never change the site
        lock = ROOT / '.claude' / 'settings.local.json'
        paths = ['web/customizer/**', 'pipeline/**', 'docs/**', 'catalog/**', 'Bases/**', '.claude/**', 'tools/**',
                 'CLAUDE.md', 'AGENTS.md', 'README.md', 'CHANGELOG.md', '.gitignore', '.gitattributes']
        deny = [f'{tool}({pre}{q})' for tool in ('Edit', 'Write') for q in paths for pre in ('', '/')]
        cur = json.loads(lock.read_text(encoding='utf-8')) if lock.exists() else {}
        cur.setdefault('permissions', {})['deny'] = sorted(set(cur.get('permissions', {}).get('deny', []) + deny))
        lock.parent.mkdir(exist_ok=True)
        lock.write_text(json.dumps(cur, indent=2), encoding='utf-8')
        say('teammate mode: the site, renderer and pipeline files are locked for the assistant on this machine')
        install_pointers()
    if shutil.which('git'):                                     # link to GitHub now, so updates just work
        try:
            cmd_update(a)
        except SystemExit:
            say('could not link to GitHub yet (doctor says why); setup carries on')
    cmd_doctor(a)
    say(f'set up in {ROOT}')


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
    line(v.startswith('Blender 5'), f'Blender: {v or "not found"} ({b})', 'run setup again (it installs Blender 5.2)')
    import imagegen
    img = imagegen.backend()
    if img == 'codex':
        cx = shutil.which('codex')
        line(cx, 'Codex CLI (image generation)', 'run setup again (it installs it)')
        if cx:
            line(codex_ready(), 'Codex signed in (image generation, ChatGPT plan)',
                 'run  codex login  and sign in with your ChatGPT account (no ChatGPT plan? setup --images assethub)')
    else:
        line(shutil.which(img), f'{img} CLI (image generation, paid)', 'run setup again (it installs it)')
        if shutil.which(img):
            cr = imagegen._credits(img)
            line(cr is not None, f'{img} images: {cr} credits, about {imagegen.cost_per_image(img)} per image',
                 f'sign in:  {img} auth login  (in your own terminal; never paste a key into chat)')
    mesh = c.get('mesh', 'none')
    if mesh == 'none':
        print('  [--] 3D mesh provider: none (fitted tees, tanks, leggings and shorts only)')
    else:
        exe = 'assethub' if mesh == 'assethub' else 'higgsfield'
        line(shutil.which(exe), f'{exe} CLI', 'run setup again (it installs it)')
        if shutil.which(exe):
            os.environ['MESH_PROVIDER'] = mesh
            import s4_meshes as S4
            S4.PROVIDER = mesh
            cr = S4.credits()
            line(cr is not None, f'{exe} credits: {cr}', f'sign in:  {exe} auth login  (never paste a password into chat)')
            if cr is not None and cr < S4.cost_per_mesh():
                print(f'  [!!] only {cr:g} credits: a 3D garment needs about {S4.cost_per_mesh()} per try - top up first')
    line(shutil.which('git'), 'git (for updates)', 'run setup again (it installs Git)')
    line((ROOT / '.git').exists(), 'linked to GitHub for updates', 'python pipeline/garment.py update')
    line(len(str(ROOT)) <= 60, f'folder path is short enough ({len(str(ROOT))} characters)',
         r'Windows limits paths to 260 characters: run setup again: it installs to %USERPROFILE%\an-maker')
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
        git('init', '-q'); git('config', 'core.autocrlf', 'false'); git('remote', 'add', 'origin', url)
        git('fetch', '-q', 'origin', 'main')
        # the zip may be older than GitHub: take GitHub's version of every pipeline file. Files that are only yours
        # (new garments, .anmaker settings) are not tracked yet, so they stay as they are.
        git('reset', '-q', '--hard', 'origin/main')
        git('branch', '-q', '--set-upstream-to=origin/main', 'main', check=False)
        say('linked')
        return
    before = git('rev-parse', 'HEAD', check=False).stdout.strip()
    dirty = git('status', '--porcelain', '--untracked-files=no').stdout.strip()
    if dirty:                                                   # teammates don't edit pipeline files: set edits aside
        git('stash', '-q')
        say('local edits to pipeline files were set aside (git stash) so the update could go in')
    r = git('pull', '-q', '--rebase', 'origin', 'main', check=False)
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
    if a.replace:
        replace(a.key)
    check_key(a.key); c = cfg(); images_note('shell-top')
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
    if a.replace:
        replace(a.key)
    check_key(a.key); c = cfg(); images_note('shell-bottom')
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
    if a.replace:
        replace(a.key)
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
    images_note()
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
            stop('the concept drawing failed - is image generation signed in? (doctor)')
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
    fitted = [str(f.relative_to(ROOT)) for f in (OUT / outfit / '06_fitted').glob('*') if f.suffix in ('.glb', '.json')]
    paths = [f'catalog/pieces/{a.key}.json', *fitted, f'Outfits/{outfit}/outfit.json',
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
    s.add_argument('--role', choices=['teammate', 'owner'], default='teammate')
    s.add_argument('--images', choices=['auto', 'codex', 'assethub', 'higgsfield'], default='auto',
                   help='who draws: Codex (ChatGPT plan) or paid images; auto picks Codex when signed in')
    s.add_argument('--home', default='', help=r'install folder for a teammate copy (default: %%USERPROFILE%%\an-maker)')
    sub.add_parser('doctor'); sub.add_parser('update'); sub.add_parser('export'); sub.add_parser('preview')
    s = sub.add_parser('shell-top')
    s.add_argument('--replace', action='store_true', help='rebuild an existing piece (a requested change)')
    s.add_argument('--key', required=True); s.add_argument('--label', required=True); s.add_argument('--theme', required=True)
    s.add_argument('--sleeve', type=float, default=0.45); s.add_argument('--hem', type=float, default=-2)
    s = sub.add_parser('shell-bottom')
    s.add_argument('--replace', action='store_true', help='rebuild an existing piece (a requested change)')
    s.add_argument('--key', required=True); s.add_argument('--label', required=True); s.add_argument('--theme', required=True)
    s.add_argument('--leg', type=float, default=1.0); s.add_argument('--rise', type=float, default=9.5)
    s = sub.add_parser('generated')
    s.add_argument('--replace', action='store_true', help='rebuild an existing piece (a requested change)')
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
    s = sub.add_parser('image')
    s.add_argument('--prompt', required=True); s.add_argument('--out', required=True)
    s.add_argument('--ref', action='append', default=[]); s.add_argument('--size', default='')
    s.add_argument('--transparent', action='store_true')
    s = sub.add_parser('save'); s.add_argument('--key', required=True)
    a = ap.parse_args()
    {'setup': cmd_setup, 'doctor': cmd_doctor, 'update': cmd_update, 'shell-top': cmd_shell_top,
     'shell-bottom': cmd_shell_bottom, 'generated': cmd_generated, 'emblem': cmd_emblem, 'badge': cmd_badge, 'remove': cmd_remove,
     'export': cmd_export, 'preview': cmd_preview, 'save': cmd_save, 'image': cmd_image}[a.cmd](a)


if __name__ == '__main__':
    main()
