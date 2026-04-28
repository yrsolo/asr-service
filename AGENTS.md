# AGENTS.md

## Project

Standalone Local ASR Service for Meeting Copilot.

The service runs on a separate GPU machine, for example a Windows/Linux PC with NVIDIA GTX 1080 Ti 11 GB, and exposes HTTP/WebSocket APIs to the main desktop assistant.

Its responsibility is speech-to-text only:

- receive audio files or chunks;
- run local ASR;
- return raw transcript segments;
- separate final and unstable transcript parts;
- preserve source labels such as `mic` and `system`;
- optionally produce light cleaned transcript blocks later.

It must not generate negotiation advice, answer questions, or control the desktop UI.

## Target Stack

Use:

- Python 3.11+
- FastAPI
- Uvicorn
- Pydantic v2
- faster-whisper as first real backend
- mock backend for tests
- optional whisper.cpp backend later
- pytest for tests

## MVP Scope

Implement:

1. `GET /health`
2. `GET /v1/models`
3. `POST /v1/transcribe/file`
4. `POST /v1/transcribe/chunk`
5. `WebSocket /v1/stream`
6. typed Pydantic contracts
7. model profile config
8. mock backend
9. faster-whisper backend
10. benchmark script

Do not implement audio capture in this repository. The desktop client captures microphone and WASAPI/system audio and sends chunks to this service.

## Privacy Rules

- Do not save raw audio by default.
- Do not save transcripts by default.
- Do not log full transcript text unless explicit debug mode is enabled.
- Default bind address must be `127.0.0.1`.
- If LAN binding is enabled, use firewall rules and optional API key.
- Never commit `.env`.

## Streaming Rule

Use pseudo-streaming first:

```text
client sends small audio chunks
↓
service transcribes chunks/windows
↓
service emits final segments and unstable tail
```

The client must treat `unstable` as temporary text that may be rewritten.

## Development Order

1. API skeleton.
2. Config and schemas.
3. Mock backend.
4. `/health` and `/v1/models`.
5. `/v1/transcribe/file`.
6. faster-whisper backend.
7. `/v1/transcribe/chunk`.
8. WebSocket `/v1/stream`.
9. Stabilization improvements.
10. Benchmarks.

## Contract Rule

If API fields change, update all of these:

- `docs/02_api_contracts.md`
- `src/local_asr_service/schemas.py`
- tests
- examples
