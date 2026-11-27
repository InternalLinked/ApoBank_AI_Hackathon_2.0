"""Zentrale Konfiguration. Werte koennen per Umgebungsvariable ueberschrieben werden."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


@dataclass
class Settings:
    db_path: Path = Path(os.getenv("APOBANK_DB_PATH", BASE_DIR / "data" / "apobank.db"))
    excel_path: Path = Path(os.getenv("APOBANK_EXCEL_PATH", BASE_DIR / "data" / "Musterliste_apoBank.xlsx"))
    vault_path: Path = Path(os.getenv("APOBANK_VAULT_PATH", BASE_DIR / "vault"))
    vault_name: str = os.getenv("APOBANK_VAULT_NAME", "vault")
    sql_max_rows: int = 1000
    sql_timeout_s: float = 5.0


settings = Settings()
