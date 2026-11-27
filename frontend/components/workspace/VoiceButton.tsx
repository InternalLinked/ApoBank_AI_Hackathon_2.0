import { useEffect, useRef, useState } from "react";
import { MAX_RECORDING_SECONDS, RecorderError, startRecording, type VoiceRecorder } from "@/lib/voice-recorder";
import { Icon } from "./Icons";

type VoiceButtonProps = {
  disabled?: boolean;
  /** Schickt die Aufnahme an das Backend (Amazon Transcribe) und liefert den Text */
  onTranscribe: (pcm: Blob, sampleRate: number) => Promise<string>;
  /** Erkannter Text – wird ins Eingabefeld übernommen, nicht direkt gesendet */
  onText: (text: string) => void;
  onError: (message: string) => void;
};

type State = "idle" | "starting" | "recording" | "transcribing";

function formatSeconds(seconds: number): string {
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

export function VoiceButton({ disabled, onTranscribe, onText, onError }: VoiceButtonProps) {
  const [state, setState] = useState<State>("idle");
  const [elapsed, setElapsed] = useState(0);
  const recorder = useRef<VoiceRecorder | null>(null);
  const timer = useRef<number | null>(null);

  // Beim Verlassen der Seite/Komponente Mikrofon freigeben
  useEffect(() => () => {
    recorder.current?.cancel();
    if (timer.current) window.clearInterval(timer.current);
  }, []);

  async function stop() {
    const active = recorder.current;
    if (!active) return;
    recorder.current = null;
    if (timer.current) window.clearInterval(timer.current);
    const recording = active.stop();
    if (recording.seconds < 0.4) {
      setState("idle");
      onError("Die Aufnahme war zu kurz.");
      return;
    }
    setState("transcribing");
    try {
      const text = (await onTranscribe(recording.pcm, recording.sampleRate)).trim();
      if (text) onText(text);
      else onError("Es wurde keine Sprache erkannt.");
    } catch (error) {
      onError(error instanceof Error ? error.message : "Die Transkription ist fehlgeschlagen.");
    } finally {
      setState("idle");
    }
  }

  async function start() {
    setState("starting");
    try {
      recorder.current = await startRecording(() => { void stop(); });
      setElapsed(0);
      const startedAt = Date.now();
      timer.current = window.setInterval(() => setElapsed(Math.floor((Date.now() - startedAt) / 1000)), 250);
      setState("recording");
    } catch (error) {
      setState("idle");
      onError(error instanceof RecorderError ? error.message : "Das Mikrofon konnte nicht gestartet werden.");
    }
  }

  if (state === "recording") {
    return (
      <button type="button" className="voice-button is-recording" onClick={() => void stop()}
        aria-label={`Aufnahme beenden (${formatSeconds(elapsed)} von max. ${formatSeconds(MAX_RECORDING_SECONDS)})`} title="Aufnahme beenden">
        <span className="voice-dot" aria-hidden="true" /> {formatSeconds(elapsed)} <Icon name="stop" size={13} />
      </button>
    );
  }
  if (state === "transcribing" || state === "starting") {
    return (
      <button type="button" className="voice-button is-busy" disabled aria-label={state === "starting" ? "Mikrofon wird gestartet" : "Wird transkribiert"}>
        <span className="voice-spinner" aria-hidden="true" /> {state === "transcribing" ? "Transkribiere …" : ""}
      </button>
    );
  }
  return (
    <button type="button" className="voice-button" onClick={() => void start()} disabled={disabled}
      aria-label="Spracheingabe starten (Amazon Transcribe)" title="Spracheingabe starten">
      <Icon name="mic" size={17} />
    </button>
  );
}
