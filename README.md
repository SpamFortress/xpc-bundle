X Post Cleaner bot bundle: the static Page source, the local helper script, and its word lists and card settings.

This repository holds no user data, secrets, or personal handles. Nothing here talks to a server; the script reads an X archive on the owner's own bot computer only.

Bots install a release by its immutable tag xpc-vX.Y.Z: download manifest.json, check its sha256 against the value pinned in the bot's skill (or in latest.json for an owner-approved update), then download every file in it and check each one's bytes and sha256. On any mismatch the bot refuses the file.

latest.json on main names the newest release. Bots only read it to offer an update, which the owner must approve.

Changes go only through pull requests. Release tags are never moved or deleted.
