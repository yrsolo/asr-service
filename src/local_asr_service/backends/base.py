from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass

from local_asr_service.config import ModelProfile
from local_asr_service.schemas import AudioSource, TranscriptSegment


@dataclass
class TranscriptionResult:
    segments: list[TranscriptSegment]
    text: str
    duration_ms: int | None = None


@dataclass
class TranscriptionStreamEvent:
    type: str
    message: str = ""
    segment: TranscriptSegment | None = None
    result: TranscriptionResult | None = None
    seq: int = 0


class ASRBackend(ABC):
    def __init__(self, profile: ModelProfile) -> None:
        self.profile = profile

    @abstractmethod
    def transcribe_bytes(
        self,
        data: bytes,
        *,
        language: str = "auto",
        source: AudioSource = AudioSource.UNKNOWN,
        start_ms: int = 0,
    ) -> TranscriptionResult:
        raise NotImplementedError

    def transcribe_bytes_stream(
        self,
        data: bytes,
        *,
        language: str = "auto",
        source: AudioSource = AudioSource.UNKNOWN,
        start_ms: int = 0,
    ) -> Iterator[TranscriptionStreamEvent]:
        yield TranscriptionStreamEvent(type="progress", message="ASR decode started")
        result = self.transcribe_bytes(
            data,
            language=language,
            source=source,
            start_ms=start_ms,
        )
        for seq, segment in enumerate(result.segments, start=1):
            yield TranscriptionStreamEvent(type="segment", segment=segment, seq=seq)
        yield TranscriptionStreamEvent(type="completed", result=result)
