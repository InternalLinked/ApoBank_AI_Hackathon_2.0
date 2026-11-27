"""Austauschbare Modellanbindung. Neue Anbieter implementieren `LLMProvider` (siehe base.py)."""
from __future__ import annotations

from ..einstellungen import Einstellungen
from .base import LLMError, LLMProvider, LLMResponse


def get_provider(e: Einstellungen) -> LLMProvider:
    if e.llm_provider == "fake":
        from .fake import FakeProvider
        return FakeProvider()
    if e.llm_provider == "bedrock":
        from .bedrock import BedrockProvider
        return BedrockProvider(model_id=e.llm_model_id, region=e.aws_region)
    raise LLMError(f"Unbekannter LLM_PROVIDER: {e.llm_provider}")


__all__ = ["LLMError", "LLMProvider", "LLMResponse", "get_provider"]
