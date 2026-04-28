# Usage and Model Preparation

This service is a local speech-to-text API. It receives audio from a desktop client or from the built-in test page and returns raw transcript segments. It must not capture audio, answer questions, generate meeting advice, or control the desktop UI.

## Quick Local Start

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev]"
python -m local_asr_service.main
```

Open:

```text
http://127.0.0.1:8765/
```

API docs:

```text
http://127.0.0.1:8765/docs
```

## Environment

Copy the example file:

```powershell
copy .env.example .env
```

Recommended local defaults:

```dotenv
LOCAL_ASR_HOST=127.0.0.1
LOCAL_ASR_PORT=8765
LOCAL_ASR_DEFAULT_MODEL=mock
LOCAL_ASR_MODELS_CONFIG=config/models.example.yaml
LOCAL_ASR_API_KEY=
LOCAL_ASR_SAVE_AUDIO=false
LOCAL_ASR_SAVE_TRANSCRIPTS=false
LOCAL_ASR_DEBUG_TRANSCRIPTS=false
```

For LAN mode set `LOCAL_ASR_HOST=0.0.0.0`, configure firewall rules, and set `LOCAL_ASR_API_KEY`.

## Model Profiles

Profiles live in `config/models.example.yaml`.

| Profile | Purpose | Notes |
|---|---|---|
| `mock` | API and UI development | No model download; deterministic fake transcript. |
| `fw-tiny-cpu` | CPU smoke test | Useful before CUDA is configured. Low quality. |
| `fw-small-int8` | Fast GPU baseline | Good first CUDA check. |
| `fw-medium-int8-fp16` | Recommended first serious profile | Better Russian quality while still realistic for 11 GB VRAM. |
| `fw-large-v3-turbo-int8-fp16` | Quality/speed candidate | Benchmark on target hardware before making it default. |

For a GTX 1080 Ti 11 GB, start with:

```dotenv
LOCAL_ASR_DEFAULT_MODEL=fw-medium-int8-fp16
```

Then benchmark `fw-small-int8`, `fw-medium-int8-fp16`, and `fw-large-v3-turbo-int8-fp16` with the same meeting samples.

## Download Models

Dry run:

```powershell
$env:PYTHONPATH="src"
python scripts/download_models.py --dry-run
```

Download every profile where `download: true`:

```powershell
$env:PYTHONPATH="src"
python scripts/download_models.py
```

Download selected profiles:

```powershell
$env:PYTHONPATH="src"
python scripts/download_models.py --models fw-small-int8,fw-medium-int8-fp16
```

Use a dedicated cache/output directory:

```powershell
$env:PYTHONPATH="src"
python scripts/download_models.py --cache-dir N:\MODELS\faster-whisper
```

`faster-whisper` downloads CTranslate2 models from Hugging Face on first use; the prefetch script makes that step explicit.

## Manual Test Flow

1. Start the service.
2. Open `http://127.0.0.1:8765/`.
3. Pick `mock` first and upload any small WAV/MP3 file to validate the API path.
4. Pick `fw-tiny-cpu` to validate real decoding without CUDA.
5. Pick a CUDA profile after NVIDIA/CUDA/CTranslate2 are working.
6. Compare `processing_ms`, transcript quality, and whether the service remains responsive.

## HTTP Examples

```powershell
python examples/client_http_file.py samples\meeting.wav --model mock --language ru
```

With API key:

```powershell
$env:LOCAL_ASR_API_KEY="change-me"
python -m local_asr_service.main
```

Then pass the bearer header from your own client:

```http
Authorization: Bearer change-me
```

## Benchmarking

Prepare samples:

- clean Russian speech;
- noisy Russian meeting;
- English technical speech;
- mixed Russian/English;
- microphone recording;
- system audio recording.

Run:

```powershell
$env:PYTHONPATH="src"
python scripts/benchmark_models.py samples\meeting_ru.wav --models fw-small-int8,fw-medium-int8-fp16,fw-large-v3-turbo-int8-fp16 --language ru
```

Track:

- real-time factor (`rtf`);
- processing seconds;
- transcript quality;
- hallucinations during silence;
- GPU memory usage;
- service stability after repeated files.

## CUDA Notes

Modern `faster-whisper` uses CTranslate2. Current CTranslate2 GPU builds are oriented around CUDA 12; older CUDA setups may require pinning CTranslate2 to an older compatible version. Confirm the target machine's NVIDIA driver, CUDA runtime, and cuDNN before treating a CUDA profile as production-ready.

References:

- `faster-whisper`: https://github.com/SYSTRAN/faster-whisper
- SYSTRAN CTranslate2 model collection: https://huggingface.co/Systran
- Faster Whisper large-v3 model card: https://huggingface.co/Systran/faster-whisper-large-v3
