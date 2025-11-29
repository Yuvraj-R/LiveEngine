from __future__ import annotations

import base64
import os
import time
from pathlib import Path
from typing import Any, Dict

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding


WS_PATH = "/trade-api/ws/v2"


def _load_private_key(path: str | Path) -> Any:
    p = Path(path)
    if not p.exists():
        raise RuntimeError(f"Kalshi private key not found at {p}")
    with p.open("rb") as f:
        return serialization.load_pem_private_key(f.read(), password=None)


def create_ws_headers() -> Dict[str, str]:
    """
    Build Kalshi WS auth headers using env:
      - KALSHI_API_KEY_ID
      - KALSHI_PRIVATE_KEY_PATH
    """
    api_key = os.getenv("KALSHI_API_KEY_ID")
    key_path = os.getenv("KALSHI_PRIVATE_KEY_PATH", "kalshi_private_key.pem")

    if not api_key:
        raise RuntimeError("KALSHI_API_KEY_ID env var is required")

    private_key = _load_private_key(key_path)

    ts = str(int(time.time() * 1000))
    msg = ts + "GET" + WS_PATH

    sig = private_key.sign(
        msg.encode("utf-8"),
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.DIGEST_LENGTH,
        ),
        hashes.SHA256(),
    )
    sig_b64 = base64.b64encode(sig).decode("utf-8")

    return {
        "Content-Type": "application/json",
        "KALSHI-ACCESS-KEY": api_key,
        "KALSHI-ACCESS-SIGNATURE": sig_b64,
        "KALSHI-ACCESS-TIMESTAMP": ts,
    }
