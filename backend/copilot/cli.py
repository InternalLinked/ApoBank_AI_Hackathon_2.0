"""Terminal-Chat (Entwicklung und Backup-Demo). Entwürfe werden hier per j/n bestätigt.

Aufruf:  .venv\\Scripts\\python -m backend.copilot.cli        Befehle: /neu (neue Sitzung), /ende
"""
from __future__ import annotations

import sys

from .einstellungen import EinstellungsFehler, lade_dotenv, lade_einstellungen

lade_dotenv()

from .. import db  # noqa: E402
from ..config import settings  # noqa: E402
from .agent import Sitzung  # noqa: E402
from .entwuerfe import bestaetigen  # noqa: E402
from .llm import LLMError, get_provider  # noqa: E402


def _wert(w, spalte: str = "") -> str:
    if w is None:
        return ""
    if spalte.lower().startswith(("jahr", "vermittler-nr", "platz")):
        return str(w)
    if isinstance(w, float) and w.is_integer():
        w = int(w)
    return f"{w:,}".replace(",", ".") if isinstance(w, int) and abs(w) >= 10_000 else str(w)


def _tabelle(spalten, zeilen, breite=60) -> str:
    if not zeilen:
        return "  (keine Einträge)"
    texte = [[_wert(w, str(s))[:breite] for w, s in zip(z, spalten)] for z in zeilen]
    b = [max(len(str(s)), *(len(z[i]) for z in texte)) for i, s in enumerate(spalten)]
    return "\n".join(["  " + " | ".join(str(s).ljust(x) for s, x in zip(spalten, b)), "  " + "-+-".join("-" * x for x in b)]
                     + ["  " + " | ".join(w.ljust(x) for w, x in zip(z, b)) for z in texte])


def formatiere(erg: dict) -> str:
    teile = [f"\n[{erg['art']}] {erg['titel']}"]
    for ab in erg.get("abschnitte", []):
        teile.append(f"\n  {ab['titel']}\n" + _tabelle(ab["spalten"], ab["zeilen"]))
    if erg.get("zeilen"):
        teile.append(_tabelle(erg["spalten"], erg["zeilen"]))
    teile += [f"  Hinweis: {h}" for h in erg.get("hinweise", [])]
    q = erg.get("quelle") or {}
    if q:
        teile.append(f"  Quelle: {q.get('werkzeug')} {q.get('parameter', {})} · {q.get('datenstand')}")
    return "\n".join(teile)


def main() -> int:
    for stream in (sys.stdin, sys.stdout):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    try:
        provider = get_provider(lade_einstellungen())
    except (EinstellungsFehler, LLMError) as exc:
        print(f"Konfiguration: {exc}")
        return 1
    db.init_db()
    print(f"Vermittler-Copilot · {provider.name}/{provider.model_id} · DB {settings.db_path} · Vault {settings.vault_path}\n"
          "Befehle: /neu (neue Sitzung), /ende\n")
    s = Sitzung(provider)
    while True:
        try:
            frage = input("Sie > ").strip()
        except (EOFError, KeyboardInterrupt):
            return 0
        if frage == "/ende":
            return 0
        if frage == "/neu":
            s = Sitzung(provider)
            print("Neue Sitzung (Kurzzeitgedächtnis leer, gespeichertes Wissen bleibt).")
            continue
        if not frage:
            continue
        while frage.endswith("\\"):  # mehrzeilige Notiz: Zeile mit \ beenden
            frage = frage[:-1] + "\n" + input("    > ")
        a = s.frage(frage)
        for erg in a.ergebnisse:
            if erg["titel"] != "Aktiver Vermittler gesetzt":
                print(formatiere(erg))
        print(f"\nCopilot > {a.text}\n")
        for erg in a.ergebnisse:
            if erg["art"] == "entwurf":
                eid = erg["entwurf"]["entwurf_id"]
                if input(f"Entwurf {eid} speichern? [j/n] > ").strip().lower() == "j":
                    res = bestaetigen(s.toolbox.kontext["entwuerfe"][eid])
                    s.app_hinweis(f"Entwurf {eid} wurde vom Nutzer bestätigt ({res['status']}).")
                    print(f"  → {res}\n")
                else:
                    s.app_hinweis(f"Entwurf {eid} wurde verworfen; nichts gespeichert.")
                    print("  → verworfen, nichts gespeichert.\n")


if __name__ == "__main__":
    sys.exit(main())
