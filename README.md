# AN Maker garment maker

Make new clothes for the AN Maker avatar just by asking for them.

## Start (once, about 20 minutes)

1. Download this repo as a zip (green **Code** button → **Download ZIP**). Unzip it somewhere short, like
   `C:\an-maker`.
2. Open that folder in **Claude Code** (desktop app: *Open folder*) or in **Codex**.
3. Type: **set me up**

The assistant asks you four quick questions:
- your name;
- which 3D account to use, if any;
- a spending limit;
- whether you can publish.

It then installs what's missing (Blender, Git, the Codex image tool) after checking with you, and has you sign in to
your own accounts in your own browser. **Never paste a password or key into the chat.** Last, it builds a local preview
of AN Maker.

## Make something

Just say what you want:

- *make me a Moncler-style puffer jacket*
- *pink camo leggings*
- *baggy sweatpants like Champion, grey*
- *a cropped tank with a retro sunset print*
- or drop in a picture and say *make a hoodie inspired by this*

It picks the right method, makes a funny parody of any brand, draws it, builds it in 3D, checks the fit from every angle
and with other clothes, and shows you a preview.
- Fitted tees, tanks, leggings and shorts cost only image generation.
- Loose 3D pieces (hoodies, jackets, puffers, sweats, cargos) cost about 25 credits a try.
- It tells you the cost first and never goes over your limit without asking.

When you like it, say **save it**. It goes to GitHub, and then to the AN Maker page.

## Updates

Every time you make something, it first pulls the newest version of the pipeline automatically. Nothing to do.

## What it can't make yet

Hair, shoes, accessories, dresses or skirts, makeup, faces or expressions, animations. Those aren't ready.

## If something's off

Say *run the doctor*. It checks every tool and sign-in and tells you exactly what to fix.
