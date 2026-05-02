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
    DRAFT = "draft"
    FINAL = "final"
    UNSTABLE = "unstable"


class StreamMode(StrEnum):
    SIMPLE = "simple"
    LIVE_REVISION = "live_revision"
    PHRASE_ENDPOINT = "phrase_endpoint"


class AdaptationMode(StrEnum):
    OFF = "off"
    SILENCE_GATE = "silence_gate"
    ADAPTIVE_WINDOW = "adaptive_window"
    DROP_STALE_DECODE = "drop_stale_decode"
    COMBINED = "combined"


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
    stream_mode: StreamMode = StreamMode.SIMPLE
    decode_interval_ms: int = Field(default=1000, ge=250, le=5000)
    window_ms: int = Field(default=8000, ge=1000, le=60000)
    raw_tail_ms: int = Field(default=1500, ge=250, le=5000)
    final_lag_ms: int = Field(default=4000, ge=1000, le=30000)
    stable_confirmations: int = Field(default=2, ge=1, le=5)
    adaptation_mode: AdaptationMode = AdaptationMode.OFF
    min_window_ms: int = Field(default=4000, ge=1000, le=60000)
    max_window_ms: int | None = Field(default=None, ge=1000, le=60000)
    rtf_warn_threshold: float = Field(default=1.0, gt=0)
    rtf_slow_threshold: float = Field(default=1.2, gt=0)
    silence_rms_threshold: float = Field(default=0.01, ge=0.0, le=1.0)
    silence_min_ms: int = Field(default=500, ge=0, le=30000)
    phrase_silence_ms: int = Field(default=700, ge=100, le=5000)
    speech_start_rms: float = Field(default=0.012, ge=0.0, le=1.0)
    speech_continue_rms: float = Field(default=0.008, ge=0.0, le=1.0)
    min_speech_ms: int = Field(default=250, ge=0, le=5000)
    pre_roll_ms: int = Field(default=300, ge=0, le=5000)
    max_phrase_ms: int = Field(default=12000, ge=1000, le=120000)
    long_window_ms: int = Field(default=12000, ge=1000, le=120000)
    long_window_step_ms: int = Field(default=8000, ge=500, le=120000)
    long_window_overlap_ms: int = Field(default=4000, ge=0, le=120000)
    urgent_min_ms: int = Field(default=800, ge=0, le=30000)


class LiveEffectiveConfig(BaseModel):
    stream_mode: StreamMode
    decode_interval_ms: int
    window_ms: int
    raw_tail_ms: int
    final_lag_ms: int
    stable_confirmations: int
    sample_rate: int
    channels: int
    format: str
    adaptation_mode: AdaptationMode
    min_window_ms: int
    max_window_ms: int
    rtf_warn_threshold: float
    rtf_slow_threshold: float
    silence_rms_threshold: float
    silence_min_ms: int
    phrase_silence_ms: int = 700
    speech_start_rms: float = 0.012
    speech_continue_rms: float = 0.008
    min_speech_ms: int = 250
    pre_roll_ms: int = 300
    max_phrase_ms: int = 12000
    long_window_ms: int = 12000
    long_window_step_ms: int = 8000
    long_window_overlap_ms: int = 4000
    urgent_min_ms: int = 800


class SessionStartedMessage(BaseModel):
    type: Literal["session_started"] = "session_started"
    session_id: str
    model_id: str
    effective_config: LiveEffectiveConfig | None = None


class TranscriptDeltaMessage(BaseModel):
    type: Literal["transcript_delta"] = "transcript_delta"
    session_id: str
    seq: int
    segments: list[TranscriptSegment]
    unstable: list[TranscriptSegment] = Field(default_factory=list)


class LiveStats(BaseModel):
    audio_window_ms: int
    buffered_ms: int
    decode_ms: int
    lag_ms: int
    audio_received_ms: int = 0
    audio_step_ms: int = 0
    decode_interval_ms: int = 0
    realtime_factor: float = 0.0
    window_factor: float = 0.0
    queue_chunks: int = 0
    queue_ms: int = 0
    dropped_chunks: int = 0
    silence_skipped_ms: int = 0
    effective_window_ms: int = 0
    adaptation_action: str = "normal"
    vad_state: str = "silence"
    current_phrase_ms: int = 0
    phrase_id: int = 0
    decoded_windows: int = 0
    stitch_confidence: str = "none"


class LiveDeltaMessage(BaseModel):
    type: Literal["live_delta"] = "live_delta"
    session_id: str
    seq: int
    revision: int
    updates: list[TranscriptSegment] = Field(default_factory=list)
    raw: list[TranscriptSegment] = Field(default_factory=list)
    stats: LiveStats


class ErrorMessage(BaseModel):
    type: Literal["error"] = "error"
    code: str
    message: str
