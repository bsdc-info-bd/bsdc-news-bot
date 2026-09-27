#!/usr/bin/env python3
"""Create a Google OAuth refresh token for the Blogger API (run once on your own computer).

Usage:
    python scripts/get_refresh_token.py --client-id XXX.apps.googleusercontent.com --client-secret YYY

What it does:
    1. Opens a local web server on http://127.0.0.1:8765 and prints a Google sign-in URL.
    2. You sign in with the Google account that OWNS the blog and approve access.
    3. It prints GOOGLE_REFRESH_TOKEN — save it as a GitHub repository secret.

Requirements (free):
    • Google Cloud project → enable "Blogger API v3".
    • OAuth consent screen → publishing status **In production** (tokens of apps left in
      "Testing" expire after 7 days — the most common reason a Blogger bot suddenly stops).
    • OAuth client of type "Desktop app" (or "Web" with redirect URI http://127.0.0.1:8765/).
Only the Python standard library is used.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import http.server
import json
import secrets
import sys
import urllib.parse
import urllib.request
import webbrowser

SCOPE = "https://www.googleapis.com/auth/blogger"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--client-id", required=True)
    parser.add_argument("--client-secret", required=True)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    redirect = f"http://127.0.0.1:{args.port}/"
    state = secrets.token_urlsafe(16)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    url = AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id": args.client_id, "redirect_uri": redirect, "response_type": "code", "scope": SCOPE,
        "access_type": "offline", "prompt": "consent", "state": state,
        "code_challenge": challenge, "code_challenge_method": "S256",
    })
    result: dict = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            result.update({k: v[0] for k, v in query.items()})
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write("<h2>Done — you can close this tab and return to the terminal.</h2>".encode())

        def log_message(self, *a):
            pass

    print("\n1) Open this URL and sign in with the Google account that owns the blog:\n")
    print(url + "\n")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    with http.server.HTTPServer(("127.0.0.1", args.port), Handler) as server:
        while "code" not in result and "error" not in result:
            server.handle_request()

    if result.get("error") or result.get("state") != state:
        print(f"❌ Authorization failed: {result.get('error', 'state mismatch')}")
        return 1

    data = urllib.parse.urlencode({
        "code": result["code"], "client_id": args.client_id, "client_secret": args.client_secret,
        "redirect_uri": redirect, "grant_type": "authorization_code", "code_verifier": verifier,
    }).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(TOKEN_URL, data=data), timeout=30) as resp:
            token = json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        print("❌ Token exchange failed:", exc.read().decode()[:400])
        return 1
    refresh = token.get("refresh_token")
    if not refresh:
        print("❌ Google did not return a refresh token. Remove the app's access at "
              "https://myaccount.google.com/permissions and run this script again.")
        return 1
    print("✅ Success! Add this as the GitHub secret GOOGLE_REFRESH_TOKEN:\n")
    print(refresh + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
