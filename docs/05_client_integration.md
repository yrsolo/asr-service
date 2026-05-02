# Client Integration

## Desktop Client Responsibilities

The main desktop assistant should:

- capture microphone audio;
- capture system audio via WASAPI loopback;
- resample to 16 kHz mono if possible;
- send chunks to this service;
- receive transcript deltas;
- maintain rolling transcript buffer;
- run LLM structuring/advice separately.

## Recommended Audio Format

For HTTP chunk MVP:

```text
WAV PCM 16-bit mono 16 kHz
```

For WebSocket MVP:

```text
base64-encoded WAV chunks or PCM chunks
```

Future optimization: binary WebSocket frames.

For live calls, prefer `stream_mode: "phrase_endpoint"` with:

```text
pcm_s16le
16 kHz
mono
20-100 ms client chunks
```

The desktop client should resample microphone and WASAPI loopback audio before sending it.

## Source Labels

Recommended mapping:

```text
mic     -> speaker=user
system  -> speaker=other
mixed   -> speaker=unknown
unknown -> speaker=unknown
```

## Two-Session Strategy

Open two WebSocket sessions:

1. microphone session;
2. system audio session.

This avoids mixing user's voice and call audio before ASR.

## Phrase Endpointing Integration

For `sobes_assistant`, keep the ASR service as speech-to-text only. The desktop assistant
opens one live WebSocket session for `mic` and one for `system`.

Start message:

```json
{
  "type": "start",
  "stream_mode": "phrase_endpoint",
  "model_id": "fw-medium-int8",
  "language": "ru",
  "source": "system",
  "sample_rate": 16000,
  "channels": 1,
  "format": "pcm_s16le",
  "phrase_silence_ms": 700,
  "speech_start_rms": 0.012,
  "speech_continue_rms": 0.008,
  "min_speech_ms": 250,
  "pre_roll_ms": 300,
  "max_phrase_ms": 12000,
  "long_window_ms": 12000,
  "long_window_step_ms": 8000,
  "long_window_overlap_ms": 4000,
  "urgent_min_ms": 800
}
```

Client behavior:

- read `session_started.effective_config` and show/log it for diagnostics;
- send increasing `seq` values with small base64 PCM frames;
- do not schedule decode jobs client-side in `phrase_endpoint`; the server endpoints phrases;
- send `{"type": "force_decode", "reason": "urgent"}` when the UI needs a current draft before phrase end;
- apply `live_delta.updates` by `segment.id` only if the incoming `revision` is newer;
- render `draft` updates as replaceable in-work text and `final` updates as main transcript;
- use `vad_state`, `current_phrase_ms`, `decoded_windows`, and `stitch_confidence` for diagnostics;
- send `flush` before closing when the user stops transcription.

The client can run LLM summarization or advice on top of the main transcript, but not on the
raw tail unless the UI clearly marks it as unstable.

`live_revision` remains available for diagnostics and comparison. If it is used, send
`should_decode=false` for regular frames and `should_decode=true` only on decode-job frames,
and keep rendering `raw` separately from the main transcript.
