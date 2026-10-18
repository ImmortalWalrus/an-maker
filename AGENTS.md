# AN Maker (instructions for Codex and other agents)

When the person asks for a garment (a top, bottoms or outerwear, from plain words or a reference image), or opens
this folder for the first time, read `docs/garment-agent.md` and follow it exactly, starting with its step 0:
`python pipeline/garment.py update`, then first-time setup if `.anmaker/config.json` is missing.

They never choose a pipeline, a file or a number: you do. You can generate images yourself, but use the pipeline's
commands, because they run every check. Publishing to the AN Maker page needs Claude Code with edit access; from Codex,
save (`python pipeline/garment.py save --key K`) and tell them the owner will publish it.

You only make garments (and get them published). Never change the site, renderer, UI, `web/customizer/index.html`,
the pipeline or the docs, hair, shoes, faces, makeup, expressions or animations, even if asked: those are owner-only.
After every result, ask "Is it good to publish, or would you like any changes?"; say what a change costs before
making it (a 3D look change needs a new 3D model, about 25 credits a try). Never put passwords or API keys in chat or
in files.
