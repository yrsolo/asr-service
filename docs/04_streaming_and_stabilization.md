# Streaming and Stabilization

## Modes

The service keeps the original simple pseudo-streaming mode, the sliding-window live revision
mode, and a phrase endpointing mode.

`simple` is the compatibility path:

```text
client sends short audio chunks
service transcribes each chunk/window
service emits final segments + one unstable tail
```

`live_revision` is the preferred live-call test path:

```text
client sends small pcm_s16le 16 kHz mono frames, for example every 50 ms
service keeps a rolling audio window
client/server start an ASR decode job only every decode_interval_ms, for example 1000 ms
service decodes the full sliding window for those jobs
service compares the new hypothesis with previous hypotheses
service emits main transcript updates plus a separate raw live tail
```

`phrase_endpoint` is the preferred quality path for calls:

```text
client sends small pcm_s16le 16 kHz mono frames
service detects speech with server-side RMS endpointing
service buffers one phrase and runs ASR after phrase end for short phrases
long phrases emit draft text while speech is still continuing
long phrase drafts are decoded as 12s windows with 8s step and 4s overlap
service stitches window text with fuzzy word overlap
urgent client requests produce replaceable draft text
```

## Phrase Endpointing Architecture

This mode avoids constant rolling-window decoding. Silence is cheap, and ASR runs only when
there is enough speech to be useful.

Default phrase settings:

```text
phrase_silence_ms: 700
speech_start_rms: 0.012
speech_continue_rms: 0.008
min_speech_ms: 250
pre_roll_ms: 300
max_phrase_ms: 12000
long_window_ms: 12000
long_window_step_ms: 8000
long_window_overlap_ms: 4000
urgent_min_ms: 800
```

VAD states:

```text
silence -> speech_candidate -> speech -> trailing_silence -> silence
```

For phrases up to 12 seconds, the full phrase is decoded once after endpointing. Longer
phrases also produce draft updates before phrase end:

```text
at 12s of speech -> decode 0..12000 and emit draft
at 20s of speech -> decode 8000..20000, stitch, emit a newer draft
at 28s of speech -> decode 16000..28000, stitch, emit a newer draft
```

When endpointing finally detects phrase end, the service runs the phrase final pass and sends
a `final` update with the same phrase segment id. The 4 second overlap gives the stitcher
enough shared text to merge windows without deleting words when Whisper produces slightly
different variants.

## Live Revision Architecture

The live mode intentionally uses one ASR model pass. There is no separate raw model and no
separate raw decoder. `raw` is the right edge of the current sliding-window hypothesis that
has not yet overlapped with a later hypothesis.

Default live settings:

```text
frame_ms: client-side test input frame size, for example 50
decode_interval_ms: 1000
window_ms: 8000
raw_tail_ms: 1500
final_lag_ms: 4000
stable_confirmations: 2
sample_rate: 16000
channels: 1
format: pcm_s16le
```

The current MVP wraps the rolling PCM buffer into an in-memory WAV and reuses the configured
backend. This keeps the backend contract simple while allowing the client and UI to exercise
real live behavior.

## Performance Model

Live ASR speed is governed by three clocks:

```text
incoming audio clock: 1 second of audio arrives every 1 real second
decode clock: faster-whisper needs decode_ms for each sliding-window pass
queue clock: if decode_ms is too high, unprocessed chunks accumulate
```

The main realtime metric is:

```text
realtime_factor = decode_ms / decode_interval_ms
```

`audio_step_ms` is still reported, but it describes the last input frame. When the test UI
sends 50 ms frames and starts a decode job once per 1000 ms, frame-level RTF is noise. The
UI therefore shows RTF only for decode jobs and keeps an average RTF:

```text
average_realtime_factor = sum(decode_ms) / sum(decode_interval_ms for decode jobs)
```

Examples:

```text
RTF 0.5  -> decode is twice as fast as realtime, there is headroom
RTF 1.0  -> exactly realtime
RTF 2.0  -> twice slower than realtime, live mode will fall behind
```

`window_factor = decode_ms / audio_window_ms` answers a different question: how expensive the
current sliding window is. It is useful for comparing model/window settings, but realtime
suitability should be judged by `realtime_factor`.

Performance depends on:

- model size and compute type: larger models usually improve quality but increase `decode_ms`;
- `window_ms`: more context usually improves stability but makes each decode heavier;
- frame size: smaller frames simulate live capture more accurately, but should not force ASR decode per frame;
- `decode_interval_ms`: how often a rolling-window decode job is started;
- `raw_tail_ms` and `final_lag_ms`: larger values make text safer but increase perceived delay;
- VAD/silence: skipping silence reduces unnecessary decode work;
- GPU load and memory pressure: shared GPUs can increase jitter and queue growth.

## Adaptation Modes

The built-in live file emulation can compare these modes:

- `off`: measure only; no automatic speed changes.
- `silence_gate`: the browser computes PCM RMS and sends `silence` events instead of quiet PCM chunks.
- `adaptive_window`: the server reduces `effective_window_ms` when RTF/queue are too high, and grows it back when there is headroom.
- `drop_stale_decode`: stale intermediate chunks update the rolling buffer but skip expensive ASR decode.
- `combined`: silence gate, adaptive window, and stale decode skipping together.

The modes are intended for testing and tuning. Default API behavior remains `off`.

## Live Test Diagnostics

The built-in UI shows several synchronized diagnostics:

- `Final`, `In work`, and `Raw` are separate text lanes.
- `Live diagram` has a full timeline of all input frames, silence skips, decode jobs, rolling windows, effective windows, and queued audio.
- `Sequence texts` keeps every sequence event, but RTF is shown only for decode jobs.
- `Full event log` keeps all WebSocket events for post-run inspection.
- The diagram and log can be filtered to all events, decode jobs, decode jobs with text,
  text-only events, or problem events.

The stabilizer uses fuzzy word matching across overlap windows. If the same overlap word is
recognized with a small spelling difference, one version is retained and the stream continues
instead of deleting the word from both the main transcript and raw tail.

Phrase endpointing uses the same fuzzy word logic for completed phrases and long-window
stitching. If no confident overlap is found, the new window text is appended and
`stitch_confidence` is reported as `low`; text is not dropped.

At file end, `flush` must keep the accumulated `live-final` transcript and merge the final
window tail into it. It must not replace the accumulated final text with only the last ASR
hypothesis.

## What To Do When RTF > 1

Use this order when a model is too slow for realtime:

1. Check `queue_chunks` and `queue_ms`; if they grow, the service is falling behind.
2. Enable `silence_gate`; silence removal is the cheapest win and does not reduce speech context.
3. Reduce `window_ms` or enable `adaptive_window`; this lowers decode cost but can reduce stability.
4. Enable `drop_stale_decode`; this keeps the freshest window responsive but emits fewer intermediate drafts.
5. Move to a smaller/faster model or lower beam size if RTF is still consistently above `1.0`.

## Main Transcript vs Raw Tail

Clients must keep two visual layers:

```text
main transcript: draft + final updates
live tail: raw/unstable text
```

`updates` are applied by `id` and `revision`; newer revisions replace older text for the same
segment. `raw` is volatile and should be replaced on every `live_delta`.

This avoids the common failure mode where fresh low-confidence text constantly rewrites the
stable transcript.

## Stabilization MVP

The MVP uses word-level fuzzy overlap alignment with `difflib.SequenceMatcher`.

Rules:

- the first live decode usually produces only `raw`;
- text that overlaps with the previous hypothesis becomes `draft`;
- confirmed words track their own first-seen time and confirmation count;
- a confirmed word can move to `final` after `stable_confirmations` and `final_lag_ms`;
- this avoids waiting on `audio_end_ms - segment.end_ms`, which often stays near zero on a rolling window;
- `live-final` is an accumulated transcript buffer and grows by overlap-merging newly finalized words;
- changed draft text is sent as a newer revision of `live-draft`, not appended;
- finalized text is sent as `live-final`; an empty `live-draft` update clears the working lane.

Later improvements can add true word timestamps, VAD phrase boundaries, local agreement over
multiple segment ids, binary WebSocket frames, and a higher-quality final pass for closed VAD
segments.
