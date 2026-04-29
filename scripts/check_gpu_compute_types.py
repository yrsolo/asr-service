from __future__ import annotations

import argparse
import json


def main() -> None:
    parser = argparse.ArgumentParser(description="Print CTranslate2 compute types for a device.")
    parser.add_argument("--device", default="cuda", choices=["cuda", "cpu"])
    parser.add_argument("--device-index", type=int, default=0)
    args = parser.parse_args()

    import ctranslate2

    get_cuda_device_count = getattr(ctranslate2, "get_cuda_device_count", None)
    cuda_count = get_cuda_device_count() if get_cuda_device_count else None
    supported = sorted(
        ctranslate2.get_supported_compute_types(args.device, device_index=args.device_index)
    )

    print(
        json.dumps(
            {
                "device": args.device,
                "device_index": args.device_index,
                "cuda_device_count": cuda_count,
                "supported_compute_types": supported,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
