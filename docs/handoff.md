# Handing the garment maker to a teammate (owner checklist)

## Once

1. On github.com, create a **private** repository, for example `an-maker`, with no README.
2. Put its address in `tools/repo.txt` (e.g. `https://github.com/<you>/an-maker.git`), then commit and push:

   ```
   git add tools/repo.txt && git commit -m "repo address"
   git remote add origin https://github.com/<you>/an-maker.git
   git push -u origin main
   ```

   (About 170 MB. Git opens a browser to sign in the first time.)
3. Repository **Settings → Collaborators** → add the teammate's GitHub account. Give it write access, so their
   `save` can push their garments.
4. Optional: AN Maker page → **Share** → give their Claude account **edit** access, so they can publish themselves.
   Without it they save, and you publish.
5. Send them the message below.

## Keep them updated

Everything they run starts with `python pipeline/garment.py update`, which pulls whatever you've pushed. So after you
change the pipeline, the docs, the page or its assets:

```
git add -A pipeline docs catalog CHANGELOG.md web/customizer/index.html web/customizer/assets && git commit -m "..." && git push
```

Add a line to `CHANGELOG.md`. They see it the next time they make something. Garments they save arrive in your copy on
your next `git pull`. Run it before you publish, so the export includes theirs.

## The message to send

> Hey Rick! Here's the AN Maker garment maker.
> 1. Accept the GitHub invite, then open https://github.com/<you>/an-maker → green **Code** button → **Download ZIP**.
> 2. Unzip it to a short path like `C:\an-maker`.
> 3. Open that folder in Claude Code (or Codex) and type **set me up**. It asks you 4 quick questions and installs
>    what's missing. Sign in to your own accounts when it asks, and never paste passwords into the chat.
> 4. Then just ask for clothes: *"make me a Moncler-style puffer"*, *"pink camo leggings"*, or drop in a picture.
>    Tops, bottoms and jackets only for now.
> It updates itself every time you use it.
