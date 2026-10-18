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
4. Publishing access (optional). On the AN Maker page, open **Share** and add the **email of their Claude account**
   with **edit** access.
   - Access belongs to the Claude account, not the coding tool. It works wherever they're signed in to Claude: Claude
     Code desktop or CLI.
   - Codex can't publish to a Claude page at all. With Codex they make and save garments, then publish by saying
     *publish it* in Claude Code (if they have Claude), or you publish after `git pull`.
   - Edit access technically allows any change to the page. What keeps them to garments is the assistant's rules plus
     the teammate block-list that setup installs, so only grant it to people you trust. If Share offers no edit option
     for their account (an organization setting), keep them view-only and publish yourself.
5. On your own machine, run setup once as owner (no block-list):
   `python pipeline/garment.py setup --name "<you>" --mesh assethub --max-credits 100 --publish yes --role owner`.
6. Send them the message below.

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
