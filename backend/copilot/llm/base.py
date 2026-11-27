"""Neutrale Schnittstelle zwischen Agent und Sprachmodell.

Nachrichtenformat (anbieterneutral, angelehnt an die Bedrock-Converse-API):
  {"role": "user" | "assistant", "content": [ {"text": ...} | {"toolUse": {...}} | {"toolResult": {...}} ]}
  toolUse:    {"toolUseId": str, "name": str, "input": dict}
  toolResult: {"toolUseId": str, "content": [{"text": json-string}], "status": "success" | "error"}
Werkzeugbeschreibung: {"name": str, "description": str, "input_schema": JSON-Schema}
Andere Anbieter (Anthropic-API, OpenAI, lokal) übersetzen dieses Format in ihrem Adapter.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


class LLMError(RuntimeError):
    """Fehler beim Modellaufruf (Zugriff, Kontingent, Zeitüberschreitung, Konfiguration)."""


@dataclass
class LLMResponse:
    message: dict
    stop_reason: str
    usage: dict = field(default_factory=dict)


class LLMProvider(Protocol):
    name: str
    model_id: str

    def converse(self, system: str, messages: list[dict], tools: list[dict]) -> LLMResponse:
        ...
