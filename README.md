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

## Page controls in 1.1.2

A tap on the Page never reaches the bot. Buttons keep their labels and look; a button whose action needs the bot has a short "Opens in the chat" note under it, and the bot offers the same choice in the chat as a tap option. The archive step also links to X's own Download your data page, which opens in the owner's own browser.
