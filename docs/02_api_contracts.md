# API Contracts

## Base URL

Default local mode:

```text
http://127.0.0.1:8765
```

LAN mode:

```text
http://<gpu-machine-ip>:8765
```

LAN mode should require firewall rules and preferably `LOCAL_ASR_API_KEY`.

Interactive OpenAPI docs are available at:

```text
http://127.0.0.1:8765/docs
```

The built-in manual test UI is available at:

```text
http://127.0.0.1:8765/
```

## Authentication

HTTP endpoints use bearer auth only when `LOCAL_ASR_API_KEY` is set:

```http
Authorization: Bearer <key>
```

The WebSocket endpoint accepts the same header from non-browser clients. Browser test clients can use:

```text
ws://127.0.0.1:8765/v1/stream?api_key=<key>
```

## Common Enums

### AudioSource

```text
mic | system | mixed | unknown
```

### Speaker

```text
user | other | unknown
```

### SegmentStatus

```text
draft | final | unstable
```

### StreamMode

```text
simple | live_revision | phrase_endpoint
```

### AdaptationMode

```text
off | silence_gate | adaptive_window | drop_stale_decode | combined
```

## TranscriptSegment

```json
{
  "id": "uuid",
  "source": "mic",
  "speaker": "user",
  "start_ms": 0,
  "end_ms": 2400,
  "text": "Нам нужно сначала зафиксировать объём.",
  "status": "final",
  "confidence": null,
  "revision": 0
}
```

`unstable` segments are temporary and may be replaced by later messages. Clients should render them separately from final text.

## GET /health

Response:

```json
{
  "status": "ok",
  "service": "local-asr-service",
  "version": "0.1.0",
  "backend": "mock",
  "default_model": "mock",
  "gpu_available": false,
  "cuda_device_index": null
}
```

`gpu_available` is best-effort CUDA detection through CTranslate2.
`cuda_device_index` is the runtime override from `LOCAL_ASR_CUDA_DEVICE_INDEX`.

## POST /shutdown

Stops the local service process. This is intended for the built-in manual UI and local Windows console runs. If `LOCAL_ASR_API_KEY` is set, the request must include the same bearer token as the other HTTP endpoints.

Response:

```json
{
  "status": "shutting_down"
}
```

## GET /v1/models

Response:

```json
{
  "default_model": "fw-medium-int8-fp16",
  "models": [
    {
      "id": "mock",
      "backend": "mock",
      "model_name": "mock",
      "device": "cpu",
      "device_index": null,
      "compute_type": "auto",
      "languages": ["ru", "en", "auto"],
      "description": "Development backend",
      "beam_size": 1,
      "vad_filter": false,
      "download": false
    }
  ]
}
```

## POST /v1/transcribe/file

Use this endpoint for complete files, manual checks, and benchmarks.

Request: `multipart/form-data`

| Field | Type | Required | Description |
|---|---|---:|---|
| `file` | file | yes | WAV, MP3, or another format supported by the active backend |
| `model_id` | string | no | model profile id; default profile is used when omitted |
| `language` | string | no | `ru`, `en`, or `auto` |
| `source` | string | no | `mic`, `system`, `mixed`, or `unknown` |

Response:

```json
{
  "request_id": "uuid",
  "model_id": "fw-medium-int8-fp16",
  "language": "ru",
  "duration_ms": 12345,
  "processing_ms": 1800,
  "segments": [],
  "text": "..."
}
```

## POST /v1/transcribe/chunk

Use this endpoint when the desktop client handles audio capture and sends short chunks.

Request: `multipart/form-data`

| Field | Type | Required | Description |
|---|---|---:|---|
| `chunk` | file | yes | short WAV/MP3/PCM container chunk |
| `session_id` | string | no | existing session id; generated when omitted |
| `seq` | integer | yes | increasing client sequence number |
| `model_id` | string | no | model profile id |
| `language` | string | no | `ru`, `en`, or `auto` |
| `source` | string | no | source label |
| `start_ms` | integer | no | original stream start timestamp |

Response:

```json
{
  "session_id": "uuid",
  "seq": 17,
  "model_id": "fw-medium-int8-fp16",
  "segments": [],
  "unstable_text": "",
  "processing_ms": 720
}
```

## WebSocket /v1/stream

Connection:

```text
ws://127.0.0.1:8765/v1/stream
```

The default mode is the existing simple pseudo-streaming contract. The live revision mode is enabled
per session with `stream_mode: "live_revision"`. For call transcription quality, prefer
`stream_mode: "phrase_endpoint"`.

### Client start

```json
{
  "type": "start",
  "session_id": "optional",
  "model_id": "fw-medium-int8-fp16",
  "stream_mode": "simple",
  "language": "ru",
  "source": "system",
  "sample_rate": 16000,
  "channels": 1,
  "format": "pcm_s16le"
}
```

### Client start for live revision mode

```json
{
  "type": "start",
  "session_id": "optional",
  "model_id": "fw-medium-int8",
  "stream_mode": "live_revision",
  "language": "ru",
  "source": "system",
  "sample_rate": 16000,
  "channels": 1,
  "format": "pcm_s16le",
  "decode_interval_ms": 1000,
  "window_ms": 8000,
  "raw_tail_ms": 1500,
  "final_lag_ms": 4000,
  "stable_confirmations": 2,
  "adaptation_mode": "off",
  "min_window_ms": 4000,
  "max_window_ms": 8000,
  "rtf_warn_threshold": 1.0,
  "rtf_slow_threshold": 1.2,
  "silence_rms_threshold": 0.01,
  "silence_min_ms": 1000
}
```

`live_revision` currently requires PCM signed 16-bit little-endian, 16 kHz, mono audio.
Use the built-in web UI live emulation to test WAV/MP3 files. Use `simple` for other
client-managed container chunks.

### Client start for phrase endpointing mode

```json
{
  "type": "start",
  "model_id": "fw-medium-int8",
  "stream_mode": "phrase_endpoint",
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

`phrase_endpoint` also requires PCM signed 16-bit little-endian, 16 kHz, mono audio. The
client sends all small frames; the server detects speech and decides when to run ASR.

### Client audio

MVP uses base64 JSON for simplicity:

```json
{
  "type": "audio",
  "seq": 1,
  "sent_seq": 1,
  "total_seq": 24,
  "start_ms": 0,
  "duration_ms": 50,
  "should_decode": false,
  "audio_b64": "base64..."
}
```

`should_decode=false` appends the frame to the rolling buffer and returns diagnostics without
running ASR. The client should set `should_decode=true` only on decode-job frames, for example
every 1000 ms while sending 50 ms input frames.

For live test silence skipping, the browser can send a lightweight event instead of PCM:

```json
{
  "type": "silence",
  "seq": 2,
  "sent_seq": 2,
  "total_seq": 24,
  "duration_ms": 1000,
  "rms": 0.004
}
```

Future optimization: binary WebSocket frames.

### Client force decode

Only `phrase_endpoint` supports urgent partial recognition:

```json
{
  "type": "force_decode",
  "seq": 42,
  "reason": "urgent"
}
```

The response is a `live_delta` with a replaceable `draft` update. A later phrase-final decode
uses the same segment id with a newer `revision`.

### Server session_started

```json
{
  "type": "session_started",
  "session_id": "uuid",
  "model_id": "fw-medium-int8-fp16",
  "effective_config": null
}
```

In `live_revision` and `phrase_endpoint` modes, `effective_config` is returned:

```json
{
  "type": "session_started",
  "session_id": "uuid",
  "model_id": "fw-medium-int8",
  "effective_config": {
    "stream_mode": "live_revision",
    "decode_interval_ms": 1000,
    "window_ms": 8000,
    "raw_tail_ms": 1500,
    "final_lag_ms": 4000,
    "stable_confirmations": 2,
    "sample_rate": 16000,
    "channels": 1,
    "format": "pcm_s16le",
    "adaptation_mode": "off",
    "min_window_ms": 4000,
    "max_window_ms": 8000,
    "rtf_warn_threshold": 1.0,
    "rtf_slow_threshold": 1.2,
    "silence_rms_threshold": 0.01,
    "silence_min_ms": 1000
  }
}
```

### Server transcript_delta

Only simple mode emits this event:

```json
{
  "type": "transcript_delta",
  "session_id": "uuid",
  "seq": 1,
  "segments": [],
  "unstable": []
}
```

### Server live_delta

`live_revision` and `phrase_endpoint` emit this event. In `phrase_endpoint`, `updates` are
phrase-level `draft` or `final` segments and `raw` is normally empty.

```json
{
  "type": "live_delta",
  "session_id": "uuid",
  "seq": 12,
  "revision": 12,
  "updates": [
    {
      "id": "live-final",
      "source": "system",
      "speaker": "other",
      "start_ms": 3000,
      "end_ms": 8600,
      "text": "then let's move the meeting",
      "status": "final",
      "confidence": null,
      "revision": 12
    },
    {
      "id": "live-draft",
      "source": "system",
      "speaker": "other",
      "start_ms": 8600,
      "end_ms": 10800,
      "text": "to Friday",
      "status": "draft",
      "confidence": null,
      "revision": 12
    }
  ],
  "raw": [
    {
      "id": "live-raw",
      "source": "system",
      "speaker": "other",
      "start_ms": 10800,
      "end_ms": 12300,
      "text": "after lunch",
      "status": "unstable",
      "confidence": null,
      "revision": 12
    }
  ],
  "stats": {
    "audio_window_ms": 8000,
    "buffered_ms": 8000,
    "decode_ms": 720,
    "lag_ms": 900,
    "audio_received_ms": 12000,
    "audio_step_ms": 50,
    "decode_interval_ms": 1000,
    "realtime_factor": 0.72,
    "window_factor": 0.09,
    "queue_chunks": 0,
    "queue_ms": 0,
    "dropped_chunks": 0,
    "silence_skipped_ms": 0,
    "effective_window_ms": 8000,
    "adaptation_action": "normal",
    "vad_state": "speech",
    "current_phrase_ms": 0,
    "phrase_id": 0,
    "decoded_windows": 0,
    "stitch_confidence": "none"
  }
}
```

Clients should apply `updates` by `id` and `revision`. The current MVP uses `live-final`
for confirmed text, `live-draft` for the replaceable working text, and `live-raw` for the
volatile tail. Empty `live-draft` text means the client should clear the working lane.
`raw` is a volatile live tail and must be rendered separately from the main transcript.

`audio_step_ms` is the duration of the last input frame. For decode jobs, 
`realtime_factor = decode_ms / decode_interval_ms`: `1.0` means realtime, `0.5` means the
decode job is twice as fast as its live budget, and `2.0` means twice too slow for realtime.
For buffered frame-only events, `decode_ms` is `0` and `realtime_factor` is not meaningful.
`window_factor = decode_ms / audio_window_ms` shows the cost of decoding the current
sliding window. `queue_chunks` and `queue_ms` are diagnostic estimates from client sequence
numbers; they show how far the UI/server are behind the sent stream.

For `phrase_endpoint`, `vad_state` is one of `silence`, `speech_candidate`, `speech`, or
`trailing_silence`. `decoded_windows` shows how many ASR windows were used for that decode.
Long phrases emit draft `live_delta` updates before phrase end: by default the service decodes
`0..12000` at 12 seconds, `8000..20000` at 20 seconds, and so on with 4 second overlap.

### Server error

```json
{
  "type": "error",
  "code": "invalid_audio",
  "message": "Could not decode audio chunk"
}
```

## Error Codes

| Code | Meaning |
|---|---|
| `invalid_audio` | audio could not be decoded |
| `model_not_found` | unknown model |
| `backend_unavailable` | backend failed |
| `gpu_unavailable` | GPU requested but unavailable |
| `bad_request` | malformed request |
| `unauthorized` | API key missing or invalid |
| `internal_error` | unexpected error |
