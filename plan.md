# Hardcover State Sync Plan

## Scope Guard
- [ ] Keep this feature separate from existing Hardcover reading progress sync.
- [ ] Do not add generic shelf syncing.
- [ ] Do not create local CWA books from Hardcover.
- [ ] Do not create Hardcover books from fuzzy title/author matches.
- [ ] Never delete Hardcover user books.

## Discovery
- [x] Locate existing per-user Hardcover token storage in `cps/ub.py` and `cps/web.py`.
- [x] Locate normal shelf models and routes in `cps/ub.py` and `cps/shelf.py`.
- [x] Confirm Magic Shelves are separate from normal shelves.
- [x] Locate read status model in `cps/ub.py`.
- [x] Locate existing Hardcover GraphQL client in `cps/services/hardcover.py`.
- [x] Locate tag update flows in `cps/editbooks.py`.
- [x] Locate all read-status update flows.
- [x] Locate scheduler/task conventions for recurring per-user jobs.

## Data Model And Migration
- [x] Add per-user Hardcover State Sync settings to `ub.User`.
- [x] Add `hardcover_state_sync` model.
- [x] Add required indexes for sync lookup.
- [x] Add migration for new user columns.
- [x] Add migration/create path for the sync state table.
- [x] Add default/fallback handling for existing users.

## Hardcover API Client
- [x] Centralize Hardcover status constants, including Did Not Finish.
- [x] Fetch user books with status, identifiers, and timestamps.
- [x] Change user book status without creating user books.
- [x] Fetch current user's Hardcover lists.
- [x] Fetch books on a selected Hardcover list, including `list_books.id`.
- [x] Add a book to a selected Hardcover list without duplicates.
- [x] Remove a book from a selected Hardcover list by `list_books.id`.

## State Sync Service
- [x] Resolve/create the configured normal CWA "Currently Reading" shelf.
- [x] Match CWA books to Hardcover using stored identifiers and safe ISBN mapping only.
- [x] Pull Hardcover Currently Reading into the configured CWA shelf.
- [x] Pull Hardcover Read into CWA read status, including initial pull.
- [x] Push configured CWA shelf additions to Hardcover Currently Reading.
- [x] Push configured CWA shelf removals to Hardcover Read or Want to Read using local read/progress rules.
- [x] Pull selected Hardcover list membership into the configured CWA tag.
- [x] Push configured CWA tag membership to selected Hardcover list.
- [x] Remove selected list/tag when a book becomes read.
- [x] Track per-user/per-book/per-sync-key state in `hardcover_state_sync`.
- [x] Implement conflict resolution with latest timestamp wins and Hardcover fallback.
- [x] Add clear info/warning/debug log lines for actions, skips, and no-ops.

## Local Change Hooks
- [x] Hook normal shelf add.
- [x] Hook normal shelf remove.
- [x] Hook bulk shelf add if applicable.
- [x] Hook configured tag add/remove.
- [x] Hook single read-status updates.
- [x] Hook bulk read-status updates if present.
- [x] Respect "Push local changes immediately".

## UI
- [x] Add "Hardcover State Sync" section near the Hardcover token in profile settings.
- [x] Add status sync enable and per-direction controls.
- [x] Add normal shelf selector with default "Currently Reading" shelf behavior.
- [x] Add list/tag sync controls.
- [x] Populate Hardcover list dropdown for valid user token.
- [x] Show warning if saved Hardcover list ID no longer exists.
- [x] Add polling interval selector.
- [x] Add "Sync Now" button and route.

## Scheduler And Manual Sync
- [x] Add per-user polling based on configured interval.
- [x] Manual sync pulls Hardcover, resolves conflicts, and pushes pending local changes.
- [x] Show success/error feedback in the UI.

## Verification
- [x] Run focused Python syntax/import checks.
- [ ] Run available focused tests. Blocked: full pytest collection fails in local Python 3.14 venv because pinned dependencies/tests are not compatible with this environment (`greenlet` build failure; existing test stubs also shadow `cps.services` during collection).
- [x] Manually inspect changed routes/templates for regressions.
- [x] Leave GitHub push untouched.
