"""Prüft die Bedrock-Anbindung der Hackathon-Sandbox, ohne Zugangsdaten auszugeben.

1. Welche Zugangsdaten-Quelle das AWS-SDK verwendet (nur die Art, keine Werte)
2. Identität (Kontonummer maskiert)
3. Je Region: verfügbare Inferenzprofile und On-Demand-Modelle (Anthropic, Amazon Nova)
4. Rauchtest je Kandidat mit einem synthetischen Satz ("Antworte nur mit OK")
Abgelehnte Aufrufe zeigen, welche Account-Guardrails greifen.

Aufruf (aus dem Repository-Wurzelordner):
  .venv\\Scripts\\python -m backend.copilot.bedrock_check [--regionen us-west-2 us-east-1] [--modelle ID ...]
"""
from __future__ import annotations

import argparse
import sys
import time

from .einstellungen import lade_dotenv as load_dotenv

STANDARD_KANDIDATEN = (
    "us.anthropic.claude-sonnet-5-5", "global.anthropic.claude-sonnet-5-5",
    "us.anthropic.claude-haiku-5-5", "us.anthropic.claude-haiku-4-5-20251001-v1:0",
    "us.amazon.nova-lite-v1:0",
)


def _code(exc) -> str:
    err = getattr(exc, "response", {}).get("Error", {})
    return f"{err.get('Code', type(exc).__name__)}: {err.get('Message', str(exc))[:160]}"


def main(argv=None) -> int:
    load_dotenv()
    parser = argparse.ArgumentParser()
    parser.add_argument("--regionen", nargs="+", default=["us-west-2", "us-east-1"])
    parser.add_argument("--modelle", nargs="+", default=None)
    parser.add_argument("--alle", action="store_true", help="alle Kandidaten testen statt nach dem ersten Erfolg je Region aufzuhören")
    args = parser.parse_args(argv)
    try:
        import boto3
        from botocore.exceptions import BotoCoreError, ClientError
    except ImportError:
        print("boto3 fehlt. In der .venv installieren: python -m pip install -r requirements.txt")
        return 1

    session = boto3.Session()
    creds = session.get_credentials()
    if creds is None:
        print("Keine AWS-Zugangsdaten gefunden. Isolierte Datei befüllen und AWS_SHARED_CREDENTIALS_FILE in .env setzen.")
        return 1
    print(f"Zugangsdaten-Quelle: {creds.method} | temporär: {'ja' if creds.token else 'NEIN (Achtung)'}")

    try:
        ident = session.client("sts", region_name=args.regionen[0]).get_caller_identity()
        konto = ident["Account"]
        arn_teile = ident["Arn"].split(":")[-1].split("/")
        print(f"Identität OK: Konto ****{konto[-4:]} | Typ {arn_teile[0]} | Rolle {arn_teile[1] if len(arn_teile) > 1 else '-'}")
    except (ClientError, BotoCoreError) as exc:
        print(f"Identität FEHLER: {_code(exc)}")
        return 1

    funktionierend = []
    for region in args.regionen:
        print(f"\n=== Region {region} ===")
        bedrock = session.client("bedrock", region_name=region)
        profile = []
        try:
            seiten = bedrock.get_paginator("list_inference_profiles").paginate(typeEquals="SYSTEM_DEFINED")
            profile = [p["inferenceProfileId"] for s in seiten for p in s.get("inferenceProfileSummaries", [])]
            relevant = sorted(p for p in profile if "anthropic" in p or "nova" in p)
            print(f"Inferenzprofile: {len(profile)} gesamt, davon Anthropic/Nova {len(relevant)}:")
            for p in relevant:
                print(f"  - {p}")
        except (ClientError, BotoCoreError) as exc:
            print(f"Inferenzprofile: nicht lesbar ({_code(exc)})")
        try:
            modelle = bedrock.list_foundation_models(byInferenceType="ON_DEMAND", byOutputModality="TEXT")["modelSummaries"]
            relevant = sorted(m["modelId"] for m in modelle if m["providerName"] in ("Anthropic", "Amazon"))
            print(f"On-Demand-Textmodelle: {len(modelle)} gesamt; Anthropic/Amazon: {', '.join(relevant) or '-'}")
        except (ClientError, BotoCoreError) as exc:
            print(f"Foundation-Modelle: nicht lesbar ({_code(exc)})")

        laufzeit = session.client("bedrock-runtime", region_name=region)
        kandidaten = args.modelle or [k for k in STANDARD_KANDIDATEN if not profile or k in profile or k.startswith("global.")]
        for modell in kandidaten:
            start = time.perf_counter()
            try:
                resp = laufzeit.converse(modelId=modell, inferenceConfig={"maxTokens": 10},
                                         messages=[{"role": "user", "content": [{"text": "Antworte nur mit: OK"}]}])
                text = "".join(b.get("text", "") for b in resp["output"]["message"]["content"]).strip()
                ms = int((time.perf_counter() - start) * 1000)
                print(f"  OK     {modell}: „{text}“ in {ms} ms, Tokens {resp.get('usage', {}).get('totalTokens')}")
                funktionierend.append((region, modell))
                if not args.alle:
                    print("  (weitere Kandidaten übersprungen – sparsame Prüfung; mit --alle alle testen)")
                    break
            except (ClientError, BotoCoreError) as exc:
                print(f"  FEHLER {modell}: {_code(exc)}")

    print("\n=== Ergebnis ===")
    if not funktionierend:
        print("Kein Modell aufrufbar. Fehlermeldungen oben zeigen, ob Guardrails, Modellzugang oder Region die Ursache sind.")
        return 2
    region, modell = funktionierend[0]
    print(f"Empfehlung für .env:  AWS_REGION={region}  LLM_MODEL_ID={modell}  LLM_PROVIDER=bedrock")
    return 0


if __name__ == "__main__":
    sys.exit(main())
