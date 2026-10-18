# Handing the garment maker to a teammate (owner checklist)

## How it fits together

| Piece | Where | Who can change it |
|---|---|---|
| Garment maker (pipeline, docs, catalog, garments) | private repo `ImmortalWalrus/an-maker` | owner; teammates push their saved garments |
| The live site | private repo `ImmortalWalrus/an-maker-site`, served free by Cloudflare Pages at https://an-maker.pages.dev | every push to `main` goes live in about a minute |
| Cloudflare Pages project `an-maker` | the owner's Cloudflare account (free plan) | owner only; nobody else needs a Cloudflare login |

The old Claude artifact (https://claude.ai/artifact/5dbuTk8EZot5Wb1QR261fN) is retired: nothing publishes there any
more, and no Claude Share is needed.

## Adding a teammate

1. Repository **Settings → Collaborators → Add people** on **both** repos (`an-maker` and `an-maker-site`), with their
   GitHub username or email. (Rick, `ricklancastermulti`, was invited to both on 2026-10-17.)
2. Text them the repo link (below). That's all: setup does the rest, and doctor walks them through accepting the
   second invite if they missed it.

## Owner machine

Run setup once as owner (no block-list, no install move):
`python pipeline/garment.py setup --name "<you>" --mesh higgsfield --max-credits 100 --role owner`.

## Keep them updated

Everything they run starts with `python pipeline/garment.py update`, which pulls whatever you've pushed to `an-maker`.
That repo is the **garment maker** only: the pipeline, its docs, the catalog and garment data. After you change those:

```
git add -A pipeline docs catalog CHANGELOG.md && git commit -m "..." && git push
```

Add a line to `CHANGELOG.md`; they see it the next time they make something. Garments they save arrive in your copy on
your next `git pull`.

**Engine / page changes** (index.html, the renderer, UI, animations) are not committed to `an-maker`. They go live
with `python pipeline/web/live_site.py publish --page web/customizer/index.html --files assets/... -m "..."`, which
pushes to `an-maker-site`. The `an-maker` repo keeps one frozen copy of the page only so local previews run; refresh it
if previews ever stop matching the site.

## The text to send

> Here u go https://github.com/ImmortalWalrus/an-maker

(Accept the GitHub invite it shows, then the README on that page says the rest: download the zip, switch the
assistant to Bypass permissions / Full access, drop the zip in, type "set me up".)
