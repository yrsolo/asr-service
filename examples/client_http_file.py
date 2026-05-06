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
    parser.add_argument("--stream", action="store_true", help="Use NDJSON progress endpoint")
    args = parser.parse_args()

    with args.audio_file.open("rb") as f:
        if args.stream:
            with requests.post(
                f"{args.url}/v1/transcribe/file",
                files={"file": (args.audio_file.name, f, "audio/wav")},
                data={
                    "model_id": args.model,
                    "language": args.language,
                    "source": "unknown",
                    "stream": "true",
                },
                stream=True,
                timeout=(10, None),
            ) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines(decode_unicode=True):
                    if not line:
                        continue
                    event = json.loads(line)
                    print(json.dumps(event, ensure_ascii=False, indent=2))
        else:
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
