# Opal-Central — working notes for Claude

Customer churn-risk dashboard (HPE customer heat levels). Single-file FastAPI app.

## Stack & layout
- FastAPI (`app.py`, single file) + Jinja2 (`templates/`) + SQLite (`opal.db`).
- Auth: passlib bcrypt (`bcrypt==4.0.1` pinned), itsdangerous signed session cookie.
- Secrets at rest (SMTP password) encrypted with Fernet; key from `OPAL_FERNET_KEY` env or `data/secret.key`.
- Prod: python:3.12-slim in Docker, behind HPE edge `theedge.ext.hpe.com/opal-central`.

## TWIN REPO — apply changes to both
`opal` and `opal-mist` are parallel apps with near-identical code. **Any feature/fix here
should also be applied to `../opal-mist`** (its cookie name, ROOT_PATH `/opal-mist`, and
some nearby lines differ — prefer direct edits over `git apply`, which has failed on the
mist copy before). See `../opal-mist/CLAUDE.md`.

## Local dev / verify
- Test venv: `/Users/rick/Projects/opal/venv` (Python 3.9 — use `from __future__ import annotations` for `str | None`).
- Cheap verification (default): `python -m py_compile app.py` + Jinja parse. TestClient round-trip for logic changes. **Screenshots only when asked** (they're token-heavy).
- Default admin bootstrap: `admin`/`admin` when no users exist.

## Git
- Remote `origin` → github.com/xod442/opal (branch `main`). **PUBLIC repo.**
- Commit only when Rick says so. Use:
  `git -c user.name="Rick Kauffman" -c user.email="rick@rickkauffman.com" commit`
  and trailer: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`
- **Never stage** `*.db`, `*.db.bak*`, `.env`, `data/`, or `secret.key`. Prefer `git add <explicit files>` over `git add -A` (a stray DB backup once leaked to this public repo).

## Gotchas
- If both opal and opal-mist break login at once with no deploy → suspect the HPE **edge/session policy**, not the app.
