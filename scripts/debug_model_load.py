from __future__ import annotations

import argparse
import io
import json
import os
import subprocess
import sys
import wave
from pathlib import Path
from tempfile import NamedTemporaryFile
from time import perf_counter

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if SRC_DIR.exists():
    sys.path.insert(0, str(SRC_DIR))

from local_asr_service.config import get_settings, load_models_config  # noqa: E402


def _nvidia_smi() -> dict:
    cmd = [
        "nvidia-smi",
        "--query-gpu=index,uuid,name,memory.total,memory.used,memory.free",
        "--format=csv,noheader,nounits",
    ]
    try:
        completed = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=15)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    gpus = []
    for line in completed.stdout.strip().splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) != 6:
            continue
        index, uuid, name, total, used, free = parts
        gpus.append(
            {
                "index": index,
                "uuid": uuid,
                "name": name,
                "memory_total_mb": int(total),
                "memory_used_mb": int(used),
                "memory_free_mb": int(free),
            }
        )
    return {"ok": True, "gpus": gpus}


def _silence_wav(seconds: int = 1) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\x00\x00" * 16000 * seconds)
    return buf.getvalue()


def _ct2_info(device: str, device_index: int) -> dict:
    try:
        import ctranslate2

        get_count = getattr(ctranslate2, "get_cuda_device_count", None)
        cuda_count = get_count() if get_count else None
        supported = sorted(ctranslate2.get_supported_compute_types(device, device_index=device_index))
        return {
            "ok": True,
            "version": getattr(ctranslate2, "__version__", None),
            "cuda_device_count": cuda_count,
            "supported_compute_types": supported,
        }
    except Exception as exc:
        return {"ok": False, "error": repr(exc)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Debug faster-whisper model loading and CUDA memory.")
    parser.add_argument("--model", default=None, help="Model profile id. Defaults to LOCAL_ASR_DEFAULT_MODEL.")
    parser.add_argument("--language", default="ru")
    parser.add_argument("--device-index", type=int, default=None, help="Override CUDA device index.")
    parser.add_argument("--audio-file", type=Path, default=None, help="Optional audio file to transcribe.")
    parser.add_argument("--skip-transcribe", action="store_true", help="Only load the model.")
    args = parser.parse_args()

    settings = get_settings()
    cfg = load_models_config()
    profile = cfg.get_profile(args.model)
    device_index = args.device_index
    if device_index is None:
        device_index = settings.cuda_device_index
    if device_index is None:
        device_index = profile.device_index
    if device_index is None:
        device_index = 0

    report: dict = {
        "env": {
            "LOCAL_ASR_DEFAULT_MODEL": os.getenv("LOCAL_ASR_DEFAULT_MODEL"),
            "LOCAL_ASR_CUDA_DEVICE_INDEX": os.getenv("LOCAL_ASR_CUDA_DEVICE_INDEX"),
            "NVIDIA_VISIBLE_DEVICES": os.getenv("NVIDIA_VISIBLE_DEVICES"),
            "NVIDIA_DRIVER_CAPABILITIES": os.getenv("NVIDIA_DRIVER_CAPABILITIES"),
            "HF_HOME": os.getenv("HF_HOME"),
            "LD_LIBRARY_PATH": os.getenv("LD_LIBRARY_PATH"),
        },
        "profile": profile.model_dump(),
        "selected_device_index": device_index,
        "nvidia_smi_before": _nvidia_smi(),
        "ctranslate2": _ct2_info(profile.device, device_index),
    }

    if profile.backend != "faster_whisper":
        report["load"] = {
            "ok": False,
            "skipped": True,
            "reason": f"Profile backend is {profile.backend!r}, not 'faster_whisper'.",
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return

    try:
        from faster_whisper import WhisperModel

        kwargs = {"device": profile.device, "compute_type": profile.compute_type}
        if profile.device == "cuda":
            kwargs["device_index"] = device_index

        started = perf_counter()
        model = WhisperModel(profile.model_name, **kwargs)
        report["load"] = {
            "ok": True,
            "seconds": round(perf_counter() - started, 3),
            "kwargs": kwargs,
        }
        report["nvidia_smi_after_load"] = _nvidia_smi()

        if not args.skip_transcribe:
            if args.audio_file:
                audio_path = args.audio_file
                cleanup_path = None
            else:
                tmp = NamedTemporaryFile(suffix=".wav", delete=False)
                tmp.write(_silence_wav())
                tmp.close()
                audio_path = Path(tmp.name)
                cleanup_path = audio_path

            try:
                started = perf_counter()
                segments_iter, info = model.transcribe(
                    str(audio_path),
                    language=None if args.language == "auto" else args.language,
                    vad_filter=profile.vad_filter,
                    beam_size=profile.beam_size,
                )
                texts = [segment.text.strip() for segment in segments_iter if segment.text.strip()]
                report["transcribe"] = {
                    "ok": True,
                    "seconds": round(perf_counter() - started, 3),
                    "duration": getattr(info, "duration", None),
                    "text_preview": " ".join(texts)[:200],
                    "segments": len(texts),
                }
                report["nvidia_smi_after_transcribe"] = _nvidia_smi()
            finally:
                if cleanup_path is not None:
                    cleanup_path.unlink(missing_ok=True)
    except Exception as exc:
        report["error"] = {"type": type(exc).__name__, "message": str(exc), "repr": repr(exc)}
        report["nvidia_smi_after_error"] = _nvidia_smi()

    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
