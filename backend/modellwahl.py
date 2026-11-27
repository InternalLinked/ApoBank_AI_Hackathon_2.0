"""Automatische Modellwahl je Nachricht – ohne eigenen KI-Aufruf (Regeln, < 1 ms).

Stufen:
  smalltalk  "Hallo", "Danke", "Guten Morgen"           -> schnelles Modell, kaum Nachdenken, kein Analyse-Agent
  analyse    "Top 10 nach Volumen", "Vergleich Nord/Sued" -> Standardmodell, Analyse-Agent parallel
  aendern    "Aendere die E-Mail von ...", "Fuege Jagen als Interesse hinzu", "Weber hat einen Hund"
                                                          -> Standardmodell, sorgfaeltiger (Vorschlag muss stimmen)
  standard   alles andere (Partnerakte, Notizen, Fragen)  -> Standardmodell, wenig Nachdenken

Modelle per Umgebungsvariable:
  OPENAI_MODEL_FAST   (Standard gpt-5-nano)  fuer smalltalk
  OPENAI_MODEL        (Standard gpt-5-mini)  fuer alles andere
  OPENAI_ANALYSE_MODEL                       fuer den parallelen Analyse-Agenten
Ist das schnelle Modell fuer den Key nicht verfuegbar, faellt der Copilot automatisch aufs Standardmodell zurueck.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass

from .config import settings

MODELL_SCHNELL = os.getenv("OPENAI_MODEL_FAST") or "gpt-5-nano"

_SMALLTALK = re.compile(
    r"^\s*(hallo|hallöchen|hi|hey|moin|servus|grüß gott|guten (morgen|tag|abend)|na|"
    r"danke( dir| schön| sehr)?|vielen dank|merci|thx|ok(ay)?|alles klar|super|top|prima|perfekt|"
    r"tschüss|ciao|bis später|bis dann|wer bist du|was kannst du( alles)?|hilfe)\b[\s!?.,:)]*\w{0,12}[\s!?.,:)]*$",
    re.IGNORECASE,
)
_ANALYSE = re.compile(
    r"\b(top|beste[nrs]?|größte[nrs]?|höchste[nrs]?|meiste[nrs]?|wenigste[nrs]?|schlechteste[nrs]?|"
    r"ranking|rangliste|summe|gesamt|insgesamt|durchschnitt\w*|schnitt|median|anteil|prozent|quote|"
    r"vergleich\w*|vergleiche|entwicklung|wachstum|gewachsen|trend|verlauf|statistik|auswertung|analyse|"
    r"diagramm|grafik|chart|wie viele|wieviele|anzahl|volumen|kreditvolumen|umsatz|pro (jahr|filiale|region|marktgebiet))\b",
    re.IGNORECASE,
)
_AENDERN = re.compile(
    r"\b(änder\w*|aender\w*|korrigier\w*|aktualisier\w*|update|berichtig\w*|ersetz\w*|"
    r"lösch\w*|loesch\w*|entfern\w*|setz\w* .* (auf|zu)|trag\w* .* ein|neue (e-?mail|adresse|telefon\w*|nummer)|"
    r"stimmt nicht|ist falsch|falsch hinterlegt|"
    r"hinzufüg\w*|hinzu|ergänz\w*|ergaenz\w*|eintrag\w*|notier\w*|vermerk\w*|speicher\w*|merk dir|"
    r"hat (einen|eine|ein|zwei|drei)\b|war (gerade |im |in |auf )|plant\b)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Modellwahl:
    stufe: str                 # smalltalk | analyse | aendern | standard
    modell: str
    denkaufwand: str           # reasoning effort: minimal | low | medium
    analyse_agent: bool        # parallelen SQL-Agenten starten?
    grund: str

    def reasoning(self) -> dict[str, str] | None:
        """Nur Reasoning-Modelle (gpt-5*, o*) kennen den Parameter; andere wuerden 400 liefern."""
        return {"effort": self.denkaufwand} if unterstuetzt_reasoning(self.modell) else None

    def als_dict(self) -> dict[str, str]:
        return {"stufe": self.stufe, "modell": self.modell, "denkaufwand": self.denkaufwand}


def unterstuetzt_reasoning(modell: str) -> bool:
    return modell.startswith(("gpt-5", "o1", "o3", "o4"))


def waehle(nachricht: str) -> Modellwahl:
    text = " ".join(nachricht.split())
    standard = settings.openai_model
    if len(text) <= 60 and _SMALLTALK.match(text) and not re.search(r"\d", text):
        return Modellwahl("smalltalk", MODELL_SCHNELL, "minimal", False, "kurze Begruessung/Dank")
    if _AENDERN.search(text):
        return Modellwahl("aendern", standard, "medium", False, "Aenderungswunsch erkannt")
    if _ANALYSE.search(text):
        return Modellwahl("analyse", standard, "low", True, "Zahlen-/Auswertungsfrage erkannt")
    return Modellwahl("standard", standard, "low", False, "allgemeine Frage")
