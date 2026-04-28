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

Docker GPU requires NVIDIA Container Toolkit. Use after native MVP works.

```bash
docker compose up --build
```
