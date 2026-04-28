# Deployment

## Native Windows

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
copy .env.example .env
python -m local_asr_service.main
```

## Linux

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
python -m local_asr_service.main
```

## LAN Access

On GPU machine:

```env
LOCAL_ASR_HOST=0.0.0.0
LOCAL_ASR_PORT=8765
LOCAL_ASR_API_KEY=change-me
```

On client machine:

```text
http://<gpu-machine-ip>:8765
```

## Docker

For CPU/dev image:

```bash
docker compose up --build
```

For GPU deployment on another machine:

```bash
cp .env.example .env
docker compose -f docker-compose.gpu.yml up --build -d
```

Select a specific host GPU in `.env`:

```dotenv
NVIDIA_VISIBLE_DEVICES=1
LOCAL_ASR_CUDA_DEVICE_INDEX=0
```

See `docs/11_docker_gpu_deployment.md` for the complete multi-GPU Docker guide.
