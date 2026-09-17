# Getting Uburinzi Health onto GitHub

Every change lands in **`/home/user/github-upload`** — a clean copy of the project laid out exactly
as GitHub should receive it: no secrets, no database, no caches.

```bash
cd ~/uburinzi
python -m app.cli bundle          # regenerates it (run after every change)
```

That prints three artefacts:

| Artefact | What it is |
|---|---|
| `~/github-upload/` | flat project folder, ready to push (its `.git` is preserved between runs) |
| `dist/uburinzi-health.zip` | source zip nested under `uburinzi/` — the one served by **`/download`** |
| `dist/uburinzi-health-github.zip` | same folder zipped at the top level, for GitHub's drag-and-drop upload |

## Option A — push the folder (keeps history)

```bash
cd ~/github-upload
git remote add origin git@github.com:YOUR-USER/uburinzi-health.git
git push -u origin main
```

Each `bundle` run refreshes the files; then:

```bash
cd ~/github-upload
git add -A
git commit -m "Update"
git push
```

## Option B — no git at all

1. Create an empty repo on GitHub (no README, no `.gitignore`).
2. Open it, choose **uploading an existing file**, and drag the **contents** of `~/github-upload`
   (files and folders, not the folder itself).

## What is never included

`.env` (your Africa's Talking key lives here), `data/*.db` (the patient database), `__pycache__`,
`dist/`, `.vercel/`. The `.gitignore` repeats those rules, so even `git add -A` stays safe.

## Then deploy

With the repo on GitHub, import it on Vercel and follow
[deploy-vercel.md](deploy-vercel.md) — set `DATABASE_URL`, `SECRET_KEY`, `CRON_SECRET` and the
Africa's Talking variables, and the site is live.
