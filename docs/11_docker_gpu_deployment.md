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

`faster-whisper` uses CTranslate2. Current GPU builds require CUDA 12 cuBLAS and CUDA 12 cuDNN 9 libraries. The GPU Dockerfile installs those Python wheels and sets `LD_LIBRARY_PATH` inside the container.

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

```dotenv
NVIDIA_VISIBLE_DEVICES=0,1
LOCAL_ASR_CUDA_DEVICE_INDEX=1
```

Here both host GPUs are visible inside the container, and faster-whisper uses the second visible CUDA device.

You can also set `device_index` per model profile in `config/models.example.yaml`, but the environment variable `LOCAL_ASR_CUDA_DEVICE_INDEX` has priority.

## Prefetch Models Into Docker Volume

The compose file mounts `asr-model-cache` at `/models`, and the container uses:

```dotenv
HF_HOME=/models/hf
```

Prefetch all configured downloadable models:

```bash
docker compose -f docker-compose.gpu.yml run --rm local-asr-service python scripts/download_models.py
```

Prefetch selected models:

```bash
docker compose -f docker-compose.gpu.yml run --rm local-asr-service python scripts/download_models.py --models fw-small-int8,fw-medium-int8,fw-large-v3-turbo-int8
```

After this, normal service startup reuses the cached models.

For GTX 1080 Ti / Pascal cards, use `*-int8` profiles. If `*-int8-fp16` reports that `int8_float16` is not supported, switch to:

```dotenv
LOCAL_ASR_DEFAULT_MODEL=fw-medium-int8
```

Check what CTranslate2 supports inside the container:

```bash
docker compose -f docker-compose.gpu.yml run --rm local-asr-service python scripts/check_gpu_compute_types.py --device cuda --device-index 0
```

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
