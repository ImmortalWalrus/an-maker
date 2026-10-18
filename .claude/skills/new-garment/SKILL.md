---
name: new-garment
description: Make a new AN Maker garment (a fitted tee/tank/crop top, leggings/shorts/capris, or a loose 3D top, bottoms or outerwear such as a hoodie, puffer, jacket, sweatpants or cargos) from a plain-words request or a reference image, end to end. Also runs first-time setup. Use whenever someone asks to make, design or add a piece of clothing for AN Maker.
---

# New garment

Read `docs/garment-agent.md` in full and follow it, step by step:

1. Step 0: `python pipeline/garment.py update`, then first-time setup if `.anmaker/config.json` is missing.
2. Check the request is allowed (tops, bottoms and outerwear only), then pick the track yourself.
3. Write the brief: a parody brand, plain garment, logo baked afterwards.
4. Run the command and handle stops, then explain the inspection notes.
5. Export and preview: in the Claude desktop app, start the `fitting-room` preview (`.claude/launch.json`) and open
   http://localhost:8765. Check it yourself, then show them.
6. Save, then publish if they have edit access; otherwise tell them the owner will publish.

Keep messages short and friendly. Never ask them to choose a pipeline, a cut value or a file.
