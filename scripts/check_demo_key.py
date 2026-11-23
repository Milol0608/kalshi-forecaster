"""Check the demo API key works with one read-only call: GET /portfolio/balance.

Never prints the key ID, the private key, or the request headers.
Run: uv run python -m scripts.check_demo_key
"""

from __future__ import annotations

import sys

import httpx

from app.config import Settings
from app.kalshi.auth import auth_headers, load_private_key


def main() -> int:
    s = Settings()
    if not s.kalshi_demo_key_id or s.kalshi_demo_private_key_path is None:
        print("KALSHI_DEMO_KEY_ID or KALSHI_DEMO_PRIVATE_KEY_PATH is missing from .env")
        return 1

    url = s.kalshi_demo_base_url.rstrip("/") + "/portfolio/balance"
    key = load_private_key(s.kalshi_demo_private_key_path)
    resp = httpx.get(url, headers=auth_headers(s.kalshi_demo_key_id.strip(), key, "GET", url), timeout=20)

    print(f"GET {url} -> HTTP {resp.status_code}")
    if resp.status_code != 200:
        print("Response:", resp.text[:500])
        return 1
    body = resp.json()
    # Kalshi reports balance in cents.
    print("Demo balance: $%.2f" % (body.get("balance", 0) / 100), "| fields:", sorted(body))
    return 0


if __name__ == "__main__":
    sys.exit(main())
