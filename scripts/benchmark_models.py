from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from time import perf_counter

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if SRC_DIR.exists():
    sys.path.insert(0, str(SRC_DIR))

from local_asr_service.backends.factory import get_backend  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("audio_file", type=Path)
    parser.add_argument("--models", required=True, help="Comma-separated model ids")
    parser.add_argument("--language", default="auto")
    args = parser.parse_args()

    data = args.audio_file.read_bytes()
    results = []
    for model_id in [m.strip() for m in args.models.split(",") if m.strip()]:
        backend = get_backend(model_id)
        started = perf_counter()
        result = backend.transcribe_bytes(data, language=args.language)
        processing_sec = perf_counter() - started
        duration_sec = (result.duration_ms or 0) / 1000 if result.duration_ms else None
        rtf = processing_sec / duration_sec if duration_sec else None
        results.append(
            {
                "model_id": backend.profile.id,
                "backend": backend.profile.backend,
                "model_name": backend.profile.model_name,
                "processing_sec": round(processing_sec, 3),
                "duration_sec": duration_sec,
                "rtf": round(rtf, 3) if rtf else None,
                "text_len": len(result.text),
                "text_preview": result.text[:300],
            }
        )

    print(json.dumps({"audio_file": str(args.audio_file), "results": results}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
