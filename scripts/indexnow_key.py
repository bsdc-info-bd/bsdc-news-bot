#!/usr/bin/env python3
"""Generate an IndexNow key and explain where to host it.

IndexNow (Bing, Yandex, Seznam, Naver, Yep …) needs a key file on YOUR domain:
    https://<your-domain>/<key>.txt   containing exactly <key>

Blogger cannot host arbitrary files at the domain root, so IndexNow works only when the
blog uses a custom domain whose root you control (e.g. via Cloudflare — free — using a
Worker/redirect rule that serves the key file). On a plain *.blogspot.com address the bot
skips IndexNow automatically and relies on Google Indexing API + WebSub pings instead.
"""

import secrets

key = secrets.token_hex(16)
print(f"IndexNow key: {key}\n")
print("1. Serve a file at  https://<your-domain>/" + key + ".txt  containing only the key.")
print("2. Add the GitHub secret INDEXNOW_KEY with the value above.")
print("3. Run the workflow 'doctor' task to verify.")
