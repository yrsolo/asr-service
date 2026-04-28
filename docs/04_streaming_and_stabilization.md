# Streaming and Stabilization

## Pseudo-Streaming

Whisper-like models are usually not ideal token-by-token streaming engines. Use pseudo-streaming:

```text
short audio chunks
+ overlap
+ rolling buffer
+ final/unstable segmentation
```

## Chunk Settings

Start with:

```text
chunk_size: 3-5 seconds
overlap: 0.5-1 second
sample_rate: 16 kHz
channels: mono
```

Test:

- 2s chunks: lower latency, weaker context;
- 5s chunks: good balance;
- 10s chunks: better context, higher latency.

## Final vs Unstable

`final` text is stable and can be appended to the transcript.

`unstable` text is the current tail and may be changed or removed.

## Current MVP Behavior

The WebSocket stream keeps one pending unstable tail:

1. each audio message is transcribed as a pseudo-streaming window;
2. all complete segments except the last are emitted as `segments`;
3. the last segment is emitted as `unstable`;
4. the previous unstable tail becomes `final` when the next audio message arrives;
5. `flush` finalizes the current unstable tail.

This is intentionally simple. It gives the desktop client the correct rendering contract before deeper overlap matching is added.

## Future Stabilization

Add later:

1. overlap matching;
2. longest common prefix;
3. local agreement;
4. VAD phrase boundaries;
5. revision numbers for changed unstable segments.
