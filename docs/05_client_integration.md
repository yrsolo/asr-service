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
