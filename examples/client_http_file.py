import argparse
import json
from pathlib import Path

import requests


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("audio_file", type=Path)
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    parser.add_argument("--model", default="mock")
    parser.add_argument("--language", default="auto")
    args = parser.parse_args()

    with args.audio_file.open("rb") as f:
        resp = requests.post(
            f"{args.url}/v1/transcribe/file",
            files={"file": (args.audio_file.name, f, "audio/wav")},
            data={"model_id": args.model, "language": args.language, "source": "unknown"},
            timeout=120,
        )
    resp.raise_for_status()
    print(json.dumps(resp.json(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
