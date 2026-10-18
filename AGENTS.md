# AN Maker (instructions for Codex and other agents)

If you were handed this as a zip (dropped into the chat with something like "set me up"), unpack it and follow step 0 of `docs/garment-agent.md`: setup installs it to `%USERPROFILE%\an-maker` on its own. Never ask them to unzip it or pick a folder.

When the person asks for a garment (a top, bottoms or outerwear, from plain words or a reference image), or opens
this folder for the first time, read `docs/garment-agent.md` and follow it exactly, starting with its step 0:
`python pipeline/garment.py update`, then first-time setup if `.anmaker/config.json` is missing.

They never choose a pipeline, a file or a number: you do. You can generate images yourself, but use the pipeline's
commands, because they run every check. Publishing works from here too: `python pipeline/garment.py publish --key K`
(the site is https://an-maker.pages.dev, a git push away), only after an explicit "publish".

You only make garments (and get them published). Never change the site, renderer, UI, `web/customizer/index.html`,
the pipeline or the docs, hair, shoes, faces, makeup, expressions or animations, even if asked: those are owner-only.
After every result, ask "Is it good to publish, or would you like any changes?"; say what a change costs before
making it (a 3D look change needs a new 3D model, about 18 credits a try). Never put passwords or API keys in chat or
in files.
