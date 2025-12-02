from __future__ import annotations

import base64
import os
import time
from pathlib import Path
from typing import Dict

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Paths / env
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[3]  # .../LiveEngine
load_dotenv(PROJECT_ROOT / ".env")

API_BASE = "https://api.elections.kalshi.com/trade-api/v2"
WS_URL = "wss://api.elections.kalshi.com/trade-api/ws/v2"

_API_KEY_ID = os.getenv("KALSHI_API_KEY_ID")
_PRIVATE_KEY = None


def _load_private_key():
    global _PRIVATE_KEY
    if _PRIVATE_KEY is None:
        key_path = PROJECT_ROOT / "kalshi_private_key.pem"
        if not key_path.exists():
            raise RuntimeError(
                f"kalshi_private_key.pem not found at {key_path}")
        with key_path.open("rb") as f:
            _PRIVATE_KEY = serialization.load_pem_private_key(
                f.read(),
                password=None,
            )
    return _PRIVATE_KEY


def _sign_pss(message: bytes) -> str:
    private_key = _load_private_key()
    signature = private_key.sign(
        message,
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.DIGEST_LENGTH,
        ),
        hashes.SHA256(),
    )
    return base64.b64encode(signature).decode("utf-8")


# ---------------------------------------------------------------------------
# REST auth headers
# ---------------------------------------------------------------------------

def build_auth_headers(
    method: str,
    route: str,
    *,
    timestamp_ms: int | None = None,
) -> Dict[str, str]:
    """
    Build Kalshi REST headers for a call to /trade-api/v2 + route.

    route examples: "/markets", "/portfolio/orders".
    """
    if not _API_KEY_ID:
        raise RuntimeError("KALSHI_API_KEY_ID missing in environment")

    if not route.startswith("/"):
        raise ValueError("route must start with '/'")

    if timestamp_ms is None:
        timestamp_ms = int(time.time() * 1000)

    method_up = method.upper()
    path_for_sig = "/trade-api/v2" + route  # what gets signed

    msg = f"{timestamp_ms}{method_up}{path_for_sig}".encode("utf-8")
    sig = _sign_pss(msg)

    return {
        "KALSHI-ACCESS-KEY": _API_KEY_ID,
        "KALSHI-ACCESS-SIGNATURE": sig,
        "KALSHI-ACCESS-TIMESTAMP": str(timestamp_ms),
        "Content-Type": "application/json",
    }


# ---------------------------------------------------------------------------
# WS auth headers (for when you hook WS up later)
# ---------------------------------------------------------------------------

def build_ws_headers() -> Dict[str, str]:
    """
    Build headers for the WebSocket endpoint /trade-api/ws/v2.
    """
    if not _API_KEY_ID:
        raise RuntimeError("KALSHI_API_KEY_ID missing in environment")

    timestamp_ms = int(time.time() * 1000)
    msg_string = f"{timestamp_ms}GET/trade-api/ws/v2"
    sig = _sign_pss(msg_string.encode("utf-8"))

    return {
        "KALSHI-ACCESS-KEY": _API_KEY_ID,
        "KALSHI-ACCESS-SIGNATURE": sig,
        "KALSHI-ACCESS-TIMESTAMP": str(timestamp_ms),
    }
