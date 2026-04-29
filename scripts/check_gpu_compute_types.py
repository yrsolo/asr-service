from __future__ import annotations

import argparse
import json
import os


def main() -> None:
    parser = argparse.ArgumentParser(description="Print CTranslate2 compute types for a device.")
    parser.add_argument("--device", default="cuda", choices=["cuda", "cpu"])
    parser.add_argument("--device-index", type=int, default=None)
    args = parser.parse_args()

    import ctranslate2

    device_index = args.device_index
    if device_index is None:
        device_index = int(os.getenv("LOCAL_ASR_CUDA_DEVICE_INDEX") or "0")

    get_cuda_device_count = getattr(ctranslate2, "get_cuda_device_count", None)
    cuda_count = get_cuda_device_count() if get_cuda_device_count else None
    supported = sorted(
        ctranslate2.get_supported_compute_types(args.device, device_index=device_index)
    )

    print(
        json.dumps(
            {
                "device": args.device,
                "device_index": device_index,
                "cuda_device_count": cuda_count,
                "supported_compute_types": supported,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
