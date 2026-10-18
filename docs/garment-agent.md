# AN Maker garment maker: the agent's playbook

You are the AI agent (Claude Code or Codex) in an AN Maker garment folder. A teammate asks for a garment in plain
words ("a Moncler puffer spoof", "pink camo leggings", "baggy sweats like Champion", maybe with a reference image).
You do all of the thinking. They never pick a pipeline, a number or a file. Every mechanical step is one command:
`python pipeline/garment.py <command>`. How and why it works: `docs/clothing-pipeline.md`.

Talk to the teammate in plain, friendly words: no file paths, flags or jargon unless they ask.

## 0. Every time, first

1. `python pipeline/garment.py update`, to get the newest pipeline. If it says "not linked", that's fine on the
   very first run: setup links it.
2. If `.anmaker/config.json` does not exist, run **First-time setup** (below) before anything else.
3. Re-read this file after an update, because it may have changed.

## First-time setup (ask, then do)

Greet them, then ask these questions one at a time. Explain each in one line, and suggest a default.

1. **Your name**, for credits on what you make.
2. **3D garments**: loose clothes (hoodies, jackets, puffers, cargo or sweat pants) are made by a paid 3D generator.
   Which account will you use?
   - **AssetHub**, with your own API key (recommended, 25 credits per try);
   - **Higgsfield**, with your own account (about 18 credits per try);
   - **None for now**: only fitted tees, tanks, crops, leggings and shorts, which are free apart from image generation.
3. **Spending limit** per garment, in credits (default 50, which allows 2 tries).
4. **Publishing**: has the owner given you edit access to the AN Maker page? (yes / no / not sure; "no" is fine,
   the owner publishes for you.)

Then:

- Run `python pipeline/garment.py setup --name "<name>" --mesh assethub|higgsfield|none --max-credits N --publish yes|no`.
  This also runs `doctor`.
- Fix every `!!` line with the teammate. Install missing tools only with their OK, one at a time:
  - Blender: `winget install BlenderFoundation.Blender`. Blender 5.x is required; afterwards run setup again so the
    pipeline finds it.
  - Git: `winget install Git.Git`.
  - Python packages: `python -m pip install -r requirements.txt`.
  - Codex CLI: `npm install -g @openai/codex` (needs Node, `winget install OpenJS.NodeJS.LTS`).
- Sign-ins are theirs: `codex login` and `assethub auth login` (or `higgsfield auth login`) open a browser or ask in
  their own terminal. **Never ask them to paste a password or API key into the chat**, and never write one into a file.
- Run `python pipeline/garment.py update` to link to GitHub. Git may open a browser to sign in. The owner must have
  added their GitHub account to the repo.
- Run `python pipeline/garment.py doctor` until it says ALL GOOD.
- Run `python pipeline/garment.py export` once. It builds the local preview files (about 10-15 minutes the first time;
  tell them it's a good coffee break).
- Then tell them, in one short message: "You're all set. Just tell me what to make, e.g. *make me a Moncler-style
  puffer* or *pink camo leggings*. Add a picture if you have one for inspiration."

## 1. What can be made (and what can't yet)

Hardened and allowed:

- **Fitted tops**: tees, tanks, crop tops, fitted long-sleeve tops → `shell-top`.
- **Fitted bottoms**: leggings, yoga pants, tights, capris, bike shorts, compression shorts → `shell-bottom`.
- **Loose 3D garments**: hoodies, sweatshirts, jackets, puffers, coats, cardigans, loose shirts; joggers, sweatpants,
  cargos, jeans, loose shorts → `generated`.

Not allowed yet (say so kindly; these pipelines aren't hardened): hair, shoes, hats, bags or accessories on their own,
dresses, jumpsuits, skirts, makeup, face or expression changes, body changes, animations, and editing the AN Maker page
(`web/customizer/index.html`). Never edit `index.html`.

## 2. Pick the track yourself

- Skin-tight top → `shell-top`:
  - `--sleeve`: tank 0, short sleeve 0.45, elbow 0.9;
  - `--hem`: standard -2, crop 6.
- Skin-tight bottom → `shell-bottom`:
  - `--leg`: bike or compression shorts 0.25-0.3, capris 0.72, leggings 0.93-1.0;
  - `--rise` 9.5.
- Loose → `generated`:
  - `--slot bottom` for anything on the legs;
  - `--slot outerwear` for anything worn over a tee (hoodie, jacket, puffer, coat, cardigan, open shirt);
  - `--slot top` for a loose base layer (boxy tee, loose shirt).
- If it is unclear, choose the safer track and say what you chose in one line. Don't ask.

## 3. Write the brief (your creative job)

- **Key**: lower_snake_case, new (e.g. `monchill_puffer_jacket`). **Label**: the tile name (e.g. `MONCHILL Puffer`).
- **Brands are always parodies**, GTA style: a funny twist on the name and logo, never the real name or logo (Moncler →
  MONCHILL, Champion → CHAMPIGNON, Lululemon → lululemur, Nike Pro → LIKE PRO). Pick the funniest one yourself.
- **A reference image** is inspiration: pass it with `--ref`, describe what to take from it, and never copy a real logo.
- **Fitted pieces** (`--theme`): describe the print or colourway. The kit's image generation paints the fabric, so keep
  letters out of prints (they garble); a short brand word is OK only as a simple chest graphic.
- **Generated pieces** (`--description`): one paragraph. The pipeline adds the layer standard; still follow these rules,
  which come from real failures:
  - **Bottoms**: a FLAT waistband with the drawcord tucked inside (nothing hanging); hips and seat lie flat (no front
    pouch); full-length legs end in loose cuffs at the top of the ankle (where a high-top's collar sits), standing off the
    ankle all round, with the whole foot visible.
  - **Sleeves**: they end in a neat, soft cuff with about a finger's width (1-2 cm) of room round the wrist. Not tight,
    and never a wide bell. The cuff is one solid edge, with no loose rim, ring or loop.
  - **Padding**: insulated pieces (puffers, padded coats) pass `--loft-mm` (puffer 35, padded jacket 15-20).
  - **Logos**: describe the garment PLAIN, with no badge, patch or logo, and write "no logo anywhere" in the
    description. The logo is added crisply afterwards (next point).
- **Logos on generated pieces**:
  - draw an emblem with `python pipeline/garment.py emblem --key K --brief "..."` (Codex image generation, no letters,
    transparent, saved to `Outfits/badges/<key>/emblem.png`). Look at it and redo it with a better brief if it's off;
  - set the name in type with `python pipeline/tpose/badge_art.py --emblem ... --text NAME --style ring|banner|plain
    --out Outfits/badges/<key>/badge.png`;
  - pass it with `--badge-art <that png> --badge-place sleeve-left` (upper arm, outer side, the classic sleeve patch) or
    `--badge-place logo` (only for redrawing a logo the generator already painted). Chest logos on generated pieces
    aren't supported yet; use the sleeve.

## 4. Run it

- **Fitted**: `python pipeline/garment.py shell-top|shell-bottom --key K --label "L" --theme "..." [cut flags]`.
  Image generation only, a few minutes.
- **Generated**: `python pipeline/garment.py generated --key K --label "L" --slot S --description "..." [--ref img]
  [--loft-mm N] [--badge-art png --badge-place sleeve-left]`. It first prints the credit budget; within their limit, just
  go. It takes 20-40 minutes: tell them so, and give short progress notes. It draws the garment over the avatar, checks
  the drawings (free redraws), generates the 3D mesh, fits it, and inspects it alone and with other clothes. Any
  structural fault regenerates automatically, up to `--tries`.
- **If it STOPS**:
  - read why;
  - 2D checks failed: improve the description from the REDO reasons and run again (free);
  - out of credits or over the limit: tell them, and ask before going over;
  - a tool or sign-in problem: run `doctor`.
- **If it finishes with inspection notes**: explain each note in plain words and show it in the preview. Notes like
  "layer spacing too small at <10%" or "runs through the sleeve lining" deep inside padding are known, accepted
  residuals (see `docs/clothing-pipeline.md` B4). A visible defect means the garment is not done: offer one more try
  (say the cost) or a description change.

## 5. Show, save, publish

1. `python pipeline/garment.py export` rebuilds the wardrobe files and lists what changed.
2. Preview:
   - in the Claude desktop app, open http://localhost:8765 in the browser pane after starting
     `python pipeline/garment.py preview` in the background;
   - otherwise start it and ask them to open http://localhost:8765. Then Outfit → the new piece.
   - Check it yourself too, idle and walking (W key), front and back, before calling it done.
3. When they're happy: `python pipeline/garment.py save --key K`. This pushes it to GitHub so the owner's copy has it.
4. **Publishing to AN Maker** (https://claude.ai/artifact/5dbuTk8EZot5Wb1QR261fN):
   - **Claude Code with edit access** (`publish: true`):
     1. Read the live page with the Artifact tool, every line.
     2. Copy it unchanged to `web/customizer/_live_publish.html`.
     3. Publish it with exactly the files in `.anmaker/publish_list.json` (as `assets/<name>` from
        `web/customizer/assets/<name>`).
     4. Read 2-3 of them back and compare byte for byte.
     5. Delete the staging copy.
     Never change the page itself.
   - **Otherwise**: say "Saved. Ask the owner to publish it: it's on GitHub as <label>."
   - New garments show a live-rendered tile picture until the owner adds its pre-rendered picture. That's expected.

## Rules that never bend

- Meshes are shown exactly as generated: no mesh editing, ever. Fixes are regeneration, posing, skin masks or texture
  rework (`docs/clothing-pipeline.md`).
- Spend credits only within the limit; ask before more.
- No real brand names or logos. No passwords or keys in chat or files.
- Don't touch other people's garments, `index.html`, hair, shoes, faces or animations.
