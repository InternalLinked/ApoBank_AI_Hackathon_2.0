import pytest

from backend import modellwahl
from backend.config import settings


@pytest.mark.parametrize("text, stufe", [
    ("hallo", "smalltalk"), ("Hallo!", "smalltalk"), ("danke dir", "smalltalk"), ("Guten Morgen :)", "smalltalk"),
    ("Ok", "smalltalk"), ("wer bist du?", "smalltalk"),
    ("Hallo, wer ist der Top-Vermittler 2025?", "analyse"),       # Begruessung + Frage -> nicht smalltalk
    ("Welche Filiale hat das meiste Volumen?", "analyse"),
    ("Wie viele Vermittler sind aktiv?", "analyse"),
    ("Ändere die E-Mail von Jens Weber auf j@x.de", "aendern"),
    ("Die Telefonnummer von Scholz ist falsch", "aendern"),
    ("Ändere das Volumen 2025 auf 11 Mio", "aendern"),             # Aendern hat Vorrang vor Zahlen
    ("Zeig mir die Partnerakte von Jens Weber", "standard"),
    ("Jens Weber hat einen Hund namens Tim", "standard"),
    ("hallo 4251", "standard"),                                    # Zahl -> kein Smalltalk
])
def test_stufen(text, stufe):
    assert modellwahl.waehle(text).stufe == stufe


def test_modelle_und_analyse_agent(monkeypatch):
    monkeypatch.setattr(settings, "openai_model", "gpt-5-mini")
    hallo = modellwahl.waehle("Hallo")
    assert (hallo.modell, hallo.denkaufwand, hallo.analyse_agent) == (modellwahl.MODELL_SCHNELL, "minimal", False)
    zahlen = modellwahl.waehle("Top 10 Vermittler nach Volumen")
    assert (zahlen.modell, zahlen.analyse_agent) == ("gpt-5-mini", True)
    assert modellwahl.waehle("Zeig mir Jens Weber").analyse_agent is False


def test_reasoning_nur_fuer_reasoning_modelle():
    assert modellwahl.Modellwahl("standard", "gpt-5-mini", "low", False, "").reasoning() == {"effort": "low"}
    assert modellwahl.Modellwahl("standard", "gpt-4.1-mini", "low", False, "").reasoning() is None
