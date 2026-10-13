"""
Trade your short-lived Meta token for a Page token that does not expire.

Runs on YOUR machine. Your app secret is typed/read locally and sent only to
Meta (graph.facebook.com), never to anyone else, and never written to a file.

Before running, put these in your .env (same folder):

    META_ACCESS_TOKEN=<fresh token from Graph API Explorer, with the
                       permissions from earlier incl. business_management>
    META_APP_ID=<App ID - developers.facebook.com > your app > Settings > Basic>

The app secret (same Basic settings page, "App secret" > Show) can also be in
.env as META_APP_SECRET, or you can just paste it when asked - the prompt
hides what you type.

Run:   python meta_make_permanent_token.py

Result: meta_page_token.txt (git-ignored) containing the Page token. Copy its
contents into a GitHub secret named META_PAGE_TOKEN, then delete the file.
"""

import getpass
import os
import re
import sys

import requests
from dotenv import load_dotenv

load_dotenv()

VERSION = os.environ.get("META_API_VERSION", "v23.0")
BASE = f"https://graph.facebook.com/{VERSION}"
OUT_FILE = "meta_page_token.txt"


def get(path, params):
    r = requests.get(f"{BASE}/{path}", params=params, timeout=60)
    try:
        body = r.json()
    except ValueError:
        body = {"error": {"message": r.text[:300]}}
    return r.status_code, body


def die(msg, body=None):
    if isinstance(body, dict) and "error" in body:
        said = str(body["error"].get("message"))
        # Meta sometimes echoes the token back in its error text - never print it
        said = re.sub(r"EA[A-Za-z0-9]{20,}", "[token hidden]", said)
        msg += f"\n  Meta said: {said}"
    sys.exit(msg)


def main():
    short = os.environ.get("META_ACCESS_TOKEN", "").strip().strip("\"'").strip()
    app_id = os.environ.get("META_APP_ID", "").strip()
    secret = os.environ.get("META_APP_SECRET", "").strip()
    if not short:
        die("META_ACCESS_TOKEN is missing from .env (paste a fresh Graph API Explorer token).")
    if short.count("EAA") > 1 or re.search(r"\s", short):
        die("META_ACCESS_TOKEN in .env looks like more than one token pasted together "
            "(or has a space in it). Replace the whole line with ONE fresh token: "
            "META_ACCESS_TOKEN=EAA... all on a single line, nothing before or after it.")
    if not app_id:
        die("META_APP_ID is missing from .env (App ID is on your app's Settings > Basic page).")
    if not secret:
        secret = getpass.getpass("App secret (input hidden): ").strip()
    if not secret:
        die("No app secret entered.")

    print("1/4 Exchanging for a long-lived user token...")
    status, body = get("oauth/access_token", {
        "grant_type": "fb_exchange_token", "client_id": app_id,
        "client_secret": secret, "fb_exchange_token": short})
    if status != 200 or "access_token" not in body:
        die("Exchange failed. The short token may have expired (they last about an hour) - "
            "generate a fresh one in Graph API Explorer and try again.", body)
    long_user = body["access_token"]

    print("2/4 Listing your Pages with the long-lived token...")
    status, body = get("me/accounts", {
        "access_token": long_user, "limit": 25,
        "fields": "id,name,access_token,instagram_business_account{id,username}"})
    if status != 200:
        die("Could not list Pages.", body)
    pages = body.get("data", [])
    if not pages:
        die("No Pages came back. Re-generate the Explorer token with business_management "
            "and run again.")
    if len(pages) == 1:
        page = pages[0]
    else:
        print("Found several Pages:")
        for i, p in enumerate(pages, 1):
            print(f"  {i}. {p.get('name')} ({p['id']})")
        page = pages[int(input("Which one (number)? ")) - 1]
    page_token = page["access_token"]

    print("3/4 Checking the Page token's expiry...")
    status, body = get("debug_token", {"input_token": page_token, "access_token": f"{app_id}|{secret}"})
    info = body.get("data", {}) if status == 200 else {}
    expires = info.get("expires_at")
    if expires == 0:
        print("   Never expires (expires_at = 0).")
    elif expires is None:
        print("   Could not read the expiry from Meta - the token may still be fine, "
              "the daily refresh will tell us.")
    else:
        print(f"   WARNING: this token expires (expires_at = {expires}). "
              "It will not last; tell Claude what you see here.")

    print("4/4 Confirming it can read the Page and Instagram account...")
    status, body = get(page["id"], {"access_token": page_token, "fields": "name,followers_count"})
    if status != 200:
        die("The Page token could not read the Page.", body)
    print(f"   Page: {body.get('name')} ({body.get('followers_count')} followers)")
    ig = page.get("instagram_business_account")
    if ig:
        status, body = get(ig["id"], {"access_token": page_token, "fields": "username,followers_count"})
        if status == 200:
            print(f"   Instagram: @{body.get('username')} ({body.get('followers_count')} followers)")
        else:
            print("   Instagram check failed (Page token OK):", body.get("error", {}).get("message"))

    with open(OUT_FILE, "w") as f:
        f.write(page_token)
    print(f"\nDone. The Page token is in {OUT_FILE}.")
    print("Next: copy its contents into a GitHub secret called META_PAGE_TOKEN, and also")
    print("put META_PAGE_TOKEN=... in your local .env. Then delete the file.")
    print(f"(Page id for reference: {page['id']}"
          + (f", Instagram id: {ig['id']}" if ig else "") + ")")


if __name__ == "__main__":
    main()
