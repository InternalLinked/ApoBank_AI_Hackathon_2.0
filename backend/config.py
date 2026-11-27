"""Zentrale Konfiguration. Werte koennen per Umgebungsvariable ueberschrieben werden."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
# .env.local (geheime Schluessel, gitignored) zuerst laden: load_dotenv ueberschreibt nichts,
# daher gewinnt .env.local vor .env. Echte Umgebungsvariablen gewinnen vor beiden.
load_dotenv(BASE_DIR / ".env.local")
load_dotenv(BASE_DIR / ".env")


@dataclass
class Settings:
    db_path: Path = Path(os.getenv("APOBANK_DB_PATH", BASE_DIR / "data" / "apobank.db"))
    excel_path: Path = Path(os.getenv("APOBANK_EXCEL_PATH", BASE_DIR / "data" / "Musterliste_apoBank.xlsx"))
    vault_path: Path = Path(os.getenv("APOBANK_VAULT_PATH", BASE_DIR / "Obsidian" / "hackathon"))
    vault_name: str = os.getenv("APOBANK_VAULT_NAME", "hackathon")
    upload_path: Path = Path(os.getenv("APOBANK_UPLOAD_PATH", BASE_DIR / "data" / "uploads"))
    openai_api_key: str | None = os.getenv("OPENAI_API_KEY")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-5-mini")
    openai_timeout_s: float = float(os.getenv("OPENAI_TIMEOUT_S", "45"))
    cors_origins: tuple[str, ...] = tuple(
        origin.strip()
        for origin in os.getenv("APOBANK_CORS_ORIGINS", "http://127.0.0.1:3000,http://localhost:3000").split(",")
        if origin.strip()
    )
    sql_max_rows: int = 1000
    sql_timeout_s: float = 5.0


settings = Settings()
