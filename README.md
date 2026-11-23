X Post Cleaner bot bundle: the static Page source, the local helper script, and its word lists and card settings.

This repository holds no user data, secrets, or personal handles. Nothing here talks to a server; the script reads an X archive on the owner's own bot computer only.

Bots install a release by its immutable tag xpc-vX.Y.Z: download manifest.json, check its sha256 against the value pinned in the bot's skill (or in latest.json for an owner-approved update), then download every file in it and check each one's bytes and sha256. On any mismatch the bot refuses the file.

latest.json on main names the newest release. Bots only read it to offer an update, which the owner must approve.

Changes go only through pull requests. Release tags are never moved or deleted.

## Building the Page in steps (1.1.1)

The Page source (page.canvas.tsx, about 152 KB) is too large for one inline WriteCanvas call, and WriteCanvas does not accept file references. So the bundle also ships the same page split into steps that each compile on their own:

- page/00-skeleton.tsx: a tiny placeholder Page plus the marker line `//~@@XPC-NEXT@@`. Write it with WriteCanvas.
- page/01.txt to page/17.txt: each is a slice of the page (about 9.5 KB) with every line commented out using `//~`, followed by the marker. Apply each with EditCanvas, replacing `//~@@XPC-NEXT@@` with the step's text. The canvas stays a compiling placeholder because the added lines are comments.
- page/99-finish.json: one EditCanvas with three edits that removes the placeholder and the marker and un-comments every line. The result is page.canvas.tsx exactly.

`python3 scripts/xpc_core.py page-steps --show N` prints the exact text for step N (step 18 prints the finish edits). `python3 scripts/xpc_core.py page-verify <saved ReadCanvas result> [--after N]` checks the canvas against the expected text after any step. `page-build` regenerates page/ from page.canvas.tsx and checks that the steps reassemble to it byte for byte.

The page itself did not change from 1.1.0 (same sha256).
