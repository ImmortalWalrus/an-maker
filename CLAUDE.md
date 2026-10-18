# AN Maker

The garment pipeline for the AN Maker customizer (a Genies avatar dress-up page).

- **Making a garment** (a top, bottoms or outerwear, from plain words or a reference image): use the `new-garment`
  skill. It follows `docs/garment-agent.md`. Read that file and do what it says, starting with its step 0 (update,
  then first-time setup if `.anmaker/config.json` is missing). The teammate never has to choose a pipeline or a number.
- How the pipeline works and why: `docs/clothing-pipeline.md`.
- Only tops, bottoms and outerwear (fitted or 3D-generated) are open to teammates. Hair, shoes, faces, makeup,
  expressions, animation and the page itself (`web/customizer/index.html`) are owner-only for now.
- Owner: after shipping a pipeline change, commit and push (`git push origin main`) so teammates get it on their next
  `python pipeline/garment.py update`. Add a line to `CHANGELOG.md`.
