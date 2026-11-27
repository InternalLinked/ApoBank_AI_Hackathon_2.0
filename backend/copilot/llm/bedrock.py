"""Amazon-Bedrock-Adapter über die modellübergreifende Converse-API (mit Tool-Use).

Zugangsdaten kommen ausschließlich aus der Standard-Kette des AWS-SDK, in diesem Projekt aus der isolierten
Datei, auf die AWS_SHARED_CREDENTIALS_FILE in der lokalen .env zeigt. Hier werden keine Zugangsdaten
gelesen, gespeichert oder ausgegeben.
"""
from __future__ import annotations

import time

from .base import LLMError, LLMResponse


class BedrockProvider:
    name = "bedrock"

    def __init__(self, model_id: str, region: str, max_tokens: int = 1500):
        try:
            import boto3
            from botocore.config import Config
        except ImportError as exc:  # pragma: no cover - abhängig von Installation
            raise LLMError("boto3 ist nicht installiert (.venv: python -m pip install -r requirements.txt).") from exc
        self.model_id = model_id
        self.region = region
        self.max_tokens = max_tokens
        self._client = boto3.client("bedrock-runtime", region_name=region,
                                    config=Config(read_timeout=90, retries={"max_attempts": 3, "mode": "standard"}))

    def converse(self, system: str, messages: list[dict], tools: list[dict]) -> LLMResponse:
        from botocore.exceptions import BotoCoreError, ClientError

        kwargs = {
            "modelId": self.model_id,
            "system": [{"text": system}],
            "messages": messages,
            "inferenceConfig": {"maxTokens": self.max_tokens},
        }
        if tools:
            kwargs["toolConfig"] = {"tools": [
                {"toolSpec": {"name": t["name"], "description": t["description"],
                              "inputSchema": {"json": t["input_schema"]}}} for t in tools]}
        start = time.perf_counter()
        try:
            resp = self._client.converse(**kwargs)
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "ClientError")
            msg = exc.response.get("Error", {}).get("Message", "")
            raise LLMError(f"Bedrock {code}: {msg}") from exc
        except BotoCoreError as exc:
            raise LLMError(f"Bedrock nicht erreichbar: {exc}") from exc
        usage = dict(resp.get("usage", {}))
        usage["latenz_ms"] = int((time.perf_counter() - start) * 1000)
        return LLMResponse(message=resp["output"]["message"], stop_reason=resp.get("stopReason", ""), usage=usage)
