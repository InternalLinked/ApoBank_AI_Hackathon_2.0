"""Deterministischer, regelbasierter Ersatz für das Sprachmodell (Tests und Offline-Backup-Demo).

Nutzt dieselben Werkzeuge und dasselbe Nachrichtenformat wie ein echtes Modell, versteht aber nur die Kernabläufe
der Demo. Alle Zahlen kommen weiterhin aus SQL; Notizen nutzen das Offline-Zeilenformat (siehe notizen.parse_offline).
"""
from __future__ import annotations

import itertools
import json
import re

from ..werkzeuge import normalisiere_name
from .base import LLMResponse

_KENNZAHL_WOERTER = (("wachstum", "wachstum_kreditvolumen"), ("darlehen", "darlehen_anzahl"),
                     ("anzahl", "darlehen_anzahl"), ("volumen", "kreditvolumen"))
_BEDEUTUNG_WOERTER = (("betreuungsbeginn", "betreuungsbeginn"), ("neu", "betreuungsbeginn"),
                      ("betreut", "betreut_im_jahr"), ("aktiv", "betreut_im_jahr"),
                      ("geschaeft", "geschaeft_im_jahr"), ("taetig", "geschaeft_im_jahr"))
_ZAHLWOERTER = {"drei": 3, "fuenf": 5, "zehn": 10, "zwei": 2, "vier": 4}
_NAME = re.compile(r"(?:bei|mit|von|für|fuer|akte)\s+((?:Dr\.\s+)?[A-ZÄÖÜ][\wäöüß-]+(?:\s+[A-ZÄÖÜ][\wäöüß-]+)+)")
_ABSICHTEN = (("notiz", ("notiz", "ergaenze", "protokoll")),
              ("gespraeche", ("besprochen", "vereinbart", "letzte gespraech", "letzten gespraech")),
              ("massnahmen", ("offen", "massnahm", "ueberfaellig")),
              ("akte", ("akte", "vorbereit", "termin", "zeige", "zeig")))


def _text(message: dict) -> str:
    return " ".join(b.get("text", "") for b in message.get("content", []) if "text" in b).strip()


def _ohne_app_hinweis(text: str) -> str:
    return re.sub(r"^\[Hinweis der Anwendung:.*?\]\n", "", text, flags=re.MULTILINE)


def _jahr(t: str) -> int | None:
    m = re.search(r"\b(20\d\d)\b", t)
    return int(m.group(1)) if m else None


def _finde(t: str, woerter) -> str | None:
    return next((wert for wort, wert in woerter if wort in t), None)


def _absicht(t: str) -> str | None:
    return next((name for name, woerter in _ABSICHTEN if any(w in t for w in woerter)), None)


class FakeProvider:
    name = "fake"
    model_id = "fake-regelbasiert"

    def __init__(self):
        self._ids = itertools.count(1)

    def _tool(self, name: str, eingabe: dict) -> LLMResponse:
        return LLMResponse({"role": "assistant", "content": [
            {"toolUse": {"toolUseId": f"fake-{next(self._ids)}", "name": name, "input": eingabe}}]}, "tool_use")

    @staticmethod
    def _antwort(text: str) -> LLMResponse:
        return LLMResponse({"role": "assistant", "content": [{"text": text}]}, "end_turn")

    @staticmethod
    def _nutzertexte(messages):
        return [normalisiere_name(_ohne_app_hinweis(_text(m))) for m in messages if m["role"] == "user" and _text(m)]

    @staticmethod
    def _letzte_frage(messages) -> str:
        for m in reversed(messages[:-1]):
            if m["role"] == "assistant" and _text(m):
                return normalisiere_name(_text(m))
        return ""

    def _offene_absicht(self, messages) -> str:
        for t in reversed(self._nutzertexte(messages)):
            a = _absicht(t)
            if a:
                return a
        return "akte"

    # ------------------------------------------------------------------ Hauptlogik
    def converse(self, system: str, messages: list[dict], tools: list[dict]) -> LLMResponse:
        letzte = messages[-1]
        ergebnisse = [b["toolResult"] for b in letzte.get("content", []) if "toolResult" in b]
        if ergebnisse:
            return self._nach_werkzeug(messages, ergebnisse[-1])
        return self._planen(_ohne_app_hinweis(_text(letzte)), messages)

    def _planen(self, original: str, messages) -> LLMResponse:
        t = normalisiere_name(original)
        frage = self._letzte_frage(messages)
        erste_zeile = normalisiere_name(original.splitlines()[0]) if original.strip() else ""

        if "welchen meinen sie" in frage or "fuer welchen vermittler" in frage:
            nr = re.search(r"\b(\d{3,7})\b", t)
            if nr:
                return self._tool("aktiven_vermittler_setzen", {"vermittler_nr": int(nr.group(1))})

        if ("lege" in t and "vermittler" in t) or "neuer vermittler" in t:
            felder = {k.strip().lower(): w.strip() for k, _, w in
                      (z.partition(":") for z in re.split(r"[,\n]", original)) if _ and w.strip()}
            eingabe = {"vorname": felder.get("vorname"), "name": felder.get("name") or felder.get("nachname"),
                       "firma_filiale": felder.get("firma"), "email": felder.get("e-mail") or felder.get("email"),
                       "ort": felder.get("ort")}
            return self._tool("entwurf_vermittler", {k: v for k, v in eingabe.items() if v})

        if _absicht(erste_zeile) == "notiz" and "\n" in original:
            return self._tool("notiz_erfassen", {})

        if "beste" in t or "top" in t.split() or "nach welcher kennzahl" in frage:
            kennzahl, jahr = _finde(t, _KENNZAHL_WOERTER), _jahr(t)
            if not kennzahl or not jahr:
                return self._antwort("Nach welcher Kennzahl soll ich die besten Vermittler bewerten – Kreditvolumen, "
                                     "Anzahl Darlehen oder Wachstum des Kreditvolumens – und für welches Jahr?")
            anzahl = 3
            for text in reversed(self._nutzertexte(messages)):
                wort = next((w for w in _ZAHLWOERTER if re.search(rf"\b{w}\b", text)), None)
                zahl = re.search(r"\b(\d{1,2})\b", text)
                if zahl or wort:
                    anzahl = int(zahl.group(1)) if zahl else _ZAHLWOERTER[wort]
                    break
            return self._tool("ranking", {"kennzahl": kennzahl, "jahr": jahr, "anzahl": anzahl, "kriterium_bestaetigt": True})

        if re.search(r"\baus (dem jahr )?20\d\d\b", t) or "was bedeutet aus" in frage:
            jahr = _jahr(t) or next((_jahr(x) for x in reversed(self._nutzertexte(messages)) if _jahr(x)), None)
            eingabe = {"jahr": jahr}
            bedeutung = _finde(t, _BEDEUTUNG_WOERTER)
            if bedeutung:
                eingabe["jahr_bedeutung"] = bedeutung
            return self._tool("vermittler_filtern", eingabe)

        absicht = _absicht(t)
        name = _NAME.search(original)
        if absicht in ("gespraeche", "massnahmen", "akte"):
            if name:
                return self._tool("vermittler_suchen", {"text": name.group(1)})
            if absicht == "massnahmen":
                return self._tool("massnahmen_abfragen", {"nur_ueberfaellig": "ueberfaellig" in t})
            return self._tool("gespraeche_abrufen" if absicht == "gespraeche" else "vermittlerakte", {})

        return self._antwort("Ich kann Vermittler suchen, Akten und Termine vorbereiten, Rankings erstellen, nach Jahren "
                             "filtern, Maßnahmen und Gespräche abfragen sowie Notizen als Entwurf erfassen. "
                             "(Offline-Modus mit eingeschränktem Sprachverständnis.)")

    def _nach_werkzeug(self, messages, block) -> LLMResponse:
        aufruf = next(b["toolUse"] for b in messages[-2]["content"] if "toolUse" in b)
        erg = json.loads(block["content"][0]["text"])
        zeilen = erg.get("zeilen", [])

        if aufruf["name"] == "vermittler_suchen" and erg["art"] in ("kandidaten", "tabelle"):
            if erg["art"] == "kandidaten":
                liste = "; ".join(f"Nr. {z[0]} – {z[1]}, {z[2]}, Marktgebiet {z[3]}" for z in zeilen)
                return self._antwort(f"Ich habe {len(zeilen)} mögliche Vermittler gefunden: {liste}. "
                                     "Welchen meinen Sie? Bitte die Vermittlernummer nennen.")
            return self._tool("aktiven_vermittler_setzen", {"vermittler_nr": zeilen[0][0]})

        if aufruf["name"] == "aktiven_vermittler_setzen" and "gesetzt" in erg.get("titel", ""):
            absicht = self._offene_absicht(messages)
            if absicht == "massnahmen":
                return self._tool("massnahmen_abfragen", {})
            if absicht == "gespraeche":
                return self._tool("gespraeche_abrufen", {})
            if absicht == "notiz":
                return self._antwort("Vermittler ausgewählt. Bitte die Gesprächsnotiz jetzt erneut senden.")
            return self._tool("vermittlerakte", {})

        hinweise = " ".join(erg.get("hinweise", []))
        if erg["art"] == "kandidaten":
            liste = "; ".join(f"Nr. {z[0]} – {z[1]}, {z[2]}, Marktgebiet {z[3]}" for z in zeilen)
            return self._antwort(f"{erg['titel']} Mögliche Vermittler: {liste}. Welchen meinen Sie?")
        if erg["art"] in ("rueckfrage", "hinweis", "fehler"):
            return self._antwort(f"{erg['titel']} {hinweise}".strip())
        if erg["art"] == "entwurf":
            return self._antwort(f"{erg['titel']}. Bitte prüfen Sie den Entwurf und bestätigen oder verwerfen Sie ihn. "
                                 f"Quelle: {erg['quelle'].get('werkzeug')}, Entwurf (nicht gespeichert).")
        quelle = erg.get("quelle", {})
        return self._antwort(f"{erg['titel']}: Ergebnis siehe Darstellung. {hinweise} "
                             f"Quelle: {quelle.get('werkzeug')}, {quelle.get('datenstand', '–')}.")
