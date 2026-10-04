# Getting Uburinzi Health onto GitHub

Every change lands in **`/home/user/github-upload`** — a clean copy of the project laid out exactly
as GitHub should receive it: no secrets, no database, no caches.

```bash
cd ~/uburinzi
python -m app.cli bundle          # regenerates it (run after every change)
```

| Artefact | What it is |
|---|---|
| `~/github-upload/` | flat project folder, ready to push (its `.git` is preserved between runs) |
| `dist/uburinzi-health.zip` | source zip nested under `uburinzi/` — the one served by **`/download`** |
| `dist/uburinzi-health-github.zip` | same folder zipped at the top level, for GitHub's drag-and-drop upload |

---

## Option A — one command (recommended)

`push` clones your repository, overlays every current file, commits and pushes. It works whether the
repo is brand new or already holds an older copy, and it **updates the branch that's already there**
(instead of creating a second one next to it) — so a Vercel project already connected to the repo
stays connected and redeploys automatically.

```bash
cd ~/uburinzi
python -m app.cli push --repo https://github.com/YOUR-USER/uburinzi-health.git
```

Useful flags:

| Flag | Effect |
|---|---|
| `--message "…"` | commit message |
| `--dry-run` | show what would change, push nothing |
| `--clean` | delete a stale nested `uburinzi/` folder left behind by an earlier zip upload |
| `--branch main` | override the branch (it uses the remote's own default by default) |

Private repositories: GitHub no longer accepts account passwords, so embed a personal-access token
(**Settings → Developer settings → Personal access tokens**, scope `repo`):

```bash
python -m app.cli push --repo https://ghp_yourtoken@github.com/YOUR-USER/uburinzi-health.git
```

> A token in a URL is a credential — treat the command as sensitive history. Delete the token from
> GitHub afterwards if the machine isn't yours.

Running git on your own computer instead? `python -m app.cli bundle`, then:

```bash
cd ~/github-upload
git remote add origin git@github.com:YOUR-USER/uburinzi-health.git
git push -u origin main
```

## Option B — no git at all

1. Create an empty repo on GitHub (no README, no `.gitignore`).
2. Open it, choose **uploading an existing file**, and drag the **contents** of `~/github-upload`
   (files and folders, not the folder itself).

Use **Option A** for every update after the first — repeated zip uploads leave an old copy behind.

---

## What is never included

`.env` (your Africa's Talking key lives here), `data/*.db` (the patient database), `__pycache__`,
`dist/`, `.vercel/`. The `.gitignore` repeats those rules, so even `git add -A` stays safe.
`.env.example` **is** included — it documents every environment variable and contains no secrets.

## Then deploy

- **Vercel connected to this repo** → the push already triggered a build. Set the environment
  variables from [deploy-vercel.md](deploy-vercel.md) and **Redeploy**, because variables only apply
  to new deployments.
- **New to Vercel** → import the repo there first, then do the same.
