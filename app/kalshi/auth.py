"""Kalshi API request signing.

Per https://docs.kalshi.com/getting_started/api_keys (checked 2026-11-23):
- message = timestamp_ms + METHOD + path, where path is the FULL URL path
  (including /trade-api/v2) with any query string removed
- Ed25519 keys (recommended) sign the message directly
- RSA keys use RSA-PSS, SHA-256, MGF1-SHA-256, salt length = digest length
- signature is base64; headers KALSHI-ACCESS-KEY / -TIMESTAMP / -SIGNATURE
"""

from __future__ import annotations

import base64
import time
from pathlib import Path
from urllib.parse import urlsplit

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ed25519, padding, rsa
from cryptography.hazmat.primitives.serialization import load_pem_private_key

PrivateKey = ed25519.Ed25519PrivateKey | rsa.RSAPrivateKey


def load_private_key(path: Path) -> PrivateKey:
    key = load_pem_private_key(path.read_bytes(), password=None)
    if not isinstance(key, (ed25519.Ed25519PrivateKey, rsa.RSAPrivateKey)):
        raise ValueError(f"Unsupported key type {type(key).__name__}; Kalshi accepts Ed25519 or RSA")
    return key


def signing_message(timestamp_ms: int, method: str, url_or_path: str) -> str:
    path = urlsplit(url_or_path).path  # drops scheme, host and query string
    return f"{timestamp_ms}{method.upper()}{path}"


def sign(key: PrivateKey, message: str) -> str:
    data = message.encode("utf-8")
    if isinstance(key, ed25519.Ed25519PrivateKey):
        sig = key.sign(data)
    else:
        sig = key.sign(
            data,
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
            hashes.SHA256(),
        )
    return base64.b64encode(sig).decode("ascii")


def auth_headers(
    key_id: str, key: PrivateKey, method: str, url: str, timestamp_ms: int | None = None
) -> dict[str, str]:
    ts = timestamp_ms if timestamp_ms is not None else int(time.time() * 1000)
    return {
        "KALSHI-ACCESS-KEY": key_id,
        "KALSHI-ACCESS-TIMESTAMP": str(ts),
        "KALSHI-ACCESS-SIGNATURE": sign(key, signing_message(ts, method, url)),
    }
