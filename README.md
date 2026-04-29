# Local ASR Service

Standalone local speech recognition service for Meeting Copilot.

The service is meant to run on a separate GPU machine, for example a PC with GTX 1080 Ti. The main desktop assistant captures audio and sends chunks to this service over HTTP or WebSocket.

## Responsibilities

This service handles:

- local speech recognition;
- model selection;
- audio file/chunk transcription;
- pseudo-streaming transcription;
- final/unstable transcript segmentation;
- optional light transcript cleanup later.

This service does **not** handle:

- microphone/WASAPI capture;
- LLM answers;
- meeting advice;
- Markdown suggestion cards;
- desktop overlay UI.

## Quick Start: Docker GPU

Use this path on the separate GPU machine.

1. Install NVIDIA driver, Docker, and NVIDIA Container Toolkit.
2. Check which GPUs are available:

```bash
nvidia-smi
```

3. Create `.env`:

```powershell
copy .env.example .env
```

4. Edit `.env`.

Pick the model:

```dotenv
LOCAL_ASR_DEFAULT_MODEL=fw-medium-int8
```

Useful model ids:

- `mock`: fake transcript for API/UI smoke test.
- `fw-small-int8`: fast CUDA baseline.
- `fw-medium-int8`: recommended first real GPU model for GTX 1080 Ti.
- `fw-large-v3-turbo-int8`: best quality candidate for GTX 1080 Ti, benchmark before live use.
- `fw-large-v3-turbo-int8-lowmem`: lower-memory large model test for GTX 1080 Ti Docker.
- `fw-medium-int8-fp16`: newer GPUs with efficient FP16/Tensor Core support.
- `fw-large-v3-turbo-int8-fp16`: newer GPUs with efficient FP16/Tensor Core support.

Pick the GPU:

```dotenv
NVIDIA_VISIBLE_DEVICES=0
LOCAL_ASR_CUDA_DEVICE_INDEX=0
```

For several GPUs, view stable ids:

```bash
nvidia-smi --query-gpu=index,uuid,name --format=csv
```

Example: use host GPU `1`, exposed as device `0` inside the container:

```dotenv
NVIDIA_VISIBLE_DEVICES=1
LOCAL_ASR_CUDA_DEVICE_INDEX=0
```

5. Start the container.

Windows:

```powershell
scripts\run_docker_gpu.cmd
```

Linux:

```bash
docker compose -f docker-compose.gpu.yml up --build -d
```

Health check:

```text
http://127.0.0.1:8765/health
```

Manual test UI:

```text
http://127.0.0.1:8765/
```

OpenAPI docs:

```text
http://127.0.0.1:8765/docs
```

Full deployment guide: `docs/11_docker_gpu_deployment.md`.

## Local Python Development

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
copy .env.example .env
python -m local_asr_service.main
```

## Endpoints

- `GET /health`
- `GET /v1/models`
- `POST /v1/transcribe/file`
- `POST /v1/transcribe/chunk`
- `WS /v1/stream`

See `docs/02_api_contracts.md`.

## Model Preparation

Use the mock backend first, then prefetch faster-whisper models:

```powershell
$env:PYTHONPATH="src"
python scripts/download_models.py --dry-run
python scripts/download_models.py --models fw-small-int8,fw-medium-int8-fp16
```

See `docs/10_usage_and_models.md` for the full setup, model selection notes, and benchmark flow.

## Docker GPU Deployment

For a separate GPU machine, use:

```bash
cp .env.example .env
docker compose -f docker-compose.gpu.yml up --build -d
```

Pick the host GPU in `.env`:

```dotenv
NVIDIA_VISIBLE_DEVICES=0
LOCAL_ASR_CUDA_DEVICE_INDEX=0
```

See `docs/11_docker_gpu_deployment.md`.

## First Development Strategy

Start with the mock backend and contracts. Then connect faster-whisper. Do not implement capture or desktop UI here.
