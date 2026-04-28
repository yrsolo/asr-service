from __future__ import annotations

import argparse
import inspect
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if SRC_DIR.exists():
    sys.path.insert(0, str(SRC_DIR))

from local_asr_service.config import load_models_config  # noqa: E402


def _download_model(model_name: str, cache_dir: Path | None) -> str:
    from faster_whisper.utils import download_model

    kwargs = {}
    params = inspect.signature(download_model).parameters
    if cache_dir is not None:
        if "cache_dir" in params:
            kwargs["cache_dir"] = str(cache_dir)
        elif "output_dir" in params:
            kwargs["output_dir"] = str(cache_dir / model_name.replace("/", "_"))

    path = download_model(model_name, **kwargs)
    return str(path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Prefetch faster-whisper/CTranslate2 models.")
    parser.add_argument(
        "--models",
        default="download",
        help=(
            "Comma-separated profile ids. Use 'download' for every profile with download=true, "
            "or 'all' for every non-mock faster-whisper profile."
        ),
    )
    parser.add_argument("--cache-dir", type=Path, default=None, help="Optional Hugging Face cache/output dir.")
    parser.add_argument("--dry-run", action="store_true", help="Print the planned downloads only.")
    args = parser.parse_args()

    cfg = load_models_config()
    if args.models == "download":
        profiles = [p for p in cfg.models if p.backend == "faster_whisper" and p.download]
    elif args.models == "all":
        profiles = [p for p in cfg.models if p.backend == "faster_whisper"]
    else:
        requested = {m.strip() for m in args.models.split(",") if m.strip()}
        profiles = [p for p in cfg.models if p.id in requested]
        missing = requested - {p.id for p in profiles}
        if missing:
            raise SystemExit(f"Unknown model profile(s): {', '.join(sorted(missing))}")

    plan = [
        {
            "id": profile.id,
            "model_name": profile.model_name,
            "device": profile.device,
            "compute_type": profile.compute_type,
        }
        for profile in profiles
    ]

    if args.dry_run:
        print(json.dumps({"planned": plan}, ensure_ascii=False, indent=2))
        return

    results = []
    for profile in profiles:
        path = _download_model(profile.model_name, args.cache_dir)
        results.append({"id": profile.id, "model_name": profile.model_name, "path": path})

    print(json.dumps({"downloaded": results}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
