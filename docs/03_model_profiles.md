# Model Profiles

## Goal

Make it easy to benchmark several ASR models on a separate GPU machine, especially a GTX 1080 Ti 11 GB class host.

## Current Profiles

Profiles are configured in `config/models.example.yaml`.

```yaml
models:
  - id: mock
    backend: mock
    model_name: mock
    device: cpu
    device_index:
    compute_type: auto
    beam_size: 1
    vad_filter: false
    download: false

  - id: fw-tiny-cpu
    backend: faster_whisper
    model_name: tiny
    device: cpu
    device_index:
    compute_type: int8
    beam_size: 1
    vad_filter: true
    download: true

  - id: fw-small-int8
    backend: faster_whisper
    model_name: small
    device: cuda
    device_index:
    compute_type: int8
    beam_size: 3
    vad_filter: true
    download: true

  - id: fw-medium-int8-fp16
    backend: faster_whisper
    model_name: medium
    device: cuda
    device_index:
    compute_type: int8_float16
    beam_size: 5
    vad_filter: true
    download: true

  - id: fw-medium-int8
    backend: faster_whisper
    model_name: medium
    device: cuda
    device_index:
    compute_type: int8
    beam_size: 5
    vad_filter: true
    download: true

  - id: fw-large-v3-turbo-int8-fp16
    backend: faster_whisper
    model_name: large-v3-turbo
    device: cuda
    device_index:
    compute_type: int8_float16
    beam_size: 5
    vad_filter: true
    download: true

  - id: fw-large-v3-turbo-int8
    backend: faster_whisper
    model_name: large-v3-turbo
    device: cuda
    device_index:
    compute_type: int8
    beam_size: 5
    vad_filter: true
    download: true
```

## Recommended Test Order

1. `mock`: validate API, UI, auth, and client integration without ASR cost.
2. `fw-tiny-cpu`: validate real audio decoding on any machine.
3. `fw-small-int8`: first CUDA smoke test.
4. `fw-medium-int8`: first serious Russian/English candidate for GTX 1080 Ti / Pascal.
5. `fw-large-v3-turbo-int8`: best quality candidate for GTX 1080 Ti / Pascal; benchmark latency.
6. `fw-medium-int8-fp16` or `fw-large-v3-turbo-int8-fp16`: use on newer GPUs with efficient FP16/Tensor Core support.

## What to Measure

For each model:

- first load time;
- VRAM usage;
- processing time;
- real-time factor;
- Russian quality;
- English quality;
- mixed Russian/English quality;
- hallucinations during silence;
- stability with chunk sizes 2s, 3s, 5s, and 10s.

## Real-Time Factor

```text
RTF = processing_time_seconds / audio_duration_seconds
```

Interpretation:

- `RTF < 1.0`: faster than real time;
- `RTF < 0.5`: comfortable;
- `RTF < 0.25`: excellent.

## GTX 1080 Ti Notes

GTX 1080 Ti has 11 GB VRAM but no tensor cores. Benchmark exact profiles on target hardware. Do not assume the largest model is best for live latency.

Modern `faster-whisper`/CTranslate2 GPU builds are CUDA-version sensitive. If CUDA loading fails, verify NVIDIA driver, CUDA runtime, cuDNN, and CTranslate2 version compatibility before changing API code.

If GTX 1080 Ti reports an error like:

```text
Requested int8_float16 compute type, but the target device or backend do not support efficient int8_float16 computation.
```

switch from `*-int8-fp16` to the matching `*-int8` profile. You can inspect runtime support with:

```powershell
python scripts/check_gpu_compute_types.py --device cuda --device-index 0
```

## Multi-GPU Selection

Prefer selecting the GPU at container runtime with `NVIDIA_VISIBLE_DEVICES`. If only one host GPU is exposed to the container, set `LOCAL_ASR_CUDA_DEVICE_INDEX=0`.

For advanced cases, set `device_index` on a model profile. The environment variable `LOCAL_ASR_CUDA_DEVICE_INDEX` overrides profile-level `device_index`.
