from __future__ import annotations

import base64

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ed25519, padding, rsa

from app.kalshi.auth import auth_headers, signing_message


def test_message_uses_full_path_and_drops_query() -> None:
    url = "https://external-api.demo.kalshi.co/trade-api/v2/markets?limit=5&cursor=abc"
    assert signing_message(1700000000000, "get", url) == "1700000000000GET/trade-api/v2/markets"


def test_ed25519_signature_verifies() -> None:
    key = ed25519.Ed25519PrivateKey.generate()
    url = "https://external-api.demo.kalshi.co/trade-api/v2/portfolio/balance"
    h = auth_headers("kid", key, "GET", url, timestamp_ms=123)
    assert h["KALSHI-ACCESS-KEY"] == "kid" and h["KALSHI-ACCESS-TIMESTAMP"] == "123"
    key.public_key().verify(
        base64.b64decode(h["KALSHI-ACCESS-SIGNATURE"]), b"123GET/trade-api/v2/portfolio/balance"
    )


def test_rsa_pss_signature_verifies() -> None:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    h = auth_headers("kid", key, "POST", "/trade-api/v2/portfolio/orders", timestamp_ms=5)
    key.public_key().verify(
        base64.b64decode(h["KALSHI-ACCESS-SIGNATURE"]),
        b"5POST/trade-api/v2/portfolio/orders",
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
        hashes.SHA256(),
    )
