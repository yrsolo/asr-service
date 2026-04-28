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

## Quick Start

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
copy .env.example .env
python -m local_asr_service.main
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
