"""Team-API (backend.main) plus Copilot-Endpunkte – ohne backend/main.py zu verändern.

Start:  .venv\\Scripts\\python -m uvicorn backend.copilot.app:app --reload
Alternativ kann das Backend-Team in backend/main.py eine Zeile ergänzen:
    from .copilot.router import router as copilot_router; app.include_router(copilot_router)
"""
from __future__ import annotations

from .einstellungen import lade_dotenv

lade_dotenv()  # vor dem Import der Team-Konfiguration, damit APOBANK_*-Pfade aus .env greifen

from ..main import app  # noqa: E402
from .router import router  # noqa: E402

app.include_router(router)
