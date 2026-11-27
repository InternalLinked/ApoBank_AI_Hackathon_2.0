"""Sprache zu Text mit Amazon Transcribe Streaming.

Der Browser nimmt Mono-PCM auf (16 bit, little endian, standardmaessig 16 kHz) und schickt die Aufnahme
nach "Stopp" an `POST /api/transkription`. Von hier geht sie per HTTP/2-Stream an Transcribe; das ist
schneller als ein Batch-Job und braucht keinen S3-Bucket.

Rechte: Die ECS-Task-Rolle braucht `transcribe:StartStreamTranscription` (ohne Ressourcen-Einschraenkung,
die Aktion unterstuetzt keine). Lokal gelten die normalen AWS-Zugangsdaten (z. B. AWS_PROFILE).
Datenschutz: Das Audio geht an Transcribe in der konfigurierten Region (Standard us-west-2).
"""
from __future__ import annotations

import asyncio
import logging
import os
import time

logger = logging.getLogger("apobank.transcribe")

REGION = os.getenv("APOBANK_TRANSCRIBE_REGION") or os.getenv("AWS_REGION") or "us-west-2"
SPRACHEN = {"de-DE", "en-US", "en-GB"}
MAX_SEKUNDEN = 120
MIN_SEKUNDEN = 0.3
CHUNK_MS = 200        # Transcribe empfiehlt 50-200 ms je Audio-Event
SENDE_PAUSE_S = 0.01  # kleine Pause zwischen Events; Aufnahme ist schon fertig, also schneller als Echtzeit
TIMEOUT_S = 90


class TranskriptionsFehler(Exception):
    def __init__(self, code: str, status: int, meldung: str):
        super().__init__(meldung)
        self.code, self.status, self.meldung = code, status, meldung


def pruefe_audio(pcm: bytes, sample_rate: int, sprache: str) -> float:
    """Wirft TranskriptionsFehler bei ungueltiger Aufnahme; liefert die Dauer in Sekunden."""
    if sprache not in SPRACHEN:
        raise TranskriptionsFehler("TRANSCRIBE_SPRACHE", 422, f"Sprache {sprache} wird nicht unterstuetzt.")
    if not 8000 <= sample_rate <= 48000:
        raise TranskriptionsFehler("TRANSCRIBE_FORMAT", 422, "Ungueltige Abtastrate.")
    if len(pcm) % 2:
        raise TranskriptionsFehler("TRANSCRIBE_FORMAT", 422, "Audio ist kein 16-bit-PCM.")
    dauer = len(pcm) / (sample_rate * 2)
    if dauer < MIN_SEKUNDEN:
        raise TranskriptionsFehler("TRANSCRIBE_ZU_KURZ", 422, "Die Aufnahme ist zu kurz.")
    if dauer > MAX_SEKUNDEN + 1:
        raise TranskriptionsFehler("TRANSCRIBE_ZU_LANG", 413, f"Die Aufnahme ist laenger als {MAX_SEKUNDEN} Sekunden.")
    return dauer


def _uebersetze(exc: Exception) -> TranskriptionsFehler:
    name = type(exc).__name__
    text = str(exc)
    if any(s in name + text for s in ("AccessDenied", "UnrecognizedClient", "credentials", "Credentials", "AWS_ERROR_AUTH")):
        return TranskriptionsFehler("TRANSCRIBE_RECHTE", 503, "Keine AWS-Berechtigung fuer Transcribe "
                                    "(transcribe:StartStreamTranscription fehlt oder keine Zugangsdaten).")
    if "LimitExceeded" in name:
        return TranskriptionsFehler("TRANSCRIBE_LIMIT", 429, "Transcribe-Limit erreicht. Bitte kurz warten.")
    if "BadRequest" in name:
        return TranskriptionsFehler("TRANSCRIBE_ANFRAGE", 422, f"Transcribe hat die Aufnahme abgelehnt: {text}")
    return TranskriptionsFehler("TRANSCRIBE_FEHLER", 502, f"Transkription fehlgeschlagen ({name}).")


async def transkribieren(pcm: bytes, sample_rate: int = 16000, sprache: str = "de-DE") -> dict[str, object]:
    """PCM-Aufnahme transkribieren. Liefert {"text", "dauer_s", "verarbeitung_ms"}."""
    dauer = pruefe_audio(pcm, sample_rate, sprache)
    try:
        from amazon_transcribe.client import TranscribeStreamingClient
        from amazon_transcribe.handlers import TranscriptResultStreamHandler
    except ImportError as exc:
        raise TranskriptionsFehler("TRANSCRIBE_FEHLT", 503, "Paket amazon-transcribe ist nicht installiert.") from exc

    teile: list[str] = []

    class _Sammler(TranscriptResultStreamHandler):
        async def handle_transcript_event(self, transcript_event) -> None:  # noqa: ANN001 (SDK-Typ)
            for result in transcript_event.transcript.results:
                if not result.is_partial and result.alternatives:
                    teile.append(result.alternatives[0].transcript)

    start = time.perf_counter()
    try:
        client = TranscribeStreamingClient(region=REGION)
        stream = await client.start_stream_transcription(
            language_code=sprache, media_sample_rate_hz=sample_rate, media_encoding="pcm")

        async def senden() -> None:
            schritt = sample_rate * 2 * CHUNK_MS // 1000
            for i in range(0, len(pcm), schritt):
                await stream.input_stream.send_audio_event(audio_chunk=pcm[i:i + schritt])
                await asyncio.sleep(SENDE_PAUSE_S)
            await stream.input_stream.end_stream()

        await asyncio.wait_for(asyncio.gather(senden(), _Sammler(stream.output_stream).handle_events()), TIMEOUT_S)
    except TranskriptionsFehler:
        raise
    except asyncio.TimeoutError as exc:
        raise TranskriptionsFehler("TRANSCRIBE_TIMEOUT", 504, "Transcribe hat nicht rechtzeitig geantwortet.") from exc
    except Exception as exc:  # SDK/CRT-Fehler: in stabile Codes uebersetzen, Details ins Log
        fehler = _uebersetze(exc)
        logger.exception("Transcribe fehlgeschlagen [%s]", fehler.code)
        raise fehler from exc

    verarbeitung_ms = round((time.perf_counter() - start) * 1000)
    text = " ".join(t.strip() for t in teile if t.strip())
    logger.info("Transkription: %.1f s Audio in %d ms, %d Zeichen", dauer, verarbeitung_ms, len(text))
    return {"text": text, "dauer_s": round(dauer, 1), "verarbeitung_ms": verarbeitung_ms}
