from __future__ import annotations

import ctypes
import ctypes.util
import json
import os
from pathlib import Path


CUDA_ERRORS = {
    0: "CUDA_SUCCESS",
    2: "CUDA_ERROR_OUT_OF_MEMORY",
    3: "CUDA_ERROR_NOT_INITIALIZED",
    4: "CUDA_ERROR_DEINITIALIZED",
    100: "CUDA_ERROR_NO_DEVICE",
    201: "CUDA_ERROR_INVALID_CONTEXT",
    209: "CUDA_ERROR_NO_BINARY_FOR_GPU",
    500: "CUDA_ERROR_NOT_FOUND",
    804: "CUDA_ERROR_COMPAT_NOT_SUPPORTED_ON_DEVICE",
}


def _err_name(code: int) -> str:
    return CUDA_ERRORS.get(code, f"CUDA_ERROR_{code}")


def _load_libcuda():
    candidates = [
        ctypes.util.find_library("cuda"),
        "libcuda.so.1",
        "/usr/lib/wsl/lib/libcuda.so.1",
    ]
    errors = []
    for candidate in candidates:
        if not candidate:
            continue
        try:
            return ctypes.CDLL(candidate), candidate, errors
        except OSError as exc:
            errors.append({"candidate": candidate, "error": str(exc)})
    return None, None, errors


def main() -> None:
    libcuda, loaded_from, load_errors = _load_libcuda()
    report: dict = {
        "env": {
            "CUDA_VISIBLE_DEVICES": os.getenv("CUDA_VISIBLE_DEVICES"),
            "NVIDIA_VISIBLE_DEVICES": os.getenv("NVIDIA_VISIBLE_DEVICES"),
            "NVIDIA_DRIVER_CAPABILITIES": os.getenv("NVIDIA_DRIVER_CAPABILITIES"),
            "LD_LIBRARY_PATH": os.getenv("LD_LIBRARY_PATH"),
        },
        "paths": {
            "/dev/dxg": Path("/dev/dxg").exists(),
            "/usr/lib/wsl/lib/libcuda.so.1": Path("/usr/lib/wsl/lib/libcuda.so.1").exists(),
        },
        "libcuda": {
            "loaded": libcuda is not None,
            "loaded_from": loaded_from,
            "load_errors": load_errors,
        },
    }

    if libcuda is None:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return

    cu_init = libcuda.cuInit
    cu_init.argtypes = [ctypes.c_uint]
    cu_init.restype = ctypes.c_int
    init_code = int(cu_init(0))
    report["cuInit"] = {"code": init_code, "name": _err_name(init_code)}

    cu_device_get_count = libcuda.cuDeviceGetCount
    cu_device_get_count.argtypes = [ctypes.POINTER(ctypes.c_int)]
    cu_device_get_count.restype = ctypes.c_int
    count = ctypes.c_int(-1)
    count_code = int(cu_device_get_count(ctypes.byref(count)))
    report["cuDeviceGetCount"] = {
        "code": count_code,
        "name": _err_name(count_code),
        "count": count.value,
    }

    devices = []
    if init_code == 0 and count_code == 0 and count.value > 0:
        cu_device_get = libcuda.cuDeviceGet
        cu_device_get.argtypes = [ctypes.POINTER(ctypes.c_int), ctypes.c_int]
        cu_device_get.restype = ctypes.c_int
        cu_device_get_name = libcuda.cuDeviceGetName
        cu_device_get_name.argtypes = [ctypes.c_char_p, ctypes.c_int, ctypes.c_int]
        cu_device_get_name.restype = ctypes.c_int

        for index in range(count.value):
            device = ctypes.c_int()
            get_code = int(cu_device_get(ctypes.byref(device), index))
            name_buf = ctypes.create_string_buffer(256)
            name_code = int(cu_device_get_name(name_buf, len(name_buf), device.value))
            devices.append(
                {
                    "index": index,
                    "cuDeviceGet": {"code": get_code, "name": _err_name(get_code)},
                    "cuDeviceGetName": {"code": name_code, "name": _err_name(name_code)},
                    "device_name": name_buf.value.decode(errors="replace"),
                }
            )
    report["devices"] = devices

    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
