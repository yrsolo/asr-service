from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class AudioSource(StrEnum):
    MIC = "mic"
    SYSTEM = "system"
    MIXED = "mixed"
    UNKNOWN = "unknown"


class Speaker(StrEnum):
    USER = "user"
    OTHER = "other"
    UNKNOWN = "unknown"


class SegmentStatus(StrEnum):
    FINAL = "final"
    UNSTABLE = "unstable"


class TranscriptSegment(BaseModel):
    id: str
    source: AudioSource = AudioSource.UNKNOWN
    speaker: Speaker = Speaker.UNKNOWN
    start_ms: int = 0
    end_ms: int = 0
    text: str
    status: SegmentStatus = SegmentStatus.FINAL
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    revision: int = 0


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    service: str = "local-asr-service"
    version: str
    backend: str
    default_model: str
    gpu_available: bool
    cuda_device_index: int | None = None


class ModelInfo(BaseModel):
    id: str
    backend: str
    model_name: str
    device: str
    device_index: int | None = None
    compute_type: str
    languages: list[str]
    description: str = ""
    beam_size: int = 5
    vad_filter: bool = True
    download: bool = True


class ModelsResponse(BaseModel):
    default_model: str
    models: list[ModelInfo]


class TranscribeResponse(BaseModel):
    request_id: str
    model_id: str
    language: str = "auto"
    duration_ms: int | None = None
    processing_ms: int
    segments: list[TranscriptSegment]
    text: str


class ChunkTranscribeResponse(BaseModel):
    session_id: str
    seq: int
    model_id: str
    segments: list[TranscriptSegment]
    unstable_text: str = ""
    processing_ms: int


class StreamStartMessage(BaseModel):
    type: Literal["start"]
    session_id: str | None = None
    model_id: str | None = None
    language: str = "auto"
    source: AudioSource = AudioSource.UNKNOWN
    sample_rate: int = 16000
    channels: int = 1
    format: str = "pcm_s16le"


class SessionStartedMessage(BaseModel):
    type: Literal["session_started"] = "session_started"
    session_id: str
    model_id: str


class TranscriptDeltaMessage(BaseModel):
    type: Literal["transcript_delta"] = "transcript_delta"
    session_id: str
    seq: int
    segments: list[TranscriptSegment]
    unstable: list[TranscriptSegment] = Field(default_factory=list)


class ErrorMessage(BaseModel):
    type: Literal["error"] = "error"
    code: str
    message: str
