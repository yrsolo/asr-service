import base64
from uuid import uuid4

from local_asr_service.backends.factory import get_backend
from local_asr_service.schemas import AudioSource, SegmentStatus, StreamStartMessage, TranscriptDeltaMessage
from local_asr_service.schemas import TranscriptSegment


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
