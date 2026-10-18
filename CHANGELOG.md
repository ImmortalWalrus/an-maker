# AN Maker changes

Newest first. `python pipeline/garment.py update` pulls these.

- 2026-10-17: Drop the zip in the chat and say "set me up": setup installs itself to `%USERPROFILE%n-maker`, installs Python packages, Blender 5.2 (portable), Git, Node and the CLIs by itself, and adds an `an-maker` skill (Claude Code) and a note (Codex) so any new chat finds it.
- 2026-10-17: Works from any harness: drawings by Codex (ChatGPT plan, free) or paid per image on AssetHub / Higgsfield (`setup --images`, `garment.py image`).
- 2026-10-17: MRI scan in every inspection (`mri.py`): body ring vs garment ring at the collar, sleeves, cuffs, waistband/hem and legs, with a picture per garment (`08_inspect/mri_<key>.png`); touching where the skin shows fails the look and regenerates.
- 2026-10-17: New front-page README.

- 2026-10-17: Safer updates: a downloaded zip always takes the newest pipeline files when it links.
- 2026-10-17: `generated --draw-only` shows the free drawings before any credits are spent; save/export pull the other person's garments first.
- 2026-10-17: Garment maker for teammates. `pipeline/garment.py` (setup, doctor, update, shell-top, shell-bottom, generated, emblem, badge, export, preview, save), the `new-garment` skill and the per-piece catalog (`catalog/pieces`).
