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
final | unstable
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
  "gpu_available": false
}
```

`gpu_available` is best-effort CUDA detection through CTranslate2.

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

### Client start

```json
{
  "type": "start",
  "session_id": "optional",
  "model_id": "fw-medium-int8-fp16",
  "language": "ru",
  "source": "system",
  "sample_rate": 16000,
  "channels": 1,
  "format": "pcm_s16le"
}
```

### Client audio

MVP uses base64 JSON for simplicity:

```json
{
  "type": "audio",
  "seq": 1,
  "start_ms": 0,
  "audio_b64": "base64..."
}
```

Future optimization: binary WebSocket frames.

### Server session_started

```json
{
  "type": "session_started",
  "session_id": "uuid",
  "model_id": "fw-medium-int8-fp16"
}
```

### Server transcript_delta

```json
{
  "type": "transcript_delta",
  "session_id": "uuid",
  "seq": 1,
  "segments": [],
  "unstable": []
}
```

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
