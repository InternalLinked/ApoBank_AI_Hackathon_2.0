"""Macht Vermittlernamen in Copilot-Antworten klickbar.

Jeder vollstaendige Name eines Vermittlers aus der Datenbank ("Jens Weber", "Dr. Hans Baumann")
wird zu einem Markdown-Link `[Jens Weber](partner:1060)`. Das Frontend oeffnet bei Klick die
Partnerakte. Deterministisch im Backend statt per Prompt: das Modell kann keine falsche Nummer
verlinken, und es klappt auch in Antworten ohne KI (Datenbank-Fallback).

Mehrdeutige Namen (mehrere Vermittler gleichen Namens) werden nur verlinkt, wenn genau einer
davon in dieser Antwort von einem Werkzeug geliefert wurde (`bevorzugt`); sonst bleiben sie Text.
"""
from __future__ import annotations

import re
import sqlite3
import threading
from typing import Iterable

PROTOKOLL = "partner:"

# Bereiche, in denen nichts ersetzt wird: vorhandene Links, Inline-Code, nackte URLs.
_GESCHUETZT_RE = re.compile(r"\[[^\]\n]*\]\([^)\s]*\)|`[^`\n]*`|(?:https?|obsidian|mailto|tel):[^\s)\]]+")

_cache_lock = threading.Lock()
_cache: dict[str, object] = {"schluessel": None, "regex": None, "namen": {}}


def _index(conn: sqlite3.Connection) -> tuple[re.Pattern[str] | None, dict[str, set[int]]]:
    """Regex ueber alle Vermittlernamen + Zuordnung Name -> Nummern. Wird nur bei DB-Aenderung neu gebaut."""
    schluessel = tuple(conn.execute("SELECT COUNT(*), MAX(geaendert_am), MAX(vermittler_nr) FROM vermittler").fetchone())
    with _cache_lock:
        if _cache["schluessel"] == schluessel:
            return _cache["regex"], _cache["namen"]  # type: ignore[return-value]
    namen: dict[str, set[int]] = {}
    for nr, titel, vorname, name in conn.execute("SELECT vermittler_nr, titel, vorname, name FROM vermittler"):
        voll = " ".join(p.strip() for p in (vorname or "", name or "") if p and p.strip())
        if " " not in voll:  # nur Vor- UND Nachname, einzelne Woerter sind zu mehrdeutig
            continue
        varianten = {voll}
        if titel and titel.strip():
            varianten.add(f"{titel.strip()} {voll}")
        for v in varianten:
            namen.setdefault(v, set()).add(int(nr))
    # Laengste Namen zuerst, damit "Dr. Hans Baumann" vor "Hans Baumann" greift
    teile = sorted(namen, key=len, reverse=True)
    regex = re.compile(r"(?<![\w.])(" + "|".join(re.escape(t) for t in teile) + r")(?!\w)") if teile else None
    with _cache_lock:
        _cache.update(schluessel=schluessel, regex=regex, namen=namen)
    return regex, namen


def verlinke(conn: sqlite3.Connection, text: str, bevorzugt: Iterable[int | None] = ()) -> str:
    """Ersetzt Vermittlernamen im Markdown-Text durch `[Name](partner:<nr>)`."""
    if not text:
        return text
    regex, namen = _index(conn)
    if regex is None:
        return text
    bevorzugt_set = {int(nr) for nr in bevorzugt if nr is not None}

    def ersetzen(m: re.Match[str]) -> str:
        nrs = namen.get(m.group(1), set())
        if len(nrs) > 1:
            nrs = nrs & bevorzugt_set
        if len(nrs) != 1:
            return m.group(0)
        return f"[{m.group(1)}]({PROTOKOLL}{next(iter(nrs))})"

    teile: list[str] = []
    pos = 0
    for g in _GESCHUETZT_RE.finditer(text):
        teile.append(regex.sub(ersetzen, text[pos:g.start()]))
        teile.append(g.group(0))
        pos = g.end()
    teile.append(regex.sub(ersetzen, text[pos:]))
    return "".join(teile)


def nummern_in(wert: object) -> set[int]:
    """Sammelt alle `vermittler_nr`-Werte aus einem Werkzeug-Ergebnis (auch aus SQL-Tabellen)."""
    gefunden: set[int] = set()

    def walk(x: object) -> None:
        if isinstance(x, dict):
            spalten = x.get("spalten")
            if isinstance(spalten, list) and "vermittler_nr" in spalten and isinstance(x.get("zeilen"), list):
                i = spalten.index("vermittler_nr")
                for zeile in x["zeilen"]:
                    if isinstance(zeile, (list, tuple)) and len(zeile) > i and isinstance(zeile[i], int):
                        gefunden.add(zeile[i])
            for k, v in x.items():
                if k == "vermittler_nr" and isinstance(v, int):
                    gefunden.add(v)
                else:
                    walk(v)
        elif isinstance(x, (list, tuple)):
            for v in x:
                walk(v)

    walk(wert)
    return gefunden
