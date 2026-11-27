/**
 * Mikrofonaufnahme als 16-bit-PCM (mono, 16 kHz) – das Format, das Amazon Transcribe Streaming erwartet.
 * Ohne Zusatzbibliothek: Web Audio API, bei Bedarf wird auf 16 kHz heruntergerechnet.
 *
 * Browser geben das Mikrofon nur in sicheren Kontexten frei (HTTPS oder localhost).
 */

export const TARGET_SAMPLE_RATE = 16_000;
export const MAX_RECORDING_SECONDS = 120;

export class RecorderError extends Error {
  constructor(message: string, readonly code: "UNSICHER" | "NICHT_UNTERSTUETZT" | "VERWEIGERT" | "KEIN_MIKROFON" | "FEHLER") {
    super(message);
    this.name = "RecorderError";
  }
}

export type Recording = { pcm: Blob; sampleRate: number; seconds: number };

export type VoiceRecorder = {
  /** Beendet die Aufnahme und liefert das PCM-Audio */
  stop(): Recording;
  /** Bricht ab, ohne etwas zu liefern */
  cancel(): void;
};

function downsample(input: Float32Array, fromRate: number, toRate: number): Float32Array {
  if (fromRate === toRate) return input;
  const ratio = fromRate / toRate;
  const length = Math.floor(input.length / ratio);
  const output = new Float32Array(length);
  for (let i = 0; i < length; i++) {
    // Mittelwert über das Quellintervall – einfacher Tiefpass gegen Aliasing
    const start = Math.floor(i * ratio);
    const end = Math.min(input.length, Math.floor((i + 1) * ratio));
    let sum = 0;
    for (let j = start; j < end; j++) sum += input[j];
    output[i] = end > start ? sum / (end - start) : input[start] ?? 0;
  }
  return output;
}

function toPcm16(samples: Float32Array): ArrayBuffer {
  const buffer = new ArrayBuffer(samples.length * 2);
  const view = new DataView(buffer);
  for (let i = 0; i < samples.length; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true); // little endian
  }
  return buffer;
}

export async function startRecording(onLimitReached: () => void): Promise<VoiceRecorder> {
  if (typeof window === "undefined") throw new RecorderError("Aufnahme nur im Browser möglich.", "NICHT_UNTERSTUETZT");
  if (!window.isSecureContext) {
    throw new RecorderError("Das Mikrofon funktioniert nur über HTTPS (oder lokal über localhost).", "UNSICHER");
  }
  if (!navigator.mediaDevices?.getUserMedia) {
    throw new RecorderError("Dieser Browser unterstützt keine Mikrofonaufnahme.", "NICHT_UNTERSTUETZT");
  }

  let stream: MediaStream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true } });
  } catch (error) {
    const name = error instanceof DOMException ? error.name : "";
    if (name === "NotAllowedError" || name === "SecurityError") throw new RecorderError("Mikrofonzugriff wurde verweigert. Bitte im Browser erlauben.", "VERWEIGERT");
    if (name === "NotFoundError") throw new RecorderError("Kein Mikrofon gefunden.", "KEIN_MIKROFON");
    throw new RecorderError("Mikrofon konnte nicht gestartet werden.", "FEHLER");
  }

  const AudioCtx = window.AudioContext ?? (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
  let context: AudioContext;
  try {
    context = new AudioCtx({ sampleRate: TARGET_SAMPLE_RATE }); // Chrome/Firefox rechnen selbst um
  } catch {
    context = new AudioCtx(); // Safari: native Rate, wir rechnen unten herunter
  }
  const source = context.createMediaStreamSource(stream);
  // ScriptProcessor ist veraltet, aber überall verfügbar und braucht keine separate Worklet-Datei.
  const processor = context.createScriptProcessor(4096, 1, 1);
  const chunks: Float32Array[] = [];
  let samples = 0;
  let stopped = false;
  const maxSamples = context.sampleRate * MAX_RECORDING_SECONDS;

  processor.onaudioprocess = (event) => {
    if (stopped) return;
    const data = event.inputBuffer.getChannelData(0);
    chunks.push(new Float32Array(data));
    samples += data.length;
    if (samples >= maxSamples) onLimitReached();
  };
  source.connect(processor);
  processor.connect(context.destination); // nötig, damit onaudioprocess feuert (Ausgang bleibt stumm)

  function cleanup() {
    stopped = true;
    processor.disconnect();
    source.disconnect();
    stream.getTracks().forEach((track) => track.stop());
    void context.close();
  }

  return {
    stop() {
      cleanup();
      const merged = new Float32Array(samples);
      let offset = 0;
      for (const chunk of chunks) { merged.set(chunk, offset); offset += chunk.length; }
      const resampled = downsample(merged, context.sampleRate, TARGET_SAMPLE_RATE);
      return {
        pcm: new Blob([toPcm16(resampled)], { type: "application/octet-stream" }),
        sampleRate: TARGET_SAMPLE_RATE,
        seconds: resampled.length / TARGET_SAMPLE_RATE,
      };
    },
    cancel() {
      cleanup();
    },
  };
}
