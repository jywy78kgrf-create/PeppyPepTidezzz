"""Central configuration. Env-overridable; safe defaults for offline dev."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# repo-root/optionsdesk
ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.getenv("OPTDESK_DATA", ROOT / "data"))
CHAINS_DIR = DATA_DIR / "chains"
UNIVERSE_DIR = DATA_DIR / "universe"
STATE_DIR = Path(os.getenv("OPTDESK_STATE", ROOT / ".state"))
STATE_DIR.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True)
class Settings:
    alpha_vantage_key: str = os.getenv("ALPHAVANTAGE_API_KEY", "")
    alpha_vantage_premium: bool = os.getenv("ALPHAVANTAGE_PREMIUM", "1") == "1"
    risk_free_apr: float = float(os.getenv("OPTDESK_RFR", "0.045"))
    starting_capital: float = float(os.getenv("OPTDESK_CAPITAL", "100000"))
    # IBKR
    ibkr_host: str = os.getenv("IBKR_HOST", "127.0.0.1")
    ibkr_port: int = int(os.getenv("IBKR_PORT", "7497"))  # 7497 paper, 7496 live
    ibkr_client_id: int = int(os.getenv("IBKR_CLIENT_ID", "11"))
    live_trading_enabled: bool = os.getenv("OPTDESK_LIVE", "0") == "1"


SETTINGS = Settings()
