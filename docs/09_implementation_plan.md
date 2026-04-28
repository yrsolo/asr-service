# Implementation Plan

## Milestone 1: API Skeleton

- FastAPI app starts.
- `/health` works.
- `/v1/models` works.
- schemas exist.
- mock backend works.

## Milestone 2: File Transcription

- `/v1/transcribe/file` accepts audio.
- mock backend returns deterministic segments.
- tests cover response schema.

## Milestone 3: faster-whisper Backend

- backend loads configured model;
- file transcription works;
- language/source supported;
- clean errors.

## Milestone 4: Chunk API

- `/v1/transcribe/chunk`;
- session id;
- sequence number;
- timestamps.

## Milestone 5: WebSocket Streaming

- start/audio/flush/close messages;
- transcript_delta responses;
- mock streaming first.

## Milestone 6: Stabilization

- final/unstable tail;
- revision numbers;
- overlap matching later.

## Milestone 7: Benchmarking

- benchmark script;
- compare profiles;
- document tested recommendations.
