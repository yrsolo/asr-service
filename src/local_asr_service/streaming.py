import base64
import io
import re
import wave
from dataclasses import dataclass
from difflib import SequenceMatcher
from time import perf_counter
from uuid import uuid4

from local_asr_service.backends.base import TranscriptionResult
from local_asr_service.backends.factory import get_backend
from local_asr_service.schemas import (
    AdaptationMode,
    AudioSource,
    LiveDeltaMessage,
    LiveEffectiveConfig,
    LiveStats,
    SegmentStatus,
    Speaker,
    StreamMode,
    StreamStartMessage,
    TranscriptDeltaMessage,
    TranscriptSegment,
)


_WORD_RE = re.compile(r"\S+")
_PUNCTUATION = ".,!?;:()[]{}«»\"'`“”„…"


def _speaker_for_source(source: AudioSource) -> Speaker:
    if source == AudioSource.MIC:
        return Speaker.USER
    if source == AudioSource.SYSTEM:
        return Speaker.OTHER
    return Speaker.UNKNOWN


def _split_words(text: str) -> list[str]:
    return _WORD_RE.findall(text.strip())


def _normalize_word(word: str) -> str:
    return word.strip(_PUNCTUATION).lower().replace("ё", "е")


def _words_similar(left: str, right: str) -> bool:
    left_norm = _normalize_word(left)
    right_norm = _normalize_word(right)
    if not left_norm or not right_norm:
        return False
    if left_norm == right_norm:
        return True
    if min(len(left_norm), len(right_norm)) <= 3:
        return False
    return SequenceMatcher(None, left_norm, right_norm, autojunk=False).ratio() >= 0.78


def _overlap_prefix_length(previous_words: list[str], current_words: list[str]) -> int:
    if not previous_words or not current_words:
        return 0
    best_current_end = 0
    best_size = 0
    for previous_start in range(len(previous_words)):
        for current_start in range(len(current_words)):
            size = 0
            while (
                previous_start + size < len(previous_words)
                and current_start + size < len(current_words)
                and _words_similar(
                    previous_words[previous_start + size],
                    current_words[current_start + size],
                )
            ):
                size += 1
            if size > best_size:
                best_size = size
                best_current_end = current_start + size
    return best_current_end


def _word_boundary_ms(start_ms: int, end_ms: int, total_words: int, boundary_words: int) -> int:
    if total_words <= 0:
        return end_ms
    boundary_words = max(0, min(boundary_words, total_words))
    return start_ms + int((end_ms - start_ms) * boundary_words / total_words)


def _pcm_duration_ms(byte_count: int, sample_rate: int, channels: int) -> int:
    if sample_rate <= 0 or channels <= 0:
        return 0
    frames = byte_count // (channels * 2)
    return int(frames * 1000 / sample_rate)


def _pcm_byte_count(duration_ms: int, sample_rate: int, channels: int) -> int:
    return int(sample_rate * channels * 2 * duration_ms / 1000)


def _pcm_rms_s16le(pcm: bytes) -> float:
    if len(pcm) < 2:
        return 0.0
    sample_count = len(pcm) // 2
    total = 0.0
    for index in range(0, sample_count * 2, 2):
        sample = int.from_bytes(pcm[index : index + 2], "little", signed=True)
        normalized = sample / 32768.0
        total += normalized * normalized
    return (total / sample_count) ** 0.5


def _pcm_slice_ms(pcm: bytes, *, start_ms: int, end_ms: int, sample_rate: int, channels: int) -> bytes:
    start_byte = _pcm_byte_count(start_ms, sample_rate, channels)
    end_byte = _pcm_byte_count(end_ms, sample_rate, channels)
    return pcm[start_byte:end_byte]


def _wrap_pcm_s16le_as_wav(pcm: bytes, *, sample_rate: int, channels: int) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm)
    return buffer.getvalue()


@dataclass(frozen=True)
class LiveStabilizerResult:
    revision: int
    updates: list[TranscriptSegment]
    raw: list[TranscriptSegment]


@dataclass(frozen=True)
class StitchedText:
    text: str
    confidence: str


class FuzzyTextStitcher:
    def __init__(self, *, max_overlap_words: int = 80) -> None:
        self.max_overlap_words = max_overlap_words

    def append(self, existing_text: str, new_text: str, *, prefer_new_overlap: bool = False) -> StitchedText:
        existing_words = _split_words(existing_text)
        new_words = _split_words(new_text)
        if not existing_words:
            return StitchedText(text=" ".join(new_words).strip(), confidence="none")
        if not new_words:
            return StitchedText(text=" ".join(existing_words).strip(), confidence="none")

        max_overlap = min(len(existing_words), len(new_words), self.max_overlap_words)
        overlap = 0
        for size in range(max_overlap, 0, -1):
            if all(
                _words_similar(existing_word, new_word)
                for existing_word, new_word in zip(existing_words[-size:], new_words[:size], strict=False)
            ):
                overlap = size
                break

        if overlap == 0:
            return StitchedText(
                text=" ".join([*existing_words, *new_words]).strip(),
                confidence="low",
            )

        if prefer_new_overlap:
            merged_words = [*existing_words[:-overlap], *new_words]
        else:
            merged_words = [*existing_words, *new_words[overlap:]]
        return StitchedText(text=" ".join(merged_words).strip(), confidence="high")


class StreamingSession:
    def __init__(
        self,
        *,
        session_id: str,
        model_id: str,
        language: str,
        source: AudioSource,
        sample_rate: int,
        channels: int,
        audio_format: str,
    ) -> None:
        self.session_id = session_id
        self.model_id = model_id
        self.language = language
        self.source = source
        self.sample_rate = sample_rate
        self.channels = channels
        self.audio_format = audio_format
        self.backend = get_backend(model_id)
        self.last_seq = 0
        self._pending_unstable: TranscriptSegment | None = None
        self._revision = 0

    @classmethod
    def from_start_message(cls, raw: dict) -> "StreamingSession":
        msg = StreamStartMessage.model_validate(raw)
        backend = get_backend(msg.model_id)
        return cls(
            session_id=msg.session_id or str(uuid4()),
            model_id=backend.profile.id,
            language=msg.language,
            source=msg.source,
            sample_rate=msg.sample_rate,
            channels=msg.channels,
            audio_format=msg.format,
        )

    def handle_audio_message(self, raw: dict) -> TranscriptDeltaMessage:
        seq = int(raw["seq"])
        audio = base64.b64decode(raw["audio_b64"])
        start_ms = int(raw.get("start_ms") or 0)
        result = self.backend.transcribe_bytes(
            audio,
            language=self.language,
            source=self.source,
            start_ms=start_ms,
        )
        self.last_seq = seq

        final_segments: list[TranscriptSegment] = []
        if self._pending_unstable is not None:
            final_segments.append(
                self._pending_unstable.model_copy(update={"status": SegmentStatus.FINAL})
            )
            self._pending_unstable = None

        if result.segments:
            final_segments.extend(
                segment.model_copy(update={"status": SegmentStatus.FINAL})
                for segment in result.segments[:-1]
            )
            self._revision += 1
            self._pending_unstable = result.segments[-1].model_copy(
                update={"status": SegmentStatus.UNSTABLE, "revision": self._revision}
            )

        return TranscriptDeltaMessage(
            session_id=self.session_id,
            seq=seq,
            segments=final_segments,
            unstable=[self._pending_unstable] if self._pending_unstable else [],
        )

    def flush(self) -> TranscriptDeltaMessage:
        final_segments = []
        if self._pending_unstable is not None:
            final_segments.append(
                self._pending_unstable.model_copy(update={"status": SegmentStatus.FINAL})
            )
            self._pending_unstable = None
        return TranscriptDeltaMessage(
            session_id=self.session_id,
            seq=self.last_seq,
            segments=final_segments,
            unstable=[],
        )


class LiveHypothesisStabilizer:
    def __init__(
        self,
        *,
        source: AudioSource,
        raw_tail_ms: int,
        final_lag_ms: int,
        stable_confirmations: int,
    ) -> None:
        self.source = source
        self.raw_tail_ms = raw_tail_ms
        self.final_lag_ms = final_lag_ms
        self.stable_confirmations = stable_confirmations
        self._previous_words: list[str] = []
        self._confirmed_norm_words: list[str] = []
        self._confirmed_first_seen_ms: list[int] = []
        self._confirmed_hits: list[int] = []
        self._final_words: list[str] = []
        self._final_start_ms = 0
        self._final_end_ms = 0
        self._last_final_update_text = ""
        self._last_draft_update_text = ""
        self._last_text = ""
        self._last_start_ms = 0
        self._last_end_ms = 0
        self._revision = 0

    @property
    def revision(self) -> int:
        return self._revision

    def next_empty_revision(self) -> int:
        self._revision += 1
        return self._revision

    def accept(
        self,
        result: TranscriptionResult,
        *,
        window_start_ms: int,
        audio_end_ms: int,
    ) -> LiveStabilizerResult:
        text = result.text.strip()
        words = _split_words(text)
        start_ms = result.segments[0].start_ms if result.segments else window_start_ms
        end_ms = result.segments[-1].end_ms if result.segments else audio_end_ms
        self._last_text = text
        self._last_start_ms = start_ms
        self._last_end_ms = end_ms

        confirmed_words = _overlap_prefix_length(self._previous_words, words)
        candidate_words = words[:confirmed_words]
        raw_words = words[confirmed_words:]
        raw_text = " ".join(raw_words).strip()

        self._refresh_confirmed_tracking(candidate_words, audio_end_ms=audio_end_ms)
        final_word_count = self._final_word_count(audio_end_ms)
        final_words = candidate_words[:final_word_count]
        draft_words = candidate_words[final_word_count:]
        draft_text = " ".join(draft_words).strip()
        final_end_ms = _word_boundary_ms(start_ms, end_ms, len(words), final_word_count)
        final_changed = self._merge_final_words(
            final_words,
            start_ms=start_ms,
            end_ms=final_end_ms,
        )
        final_text = " ".join(self._final_words).strip()

        self._previous_words = words
        self._revision += 1

        updates: list[TranscriptSegment] = []
        if final_text and final_changed and final_text != self._last_final_update_text:
            updates.append(
                TranscriptSegment(
                    id="live-final",
                    source=self.source,
                    speaker=_speaker_for_source(self.source),
                    start_ms=self._final_start_ms,
                    end_ms=self._final_end_ms,
                    text=final_text,
                    status=SegmentStatus.FINAL,
                    revision=self._revision,
                )
            )
            self._last_final_update_text = final_text

        if draft_text != self._last_draft_update_text:
            draft_start_ms = _word_boundary_ms(start_ms, end_ms, len(words), final_word_count)
            draft_end_ms = _word_boundary_ms(start_ms, end_ms, len(words), confirmed_words)
            updates.append(
                TranscriptSegment(
                    id="live-draft",
                    source=self.source,
                    speaker=_speaker_for_source(self.source),
                    start_ms=draft_start_ms,
                    end_ms=draft_end_ms,
                    text=draft_text,
                    status=SegmentStatus.DRAFT,
                    revision=self._revision,
                )
            )
            self._last_draft_update_text = draft_text

        raw: list[TranscriptSegment] = []
        if raw_text:
            raw_start_ms = _word_boundary_ms(start_ms, end_ms, len(words), confirmed_words)
            raw.append(
                TranscriptSegment(
                    id="live-raw",
                    source=self.source,
                    speaker=_speaker_for_source(self.source),
                    start_ms=max(raw_start_ms, end_ms - self.raw_tail_ms),
                    end_ms=end_ms,
                    text=raw_text,
                    status=SegmentStatus.UNSTABLE,
                    revision=self._revision,
                )
            )

        return LiveStabilizerResult(revision=self._revision, updates=updates, raw=raw)

    def _refresh_confirmed_tracking(self, candidate_words: list[str], *, audio_end_ms: int) -> None:
        candidate_norm_words = [_normalize_word(word) for word in candidate_words]
        previous_norm_words = self._confirmed_norm_words
        first_seen_ms = [audio_end_ms] * len(candidate_norm_words)
        hits = [1] * len(candidate_norm_words)

        previous_index = 0
        for current_index, current_word in enumerate(candidate_norm_words):
            for search_index in range(previous_index, len(previous_norm_words)):
                if not _words_similar(previous_norm_words[search_index], current_word):
                    continue
                first_seen_ms[current_index] = self._confirmed_first_seen_ms[search_index]
                hits[current_index] = self._confirmed_hits[search_index] + 1
                previous_index = search_index + 1
                break

        self._confirmed_norm_words = candidate_norm_words
        self._confirmed_first_seen_ms = first_seen_ms
        self._confirmed_hits = hits

    def _final_word_count(self, audio_end_ms: int) -> int:
        count = 0
        for first_seen_ms, hits in zip(
            self._confirmed_first_seen_ms,
            self._confirmed_hits,
            strict=False,
        ):
            if hits < self.stable_confirmations:
                break
            if audio_end_ms - first_seen_ms < self.final_lag_ms:
                break
            count += 1
        return count

    def _merge_final_words(self, words: list[str], *, start_ms: int, end_ms: int) -> bool:
        if not words:
            return False

        if not self._final_words:
            self._final_words = list(words)
            self._final_start_ms = start_ms
            self._final_end_ms = end_ms
            return True

        max_overlap = min(len(self._final_words), len(words))
        overlap = 0
        for size in range(max_overlap, 0, -1):
            if all(
                _words_similar(final_word, new_word)
                for final_word, new_word in zip(self._final_words[-size:], words[:size], strict=False)
            ):
                overlap = size
                break

        if overlap == len(words):
            self._final_end_ms = max(self._final_end_ms, end_ms)
            return False

        append_words = words[overlap:]
        if not append_words:
            return False

        self._final_words.extend(append_words)
        self._final_end_ms = max(self._final_end_ms, end_ms)
        return True

    def flush(self) -> LiveStabilizerResult:
        self._revision += 1
        updates = []
        if self._last_text:
            self._merge_final_words(
                _split_words(self._last_text),
                start_ms=self._last_start_ms,
                end_ms=self._last_end_ms,
            )
            final_text = " ".join(self._final_words).strip()
            updates.append(
                TranscriptSegment(
                    id="live-final",
                    source=self.source,
                    speaker=_speaker_for_source(self.source),
                    start_ms=self._final_start_ms,
                    end_ms=self._final_end_ms,
                    text=final_text,
                    status=SegmentStatus.FINAL,
                    revision=self._revision,
                )
            )
            self._last_final_update_text = final_text
            if self._last_draft_update_text:
                updates.append(
                    TranscriptSegment(
                        id="live-draft",
                        source=self.source,
                        speaker=_speaker_for_source(self.source),
                        start_ms=self._last_end_ms,
                        end_ms=self._last_end_ms,
                        text="",
                        status=SegmentStatus.DRAFT,
                        revision=self._revision,
                    )
                )
                self._last_draft_update_text = ""
        return LiveStabilizerResult(revision=self._revision, updates=updates, raw=[])


class LiveStreamingSession:
    def __init__(
        self,
        *,
        session_id: str,
        model_id: str,
        language: str,
        source: AudioSource,
        sample_rate: int,
        channels: int,
        audio_format: str,
        decode_interval_ms: int,
        window_ms: int,
        raw_tail_ms: int,
        final_lag_ms: int,
        stable_confirmations: int,
        adaptation_mode: AdaptationMode,
        min_window_ms: int,
        max_window_ms: int,
        rtf_warn_threshold: float,
        rtf_slow_threshold: float,
        silence_rms_threshold: float,
        silence_min_ms: int,
    ) -> None:
        self.session_id = session_id
        self.model_id = model_id
        self.language = language
        self.source = source
        self.sample_rate = sample_rate
        self.channels = channels
        self.audio_format = audio_format
        self.decode_interval_ms = decode_interval_ms
        self.window_ms = window_ms
        self.raw_tail_ms = raw_tail_ms
        self.final_lag_ms = final_lag_ms
        self.stable_confirmations = stable_confirmations
        self.adaptation_mode = adaptation_mode
        self.min_window_ms = min(min_window_ms, window_ms)
        self.max_window_ms = max_window_ms or window_ms
        self.rtf_warn_threshold = rtf_warn_threshold
        self.rtf_slow_threshold = rtf_slow_threshold
        self.silence_rms_threshold = silence_rms_threshold
        self.silence_min_ms = silence_min_ms
        self.backend = get_backend(model_id)
        self.last_seq = 0
        self._pcm = bytearray()
        self._total_pcm_bytes = 0
        self._silence_skipped_ms = 0
        self._dropped_chunks = 0
        self._effective_window_ms = min(window_ms, self.max_window_ms)
        self._last_realtime_factor = 0.0
        self._last_action = "normal"
        self._stabilizer = LiveHypothesisStabilizer(
            source=source,
            raw_tail_ms=raw_tail_ms,
            final_lag_ms=final_lag_ms,
            stable_confirmations=stable_confirmations,
        )

    @classmethod
    def from_start_message(cls, raw: dict) -> "LiveStreamingSession":
        msg = StreamStartMessage.model_validate(raw)
        if msg.stream_mode != StreamMode.LIVE_REVISION:
            raise ValueError("LiveStreamingSession requires stream_mode=live_revision")
        if msg.format != "pcm_s16le" or msg.sample_rate != 16000 or msg.channels != 1:
            raise ValueError(
                "live_revision requires pcm_s16le, 16 kHz, mono audio. "
                "Use the built-in web UI live emulation or stream_mode=simple for other formats."
            )
        backend = get_backend(msg.model_id)
        return cls(
            session_id=msg.session_id or str(uuid4()),
            model_id=backend.profile.id,
            language=msg.language,
            source=msg.source,
            sample_rate=msg.sample_rate,
            channels=msg.channels,
            audio_format=msg.format,
            decode_interval_ms=msg.decode_interval_ms,
            window_ms=msg.window_ms,
            raw_tail_ms=msg.raw_tail_ms,
            final_lag_ms=msg.final_lag_ms,
            stable_confirmations=msg.stable_confirmations,
            adaptation_mode=msg.adaptation_mode,
            min_window_ms=msg.min_window_ms,
            max_window_ms=msg.max_window_ms or msg.window_ms,
            rtf_warn_threshold=msg.rtf_warn_threshold,
            rtf_slow_threshold=msg.rtf_slow_threshold,
            silence_rms_threshold=msg.silence_rms_threshold,
            silence_min_ms=msg.silence_min_ms,
        )

    @property
    def effective_config(self) -> LiveEffectiveConfig:
        return LiveEffectiveConfig(
            stream_mode=StreamMode.LIVE_REVISION,
            decode_interval_ms=self.decode_interval_ms,
            window_ms=self.window_ms,
            raw_tail_ms=self.raw_tail_ms,
            final_lag_ms=self.final_lag_ms,
            stable_confirmations=self.stable_confirmations,
            sample_rate=self.sample_rate,
            channels=self.channels,
            format=self.audio_format,
            adaptation_mode=self.adaptation_mode,
            min_window_ms=self.min_window_ms,
            max_window_ms=self.max_window_ms,
            rtf_warn_threshold=self.rtf_warn_threshold,
            rtf_slow_threshold=self.rtf_slow_threshold,
            silence_rms_threshold=self.silence_rms_threshold,
            silence_min_ms=self.silence_min_ms,
        )

    def handle_audio_message(self, raw: dict) -> LiveDeltaMessage:
        seq = int(raw["seq"])
        audio = base64.b64decode(raw["audio_b64"])
        self.last_seq = seq
        self._append_pcm(audio)

        audio_step_ms = int(raw.get("duration_ms") or _pcm_duration_ms(len(audio), self.sample_rate, self.channels))
        should_decode = bool(raw.get("should_decode", True))
        sent_seq = int(raw.get("sent_seq") or seq)
        total_seq = int(raw.get("total_seq") or sent_seq)
        queue_chunks = max(0, max(sent_seq, total_seq) - seq)
        queue_ms = queue_chunks * max(audio_step_ms, self.decode_interval_ms)
        self._adjust_effective_window(queue_chunks=queue_chunks)
        audio_end_ms = _pcm_duration_ms(self._total_pcm_bytes, self.sample_rate, self.channels)
        window_pcm = self._window_pcm()
        buffered_ms = _pcm_duration_ms(len(window_pcm), self.sample_rate, self.channels)
        window_start_ms = max(0, audio_end_ms - buffered_ms)

        if not should_decode:
            return self._empty_delta(
                seq=seq,
                audio_step_ms=audio_step_ms,
                audio_end_ms=audio_end_ms,
                buffered_ms=buffered_ms,
                queue_chunks=queue_chunks,
                queue_ms=queue_ms,
                action="frame buffered",
            )

        if self._should_drop_decode(queue_chunks):
            self._dropped_chunks += 1
            self._last_action = "decode skipped"
            self._last_realtime_factor = 0.0
            return self._empty_delta(
                seq=seq,
                audio_step_ms=audio_step_ms,
                audio_end_ms=audio_end_ms,
                buffered_ms=buffered_ms,
                queue_chunks=queue_chunks,
                queue_ms=queue_ms,
                action=self._last_action,
            )

        started = perf_counter()
        wav_bytes = _wrap_pcm_s16le_as_wav(
            window_pcm,
            sample_rate=self.sample_rate,
            channels=self.channels,
        )
        result = self.backend.transcribe_bytes(
            wav_bytes,
            language=self.language,
            source=self.source,
            start_ms=window_start_ms,
        )
        decode_ms = int((perf_counter() - started) * 1000)
        realtime_base_ms = self.decode_interval_ms or audio_step_ms
        realtime_factor = decode_ms / realtime_base_ms if realtime_base_ms else 0.0
        self._last_realtime_factor = realtime_factor
        self._last_action = self._action_for_decode(realtime_factor)
        stabilized = self._stabilizer.accept(
            result,
            window_start_ms=window_start_ms,
            audio_end_ms=audio_end_ms,
        )
        latest_end_ms = _latest_end_ms(stabilized, default=window_start_ms)
        return LiveDeltaMessage(
            session_id=self.session_id,
            seq=seq,
            revision=stabilized.revision,
            updates=stabilized.updates,
            raw=stabilized.raw,
            stats=LiveStats(
                audio_window_ms=buffered_ms,
                buffered_ms=buffered_ms,
                decode_ms=decode_ms,
                lag_ms=max(0, audio_end_ms - latest_end_ms),
                audio_received_ms=audio_end_ms,
                audio_step_ms=audio_step_ms,
                decode_interval_ms=self.decode_interval_ms,
                realtime_factor=round(realtime_factor, 3),
                window_factor=round(decode_ms / buffered_ms, 3) if buffered_ms else 0.0,
                queue_chunks=queue_chunks,
                queue_ms=queue_ms,
                dropped_chunks=self._dropped_chunks,
                silence_skipped_ms=self._silence_skipped_ms,
                effective_window_ms=self._effective_window_ms,
                adaptation_action=self._last_action,
            ),
        )

    def handle_silence_message(self, raw: dict) -> LiveDeltaMessage:
        seq = int(raw["seq"])
        duration_ms = int(raw.get("duration_ms") or self.decode_interval_ms)
        sent_seq = int(raw.get("sent_seq") or seq)
        total_seq = int(raw.get("total_seq") or sent_seq)
        self.last_seq = seq
        self._total_pcm_bytes += _pcm_byte_count(duration_ms, self.sample_rate, self.channels)
        self._silence_skipped_ms += duration_ms
        queue_chunks = max(0, max(sent_seq, total_seq) - seq)
        queue_ms = queue_chunks * duration_ms
        buffered_ms = _pcm_duration_ms(len(self._window_pcm()), self.sample_rate, self.channels)
        return self._empty_delta(
            seq=seq,
            audio_step_ms=duration_ms,
            audio_end_ms=_pcm_duration_ms(self._total_pcm_bytes, self.sample_rate, self.channels),
            buffered_ms=buffered_ms,
            queue_chunks=queue_chunks,
            queue_ms=queue_ms,
            action="silence skipped",
        )

    def flush(self) -> LiveDeltaMessage:
        stabilized = self._stabilizer.flush()
        buffered_ms = _pcm_duration_ms(len(self._pcm), self.sample_rate, self.channels)
        return LiveDeltaMessage(
            session_id=self.session_id,
            seq=self.last_seq,
            revision=stabilized.revision,
            updates=stabilized.updates,
            raw=[],
            stats=LiveStats(
                audio_window_ms=buffered_ms,
                buffered_ms=buffered_ms,
                decode_ms=0,
                lag_ms=0,
                audio_received_ms=_pcm_duration_ms(self._total_pcm_bytes, self.sample_rate, self.channels),
                audio_step_ms=0,
                decode_interval_ms=self.decode_interval_ms,
                realtime_factor=0.0,
                window_factor=0.0,
                queue_chunks=0,
                queue_ms=0,
                dropped_chunks=self._dropped_chunks,
                silence_skipped_ms=self._silence_skipped_ms,
                effective_window_ms=self._effective_window_ms,
                adaptation_action="flush",
            ),
        )

    def _append_pcm(self, audio: bytes) -> None:
        self._pcm.extend(audio)
        self._total_pcm_bytes += len(audio)
        max_bytes = int(self.sample_rate * self.channels * 2 * self.window_ms / 1000)
        if len(self._pcm) > max_bytes:
            del self._pcm[: len(self._pcm) - max_bytes]

    def _window_pcm(self) -> bytes:
        max_bytes = int(self.sample_rate * self.channels * 2 * self._effective_window_ms / 1000)
        if len(self._pcm) <= max_bytes:
            return bytes(self._pcm)
        return bytes(self._pcm[-max_bytes:])

    def _adjust_effective_window(self, *, queue_chunks: int) -> None:
        if self.adaptation_mode not in {AdaptationMode.ADAPTIVE_WINDOW, AdaptationMode.COMBINED}:
            self._effective_window_ms = min(self.window_ms, self.max_window_ms)
            return
        step_ms = 2000
        if self._last_realtime_factor > self.rtf_slow_threshold or queue_chunks > 1:
            self._effective_window_ms = max(self.min_window_ms, self._effective_window_ms - step_ms)
            self._last_action = "window reduced"
        elif self._last_realtime_factor and self._last_realtime_factor < self.rtf_warn_threshold * 0.75 and queue_chunks == 0:
            self._effective_window_ms = min(self.max_window_ms, self._effective_window_ms + step_ms)
            self._last_action = "recovering"

    def _should_drop_decode(self, queue_chunks: int) -> bool:
        return (
            self.adaptation_mode in {AdaptationMode.DROP_STALE_DECODE, AdaptationMode.COMBINED}
            and queue_chunks > 0
        )

    def _action_for_decode(self, realtime_factor: float) -> str:
        if self.adaptation_mode in {AdaptationMode.ADAPTIVE_WINDOW, AdaptationMode.COMBINED}:
            if realtime_factor > self.rtf_slow_threshold:
                return "window reduced"
            if self._last_action == "recovering":
                return "recovering"
        if realtime_factor > self.rtf_slow_threshold:
            return "slow"
        if realtime_factor > self.rtf_warn_threshold:
            return "warning"
        return "normal"

    def _empty_delta(
        self,
        *,
        seq: int,
        audio_step_ms: int,
        audio_end_ms: int,
        buffered_ms: int,
        queue_chunks: int,
        queue_ms: int,
        action: str,
    ) -> LiveDeltaMessage:
        revision = self._stabilizer.next_empty_revision()
        return LiveDeltaMessage(
            session_id=self.session_id,
            seq=seq,
            revision=revision,
            updates=[],
            raw=[],
            stats=LiveStats(
                audio_window_ms=buffered_ms,
                buffered_ms=buffered_ms,
                decode_ms=0,
                lag_ms=0,
                audio_received_ms=audio_end_ms,
                audio_step_ms=audio_step_ms,
                decode_interval_ms=self.decode_interval_ms,
                realtime_factor=0.0,
                window_factor=0.0,
                queue_chunks=queue_chunks,
                queue_ms=queue_ms,
                dropped_chunks=self._dropped_chunks,
                silence_skipped_ms=self._silence_skipped_ms,
                effective_window_ms=self._effective_window_ms,
                adaptation_action=action,
            ),
        )


class PhraseEndpointStreamingSession:
    def __init__(
        self,
        *,
        session_id: str,
        model_id: str,
        language: str,
        source: AudioSource,
        sample_rate: int,
        channels: int,
        audio_format: str,
        phrase_silence_ms: int,
        speech_start_rms: float,
        speech_continue_rms: float,
        min_speech_ms: int,
        pre_roll_ms: int,
        max_phrase_ms: int,
        long_window_ms: int,
        long_window_step_ms: int,
        long_window_overlap_ms: int,
        urgent_min_ms: int,
    ) -> None:
        self.session_id = session_id
        self.model_id = model_id
        self.language = language
        self.source = source
        self.sample_rate = sample_rate
        self.channels = channels
        self.audio_format = audio_format
        self.phrase_silence_ms = phrase_silence_ms
        self.speech_start_rms = speech_start_rms
        self.speech_continue_rms = speech_continue_rms
        self.min_speech_ms = min_speech_ms
        self.pre_roll_ms = pre_roll_ms
        self.max_phrase_ms = max_phrase_ms
        self.long_window_ms = long_window_ms
        self.long_window_step_ms = long_window_step_ms
        self.long_window_overlap_ms = long_window_overlap_ms
        self.urgent_min_ms = urgent_min_ms
        self.backend = get_backend(model_id)
        self.last_seq = 0
        self._revision = 0
        self._total_pcm_bytes = 0
        self._pre_roll_pcm = bytearray()
        self._candidate_pcm = bytearray()
        self._candidate_start_ms = 0
        self._phrase_pcm = bytearray()
        self._phrase_start_ms = 0
        self._phrase_id = 0
        self._vad_state = "silence"
        self._trailing_silence_ms = 0
        self._next_partial_start_ms = 0
        self._next_partial_end_ms = long_window_ms
        self._partial_text = ""
        self._decoded_windows = 0
        self._last_decode_ms = 0
        self._last_stitch_confidence = "none"
        self._stitcher = FuzzyTextStitcher()

    @classmethod
    def from_start_message(cls, raw: dict) -> "PhraseEndpointStreamingSession":
        msg = StreamStartMessage.model_validate(raw)
        if msg.stream_mode != StreamMode.PHRASE_ENDPOINT:
            raise ValueError("PhraseEndpointStreamingSession requires stream_mode=phrase_endpoint")
        if msg.format != "pcm_s16le" or msg.sample_rate != 16000 or msg.channels != 1:
            raise ValueError(
                "phrase_endpoint requires pcm_s16le, 16 kHz, mono audio. "
                "Use the built-in web UI phrase emulation or stream_mode=simple for other formats."
            )
        backend = get_backend(msg.model_id)
        return cls(
            session_id=msg.session_id or str(uuid4()),
            model_id=backend.profile.id,
            language=msg.language,
            source=msg.source,
            sample_rate=msg.sample_rate,
            channels=msg.channels,
            audio_format=msg.format,
            phrase_silence_ms=msg.phrase_silence_ms,
            speech_start_rms=msg.speech_start_rms,
            speech_continue_rms=msg.speech_continue_rms,
            min_speech_ms=msg.min_speech_ms,
            pre_roll_ms=msg.pre_roll_ms,
            max_phrase_ms=msg.max_phrase_ms,
            long_window_ms=msg.long_window_ms,
            long_window_step_ms=msg.long_window_step_ms,
            long_window_overlap_ms=msg.long_window_overlap_ms,
            urgent_min_ms=msg.urgent_min_ms,
        )

    @property
    def effective_config(self) -> LiveEffectiveConfig:
        return LiveEffectiveConfig(
            stream_mode=StreamMode.PHRASE_ENDPOINT,
            decode_interval_ms=0,
            window_ms=self.long_window_ms,
            raw_tail_ms=0,
            final_lag_ms=0,
            stable_confirmations=1,
            sample_rate=self.sample_rate,
            channels=self.channels,
            format=self.audio_format,
            adaptation_mode=AdaptationMode.OFF,
            min_window_ms=self.long_window_ms,
            max_window_ms=self.long_window_ms,
            rtf_warn_threshold=1.0,
            rtf_slow_threshold=1.2,
            silence_rms_threshold=self.speech_continue_rms,
            silence_min_ms=self.phrase_silence_ms,
            phrase_silence_ms=self.phrase_silence_ms,
            speech_start_rms=self.speech_start_rms,
            speech_continue_rms=self.speech_continue_rms,
            min_speech_ms=self.min_speech_ms,
            pre_roll_ms=self.pre_roll_ms,
            max_phrase_ms=self.max_phrase_ms,
            long_window_ms=self.long_window_ms,
            long_window_step_ms=self.long_window_step_ms,
            long_window_overlap_ms=self.long_window_overlap_ms,
            urgent_min_ms=self.urgent_min_ms,
        )

    def handle_audio_message(self, raw: dict) -> LiveDeltaMessage:
        seq = int(raw["seq"])
        audio = base64.b64decode(raw["audio_b64"])
        audio_step_ms = int(raw.get("duration_ms") or _pcm_duration_ms(len(audio), self.sample_rate, self.channels))
        chunk_start_ms = _pcm_duration_ms(self._total_pcm_bytes, self.sample_rate, self.channels)
        self._total_pcm_bytes += len(audio)
        self.last_seq = seq
        rms = _pcm_rms_s16le(audio)

        finalized = self._ingest_audio(audio, rms=rms, chunk_start_ms=chunk_start_ms, duration_ms=audio_step_ms)
        if finalized is not None:
            return finalized

        partial = self._maybe_decode_long_partial(seq=seq, audio_step_ms=audio_step_ms)
        if partial is not None:
            return partial

        return self._empty_delta(seq=seq, audio_step_ms=audio_step_ms, action=self._vad_state)

    def handle_force_decode_message(self, raw: dict) -> LiveDeltaMessage:
        seq = int(raw.get("seq") or self.last_seq)
        if self._current_phrase_ms() < self.urgent_min_ms:
            return self._empty_delta(seq=seq, audio_step_ms=0, action="force ignored")
        return self._decode_current_phrase(seq=seq, status=SegmentStatus.DRAFT, action="force decode")

    def flush(self) -> LiveDeltaMessage:
        if self._phrase_pcm or self._candidate_pcm:
            self._promote_candidate_if_needed()
            return self._decode_current_phrase(
                seq=self.last_seq,
                status=SegmentStatus.FINAL,
                action="flush",
                reset_phrase=True,
            )
        return self._empty_delta(seq=self.last_seq, audio_step_ms=0, action="flush")

    def _ingest_audio(
        self,
        audio: bytes,
        *,
        rms: float,
        chunk_start_ms: int,
        duration_ms: int,
    ) -> LiveDeltaMessage | None:
        is_speech_start = rms >= self.speech_start_rms
        is_speech_continue = rms >= self.speech_continue_rms

        if self._vad_state == "silence":
            if is_speech_start:
                self._vad_state = "speech_candidate"
                self._candidate_start_ms = max(0, chunk_start_ms - self.pre_roll_ms)
                self._candidate_pcm = bytearray(self._pre_roll_pcm)
                self._candidate_pcm.extend(audio)
                self._promote_candidate_if_needed()
            else:
                self._append_pre_roll(audio)
            return None

        if self._vad_state == "speech_candidate":
            if is_speech_start:
                self._candidate_pcm.extend(audio)
                self._promote_candidate_if_needed()
            else:
                self._candidate_pcm.clear()
                self._vad_state = "silence"
                self._append_pre_roll(audio)
            return None

        self._phrase_pcm.extend(audio)
        if is_speech_continue:
            self._vad_state = "speech"
            self._trailing_silence_ms = 0
            return None

        self._vad_state = "trailing_silence"
        self._trailing_silence_ms += duration_ms
        if self._trailing_silence_ms >= self.phrase_silence_ms:
            return self._decode_current_phrase(
                seq=self.last_seq,
                status=SegmentStatus.FINAL,
                action="phrase final",
                reset_phrase=True,
            )
        return None

    def _append_pre_roll(self, audio: bytes) -> None:
        self._pre_roll_pcm.extend(audio)
        max_bytes = _pcm_byte_count(self.pre_roll_ms, self.sample_rate, self.channels)
        if len(self._pre_roll_pcm) > max_bytes:
            del self._pre_roll_pcm[: len(self._pre_roll_pcm) - max_bytes]

    def _promote_candidate_if_needed(self) -> None:
        candidate_ms = _pcm_duration_ms(len(self._candidate_pcm), self.sample_rate, self.channels)
        if candidate_ms < self.min_speech_ms:
            return
        self._phrase_id += 1
        self._phrase_start_ms = self._candidate_start_ms
        self._phrase_pcm = self._candidate_pcm
        self._candidate_pcm = bytearray()
        self._pre_roll_pcm = bytearray()
        self._trailing_silence_ms = 0
        self._next_partial_start_ms = 0
        self._next_partial_end_ms = self.long_window_ms
        self._partial_text = ""
        self._vad_state = "speech"

    def _maybe_decode_long_partial(self, *, seq: int, audio_step_ms: int) -> LiveDeltaMessage | None:
        phrase_ms = self._current_phrase_ms()
        if self._vad_state not in {"speech", "trailing_silence"}:
            return None
        if phrase_ms < self._next_partial_end_ms:
            return None
        started = perf_counter()
        window_start_ms = self._next_partial_start_ms
        window_end_ms = self._next_partial_end_ms
        result = self._transcribe_phrase_window(window_start_ms, window_end_ms)
        if result.text.strip():
            stitched = self._stitcher.append(self._partial_text, result.text)
            self._partial_text = stitched.text
            self._last_stitch_confidence = stitched.confidence
        else:
            self._last_stitch_confidence = "none"
        decode_ms = int((perf_counter() - started) * 1000)
        self._decoded_windows += 1
        self._last_decode_ms = decode_ms
        self._revision += 1
        delta = self._phrase_delta(
            seq=seq,
            status=SegmentStatus.DRAFT,
            text=self._partial_text,
            end_ms=self._phrase_start_ms + window_end_ms,
            action="long partial",
            audio_step_ms=audio_step_ms,
            decode_ms=decode_ms,
            decoded_windows=self._decoded_windows,
            stitch_confidence=self._last_stitch_confidence,
        )
        self._next_partial_start_ms += self.long_window_step_ms
        self._next_partial_end_ms = self._next_partial_start_ms + self.long_window_ms
        return delta

    def _decode_current_phrase(
        self,
        *,
        seq: int,
        status: SegmentStatus,
        action: str,
        audio_step_ms: int = 0,
        reset_phrase: bool = False,
    ) -> LiveDeltaMessage:
        started = perf_counter()
        text, decoded_windows, confidence = self._decode_phrase_text()
        decode_ms = int((perf_counter() - started) * 1000)
        self._revision += 1
        self._last_decode_ms = decode_ms
        self._decoded_windows = decoded_windows
        self._last_stitch_confidence = confidence
        phrase_ms = self._current_phrase_ms()
        delta = self._phrase_delta(
            seq=seq,
            status=status,
            text=text,
            end_ms=self._phrase_start_ms + phrase_ms,
            action=action,
            audio_step_ms=audio_step_ms,
            decode_ms=decode_ms,
            decoded_windows=decoded_windows,
            stitch_confidence=confidence,
        )
        if reset_phrase:
            self._reset_phrase_state()
        return delta

    def _phrase_delta(
        self,
        *,
        seq: int,
        status: SegmentStatus,
        text: str,
        end_ms: int,
        action: str,
        audio_step_ms: int,
        decode_ms: int,
        decoded_windows: int,
        stitch_confidence: str,
    ) -> LiveDeltaMessage:
        updates = []
        if text:
            updates.append(
                TranscriptSegment(
                    id=f"phrase-current-{self._phrase_id}",
                    source=self.source,
                    speaker=_speaker_for_source(self.source),
                    start_ms=self._phrase_start_ms,
                    end_ms=end_ms,
                    text=text,
                    status=status,
                    revision=self._revision,
                )
            )
        return LiveDeltaMessage(
            session_id=self.session_id,
            seq=seq,
            revision=self._revision,
            updates=updates,
            raw=[],
            stats=self._stats(
                audio_step_ms=audio_step_ms,
                decode_ms=decode_ms,
                decoded_windows=decoded_windows,
                action=action,
                stitch_confidence=stitch_confidence,
            ),
        )

    def _decode_phrase_text(self) -> tuple[str, int, str]:
        phrase_ms = self._current_phrase_ms()
        if phrase_ms <= 0:
            return "", 0, "none"

        windows = self._decode_windows(phrase_ms)
        stitched_text = ""
        stitch_confidence = "none"
        for start_ms, end_ms in windows:
            result = self._transcribe_phrase_window(start_ms, end_ms)
            if not result.text.strip():
                continue
            stitched = self._stitcher.append(stitched_text, result.text)
            stitched_text = stitched.text
            stitch_confidence = stitched.confidence
        return stitched_text, len(windows), stitch_confidence

    def _transcribe_phrase_window(self, start_ms: int, end_ms: int) -> TranscriptionResult:
        window_pcm = _pcm_slice_ms(
            bytes(self._phrase_pcm),
            start_ms=start_ms,
            end_ms=end_ms,
            sample_rate=self.sample_rate,
            channels=self.channels,
        )
        wav_bytes = _wrap_pcm_s16le_as_wav(
            window_pcm,
            sample_rate=self.sample_rate,
            channels=self.channels,
        )
        return self.backend.transcribe_bytes(
            wav_bytes,
            language=self.language,
            source=self.source,
            start_ms=self._phrase_start_ms + start_ms,
        )

    def _decode_windows(self, phrase_ms: int) -> list[tuple[int, int]]:
        if phrase_ms <= self.max_phrase_ms:
            return [(0, phrase_ms)]
        windows: list[tuple[int, int]] = []
        start_ms = 0
        while start_ms < phrase_ms:
            end_ms = min(start_ms + self.long_window_ms, phrase_ms)
            windows.append((start_ms, end_ms))
            if end_ms >= phrase_ms:
                break
            start_ms += self.long_window_step_ms
        return windows

    def _current_phrase_ms(self) -> int:
        return _pcm_duration_ms(len(self._phrase_pcm), self.sample_rate, self.channels)

    def _reset_phrase_state(self) -> None:
        self._phrase_pcm = bytearray()
        self._candidate_pcm = bytearray()
        self._trailing_silence_ms = 0
        self._next_partial_start_ms = 0
        self._next_partial_end_ms = self.long_window_ms
        self._partial_text = ""
        self._vad_state = "silence"

    def _empty_delta(self, *, seq: int, audio_step_ms: int, action: str) -> LiveDeltaMessage:
        self._revision += 1
        return LiveDeltaMessage(
            session_id=self.session_id,
            seq=seq,
            revision=self._revision,
            updates=[],
            raw=[],
            stats=self._stats(audio_step_ms=audio_step_ms, decode_ms=0, action=action),
        )

    def _stats(
        self,
        *,
        audio_step_ms: int,
        decode_ms: int,
        action: str,
        decoded_windows: int = 0,
        stitch_confidence: str | None = None,
    ) -> LiveStats:
        phrase_ms = self._current_phrase_ms()
        realtime_base_ms = max(phrase_ms, audio_step_ms, 1)
        return LiveStats(
            audio_window_ms=phrase_ms,
            buffered_ms=phrase_ms,
            decode_ms=decode_ms,
            lag_ms=0,
            audio_received_ms=_pcm_duration_ms(self._total_pcm_bytes, self.sample_rate, self.channels),
            audio_step_ms=audio_step_ms,
            decode_interval_ms=0,
            realtime_factor=round(decode_ms / realtime_base_ms, 3) if decode_ms else 0.0,
            window_factor=round(decode_ms / phrase_ms, 3) if decode_ms and phrase_ms else 0.0,
            queue_chunks=0,
            queue_ms=0,
            dropped_chunks=0,
            silence_skipped_ms=0,
            effective_window_ms=phrase_ms,
            adaptation_action=action,
            vad_state=self._vad_state,
            current_phrase_ms=phrase_ms,
            phrase_id=self._phrase_id,
            decoded_windows=decoded_windows,
            stitch_confidence=stitch_confidence or self._last_stitch_confidence,
        )


def _latest_end_ms(stabilized: LiveStabilizerResult, *, default: int) -> int:
    segments = [*stabilized.updates, *stabilized.raw]
    if not segments:
        return default
    return max(segment.end_ms for segment in segments)
