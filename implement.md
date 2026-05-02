# Server-Wide Worker Process Fix

## Goal

Move long-running CWA jobs out of the web process into a dedicated worker process, add durable task visibility, and prevent library-write jobs from freezing the browser UI.

## Checklist

- [x] Create implementation branch `codex/server-wide-worker`.
- [x] Add `implement.md` with this checklist.
- [x] Add durable app-db-backed job queue models and migrations.
- [x] Add a queue API for enqueue, claim, progress, finish, fail, cancel, stale recovery, and dedupe.
- [x] Add task registry/serialization for supported `CalibreTask` jobs.
- [x] Add dedicated worker entrypoint `cps_worker.py`.
- [x] Add s6 service `svc-cwa-worker`.
- [x] Route supported `WorkerThread.add(...)` calls into the durable queue outside the worker process.
- [x] Keep in-process execution available only as a worker-side compatibility executor/fallback.
- [x] Update task status UI/API to read durable jobs and legacy in-memory tasks during transition.
- [x] Make Hardcover "Sync now" enqueue and return immediately.
- [x] Make scheduled Hardcover state sync enqueue durable jobs with dedupe.
- [x] Route convert library, EPUB fixer, duplicate scan, auto Hardcover ID fetch, thumbnail/cache jobs, metadata backup, reconnect, upload/import follow-up jobs, and auto-send through the durable queue where practical.
- [x] Add shared library-busy state for Calibre library writers.
- [x] Mark import, cover enforcer, convert library, EPUB fixer, and other Calibre DB writers busy in `finally`-safe blocks where practical.
- [x] Make book-heavy UI routes fail fast or show a library-busy state instead of hanging on SQLite locks.
- [x] Isolate worker app DB and Calibre DB sessions from web globals where practical.
- [x] Add tests for enqueue, claim, finish, fail, cancel, stale recovery, and dedupe.
- [x] Add tests for Hardcover manual sync enqueue behavior.
- [x] Add tests for task status JSON returning durable jobs.
- [x] Add tests for library-busy helper behavior.
- [x] Update GHCR workflow to build/publish `dev` and `dev-<shortsha>` from the `dev` branch.
- [x] Run relevant tests. `/opt/homebrew/bin/pytest` was missing `requests`, so tests were run with `testing/venv/bin/pytest`.
- [x] Build Docker locally if feasible. Built `cwa-tasse:dev-local` for `linux/arm64`.
- [ ] Push local branch to remote `dev` and let GHCR build the dev-tagged image.

## Notes

- Production deployment is intentionally out of scope for this branch.
- Do not commit private deploy scripts, tokens, remote logs, or machine-specific secrets.
- Compatibility fallback: unsupported `CalibreTask` adapters still log a warning and run through the legacy in-process queue. No known import, Hardcover, metadata, conversion, duplicate scan, thumbnail, cleanup, or mail task that commonly freezes the UI is intentionally left unregistered in v1.
