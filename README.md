X Post Cleaner bot bundle: the static Page source, the local helper script, and its word lists and card settings.

This repository holds no user data, secrets, or personal handles. Nothing here talks to a server; the script reads an X archive on the owner's own bot computer only.

Bots install a release by its immutable tag xpc-vX.Y.Z: download manifest.json, check its sha256 against the value pinned in the bot's skill (or in latest.json for an owner-approved update), then download every file in it and check each one's bytes and sha256. On any mismatch the bot refuses the file.

latest.json on main names the newest release. Bots only read it to offer an update, which the owner must approve.

Changes go only through pull requests. Release tags are never moved or deleted.

## Building the Page (1.1.2: small first page, rest in the background)

A bot has to type every byte of a Page into WriteCanvas and EditCanvas, so a big page is slow to publish. 1.1.2 makes the first page small and fills in the rest afterwards, into the same canvas.

- page.canvas.tsx is the readable design source. page.min.tsx is the same page with comments, indentation and repeated style objects removed (152,355 bytes down to 106,870). It compiles to exactly the same JavaScript as the design source. This is what the canvas holds when the build is done.
- page/01-first.tsx (14,546 bytes) is the first page a bot types: the same styles, header, stepper, and status banner, the five state lines, a one-line Sign in note, and the Archive view, including the requested-archive line. Pick, Review and Run show as locked steps. The full Sign in steps and both Where your data goes panels are filled in by a later step. It is generated from page.min.tsx, not written by hand. `page-steps --show 1` prints it in two parts; join them with nothing between.
- page/02.json through the last numbered JSON file are EditCanvas edit lists. `page/plan.json` names each step. Phase A fills in the Pick screen; Pick unlocks when that phase finishes. Phase B fills in Review and Run; the canvas is page.min.tsx exactly when the last step finishes. Every step compiles on its own, because each missing part waits inside a comment.
- page/plan.json lists every step with the sha256 the canvas must have after it. page/regions.json records which parts of page.min.tsx each phase adds.

Commands:

- `python3 scripts/xpc_core.py page-steps` lists the steps. `page-steps --show 1 --part K` prints the first page in parts (join them with nothing between). `page-steps --show N` prints the edits for step N as JSON. If N is past the last step, it exits non-zero and prints `the plan has N steps`.
- `python3 scripts/xpc_core.py page-verify <saved ReadCanvas result> [--after N]` checks the canvas against the expected text after step N (no --after: the finished page).
- `python3 scripts/xpc_core.py page-where <saved ReadCanvas result>` tells which step the canvas is at, so an interrupted build can resume.
- `python3 scripts/xpc_core.py page-build` regenerates page/ from page.min.tsx and page/regions.json and checks that every step reassembles byte for byte.

Release-time only (bots never need these): `node tools/shrink_page.js page.canvas.tsx page.min.tsx` and `node tools/stage_plan.js page.min.tsx page/regions.json`. They need Node with the typescript and esbuild packages; set XPC_NODE_TOOLS to a folder that has them installed.

## Order (1.1.5)

Sign-in happens first, in parallel with the Page build.

1. The bot's first message.
2. The X sign-in window opens immediately, while the Page builds in the background.
3. On sign-in the bot requests the archive itself. There is no grab button and no grab tap card.
4. The Page card appears. Once the archive is requested (`START_PHASE` `grabbing` or `waiting`), the Archive step shows one plain line: "Your archive has been requested. X usually takes 1 to 3 days. The bot will pull it in automatically and let you know when it's ready. Meanwhile, set up your rules." There is no spinner. The owner can open Pick and set rules while X prepares the file. When the archive is ready, the Page shows the archive-ready view as designed.

The sign-in line on the Page reads the same either way: "Sign in in the X window in the chat. If you already signed in, you're set." There is no Sign in button. A Page button cannot drive the browser.

If sign-in finished before the Page existed, the first write can open on the archive step with the handle already filled. The shipped page still starts at sign-in with an empty handle, so nothing identifies anyone before sign-in.

- `python3 scripts/xpc_core.py page-steps --show 1 --part K --start archive --handle HANDLE --phase grabbing` prints that first page. Join the parts with nothing between them.
- `python3 scripts/xpc_core.py page-state --start archive --handle HANDLE --phase grabbing` prints the exact `START_STEP`, `SIGNED_IN_HANDLE`, and `START_PHASE` edits. `page-state --phase grabbing` or `--phase waiting` is the one-line edit for the requested-archive line. `page-state --phase ready` is the one-line edit for the archive-ready view.

The full archive is the default. If X is slow, the bot can offer recent posts with a tap card. "Wait for the full archive" stays a tap-card line only on the recent-only view.

`page-verify` and `page-where` put those lines back to the defaults before comparing, so either start still matches the build.

Bot actions are not buttons. A plain line names the tap card in the chat (approve, grab the archive, recent posts, retry, removal requests, and the rest). Buttons that only change the Page, such as rules, filters, Keep on the preview list, sort, and download, stay.

`python3 scripts/xpc_core.py selftest --no-typecheck` is the first-turn fast path: it checks the Python logic and that every file in manifest.json matches its bytes and sha256, and it does not run Node. The full `selftest` is the release gate. It also type-checks every build step. `page-typecheck` looks for typescript and `@types/react` in `XPC_NODE_TOOLS`, or in `/workspace/xpc-node-tools` when that variable is unset. If those packages are missing, the script installs `typescript@5.6.3`, `esbuild@0.28.2`, and `@types/react@18.3.18` there. If that install cannot run, the type-check is skipped and the full selftest still finishes.

## Archive data on the Page (1.1.6)

The Page never holds every post. Python computes the totals. The Page shows those totals plus a sample of at most 50 posts (the Worst 50 first). Each EditCanvas payload from `page-pool` is at most 20,000 bytes. `page-steps` parts stay at most 9,500 bytes. `page.min.tsx` in this release is 98,890 bytes. The Pick, Review, and Run controls are still in that file.

- `python3 scripts/xpc_core.py verdict posts.jsonl [--rules rules.json | --qa everything|oldest|era|replies|reposts|best] [--handle HANDLE] [--pins id,id]` prints full-archive counts, the no-date count, and whether Delete everything needs the typed phrase.
- `python3 scripts/xpc_core.py page-pool posts.jsonl [--qa ...] [--handle HANDLE]` prints the EditCanvas edits for `ARCHIVE_CAPS`, `ARCHIVE_POST_COUNT`, `LOADED_TOTALS`, and `POOL`.
- `python3 scripts/xpc_core.py export posts.jsonl --out list.csv [--qa ...] [--handle HANDLE]` writes the doomed list. Free-text fields are SSN-masked. Ids are `="..."`.
- `python3 scripts/xpc_core.py export-check list.csv` prints the row count and the ids unwrapped from `="..."`.
- `python3 scripts/xpc_core.py rules --qa era [--posts posts.jsonl]` prints that card's rules JSON. `page-state --qa era` writes both `LOADED_QA` and `LOADED_RULES`.
- `python3 scripts/xpc_core.py page-state --run running` edits `START_RUN`. `--qa`, `--kept`, `--lane`, `--pace`, `--cooling on|off`, `--rules`, `--failed`, `--deleted`, `--verified`, `--left`, `--unchecked`, `--likes`, `--totals`, and `--proof` edit the loadable constants. Pass `--canvas FILE` so the next edit matches the current line, and `--apply` to write it. Clear all rules still uses `BASE`, not those constants.
- `export-check` prints the row count and the sha256 of the sorted ids. `--ids` adds the full list. `verdict`, `export`, and `page-pool` all take `--pins`, and a kept id is left out of the export and the sample.

Posts with no readable date are left out of deletes and counted. Replies-to-others does not delete replies in your own threads. A past era starts at the oldest year and the year after it. `page-verify` and `page-where` ignore `POOL`, the archive caps, and the loaded constants, so a canvas still matches after data is loaded.

Page 1 is the small file a bot types first: styles, header, stepper, the status banner, the five state lines, a one-line Sign in note, and the Archive view. The full Sign in steps and the Where your data goes panels are filled in by a later step.

## Page status (1.1.3)

The bot can show where things stand without sending a chat message. These top-level lines are the ones it edits:

- `PAGE_STATUS` is `null` when the banner is hidden. Otherwise it is `{tone, lead, text}` with tone `info`, `warn`, `error`, or `ok`. The banner sits under the stepper on every step, including the first page. Empty lead and text stay hidden.
- `START_STEP`, `START_PHASE`, `START_RUN`, and `SIGNED_IN_HANDLE` are the starting step, archive phase, run phase, and signed-in handle. Each is one line. An empty handle is not shown. The shipped handle line is exactly `const SIGNED_IN_HANDLE:string="";` (the `:string` keeps the canvas type-check from treating it as the literal `""`).
- `PHONE_FORTRESS_URL` and `EMAIL_FORTRESS_URL` are also annotated `:string`, so comparing them to `""` type-checks. Shipped lines: `const PHONE_FORTRESS_URL:string="https://x.ai/bot/a_4tVB4gwbwFBLkUhkTCW";` and `const EMAIL_FORTRESS_URL:string="https://x.ai/bot/MyKDbPYVwJeJpCNtVTFym";`.
- `page-verify` and `page-where` put those five lines back to their defaults before comparing, so a status edit does not fail the build check.
- `python3 scripts/xpc_core.py page-status --tone info --lead "..." --text "..."` prints one JSON object, `{"old_string","new_string"}`, for EditCanvas. `old_string` is the shipped `const PAGE_STATUS:...=null;` declaration. `new_string` is that same declaration with the initializer replaced. Quotes, backslashes, and newlines are escaped. SSN-shaped numbers are masked as `***-**-NNNN` and the full number is never printed. `--clear` hides the banner. `--apply <file>` writes the initializer into a saved canvas.

`PHONE_FORTRESS_URL` and `EMAIL_FORTRESS_URL` are the share links for Phone Fortress and Email Fortress. Each name is a real external link that opens in a new tab, on the archive step once the Where your data goes panel is restored and on the finished run step. An empty URL would have no link styling and no external-link arrow.

`python3 scripts/xpc_core.py page-typecheck` type-checks the first page, every later build step, and the finished page with `tsc --strict` and the React types. It must pass before a release is tagged.

## Page controls in 1.1.2

A tap on the Page never reaches the bot. Buttons keep their labels and look; a button whose action needs the bot has a short "Opens in the chat" note under it, and the bot offers the same choice in the chat as a tap option. The archive step also links to X's own Download your data page, which opens in the owner's own browser.
