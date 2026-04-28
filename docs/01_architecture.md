# Architecture

## Components

```text
Client app
  └─ captures audio
      └─ sends chunks/files over HTTP/WebSocket

Local ASR Service
  ├─ FastAPI API layer
  ├─ Auth/API-key middleware
  ├─ Audio decoder/converter
  ├─ ASR backend interface
  ├─ faster-whisper backend
  ├─ mock backend
  ├─ streaming session manager
  ├─ transcript stabilizer
  └─ response serializer
```

## API Layer

Validates requests, accepts audio, routes to backend, returns typed responses.

## Audio Decoder

Preferred internal format:

```text
PCM mono, 16 kHz
```

MVP should accept WAV. MP3/WebM/Opus may be added after the core flow works.

## ASR Backend Interface

Initial backends:

- `mock`
- `faster_whisper`

Future backends:

- `whisper_cpp`
- `onnx_whisper`
- `remote_api_fallback`

## Transcript Stabilizer

Streaming output has two layers:

- `final` — stable enough to append permanently;
- `unstable` — current tail that may be rewritten.

MVP can mark processed chunks as final. Later versions should add overlap matching and local agreement.

## Session Manager

For WebSocket sessions, store:

- session id;
- model profile;
- source label;
- sequence number;
- rolling buffer;
- transcript segments;
- unstable tail.

## Data Ownership

Default behavior:

- raw audio in memory only;
- transcript in memory only;
- nothing saved to disk;
- privacy-safe logs only.
