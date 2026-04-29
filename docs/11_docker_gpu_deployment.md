# Docker GPU Deployment

This guide is for deploying the ASR service on another machine with one or more NVIDIA GPUs.

## Prerequisites

On the target machine:

1. Install a recent NVIDIA driver.
2. Install Docker Engine or Docker Desktop with Linux containers.
3. Install NVIDIA Container Toolkit.
4. Verify GPU access:

```bash
nvidia-smi
docker run --rm --gpus all nvidia/cuda:12.3.2-base-ubuntu22.04 nvidia-smi
```

`faster-whisper` uses CTranslate2. This repository's GPU Dockerfile is tuned for GTX 1080 Ti / Pascal cards and uses the official `nvidia/cuda:11.8.0-cudnn8-runtime-ubuntu22.04` base image plus `ctranslate2==3.24.0`. This avoids early CUDA initialization failures that can appear with newer CUDA12/cuDNN9 builds on Pascal.

## Files

- `Dockerfile`: small CPU/dev image.
- `Dockerfile.gpu`: GPU image with CUDA user-space libraries from Python wheels.
- `docker-compose.yml`: simple local/dev compose.
- `docker-compose.gpu.yml`: GPU compose for deployment.
- `.env.example`: environment template.

## First Deploy

Clone the repo on the GPU machine:

```bash
git clone git@github.com:yrsolo/asr-service.git
cd asr-service
cp .env.example .env
```

Edit `.env`:

```dotenv
LOCAL_ASR_HOST=127.0.0.1
LOCAL_ASR_PORT=8765
LOCAL_ASR_API_KEY=change-me
LOCAL_ASR_DEFAULT_MODEL=fw-medium-int8
LOCAL_ASR_MODELS_CONFIG=config/models.example.yaml

NVIDIA_VISIBLE_DEVICES=0
NVIDIA_DRIVER_CAPABILITIES=compute,utility
LOCAL_ASR_CUDA_DEVICE_INDEX=0
```

For LAN access:

```dotenv
LOCAL_ASR_HOST=0.0.0.0
```

Also configure firewall rules so only trusted client machines can reach port `8765`.

Build and start:

Windows:

```cmd
scripts\run_docker_gpu.cmd
```

Linux:

```bash
docker compose -f docker-compose.gpu.yml up --build -d
```

Check:

```bash
docker compose -f docker-compose.gpu.yml ps
curl http://127.0.0.1:8765/health
```

Open from the GPU machine:

```text
http://127.0.0.1:8765/
http://127.0.0.1:8765/docs
```

## GPU Selection

There are two layers:

1. `NVIDIA_VISIBLE_DEVICES`: which host GPUs are exposed to the container.
2. `LOCAL_ASR_CUDA_DEVICE_INDEX`: which CUDA index faster-whisper uses inside the container.

Recommended simple mode:

```dotenv
NVIDIA_VISIBLE_DEVICES=1
LOCAL_ASR_CUDA_DEVICE_INDEX=0
```

This exposes only host GPU `1` to the container. Inside the container it becomes CUDA device `0`, so the service should use `LOCAL_ASR_CUDA_DEVICE_INDEX=0`.

Stable production mode with UUID:

```bash
nvidia-smi --query-gpu=index,uuid,name --format=csv
```

Then:

```dotenv
NVIDIA_VISIBLE_DEVICES=GPU-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
LOCAL_ASR_CUDA_DEVICE_INDEX=0
```

Advanced mode, exposing multiple GPUs:

The bundled `docker-compose.gpu.yml` is intentionally configured for one GPU per service container. To run several GPUs, start separate service copies with different `NVIDIA_VISIBLE_DEVICES` values or edit `device_ids` in the compose file.

You can also set `device_index` per model profile in `config/models.example.yaml`, but the environment variable `LOCAL_ASR_CUDA_DEVICE_INDEX` has priority.

## Prefetch Models Into Docker Volume

The compose file mounts `asr-model-cache` at `/models`, and the container uses:

```dotenv
HF_HOME=/models/hf
```

Prefetch all configured downloadable models:

```bash
docker compose -f docker-compose.gpu.yml run --rm local-asr-service python3.11 scripts/download_models.py
```

Prefetch selected models:

```bash
docker compose -f docker-compose.gpu.yml run --rm local-asr-service python3.11 scripts/download_models.py --models fw-small-int8,fw-medium-int8,fw-large-v3-turbo-int8
```

After this, normal service startup reuses the cached models.

For GTX 1080 Ti / Pascal cards, use `*-int8` profiles. If `*-int8-fp16` reports that `int8_float16` is not supported, switch to:

```dotenv
LOCAL_ASR_DEFAULT_MODEL=fw-medium-int8
```

If Docker reports CUDA out of memory on the regular large profile, use:

```dotenv
LOCAL_ASR_DEFAULT_MODEL=fw-medium-int8
```

or test the lower-memory large profile:

```dotenv
LOCAL_ASR_DEFAULT_MODEL=fw-large-v3-turbo-int8-lowmem
```

Check what CTranslate2 supports inside the container:

```bash
docker compose -f docker-compose.gpu.yml run --rm local-asr-service python3.11 scripts/check_gpu_compute_types.py --device cuda
```

On Windows you can run the bundled diagnostic:

```cmd
scripts\check_docker_gpu.cmd
```

This also runs NVIDIA's standalone CUDA `nbody` sample. If that sample fails, the problem is Docker/WSL/NVIDIA runtime rather than this ASR service or CTranslate2.

To inspect the CUDA Driver API directly:

```bash
docker compose -f docker-compose.gpu.yml run --rm local-asr-service python3.11 scripts/check_cuda_driver.py
```

If this reports `cuDeviceGetCount.count = 0`, Docker has NVML/`nvidia-smi` access but no CUDA compute devices.

For a detailed model-load report inside Docker:

```bash
docker compose -f docker-compose.gpu.yml run --rm local-asr-service python3.11 scripts/debug_model_load.py --model fw-medium-int8 --skip-transcribe
```

To test transcription and compare VRAM before/after:

```bash
docker compose -f docker-compose.gpu.yml run --rm local-asr-service python3.11 scripts/debug_model_load.py --model fw-medium-int8
```

If `nvidia-smi` does not show memory movement but CTranslate2 reports `CUDA out of memory`, treat it as an early CUDA/CTranslate2 allocation failure rather than a real model-size OOM. Rebuild the image after pulling the latest Dockerfile:

```bash
docker compose -f docker-compose.gpu.yml build --no-cache
docker compose -f docker-compose.gpu.yml up -d
```

If the container still shows all GPUs after setting `NVIDIA_VISIBLE_DEVICES`, inspect the resolved compose file:

```bash
docker compose -f docker-compose.gpu.yml config
```

Look for:

```yaml
device_ids:
  - "2"
```

or the selected GPU UUID.

## Useful Commands

Logs:

```bash
docker compose -f docker-compose.gpu.yml logs -f local-asr-service
```

Restart:

```bash
docker compose -f docker-compose.gpu.yml restart local-asr-service
```

Rebuild after code update:

```bash
git pull --ff-only
docker compose -f docker-compose.gpu.yml up --build -d
```

Stop:

```bash
docker compose -f docker-compose.gpu.yml down
```

Keep model cache while recreating containers. Remove it only when you intentionally want to delete downloaded models:

```bash
docker volume rm asr-service_asr-model-cache
```

## References

- Docker Compose GPU support: https://docs.docker.com/compose/how-tos/gpu-support/
- NVIDIA Container Toolkit GPU enumeration: https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/docker-specialized.html
- faster-whisper GPU requirements: https://github.com/SYSTRAN/faster-whisper
