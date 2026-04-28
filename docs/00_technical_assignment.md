# Technical Assignment: Local ASR Service

## Purpose

Create a standalone speech-to-text service for Meeting Copilot.

The service runs on a GPU machine and receives audio from the main desktop app. It returns transcript segments that can later be structured into Markdown or used by LLM-based assistants.

## Why Separate Service

Separate ASR service allows:

- using a dedicated GPU;
- testing several ASR models independently;
- keeping the desktop app responsive;
- avoiding cloud transcription costs;
- preserving privacy by processing audio locally.

## Target Hardware

Initial target:

- NVIDIA GTX 1080 Ti, 11 GB VRAM;
- Windows 11 or Linux;
- CUDA runtime if using faster-whisper/CTranslate2 on GPU.

## Main Flow

```text
Desktop assistant captures mic/system audio
↓
sends audio chunks to Local ASR Service
↓
service transcribes audio
↓
service returns raw/final/unstable transcript segments
↓
main assistant structures transcript and generates suggestions
```

## MVP Features

1. HTTP API for file and chunk transcription.
2. WebSocket API for pseudo-streaming.
3. Model profile system.
4. Mock backend.
5. faster-whisper backend.
6. Stable Pydantic contracts.
7. Basic final/unstable transcript support.
8. No persistent storage by default.

## Out of Scope

- audio capture;
- neural diarization;
- LLM answer generation;
- meeting summary generation;
- desktop overlay;
- user accounts;
- public internet deployment.

## Success Criteria

MVP is successful when:

1. service starts;
2. `/health` returns ok;
3. `/v1/models` lists profiles;
4. file transcription works with mock backend;
5. file transcription works with faster-whisper;
6. chunk transcription returns typed segments;
7. WebSocket stream accepts chunks and emits `transcript_delta`;
8. benchmark script can compare profiles.
