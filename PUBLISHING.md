# Publishing Reel to PyPI

Published as **`reel-sync`** (plain `reel` was taken). Friends run
**`pip install reel-sync`** and get the tool — the command they then use is just
`reel`. You edit code in this folder; when you publish, they
`pip install --upgrade reel-sync`.

Two facts up front:
- **Your local install already auto-updates.** You installed with `pip install -e .`
  (editable), so every code change in this folder is live the instant you save —
  no reinstall needed. (That's the "it updates on the folder automatically" part.)
- **Friends update by version.** They don't get your edits live; they get them when
  you publish a new version and they run `pip install --upgrade reel`.

---

## 0. Name — done

We're publishing as **`reel-sync`** (set in `pyproject.toml`). The `pip install`
name is `reel-sync`; the import package and the command both stay `reel`.

---

## 1. One-time setup (~10 min)

1. Make a PyPI account: <https://pypi.org/account/register/>. Verify email + turn on 2FA.
2. Install the build/upload tools:
   ```
   pip install --upgrade build twine
   ```

---

## 2. Publish (every release)

From this folder:

```
# 1. bump the version — ONE place: reel/__init__.py
#    __version__ = "1.0.1"

# 2. build the package (creates dist/)
python -m build

# 3. upload to PyPI
python -m twine upload dist/*
```

`twine` will ask for your username (`__token__`) and password (a PyPI **API
token** — create one at <https://pypi.org/manage/account/token/>). Tip: store it
once in `%USERPROFILE%\.pypirc` so you never type it again:

```ini
[pypi]
  username = __token__
  password = pypi-AgEI...your-token...
```

That's it — within a minute it's live at `https://pypi.org/project/reel/` and
anyone can `pip install reel`.

### Bumping versions
PyPI **never lets you re-upload the same version number**, so every publish needs
a new one. Use simple semver in `reel/__init__.py`:
- `1.0.1` — bug fix
- `1.1.0` — new feature
- `2.0.0` — big/breaking change

Before uploading it's worth clearing the old build: delete the `dist/` folder
(or `python -m build` into a clean one) so you only upload the new files.

---

## 3. Optional: fully automatic publishing (GitHub Actions)

If you keep the code on GitHub, you can make publishing happen by itself:
**push a version tag → GitHub builds and uploads to PyPI for you.** No tokens to
copy each time.

It's already scaffolded at `.github/workflows/publish.yml`. To turn it on:

1. Push this folder to a GitHub repo.
2. On PyPI: project → *Settings* → *Publishing* → add a **Trusted Publisher**
   for your GitHub repo + workflow `publish.yml`. (This is the modern, token-free
   way — PyPI trusts your GitHub Action directly.)
3. Release by tagging:
   ```
   git tag v1.0.1
   git push origin v1.0.1
   ```
   The Action builds and publishes automatically. Tell friends: `pip install --upgrade reel`.

---

## Telling your friend

Once it's live, the whole message to your friend is:

> Install Python 3.11+, then run: `pip install reel`
> Plug in your recorder and run: `reel setup`

No Python knowledge needed beyond that.
