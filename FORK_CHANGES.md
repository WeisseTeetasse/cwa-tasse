# cwa-tasse Fork Changes

This repository is a personal fork of
[crocodilestick/Calibre-Web-Automated](https://github.com/crocodilestick/Calibre-Web-Automated).

Additional code in this fork is 100% AI-generated. The goal of this file is to keep
the local patch stack visible so future upstream CWA releases can be merged or rebased
with less guesswork.

## Local Patch Stack

The fork currently carries these local changes on top of upstream CWA:

1. Hardcover sync is progress-only.
   - Does not change Hardcover shelves/lists.
   - Does not move books into "currently reading".
   - Only tracks progress when the book is already currently reading on Hardcover.

2. Kobo read-state full sync batching fix.
   - Prevents read-status sync from stopping after the first full-sync batch.

3. Safari dialog/upload compatibility fixes.
   - Fixes empty dialogs and broken add-book behavior seen in Safari/WebKit.

4. KOReader progress updates Hardcover too.
   - KOReader sync now updates the shared CWA/Kobo reading state so Hardcover progress sync can run from KOReader-originated progress updates.

5. Magic Shelf refresh behavior.
   - Refreshes Magic Shelf contents on web navigation so user-created Magic Shelves do not show stale book lists after navigating away and back.

6. Multiple Kobo device tokens per user.
   - Allows one CWA user account to have separate Kobo sync tokens for separate physical Kobo devices.
   - Tracks `kobo_synced_books` per token/device.
   - Keeps reading state shared at the user/book level.
   - Adds migration support for existing single-token installations.

7. Kobo device names and sync logging.
   - Allows renaming "Kobo Device X" in the UI.
   - Logs Kobo requests and library syncs with the configured device name and token id.

## Private/Deployment Files

Deployment helper scripts, private hostnames/IP addresses, image tarballs, and personal runtime
configuration are intentionally not part of this public branch.

## Updating From Upstream

Recommended future update flow:

```bash
git remote add upstream https://github.com/crocodilestick/Calibre-Web-Automated.git
git fetch upstream
git switch main
git merge upstream/main
```

If conflicts are difficult, create a fresh branch from upstream and replay the local patch commits
one by one, resolving conflicts as they appear.
