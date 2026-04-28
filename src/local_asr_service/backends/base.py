from abc import ABC, abstractmethod
from dataclasses import dataclass

from local_asr_service.config import ModelProfile
from local_asr_service.schemas import AudioSource, TranscriptSegment


@dataclass
class TranscriptionResult:
    segments: list[TranscriptSegment]
    text: str
    duration_ms: int | None = None


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
