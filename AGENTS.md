# AN Maker (instructions for Codex and other agents)

When the person asks for a garment (a top, bottoms or outerwear, from plain words or a reference image), or opens
this folder for the first time, read `docs/garment-agent.md` and follow it exactly, starting with its step 0:
`python pipeline/garment.py update`, then first-time setup if `.anmaker/config.json` is missing.

They never choose a pipeline, a file or a number: you do. You can generate images yourself, but use the pipeline's
commands, because they run every check. Publishing to the AN Maker page needs Claude Code with edit access; from Codex,
save (`python pipeline/garment.py save --key K`) and tell them the owner will publish it.

Never edit `web/customizer/index.html`, hair, shoes, faces, makeup, expressions or animations. Never put passwords or
API keys in chat or in files.
