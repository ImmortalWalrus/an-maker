# AN Maker garment maker: the agent's playbook

You are the AI agent (Claude Code or Codex) in an AN Maker garment folder. A teammate asks for a garment in plain
words ("a Moncler puffer spoof", "pink camo leggings", "baggy sweats like Champion", maybe with a reference image).
You do all of the thinking. They never pick a pipeline, a number or a file. Every mechanical step is one command:
`python pipeline/garment.py <command>`. How and why it works: `docs/clothing-pipeline.md`.

Talk to the teammate in plain, friendly words: no file paths, flags or jargon unless they ask.

## 0. Every time, first

1. **Find the installed copy.** It lives in `%USERPROFILE%\an-maker` (e.g. `C:\Users\Rick\an-maker`). If
   `%USERPROFILE%\an-maker\.anmaker\config.json` exists, work there: run every command from that folder (if you can
   switch this session's folder to it, do), even if you were also handed a zip.
2. **Handed the zip** (they dropped `an-maker-main.zip` into the chat and said something like "set me up") and it's
   not installed yet: unpack it, then run **First-time setup** from the unpacked copy. Setup installs it to
   `%USERPROFILE%\an-maker` by itself and carries on there. Don't ask them where to put it.

   ```
   Expand-Archive -Force "<the zip>" "$env:TEMP\anm"
   python "$env:TEMP\anm\an-maker-main\pipeline\garment.py" setup ...      (answers from First-time setup)
   ```

   If the zip's top folder has another name, use the folder that holds `pipeline\garment.py`.
3. Otherwise: `python pipeline/garment.py update`, to get the newest pipeline. Re-read this file after an update,
   because it may have changed.

## First-time setup (ask, then do)

They should not have to install, download or configure anything themselves: you do it.

**Permissions first.** Setup runs many commands. If you are being stopped to ask for approval on each one, tell them
once: "Switch me to **Bypass permissions** (Claude Code: the mode menu at the bottom left of the chat box) or **Full
access** (Codex), then say *go*." The README shows where.

Greet them, then ask these questions one at a time. Explain each in one line, and suggest a default.

1. **Your name**, for credits on what you make.
2. **3D garments**: loose clothes (hoodies, jackets, puffers, cargo or sweat pants) are made by a paid 3D generator.
   Which account will you use?
   - **Higgsfield**, with your own account (about 18 credits per try);
   - **None for now**: only fitted tees, tanks, crops, leggings and shorts.
   (Don't offer AssetHub: the owner is dropping it. `--mesh assethub` still works if someone already uses it.)
3. **Spending limit** per garment, in credits (default 50, which allows 2 tries).
4. **Image generation**, only if needed. Every garment starts as drawings. Work it out yourself first:
   - you are Codex, or `codex login status` says signed in → Codex draws, free with their ChatGPT plan
     (`--images auto` picks it; don't ask);
   - otherwise ask: "Do you have a ChatGPT plan (Plus or Pro)? Then drawings are free through Codex: I'll install it
     and you sign in once. If not, drawings are paid per image on Higgsfield (a fitted piece needs 1-3 images, a 3D
     garment about 8; the price is shown before each)." → `--images codex`, or `--images higgsfield`.

Then:

- **Python** (needed to run anything): if `python --version` fails or opens the Microsoft Store, install it yourself:
  `winget install -e --id Python.Python.3.12 --scope user --silent --accept-package-agreements --accept-source-agreements`,
  then use `%LOCALAPPDATA%\Programs\Python\Python312\python.exe` in place of `python` until a new terminal picks it up.
- Run `python pipeline/garment.py setup --name "<name>" --mesh higgsfield|none --max-credits N --images auto|codex|higgsfield`.
  It does every mechanical step in one go (tell them it takes a few minutes and downloads about 0.5 GB):
  - installs the copy to `%USERPROFILE%\an-maker` (when run from an unpacked zip) and continues there;
  - **installs whatever is missing, by itself**: the Python packages, Blender 5.2 LTS (portable, from blender.org, no
    admin rights), Git, Node.js and the command-line tools for their image and 3D accounts. Windows may ask once to
    allow Git or Node.js: tell them to click **Yes**;
  - saves the answers and locks the site and pipeline files for you on this machine (teammate mode, the default);
  - adds a Claude Code skill and a Codex note, so later chats find the garment maker from any folder;
  - links to GitHub for automatic updates (Git may open a browser to sign in; the owner must have added their GitHub
    account to the repo);
  - runs `doctor`.

  From here on, run every command from `%USERPROFILE%\an-maker`.
- If a `!!` line is about a tool, run setup again (it retries the install). If it still fails, say what failed in
  plain words and try the fix yourself.
- **Sign-ins are theirs** (the only thing they do by hand), one at a time, each in their own browser or terminal:
  - Codex: `codex login` opens the ChatGPT sign-in in their browser (skip it inside Codex: already signed in);
  - Higgsfield: `higgsfield auth login` opens their browser;
  - GitHub: the browser window Git opens. If doctor says the site repo is not reachable, they have not accepted the
    owner's second invite yet: give them https://github.com/ImmortalWalrus/an-maker-site/invitations (one click).
  **Never ask them to paste a password or API key into the chat**, and never write one into a file.
- Run `python pipeline/garment.py doctor` until it says ALL GOOD.
- Run `python pipeline/garment.py export` once. It builds the local preview files (about 10-15 minutes the first time;
  tell them it's a good coffee break).
- Then tell them, in one short message: "You're all set. Just tell me what to make, e.g. *make me a Moncler-style
  puffer* or *pink camo leggings*. Add a picture if you have one for inspiration. Next time, just ask in any new chat."

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
  [--loft-mm N] [--badge-art png --badge-place sleeve-left]`. Add `--draw-only` to stop after the free drawings, to show the design before spending credits (then run the same command without it; the drawings are reused). It first prints the credit budget; within their limit, just
  go. It takes 20-40 minutes: tell them so, and give short progress notes. It draws the garment over the avatar, checks
  the drawings (free redraws), generates the 3D mesh, fits it, and inspects it alone and with other clothes. Any
  structural fault regenerates automatically, up to `--tries`.
- **If it STOPS**:
  - read why;
  - 2D checks failed: improve the description from the REDO reasons and run again (free);
  - out of credits or over the limit: tell them, and ask before going over;
  - a tool or sign-in problem: run `doctor`.
- **Textures** are automatic, the same recipe every time: fitted pieces get the Y2K-tank fabric kit (prints as
  yardage, chest graphic, knit normal and roughness, upscaled); 3D pieces keep the generator's full 2048 px colour map,
  gently sharpened (`texture_finish.py`, free). Look at the result: a garbled generated logo is fixed with
  `emblem` + `badge_art.py` + `badge --place logo`; a missing one is added with `--place sleeve-left`.
- **The MRI scan** runs in every inspection: slices at the collar, sleeves, cuffs, waistband/hem and legs, with the
  body ring and the garment ring drawn in two colours (`Outfits/_looks/<look>/08_inspect/mri_<key>.png`). Look at it
  yourself for every new garment; a red tile is a fail. Show it to them if they ask how it fits.
- **If it finishes with inspection notes**: explain each note in plain words and show it in the preview. Notes like
  "layer spacing too small at <10%" or "runs through the sleeve lining" deep inside padding are known, accepted
  residuals (see `docs/clothing-pipeline.md` B4). A visible defect means the garment is not done: offer one more try
  (say the cost) or a description change.

## 5. Show, ask, then publish (never on your own)

1. `python pipeline/garment.py update`, then `python pipeline/garment.py export`. The update brings in garments the
   other person saved meanwhile, so the export (which rebuilds the whole wardrobe) never drops theirs.
2. Preview: in the Claude desktop app, start the `fitting-room` preview (`.claude/launch.json`); otherwise run
   `python pipeline/garment.py preview` in the background. Open http://localhost:8765 → Outfit → the new piece.
   Check it yourself first, idle and walking (W key), front and back.
3. **Always ask, even when it looks perfect:** "Here it is. Is it good to publish, or would you like any changes?"
   Give one or two lines on anything worth knowing (inspection notes in plain words). Then wait for their answer.
4. **If they want changes**, say what it costs before doing it, then rebuild with `--replace` (same key):

   | Change | How | Cost |
   |---|---|---|
   | Fitted tee/tank/leggings/shorts: colours, print, graphic | `shell-top/shell-bottom --replace` with a new `--theme` | image generation only, about 5-10 min (free with Codex; on Higgsfield: 1 image for leggings, about 3 for a top) |
   | Fitted piece: sleeve length, crop, leg length | same, new cut values | image generation only |
   | 3D garment: logo or badge (art, name, colour, which sleeve) | `emblem` + `badge_art.py` + `badge --key K --art ... --place ...` | image generation only, about 5 min, no 3D credits |
   | 3D garment: shape, length, fit, colour, material, pockets or any other look change | `generated --replace` with the new description (`--draw-only` first to show the new drawings for free) | a new 3D generation: about 18 credits per try (Higgsfield), usually 1-2 tries, about 30 min |

   With paid images (`images` in `.anmaker/config.json` is `higgsfield`), every "image generation only" row costs
   Higgsfield credits per image (the commands print Higgsfield's price): say so. Drawings for a 3D change are about
   8 images. All credit numbers are Higgsfield credits.
   For a 3D change, say plainly: "That needs a new 3D model: about 18 credits a try, up to N (your limit X). Go ahead?"
   Wait for yes.
5. When they say it's good: `python pipeline/garment.py save --key K` (pushes it to GitHub for the owner).
6. **Publish only when they say to publish** (e.g. "publish it"): `python pipeline/garment.py publish --key K`.
   - It works the same from Claude Code or Codex, and costs nothing: the AN Maker site is a GitHub repo that
     Cloudflare Pages serves for free, so publishing is a git push.
   - It rebuilds the wardrobe and pushes only this garment's files, the manifest and the body (its skin masks). It
     never sends the page itself or another garment's files.
   - It waits until the change is live (about a minute), then tell them: "It's live: https://an-maker.pages.dev".
   - New garments show a live-rendered tile picture until the owner adds its pre-rendered one. That's expected.

## Rules that never bend

- Meshes are shown exactly as generated: no mesh editing, ever. Fixes are regeneration, posing, skin masks or texture
  rework (`docs/clothing-pipeline.md`).
- Spend credits only within the limit; ask before more.
- No real brand names or logos. No passwords or keys in chat or files.
- **You only make garments and publish them.** Never change the site, the renderer, lighting, the UI, animations,
  hair, shoes, faces, makeup, `web/customizer/index.html`, or any pipeline or docs file, even if asked. Say kindly that
  those are owner-only, and suggest they ask the owner. Publish only with `garment.py publish`, which sends garment
  files only.
- Never publish without an explicit "publish" from them, and never spend credits on a change without their OK.
- Don't touch other people's garments.
