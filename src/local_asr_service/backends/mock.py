from uuid import uuid4

from local_asr_service.backends.base import ASRBackend, TranscriptionResult
from local_asr_service.schemas import AudioSource, SegmentStatus, Speaker, TranscriptSegment


class MockASRBackend(ASRBackend):
    def transcribe_bytes(
        self,
        data: bytes,
        *,
        language: str = "auto",
        source: AudioSource = AudioSource.UNKNOWN,
        start_ms: int = 0,
    ) -> TranscriptionResult:
        speaker = Speaker.USER if source == AudioSource.MIC else Speaker.OTHER
        text = "Это тестовый фрагмент распознавания речи."
        segment = TranscriptSegment(
            id=str(uuid4()),
            source=source,
            speaker=speaker,
            start_ms=start_ms,
            end_ms=start_ms + 2500,
            text=text,
            status=SegmentStatus.FINAL,
            confidence=None,
            revision=0,
        )
        return TranscriptionResult(segments=[segment], text=text, duration_ms=2500)
