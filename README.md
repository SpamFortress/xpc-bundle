X Post Cleaner bot bundle: the static Page source, the local helper script, and its word lists and card settings.

This repository holds no user data, secrets, or personal handles. Nothing here talks to a server; the script reads an X archive on the owner's own bot computer only.

Bots install a release by its immutable tag xpc-vX.Y.Z: download manifest.json, check its sha256 against the value pinned in the bot's skill (or in latest.json for an owner-approved update), then download every file in it and check each one's bytes and sha256. On any mismatch the bot refuses the file.

latest.json on main names the newest release. Bots only read it to offer an update, which the owner must approve.

Changes go only through pull requests. Release tags are never moved or deleted.

## Building the Page (1.1.2: small first page, rest in the background)

A bot has to type every byte of a Page into WriteCanvas and EditCanvas, so a big page is slow to publish. 1.1.2 makes the first page small and fills in the rest afterwards, into the same canvas.

- page.canvas.tsx is the readable design source. page.min.tsx is the same page with comments, indentation and repeated style objects removed (152,355 bytes down to 106,870). It compiles to exactly the same JavaScript as the design source. This is what the canvas holds when the build is done.
- page/01-first.tsx (about 34.3 KB) is the first page: the same styles, header and stepper, with the Sign in and Get your archive screens. Pick, Review and Run show as locked steps. It is generated from page.min.tsx, not written by hand. Write it with one WriteCanvas call.
- page/02.json to page/13.json are EditCanvas edit lists. Steps 2 to 7 (phase A) fill in the Pick screen; after step 7 Pick unlocks. Steps 8 to 13 (phase B) fill in Review and Run; after step 13 the canvas is page.min.tsx exactly and Review unlocks. Every step compiles on its own, because each missing part waits inside a comment.
- page/plan.json lists every step with the sha256 the canvas must have after it. page/regions.json records which parts of page.min.tsx each phase adds.

Commands:

- `python3 scripts/xpc_core.py page-steps` lists the steps. `page-steps --show 1 --part K` prints the first page in parts of up to 9,500 bytes (join them with nothing between). `page-steps --show N` prints the edits for step N as JSON.
- `python3 scripts/xpc_core.py page-verify <saved ReadCanvas result> [--after N]` checks the canvas against the expected text after step N (no --after: the finished page).
- `python3 scripts/xpc_core.py page-where <saved ReadCanvas result>` tells which step the canvas is at, so an interrupted build can resume.
- `python3 scripts/xpc_core.py page-build` regenerates page/ from page.min.tsx and page/regions.json and checks that every step reassembles byte for byte.

Release-time only (bots never need these): `node tools/shrink_page.js page.canvas.tsx page.min.tsx` and `node tools/stage_plan.js page.min.tsx page/regions.json`. They need Node with the typescript and esbuild packages; set XPC_NODE_TOOLS to a folder that has them installed.

## Page status (1.1.3)

The bot can show where things stand without sending a chat message. These top-level lines are the ones it edits:

- `PAGE_STATUS` is `null` when the banner is hidden. Otherwise it is `{tone, lead, text}` with tone `info`, `warn`, `error`, or `ok`. The banner sits under the stepper on every step, including the first page. Empty lead and text stay hidden.
- `START_STEP`, `START_PHASE`, `START_RUN`, and `SIGNED_IN_HANDLE` are the starting step, archive phase, run phase, and signed-in handle. Each is one line. An empty handle is not shown. The shipped handle line is exactly `const SIGNED_IN_HANDLE:string="";` (the `:string` keeps the canvas type-check from treating it as the literal `""`).
- `PHONE_FORTRESS_URL` and `EMAIL_FORTRESS_URL` are also annotated `:string`, so comparing them to `""` type-checks. Shipped lines: `const PHONE_FORTRESS_URL:string="https://x.ai/bot/a_4tVB4gwbwFBLkUhkTCW";` and `const EMAIL_FORTRESS_URL:string="https://x.ai/bot/MyKDbPYVwJeJpCNtVTFym";`.
- `page-verify` and `page-where` put those five lines back to their defaults before comparing, so a status edit does not fail the build check.
- `python3 scripts/xpc_core.py page-status --tone info --lead "..." --text "..."` prints one JSON object, `{"old_string","new_string"}`, for EditCanvas. `old_string` is the shipped `const PAGE_STATUS:...=null;` declaration. `new_string` is that same declaration with the initializer replaced. Quotes, backslashes, and newlines are escaped. SSN-shaped numbers are masked as `***-**-NNNN` and the full number is never printed. `--clear` hides the banner. `--apply <file>` writes the initializer into a saved canvas.

`PHONE_FORTRESS_URL` and `EMAIL_FORTRESS_URL` are the share links for Phone Fortress and Email Fortress. On the archive step (first page) and on the finished run step, each name is a real external link that opens in a new tab. An empty URL would have no link styling and no external-link arrow.

`python3 scripts/xpc_core.py page-typecheck` type-checks the first page, every later build step, and the finished page with `tsc --strict` and the React types. It must pass before a release is tagged.

## Page controls in 1.1.2

A tap on the Page never reaches the bot. Buttons keep their labels and look; a button whose action needs the bot has a short "Opens in the chat" note under it, and the bot offers the same choice in the chat as a tap option. The archive step also links to X's own Download your data page, which opens in the owner's own browser.
