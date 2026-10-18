# AN Maker

The garment pipeline for the AN Maker customizer (a Genies avatar dress-up page).

- **Making a garment** (a top, bottoms or outerwear, from plain words or a reference image): use the `new-garment`
  skill. It follows `docs/garment-agent.md`. Read that file and do what it says, starting with its step 0 (update,
  then first-time setup if `.anmaker/config.json` is missing). The teammate never has to choose a pipeline or a number.
- **Handed the zip** (dropped into the chat, "set me up"): unpack it and follow step 0 of `docs/garment-agent.md`;
  setup installs it to `%USERPROFILE%\an-maker` on its own. Never ask them to unzip it or pick a folder.
- How the pipeline works and why: `docs/clothing-pipeline.md`.
- Only tops, bottoms and outerwear (fitted or 3D-generated) are open to teammates. Hair, shoes, faces, makeup,
  expressions, animation and the page itself (`web/customizer/index.html`) are owner-only for now.
- **The live site** is https://an-maker.pages.dev: the private repo ImmortalWalrus/an-maker-site, served free by
  Cloudflare Pages (every push to main goes live in about a minute). The old Claude artifact is retired. Publish a
  garment with `python pipeline/garment.py publish --key K`; publish page or engine changes with
  `python pipeline/web/live_site.py publish --page web/customizer/index.html --files assets/... -m "..."`.
- The git repo is the garment maker only (pipeline, docs, catalog, garment data). After a garment-maker change, commit
  and push so teammates get it on their next `python pipeline/garment.py update`, and add a line to `CHANGELOG.md`.
  Engine changes (the page and its assets) are NOT committed; the repo holds one frozen preview copy of the page
  (see `docs/handoff.md`).
