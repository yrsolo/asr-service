from types import SimpleNamespace

from local_asr_service.config import get_settings, resolve_cuda_device_index


def test_resolve_cuda_device_index_prefers_visible_uuid(monkeypatch) -> None:
    def fake_run(*args, **kwargs):
        return SimpleNamespace(
            stdout=(
                "0, GPU-c11608a2-fa23-6399-d77b-bb8719fb2e1a\n"
                "1, GPU-120ee067-90c0-9f37-cb07-6879e7c3adda\n"
                "2, GPU-625140a3-7883-808e-d15a-4b630bf94ef3\n"
            )
        )

    monkeypatch.setenv("NVIDIA_VISIBLE_DEVICES", "GPU-625140a3-7883-808e-d15a-4b630bf94ef3")
    monkeypatch.setenv("LOCAL_ASR_CUDA_DEVICE_INDEX", "0")
    monkeypatch.setattr("local_asr_service.config.subprocess.run", fake_run)
    get_settings.cache_clear()

    try:
        assert resolve_cuda_device_index() == 2
    finally:
        get_settings.cache_clear()


def test_resolve_cuda_device_index_falls_back_to_local_asr_index(monkeypatch) -> None:
    monkeypatch.delenv("NVIDIA_VISIBLE_DEVICES", raising=False)
    monkeypatch.setenv("LOCAL_ASR_CUDA_DEVICE_INDEX", "1")

    get_settings.cache_clear()
    try:
        assert resolve_cuda_device_index() == 1
    finally:
        get_settings.cache_clear()
