import argparse
import asyncio
import base64
import json
from pathlib import Path

import websockets


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("audio_file", type=Path, help="Small WAV file used as one fake chunk")
    parser.add_argument("--url", default="ws://127.0.0.1:8765/v1/stream")
    parser.add_argument("--model", default="mock")
    parser.add_argument("--language", default="auto")
    args = parser.parse_args()

    async with websockets.connect(args.url) as ws:
        await ws.send(json.dumps({
            "type": "start",
            "model_id": args.model,
            "language": args.language,
            "source": "mic",
            "sample_rate": 16000,
            "channels": 1,
            "format": "pcm_s16le",
        }))
        print(await ws.recv())

        payload = base64.b64encode(args.audio_file.read_bytes()).decode("ascii")
        await ws.send(json.dumps({"type": "audio", "seq": 1, "start_ms": 0, "audio_b64": payload}))
        print(await ws.recv())

        await ws.send(json.dumps({"type": "close"}))


if __name__ == "__main__":
    asyncio.run(main())
