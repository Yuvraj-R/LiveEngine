# src/connectors/kalshi/auth.py

from __future__ import annotations

import base64
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[3]  # .../LiveEngine
ENV_PATH = PROJECT_ROOT / ".env"
PRIVATE_KEY_PATH = PROJECT_ROOT / "kalshi_private_key.pem"


@dataclass
class KalshiAuth:
    api_key_id: str
    private_key_path: Path

    @classmethod
    def from_env(cls) -> "KalshiAuth":
        if ENV_PATH.exists():
            load_dotenv(ENV_PATH)

        api_key_id = os.getenv("KALSHI_API_KEY_ID")
        if not api_key_id:
            raise RuntimeError("KALSHI_API_KEY_ID must be set in .env")

        return cls(api_key_id=api_key_id, private_key_path=PRIVATE_KEY_PATH)

    def _load_private_key(self):
        if not self.private_key_path.exists():
            raise RuntimeError(
                f"Kalshi private key not found at {self.private_key_path}")
        with self.private_key_path.open("rb") as f:
            return serialization.load_pem_private_key(f.read(), password=None)

    def _sign_pss(self, text: str) -> str:
        priv = self._load_private_key()
        message = text.encode("utf-8")
        signature = priv.sign(
            message,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.DIGEST_LENGTH,
            ),
            hashes.SHA256(),
        )
        return base64.b64encode(signature).decode("utf-8")

    def build_ws_headers(self) -> Dict[str, str]:
        """
        Headers for Kalshi WS:
          timestamp + "GET" + "/trade-api/ws/v2"
        """
        timestamp = str(int(time.time() * 1000))
        msg = timestamp + "GET" + "/trade-api/ws/v2"
        sig = self._sign_pss(msg)

        return {
            "Content-Type": "application/json",
            "KALSHI-ACCESS-KEY": self.api_key_id,
            "KALSHI-ACCESS-SIGNATURE": sig,
            "KALSHI-ACCESS-TIMESTAMP": timestamp,
        }
