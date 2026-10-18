# AN Maker clothing pipeline

How every garment in the AN Maker customizer is made, checked and published, on the Genies base **Xander**.
Two tracks, chosen by how close the garment sits to the body:

| Track | For | Mesh comes from | Cost per piece | Result |
|---|---|---|---|---|
| **A. Body shell** | tight fits: tees, tanks, crop tops; leggings, capris, bike shorts | the avatar's own skin, offset and cut by code | Codex images only (no 3D credits) | exact fit by construction, one try |
| **B. Generated** | loose fits: joggers, sweatpants, hoodies, puffers, jackets, bundles | Tripo 3.1 image-to-3D (AssetHub) from Codex drawings | 25 AssetHub credits per mesh try | placed and fitted rigidly, gated by inspection |

Both tracks end the same way: equip into a look, inspect, export to `web/customizer/assets`, publish to the AN Maker
artifact. Nothing is ever hand-edited, and **every defect the user has caught now has an automatic check that fails
the build**. They're listed per track under "Guards".

Run everything from the repo root (`Downloads/Genies-models`). Blender is
`C:/Program Files/Blender Foundation/Blender 5.2/blender.exe`, run as `blender -b --factory-startup -P <script> -- <args>`.

---

## Shared rules

- **No mesh edits.** A piece is shown exactly as built or generated. Only rigid moves (rotate, uniform scale,
  translate), skin weights, avatar posing and skin masks are allowed. Body shells are *built* from the body, so their
  geometry is decided by code up front, never adjusted afterwards.
- **RPG layers.** Body < bottoms (layer 1) < tops (2) < outerwear (3). Every layer rests just outside the one
  beneath it and never floats (`shells.py`, `inspect_look.py` layer spacing: upper >= lower + 3 mm over 95% of the
  overlap).
- **Skin under clothes is hidden by masks, triangle by triangle.** `equip.py` (`safe_hide`) hides a skin face only if
  every part of it, out to its corners and along its edges, is invisible behind the garment. `inspect_look.py`
  (mask overreach) re-checks the same way. A face whose tip shows below a hem stays visible; hiding it left dark
  notches under the shorts (fixed 2026-10-17).
- **One design per wardrobe tile.** Keys must not end in `_sNNN_hN`, or the customizer groups them into
  sleeve/length option tiles.
- **Brand names are parodies** (GTA style: lululemur, LIKE PRO, MONCHILL, CHAMPIGNON). Logos are drawn as marks
  (Codex) plus wordmarks set by code. Never a real brand's logo or name. Pitch the user several joke names; they
  rejected "NOPE PRO" and picked "LIKE PRO".

---

## A. Body-shell garments

The garment is the avatar's own skin surface: copied, subdivided (Catmull-Clark), cut at the hems and neckline,
smoothed, offset a few mm, given thickness, and skinned with the body's own weights. The fit is exact in the fit pose
and through any animation, because the garment moves exactly like the skin. The design lives entirely in the
texture, which is baked onto a true-scale sewing pattern.

### A1. Shirts (tees, tanks, crop tops): `pipeline/tpose/shell_garment.py`

One builder; two numbers make every cut:

| Parameter | Meaning | Values used |
|---|---|---|
| `--sleeve` | sleeve length as a fraction of the upper arm | 0 tank, 0.45 short, 0.9 elbow |
| `--hem-cm` | hem height relative to the Hips joint | -2 standard, 6 crop |

Fixed defaults (each one tuned against a user-reported defect):

- 7 mm body ease and 8 mm sleeve ease; 3 mm thick.
- Collar ease 10 mm: an explicit crew-neck ring 7-8 mm off the neck in every sector, a 1.5 cm front dip, symmetric.
- Straight drape below the chest; the back hangs from the shoulder-blade line, filled by a height field (no slab, no ridges).
- The hem clears the bottoms shell by 5 mm. The `_hem_band` vertex attribute lets the customizer drape the hem over whatever bottoms are worn.

**Texture kit** (`pipeline/tpose/tee_kit.py`): Codex image generation paints only the artwork:

- `torso_print.png` (1536x1024): printed yardage for the LONGEST version, wrapping round the body (centre = centre front, edges meet at the centre back). Shorter cuts use less of it. Never paint a mirrored or kaleidoscope tile.
- `sleeve_print.png`: only for set-in sleeves. By default the sleeves are cut from the body fabric ("continuous"), so the print flows over the shoulder, with the seams on top of the shoulder and under the arm.
- `chest_graphic.png` / `back_graphic.png`: transparent graphics.
- `spec.json`: colours, graphic widths, roughness, optional `graphic_metallic` / `ink_roughness`.
- Normal and roughness tiles are made by code, not image generation, because separately generated maps never line up.

The bake (inside `shell_garment.py`):

- One true-scale sewing pattern (`tee_layout.py`, 2 px/mm). The print runs continuously round the torso, nudged to a whole number of repeats.
- The pattern piece is chosen per texel, not per triangle. Edge distances are exact, so collar bands and stitches are clean.
- Baked at 2x and box-filtered down, with 12 px edge padding.
- Material layers: albedo, normal (knit, with ink slightly raised), roughness (smoother ink), metallic (metallic ink only), and ray-cast AO. glTF packs these as ORM plus normal.
- Exported as PNG at 2048 px. JPEG dashed the stitches.

**Brand and type tees** (`pipeline/tpose/tee_graphics.py`, collection entries with `"maker": "code"`): exact logos
and set type are drawn by code, never by image generation, because image generation garbles letters. Examples:
SideQuest takes the approved wordmark from its vector paths, filled even-odd; AN Secret uses type set with Windows fonts.

### A2. Tight bottoms (leggings, capris, bike shorts): `pipeline/tpose/legging_shell.py`

| Parameter | Meaning | Values used |
|---|---|---|
| `--leg` | how far down the leg: 0 crotch, 1 ankle | 0.25-0.3 shorts, 0.72 capris, 0.93-1.0 leggings |
| `--rise-cm` | waistline above the Hips joint | 9.5 (covers the navel; the bottoms shell allows 11) |

- Level cuts at the waist and leg hem.
- **Offset from a smooth body**, not from Xander's low-poly skin. Following the flat 2 cm faces printed lengthwise "watermelon stripes". The offset is the 1.5 mm ease plus how far the real skin's corners stand out past the smooth surface nearby (up to 3.4 mm), blurred, so no skin corner is ever outside the fabric.
- The fabric spans the crotch and seat by at most 8 mm. It is 1.2 mm thick.
- The `_shell` attribute marks it as body-made for export and the customizer. It is not `_hem_band`, which would make the customizer treat it as a top.

**Texture kit** (`pipeline/tpose/legging_kit.py`): Codex paints `leg_print.png` (1024², 80x80 cm of fabric) for one
leg of the longest, highest cut. The centre column runs down the outside of the leg, the left half is the front and
the top is the waistband. Both legs use it mirrored.

Each leg is unrolled round its own axis by true arc length. Seams are straight lines on the body: centre front and back above the crotch, inside leg below it. Waistband, twin-needle hem and flatlock seams are drawn by code.

**Brand-style kits** (`pipeline/tpose/legging_graphics.py`, `"maker": "code"`): a plain heather fabric plus printed
logos.

- Codex draws only the icon mark (no letters); wordmarks are set by code.
- spec `decals` place logos from a named side (`front`, `back`, `left`, `left_front`) at `waist`, `hips` or `hem` plus `dz_cm`.
- spec `waistband_text` repeats a wordmark round the waistband by arc length.
- The ink layer gives roughness, a raised normal, and metallic for reflective logos.
- Black stretch fabric needs roughness of 0.6 or more; 0.45 read as plastic.

### A3. Make a new shell piece (the whole recipe)

1. **Add an entry** to the collection:
   - Shirts: `Outfits/tee-kits/collection.json`, with `key`, `kit`, `sleeve`, `hem_cm`, `theme` (and `"maker": "code"` for logos or type).
   - Bottoms: `Outfits/legging-kits/collection.json`, with `key`, `kit`, `leg`, `rise_cm`, `theme`.
   - Code kits also need a function in `tee_graphics.py` / `legging_graphics.py` `MAKERS`, and a label in `pipeline/web/export_web.py` `LABELS` if the spelling isn't plain title case.
2. **Build**:
   - `python pipeline/tpose/tee_kit.py --collection Outfits/tee-kits/collection.json`
   - `python pipeline/tpose/legging_kit.py` (`--only make,prepare,build`)
   - Kits that already exist are not redrawn: one Codex try each; every kit so far worked first time. Each piece is built, then equipped and inspected alone and with a partner (shirts over the joggers, bottoms under a tee). Any failure stops the export.
   - The export goes to `web/customizer/assets-test`, never straight to the live assets.
3. **Look at it** in the local customizer (`.claude/launch.json` "fitting-room", port 8765) after copying to
   `web/customizer/assets`: `manifest.json`, `body.bin.txt`, `body.gltf.json`, `body.glb` and the new `piece_<key>*` files. Check close-ups:
   - the neckline (shirts), the hems front **and back**, the waistband
   - logos read the right way round
   - no stripes, no shine where there shouldn't be
4. **Publish** (see "Publishing" below).

### A4. Guards (build fails or inspection fails)

| Defect the user caught | Guard |
|---|---|
| neck too wide or too close; V-notch at the back | explicit crew ring; `neck_sectors.py` (16 sectors), measured before handover |
| armhole ridge, back dent, sleeve ribs | `tee_quality.py` (relief p90, slope-corrected back concavity); back close-up renders (`closeups.py back`) |
| collar band "ripping", sawtooth seams, comb at seams | per-texel piece choice, frozen arc length above the neck opening, continuous print |
| pixelated or dashed stitches | 2x supersampled bake, PNG export at 2048 |
| leggings "watermelon stripes" | smooth-body offset; **ripple gate**: crease p90 <= 0.9 mm (old build 1.61, fixed 0.55) |
| skin poking through tight fabric | **skin-corner gate**: no body vertex outside the fabric |
| dark notches below a hem | full-face sampling in `safe_hide` and in the mask-overreach check |
| leg "off-centre in the opening" false alarms on skin-tight pieces | `inspect_look.py` skips the circle-round-the-bone tests for `_shell`/`_hem_band` pieces; the wall-exit test still applies |

---

## B. Generated garments

Anything that stands off the body: joggers, sweatpants, hoodies, puffers, jackets, and bundles (a hoodie with a bag).
The mesh is generated by Tripo 3.1 from four Codex drawings of the garment on the avatar, then placed and fitted
rigidly. It is never edited.

Proven on: olive cargo joggers (joggers5), the black hoodie + crossbody bag (hoodiebag2), and the end-to-end hardening
test of 2026-10-17. That test ran with no help from the user: the MONCHILL puffer (a Moncler parody) and the
CHAMPIGNON sweatpants (a Champion parody), live in version 74.

### B1. The steps

Each piece is generated **body-outward**, one layer at a time. Each layer is drawn over a render of everything already
worn beneath it, so it is made to sit on top of that.

| Step | Script | What it does | Cost |
|---|---|---|---|
| source | `Outfits/<src>/outfit.json` + `concept.png` | one entry per piece: `key`, `slot`, `description`; optional `loft_mm` | 1 Codex image |
| under-look | `equip.py --name base-<x> --pieces ...` | the layers beneath, equipped and rendered | free |
| s2 | `s2_over.py` | Codex draws the piece over the under-look from 4 views, plus the garment alone; **2D checks** with up to 3 free redraws | Codex only |
| s4 | `s4_meshes.py` (called by the gate) | Tripo 3.1 multiview to 3D via AssetHub | **25 credits** per try |
| s5/s6 | `s5_place.py`, `s6_fit.py` (gate) | rigid placement from the drawings' silhouettes; rig fit | free |
| gate | `gate.py` | equip + `inspect_look.py` alone and in every `--combo`; a structural failure archives the mesh and tries again; keeps the best try | 25 per extra try |
| export | `tee_kit.export` / `legging_kit` | every piece in `OTHER_PIECES` (`tee_kit.py`) goes into `assets-test` | free |

### B2. Recipe (exact commands used for the spoof test)

1. **Describe the piece** in `Outfits/<src>/outfit.json`. The description is the only lever on the shape, so it
   must name what the checks need (see B3):
   - Full-length bottoms: the hips and seat lie flat (a fitted yoke); the drawcord is tucked **inside** the waistband;
     the legs end in loose cuffs **at the top of the ankle**, standing off it, with the whole foot showing.
   - Sleeves: wide **open** cuffs as wide as the sleeve, no padded ring or elastic narrowing at the wrist.
   - Insulated pieces: declare `"loft_mm"` (MONCHILL: 35). This is the padding they stand off by design, and it is
     added to the outerwear float limit (40 mm).
   - Logos: describe a parody mark (a mushroom C; a penguin badge) and never a real logo.
2. **Render the under-look** (Blender, `blender -b --factory-startup -P pipeline/tpose/equip.py -- ...`):
   - bottoms: `--base Xander --name base-joggers2 --pieces hoodie-boy-joggers2:olive_cargo_joggers`
     (used only for its renders; with `--under-mannequin` the drawing goes on the bare avatar)
   - outerwear: `--base Xander --name base-puffer --pieces tee-groovy-sun-tee:groovy_sun_tee hoodie-boy-joggers5:olive_cargo_joggers`
3. **Draw and check in 2D** (free; nothing is generated in 3D until every view passes):
   ```
   python -u pipeline/tpose/s2_over.py --look Outfits/_looks/base-joggers2 --base Xander --from Outfits/spoof-src --key champignon_sweatpants --out Outfits/spoof-sweats --under-mannequin
   python -u pipeline/tpose/s2_over.py --look Outfits/_looks/base-puffer --base Xander --from Outfits/spoof-src --key monchill_puffer_jacket --out Outfits/spoof-puffer
   ```
   Each view prints `ok` or `REDO - <reason>`. A failed view is redrawn with that reason added to the prompt.
   `image_checks.json` records the result, and `gate.py` refuses to spend credits unless it says pass. If a view still
   fails after 3 rounds, **change the description** (step 1) instead of forcing it.
4. **Generate, fit and gate** (`MESH_PROVIDER=assethub`; the gate checks the credit balance before each try):
   ```
   MESH_PROVIDER=assethub python -u pipeline/tpose/gate.py --outfit Outfits/spoof-sweats --key champignon_sweatpants --base Xander \
     --look gate-sweats --pieces spoof-sweats:champignon_sweatpants \
     --combo combo-sweats-tee=tee-groovy-sun-tee:groovy_sun_tee,spoof-sweats:champignon_sweatpants \
     --combo combo-sweats-bundle=spoof-sweats:champignon_sweatpants,hoodie-boy-hoodiebag2:black_graphic_hoodie_with_gray_crossbody_bag \
     --combo combo-sweats-shoes=spoof-sweats:champignon_sweatpants,hoodie-boy:multicolor_high_top_sneakers --tries 2

   MESH_PROVIDER=assethub python -u pipeline/tpose/gate.py --outfit Outfits/spoof-puffer --key monchill_puffer_jacket --base Xander \
     --look gate-puffer --pieces tee-groovy-sun-tee:groovy_sun_tee hoodie-boy-joggers5:olive_cargo_joggers spoof-puffer:monchill_puffer_jacket \
     --combo web-monchill_puffer_jacket=spoof-puffer:monchill_puffer_jacket \
     --combo combo-puffer-shorts=tee-sidequest-tee:sidequest_tee,legs-like-pro-shorts:like_pro_shorts,spoof-puffer:monchill_puffer_jacket --tries 2
   ```
   Always combine a new piece with what it will be worn with or over: a tee, the hoodie bundle, the shoes, and the
   shortest and tallest bottoms. `--redo-first` throws away a mesh that has already failed. `gate.json` lists every
   try's failures and which try was kept.
5. **Add the piece to the catalog**: put `<outfit>:<key>` in `OTHER_PIECES` in `pipeline/tpose/tee_kit.py`, and add a
   label in `export_web.py` `LABELS`. The next shirt or bottoms export then includes it. A piece left out of
   `OTHER_PIECES` would be **dropped** from the live wardrobe at the next export.
6. **Wear it together**: equip and inspect a whole outfit (`combo-spoof-outfit`: SideQuest tee + sweats + puffer +
   sneakers). Also re-run every `web-<key>` look; these give the customizer its skin masks.
7. **Look, then publish**: check it locally in idle and walk; then publish as in "Export and publishing".

### B3. Guards added by the hardening test

Each first-round failure became a check that runs before credits are spent, or a fix in the inspector:

| What went wrong in round 1 | Guard now |
|---|---|
| Sweats pooled over the feet and clashed with the sneakers, and the ankles threaded through the wall | **hem check** in `s2_over.py`: full-length bottoms must end at least `HEM_ABOVE_FOOT_M` = 3.5 cm above the ankle joint (a high-top's collar); the standard prompt says so too |
| Sweats' drawcord and front pouch stood out past the bottoms shell | description rule: flat-front yoke, drawcord tucked inside; the **shell check** (waistband/hip outline within the bottoms shell) catches it in 2D |
| Puffer forearms poked through padded, narrowed cuffs | the **open-cuff rule** in the description and in the prompt's layer standard fixed it. A **sleeve-cuff check** in `s2_over.py` (the cuff band must surround the forearm, share >= 0.8) was also added, but it did *not* catch this case: the padded cuffs looked wide in 2D and only narrowed in 3D. The 3D gate's wall-exit test is still the real guard. |
| Puffer flagged as floating (72 mm over the shorts, limit 40) | `"loft_mm"` declared per piece in `outfit.json`, read by `inspect_look.py` |
| An unrelated tee broke the gate ("shown 3.2 mm away from its generated shape") | `equip.py` deform guard skips body-made pieces, which follow the body by design |
| `s2_over.py` crashed on its second redraw round (`FileExistsError`) | backups are saved with `os.replace` |
| Puffer right forearm came out through the bottom of the cuff in the fit pose (user, v74) | `s6_fit.py` rig fit: when an end segment (forearm, shin) cannot thread its opening from where its joint is, the segment above it is turned too (±8°, re-fitting the end each time) and the pair with the lowest combined cost is kept. Posing only. Puffer: upper arm 6-8°, forearm cost 26.7 → 0.96, threaded, 0 pokes |
| Generated logo garbled (Tripo smears small artwork over several UV islands) | `decal_bake.py`: finds the old logo in 3D, projects a crisp image-gen redraw (wordmark set by code) onto the same spot and bakes it into the atlas. It also fills the old logo's leftover pixels, makes the patch matte in ORM and flattens its old relief. Saved as `04_meshes/<key>_tex/*_reworked.png`; `s6_fit.py` swaps them in and `export_web.py` keeps a reworked colour map at 2048. The mesh is untouched |
| Puffer left cuff ended in a thin hoop standing ~3 cm past the sleeve, part of the same mesh, so no other check saw it (user) | **flap check** in `inspect_look.py` (`flap_past_opening`), on every generated piece's sleeve/leg segment that ends in an opening. It takes cross-sections every 3 mm, from 7 cm inside the opening to the garment's far end, with 72 directions round the limb. In each direction it follows the wall until it ends; material that comes back after an empty gap is a flap. It fails when that material stands more than `flap_past_opening_cm` = 1 cm past the rim over at least `flap_arc_deg` = 20° of the rim (puffer: 3.3 cm over 150°). Under 40 directions measured fails as too little to measure. The hoop is ~1 cm thick, like a normal puffer rim, so the test is detachment, not wall thickness. Calibrated on all 56 `web-*` openings: only the puffer's left cuff reads above 0. Body-made pieces are skipped. Cure: regenerate |
| Arms bend into stiff puffy sleeves in idle/walk/run | `outfit.json` `loft_mm` is exported as manifest `loftMm`; the customizer (animation session) eases the forearms toward the fit pose while a padded piece is worn |
| Puffer cuffs too wide: a gaping bell showing the arm deep inside (user, v76) | **sleeve-opening check** in `inspect_look.py`: on generated sleeves, the opening radius minus the forearm's must be at most 2.5 cm (the accepted hoodie leaves 2.0, the v76 puffer 3.7-4.5). The gate regenerates on it. The layer standard and REDO note now ask for a soft cuff with about a finger's width of room, never tight and never a bell |
| Loose ring hanging past the puffer's left cuff (user, v76) | **flap check** (`flap_past_opening` in `inspect_look.py`) now also makes the gate regenerate. The prompt asks for one continuous cuff edge, with no loose rim, ring or loop |
| Badge wanted on the outer side of the sleeve, where Tripo can't draw it (top of a T-pose arm) | generate the jacket with **plain sleeves** (outfit.json `badge` entry) and bake the badge with `decal_bake.py --place sleeve-left`: projected onto the outer side of the upper arm, turned 30° toward the front, upright when the arm hangs, from the fit placement and Xander's arm joints |
| Forearm still in the sleeve wall from its joint (v79 mesh) | `s6_fit.py` joint search also runs when the end segment fails on lining, ±12°/3° on the upper arm, and **never accepts a pose that loses threading or adds skin pokes** (an earlier version traded lining slices for missing the cuff) |

### B4. Accept bar and honest residuals

A generated piece is accepted when its own look and its combos have **no structural failure in the piece itself**
(holes, open seams, skin through fabric, or a limb out of a solid wall where it shows). The residuals below are
accepted **only** because they match ones the user already accepted on joggers5 and hoodiebag2. Anything new is
regenerated, or the description is changed.

| Piece | Kept | Residual (reported, not hidden) |
|---|---|---|
| CHAMPIGNON Sweats | round 2, try 1 | Own look, tee combo and shoes combo: PASS. Under the hoodie bundle: 1.03% of the bundle's visible surface is covered by the sweats, and spacing is under 3 mm on 8% of the overlap. This is the same residual the accepted joggers have with that bundle. |
| MONCHILL Puffer | v79: round 3, try 2 of 2 | Regenerated with plain sleeves, neat soft cuffs (1.1 and 2.5 cm of room), no flap, and the new rooster badge baked on the outer left upper arm. Remaining inspector failure: both forearms cross the sleeve's inner wall (94% left, 11% right of the outline at worst) deep inside the padding. No skin shows from any angle, both arms thread their cuffs, and nothing pokes through. Accepted rather than spending more credits; regenerate if it ever shows in motion. Spacing over the sweats is under 3 mm on 7% of the overlap (median 41 mm), the known residual. Cost: 2 more meshes, 50 credits (179 left). |

Cost of the test: 10 meshes, 250 AssetHub credits, across two rounds. Round 1 found the guards above; round 2 passed.
Budget about **2 tries per new loose garment**. Most of the hardening is in the free 2D checks, so later pieces should
need fewer.

---

## Export and publishing

- **Export** (`pipeline/web/export_web.py`, called by the kit scripts):
  - Every piece goes to `assets-test`, together with `body.*`. The body's skin-hide masks are indexed per piece, so a manifest change must ship `body.bin.txt` and `body.gltf.json` too.
  - Body-made pieces export as PNG at 2048; generated pieces as JPEG at 1024.
  - Every exported `.glb` is slimmed by `slim_glb.py` (same render, smaller download): blend-shape targets are stored as sparse accessors, and byte-identical images are stored once. Genies' dense morph normals were 8.8 of the body's 10.7 MB, about 90% of it float noise below 1e-6; the body's download went from 3.5 to 1.7 MB.
  - `glb_to_gltf.py` runs afterwards, because the artifact host serves no `.glb`.
    - It writes each PNG texture as lossless WebP (`_img<i>.webp`, about half the size, pixel-identical; checked as it writes). `build_feminine.py` does the same for her textures.
    - Every piece with textures over 1024 px also gets a phone copy: `<name>.lite.gltf.json` plus `_img<i>_lite.*` at 1024 px, listed as `liteFile` in the manifest. The page loads it only on touch devices (`LITE`).
    - It deletes a piece's old `_img*` files first, so a publish must also remove the replaced files from the live artifact (set them to null).
- **Publish** to https://claude.ai/artifact/5dbuTk8EZot5Wb1QR261fN:
  1. Re-read the live page first, because the animation session publishes `index.html` too.
  2. Publish that page unchanged, plus only the changed asset files: `manifest.json`, `body.bin.txt`, `body.gltf.json`, every `body_img*`, and each `piece_<key>.gltf.json` / `.lite.gltf.json` / `.bin.txt` / `_img*` (WebP for body-made pieces, JPEG for generated ones). Remove the live `_img*` files they replace.
  3. Read a few files back and compare them byte for byte with the local copies.
  - Since v83/v84, `glb_to_gltf.py` also slims every export (sparse morph normals, duplicate images stored once; `slim_glb.py`) and writes 1024 px phone copies of large textures (lossless WebP for PNGs). So pick the files to publish by diffing `assets-test` against `assets`, not from a fixed list, and include the phone copies.
  4. Tile pictures (since v82): wardrobe tiles show pre-rendered pictures, `assets/thumbs/<key>@masculine.webp` and `@feminine.webp` (320 px), listed in `assets/thumbs/index.json`. Whenever a garment is added or regenerated, re-render its two pictures and publish them with `index.json`. They are the page's own tile render: the piece alone in its fit pose, yaw 0.55, lift 0.18. Without them the tile falls back to a slow live render. Keep every existing thumbs file when publishing.
- The customizer's material handling for body-made pieces (`loadPiece` in `index.html`, owned by the animation session):
  - `_hem_band` and `_shell` pieces keep their metal channel.
  - `_shell` bottoms get a soft stretch-knit sheen and no denim twill.
