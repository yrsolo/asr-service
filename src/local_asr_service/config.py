from functools import lru_cache
import os
from pathlib import Path
import subprocess
from typing import Literal

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ModelProfile(BaseModel):
    id: str
    backend: Literal["mock", "faster_whisper", "whisper_cpp"]
    model_name: str
    device: str = "auto"
    device_index: int | None = None
    compute_type: str = "auto"
    languages: list[str] = Field(default_factory=lambda: ["ru", "en", "auto"])
    description: str = ""
    beam_size: int = 5
    vad_filter: bool = True
    download: bool = True


class ModelsConfig(BaseModel):
    default_model: str = "mock"
    models: list[ModelProfile]

    def get_profile(self, model_id: str | None) -> ModelProfile:
        target = model_id or self.default_model
        for model in self.models:
            if model.id == target:
                return model
        raise KeyError(f"Unknown model profile: {target}")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="LOCAL_ASR_", extra="ignore")

    host: str = "127.0.0.1"
    port: int = 8765
    log_level: str = "info"
    api_key: str = ""

    default_model: str = "mock"
    models_config: str = "config/models.example.yaml"
    cuda_device_index: int | None = None

    save_audio: bool = False
    save_transcripts: bool = False
    debug_transcripts: bool = False

    sample_rate: int = 16000
    chunk_seconds: float = 5.0
    overlap_seconds: float = 1.0


@lru_cache
def get_settings() -> Settings:
    return Settings()


def _cuda_index_for_visible_uuid(gpu_uuid: str) -> int | None:
    cmd = [
        "nvidia-smi",
        "--query-gpu=index,uuid",
        "--format=csv,noheader,nounits",
    ]
    try:
        completed = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=10)
    except Exception:
        return None

    for line in completed.stdout.strip().splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) != 2:
            continue
        index, visible_uuid = parts
        if visible_uuid == gpu_uuid:
            try:
                return int(index)
            except ValueError:
                return None
    return None


def resolve_cuda_device_index(profile_device_index: int | None = None) -> int | None:
    """Resolve the CUDA index the process should pass to CTranslate2.

    Docker Desktop / WSL can show multiple GPUs inside the container even when
    NVIDIA_VISIBLE_DEVICES contains one UUID. In that case CUDA indices are not
    remapped to 0, so prefer the UUID-to-visible-index mapping over the manual
    LOCAL_ASR_CUDA_DEVICE_INDEX value.
    """
    visible_devices = (os.getenv("NVIDIA_VISIBLE_DEVICES") or "").strip()
    if visible_devices.startswith("GPU-") and "," not in visible_devices:
        uuid_index = _cuda_index_for_visible_uuid(visible_devices)
        if uuid_index is not None:
            return uuid_index

    settings = get_settings()
    if settings.cuda_device_index is not None:
        return settings.cuda_device_index
    return profile_device_index


@lru_cache
def load_models_config() -> ModelsConfig:
    settings = get_settings()
    path = Path(settings.models_config)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    cfg = ModelsConfig.model_validate(data)
    if settings.default_model:
        cfg.default_model = settings.default_model
    return cfg
