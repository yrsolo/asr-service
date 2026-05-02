import base64
from array import array
from dataclasses import dataclass

from local_asr_service.backends.base import TranscriptionResult
from local_asr_service.config import ModelProfile
from local_asr_service.schemas import AdaptationMode, AudioSource, SegmentStatus, TranscriptSegment
from local_asr_service.streaming import (
    FuzzyTextStitcher,
    LiveHypothesisStabilizer,
    LiveStreamingSession,
    PhraseEndpointStreamingSession,
)


def _result(text: str, *, end_ms: int = 1000) -> TranscriptionResult:
    return TranscriptionResult(
        segments=[
            TranscriptSegment(
                id="seg",
                source=AudioSource.MIC,
                start_ms=0,
                end_ms=end_ms,
                text=text,
            )
        ],
        text=text,
        duration_ms=end_ms,
    )


def _pcm(amplitude: int, duration_ms: int) -> bytes:
    samples = int(16000 * duration_ms / 1000)
    return array("h", [amplitude] * samples).tobytes()


@dataclass
class _FakeBackend:
    texts: list[str]
    calls: int = 0

    def __post_init__(self) -> None:
        self.profile = ModelProfile(
            id="fake",
            backend="mock",
            model_name="fake",
            device="cpu",
            compute_type="int8",
            languages=["auto"],
        )

    def transcribe_bytes(
        self,
        data: bytes,
        *,
        language: str = "auto",
        source: AudioSource = AudioSource.UNKNOWN,
        start_ms: int = 0,
    ) -> TranscriptionResult:
        self.calls += 1
        text = self.texts[min(self.calls - 1, len(self.texts) - 1)]
        return _result(text, end_ms=start_ms + 1000)


def _phrase_session(monkeypatch, backend: _FakeBackend) -> PhraseEndpointStreamingSession:
    monkeypatch.setattr("local_asr_service.streaming.get_backend", lambda _model_id: backend)
    return PhraseEndpointStreamingSession.from_start_message(
        {
            "type": "start",
            "stream_mode": "phrase_endpoint",
            "model_id": "fake",
            "source": "mic",
        }
    )


def test_live_stabilizer_keeps_raw_tail_out_of_main_transcript() -> None:
    stabilizer = LiveHypothesisStabilizer(
        source=AudioSource.MIC,
        raw_tail_ms=1500,
        final_lag_ms=4000,
        stable_confirmations=2,
    )

    first = stabilizer.accept(_result("hello world"), window_start_ms=0, audio_end_ms=1000)
    second = stabilizer.accept(
        _result("hello world today"),
        window_start_ms=0,
        audio_end_ms=2000,
    )

    assert first.updates == []
    assert first.raw[0].text == "hello world"
    assert second.updates[0].text == "hello world"
    assert second.updates[0].status is SegmentStatus.DRAFT
    assert second.raw[0].text == "today"


def test_live_stabilizer_promotes_confirmed_text_to_final() -> None:
    stabilizer = LiveHypothesisStabilizer(
        source=AudioSource.SYSTEM,
        raw_tail_ms=1500,
        final_lag_ms=1000,
        stable_confirmations=2,
    )

    stabilizer.accept(_result("move meeting Friday", end_ms=1000), window_start_ms=0, audio_end_ms=1000)
    stabilizer.accept(_result("move meeting Friday", end_ms=1000), window_start_ms=0, audio_end_ms=2500)
    final = stabilizer.accept(
        _result("move meeting Friday", end_ms=1000),
        window_start_ms=0,
        audio_end_ms=3500,
    )

    assert final.updates[0].text == "move meeting Friday"
    assert final.updates[0].status is SegmentStatus.FINAL
    assert final.updates[0].id == "live-final"


def test_live_stabilizer_finalizes_even_when_segment_end_follows_audio_end() -> None:
    stabilizer = LiveHypothesisStabilizer(
        source=AudioSource.MIC,
        raw_tail_ms=1500,
        final_lag_ms=2000,
        stable_confirmations=2,
    )

    stabilizer.accept(_result("hello world", end_ms=1000), window_start_ms=0, audio_end_ms=1000)
    stabilizer.accept(_result("hello world", end_ms=2000), window_start_ms=0, audio_end_ms=2000)
    stabilizer.accept(_result("hello world", end_ms=3000), window_start_ms=0, audio_end_ms=3000)
    final = stabilizer.accept(_result("hello world", end_ms=4000), window_start_ms=0, audio_end_ms=4000)

    assert final.updates[0].status is SegmentStatus.FINAL
    assert final.updates[0].text == "hello world"


def test_live_stabilizer_final_text_grows_after_rolling_window_moves() -> None:
    stabilizer = LiveHypothesisStabilizer(
        source=AudioSource.MIC,
        raw_tail_ms=1500,
        final_lag_ms=1000,
        stable_confirmations=2,
    )

    stabilizer.accept(_result("one two three", end_ms=1000), window_start_ms=0, audio_end_ms=1000)
    stabilizer.accept(_result("one two three", end_ms=2000), window_start_ms=0, audio_end_ms=2000)
    first_final = stabilizer.accept(
        _result("one two three", end_ms=3000),
        window_start_ms=0,
        audio_end_ms=3000,
    )

    stabilizer.accept(_result("three four five", end_ms=4000), window_start_ms=2000, audio_end_ms=4000)
    stabilizer.accept(_result("three four five", end_ms=5000), window_start_ms=3000, audio_end_ms=5000)
    grown_final = stabilizer.accept(
        _result("three four five", end_ms=6000),
        window_start_ms=4000,
        audio_end_ms=6000,
    )

    assert first_final.updates[0].text == "one two three"
    assert grown_final.updates[0].id == "live-final"
    assert grown_final.updates[0].text == "one two three four five"


def test_live_stabilizer_flush_keeps_accumulated_final_text() -> None:
    stabilizer = LiveHypothesisStabilizer(
        source=AudioSource.MIC,
        raw_tail_ms=1500,
        final_lag_ms=1000,
        stable_confirmations=2,
    )

    stabilizer.accept(_result("one two three", end_ms=1000), window_start_ms=0, audio_end_ms=1000)
    stabilizer.accept(_result("one two three", end_ms=2000), window_start_ms=0, audio_end_ms=2000)
    stabilizer.accept(_result("one two three", end_ms=3000), window_start_ms=0, audio_end_ms=3000)
    stabilizer.accept(_result("three four five", end_ms=5000), window_start_ms=2000, audio_end_ms=5000)

    flushed = stabilizer.flush()

    assert flushed.updates[0].id == "live-final"
    assert flushed.updates[0].text == "one two three four five"


def test_live_stabilizer_revises_draft_instead_of_appending() -> None:
    stabilizer = LiveHypothesisStabilizer(
        source=AudioSource.MIC,
        raw_tail_ms=1500,
        final_lag_ms=4000,
        stable_confirmations=2,
    )

    stabilizer.accept(_result("hello world"), window_start_ms=0, audio_end_ms=1000)
    draft = stabilizer.accept(_result("hello brave world"), window_start_ms=0, audio_end_ms=2000)

    assert draft.updates[0].id == "live-draft"
    assert draft.updates[0].text == "hello"
    assert draft.raw[0].text == "brave world"
    assert draft.updates[0].revision == draft.revision


def test_live_stabilizer_keeps_fuzzy_overlap_variant() -> None:
    stabilizer = LiveHypothesisStabilizer(
        source=AudioSource.MIC,
        raw_tail_ms=1500,
        final_lag_ms=4000,
        stable_confirmations=2,
    )

    stabilizer.accept(_result("hello world"), window_start_ms=0, audio_end_ms=1000)
    draft = stabilizer.accept(_result("helo world today"), window_start_ms=0, audio_end_ms=2000)

    assert draft.updates[0].id == "live-draft"
    assert draft.updates[0].text == "helo world"
    assert draft.raw[0].text == "today"


def test_live_stabilizer_fuzzy_final_merge_keeps_one_overlap_version() -> None:
    stabilizer = LiveHypothesisStabilizer(
        source=AudioSource.MIC,
        raw_tail_ms=1500,
        final_lag_ms=1000,
        stable_confirmations=2,
    )

    stabilizer.accept(_result("hello world", end_ms=1000), window_start_ms=0, audio_end_ms=1000)
    stabilizer.accept(_result("hello world", end_ms=2000), window_start_ms=0, audio_end_ms=2000)
    stabilizer.accept(_result("hello world", end_ms=3000), window_start_ms=0, audio_end_ms=3000)
    stabilizer.accept(_result("helo world today", end_ms=5000), window_start_ms=2000, audio_end_ms=5000)

    flushed = stabilizer.flush()

    assert flushed.updates[0].text == "hello world today"


def test_pcm_payload_helper_shape() -> None:
    pcm = bytes(16000 * 2)
    encoded = base64.b64encode(pcm).decode("ascii")

    assert encoded


def test_live_stats_realtime_factor_uses_audio_step(monkeypatch) -> None:
    values = iter([0.0, 0.5])
    monkeypatch.setattr("local_asr_service.streaming.perf_counter", lambda: next(values))
    session = LiveStreamingSession.from_start_message(
        {
            "type": "start",
            "stream_mode": "live_revision",
            "model_id": "mock",
            "source": "mic",
        }
    )

    delta = session.handle_audio_message(
        {
            "type": "audio",
            "seq": 1,
            "duration_ms": 1000,
            "audio_b64": base64.b64encode(bytes(16000 * 2)).decode("ascii"),
        }
    )

    assert delta.stats.decode_ms == 500
    assert delta.stats.audio_step_ms == 1000
    assert delta.stats.decode_interval_ms == 1000
    assert delta.stats.realtime_factor == 0.5


def test_live_stats_realtime_factor_uses_decode_interval_for_small_frames(monkeypatch) -> None:
    values = iter([0.0, 0.5])
    monkeypatch.setattr("local_asr_service.streaming.perf_counter", lambda: next(values))
    session = LiveStreamingSession.from_start_message(
        {
            "type": "start",
            "stream_mode": "live_revision",
            "model_id": "mock",
            "source": "mic",
            "decode_interval_ms": 1000,
        }
    )

    delta = session.handle_audio_message(
        {
            "type": "audio",
            "seq": 20,
            "duration_ms": 50,
            "should_decode": True,
            "audio_b64": base64.b64encode(bytes(1600)).decode("ascii"),
        }
    )

    assert delta.stats.decode_ms == 500
    assert delta.stats.audio_step_ms == 50
    assert delta.stats.decode_interval_ms == 1000
    assert delta.stats.realtime_factor == 0.5


def test_live_drop_stale_decode_skips_decode_but_keeps_audio() -> None:
    session = LiveStreamingSession.from_start_message(
        {
            "type": "start",
            "stream_mode": "live_revision",
            "model_id": "mock",
            "source": "mic",
            "adaptation_mode": AdaptationMode.DROP_STALE_DECODE,
        }
    )

    delta = session.handle_audio_message(
        {
            "type": "audio",
            "seq": 1,
            "sent_seq": 1,
            "total_seq": 2,
            "duration_ms": 1000,
            "audio_b64": base64.b64encode(bytes(16000 * 2)).decode("ascii"),
        }
    )

    assert delta.updates == []
    assert delta.raw == []
    assert delta.stats.dropped_chunks == 1
    assert delta.stats.audio_received_ms == 1000
    assert delta.stats.audio_window_ms == 1000
    assert delta.stats.adaptation_action == "decode skipped"


def test_live_silence_message_advances_timeline_without_decode() -> None:
    session = LiveStreamingSession.from_start_message(
        {
            "type": "start",
            "stream_mode": "live_revision",
            "model_id": "mock",
            "source": "mic",
            "adaptation_mode": AdaptationMode.SILENCE_GATE,
        }
    )

    delta = session.handle_silence_message(
        {
            "type": "silence",
            "seq": 1,
            "duration_ms": 750,
        }
    )

    assert delta.stats.audio_received_ms == 750
    assert delta.stats.silence_skipped_ms == 750
    assert delta.stats.decode_ms == 0
    assert delta.stats.adaptation_action == "silence skipped"


def test_live_adaptive_window_reduces_and_recovers() -> None:
    session = LiveStreamingSession.from_start_message(
        {
            "type": "start",
            "stream_mode": "live_revision",
            "model_id": "mock",
            "source": "mic",
            "adaptation_mode": AdaptationMode.ADAPTIVE_WINDOW,
            "window_ms": 8000,
            "min_window_ms": 4000,
        }
    )

    session._last_realtime_factor = 2.0
    session._adjust_effective_window(queue_chunks=0)
    assert session._effective_window_ms == 6000

    session._last_realtime_factor = 0.5
    session._adjust_effective_window(queue_chunks=0)
    assert session._effective_window_ms == 8000


def test_phrase_endpoint_silence_does_not_decode(monkeypatch) -> None:
    backend = _FakeBackend(["silence should not decode"])
    session = _phrase_session(monkeypatch, backend)

    delta = session.handle_audio_message(
        {
            "type": "audio",
            "seq": 1,
            "duration_ms": 1000,
            "audio_b64": base64.b64encode(_pcm(0, 1000)).decode("ascii"),
        }
    )

    assert backend.calls == 0
    assert delta.updates == []
    assert delta.stats.vad_state == "silence"


def test_phrase_endpoint_speech_starts_after_min_duration(monkeypatch) -> None:
    backend = _FakeBackend(["hello"])
    session = _phrase_session(monkeypatch, backend)

    first = session.handle_audio_message(
        {
            "type": "audio",
            "seq": 1,
            "duration_ms": 100,
            "audio_b64": base64.b64encode(_pcm(1200, 100)).decode("ascii"),
        }
    )
    second = session.handle_audio_message(
        {
            "type": "audio",
            "seq": 2,
            "duration_ms": 200,
            "audio_b64": base64.b64encode(_pcm(1200, 200)).decode("ascii"),
        }
    )

    assert first.stats.vad_state == "speech_candidate"
    assert second.stats.vad_state == "speech"
    assert backend.calls == 0


def test_phrase_endpoint_finalizes_after_silence(monkeypatch) -> None:
    backend = _FakeBackend(["final phrase"])
    session = _phrase_session(monkeypatch, backend)

    session.handle_audio_message(
        {
            "type": "audio",
            "seq": 1,
            "duration_ms": 1000,
            "audio_b64": base64.b64encode(_pcm(1200, 1000)).decode("ascii"),
        }
    )
    delta = session.handle_audio_message(
        {
            "type": "audio",
            "seq": 2,
            "duration_ms": 700,
            "audio_b64": base64.b64encode(_pcm(0, 700)).decode("ascii"),
        }
    )

    assert backend.calls == 1
    assert delta.updates[0].status is SegmentStatus.FINAL
    assert delta.updates[0].text == "final phrase"
    assert delta.stats.adaptation_action == "phrase final"


def test_phrase_endpoint_long_phrase_decodes_overlapping_windows(monkeypatch) -> None:
    backend = _FakeBackend(
        ["partial first window", "one two three", "three four five", "five six"]
    )
    session = _phrase_session(monkeypatch, backend)

    session.handle_audio_message(
        {
            "type": "audio",
            "seq": 1,
            "duration_ms": 25000,
            "audio_b64": base64.b64encode(_pcm(1200, 25000)).decode("ascii"),
        }
    )
    delta = session.handle_audio_message(
        {
            "type": "audio",
            "seq": 2,
            "duration_ms": 700,
            "audio_b64": base64.b64encode(_pcm(0, 700)).decode("ascii"),
        }
    )

    assert delta.stats.decoded_windows == 3
    assert delta.updates[0].text == "one two three four five six"


def test_phrase_endpoint_long_phrase_emits_draft_before_phrase_end(monkeypatch) -> None:
    backend = _FakeBackend(["early window", "later final"])
    session = _phrase_session(monkeypatch, backend)
    draft = None

    for seq in range(1, 261):
        delta = session.handle_audio_message(
            {
                "type": "audio",
                "seq": seq,
                "duration_ms": 50,
                "audio_b64": base64.b64encode(_pcm(1200, 50)).decode("ascii"),
            }
        )
        if delta.updates:
            draft = delta
            break

    assert draft is not None
    assert draft.stats.adaptation_action == "long partial"
    assert draft.updates[0].status is SegmentStatus.DRAFT
    assert draft.updates[0].text == "early window"
    assert backend.calls == 1


def test_phrase_endpoint_force_decode_returns_draft(monkeypatch) -> None:
    backend = _FakeBackend(["urgent draft", "urgent final"])
    session = _phrase_session(monkeypatch, backend)

    session.handle_audio_message(
        {
            "type": "audio",
            "seq": 1,
            "duration_ms": 1000,
            "audio_b64": base64.b64encode(_pcm(1200, 1000)).decode("ascii"),
        }
    )
    draft = session.handle_force_decode_message({"type": "force_decode", "seq": 2})

    assert draft.updates[0].status is SegmentStatus.DRAFT
    assert draft.updates[0].id.startswith("phrase-current-")
    assert draft.updates[0].text == "urgent draft"

    final = session.handle_audio_message(
        {
            "type": "audio",
            "seq": 3,
            "duration_ms": 700,
            "audio_b64": base64.b64encode(_pcm(0, 700)).decode("ascii"),
        }
    )

    assert final.updates[0].status is SegmentStatus.FINAL
    assert final.updates[0].id == draft.updates[0].id
    assert final.updates[0].text == "urgent final"


def test_fuzzy_text_stitcher_fallback_keeps_text_when_no_overlap() -> None:
    stitcher = FuzzyTextStitcher()

    stitched = stitcher.append("alpha beta", "gamma delta")

    assert stitched.text == "alpha beta gamma delta"
    assert stitched.confidence == "low"


def test_fuzzy_text_stitcher_keeps_one_overlap_variant() -> None:
    stitcher = FuzzyTextStitcher()

    stitched = stitcher.append("hello world", "helo world today")

    assert stitched.text == "hello world today"
    assert stitched.confidence == "high"
