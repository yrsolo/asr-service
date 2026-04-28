from functools import lru_cache

from local_asr_service.backends.base import ASRBackend
from local_asr_service.backends.faster_whisper_backend import FasterWhisperBackend
from local_asr_service.backends.mock import MockASRBackend
from local_asr_service.config import load_models_config


@lru_cache
def get_backend(model_id: str | None = None) -> ASRBackend:
    cfg = load_models_config()
    profile = cfg.get_profile(model_id)
    if profile.backend == "mock":
        return MockASRBackend(profile)
    if profile.backend == "faster_whisper":
        return FasterWhisperBackend(profile)
    raise ValueError(f"Unsupported backend: {profile.backend}")
