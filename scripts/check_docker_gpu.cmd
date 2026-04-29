@echo off
setlocal

cd /d "%~dp0\.."

echo [local-asr-service] Host GPUs:
nvidia-smi --query-gpu=index,uuid,name,memory.total,memory.free --format=csv
if errorlevel 1 (
  echo [local-asr-service] nvidia-smi failed on the host.
  exit /b 1
)

echo.
echo [local-asr-service] NVIDIA CUDA sample outside compose:
docker run --rm --gpus all nvcr.io/nvidia/k8s/cuda-sample:nbody nbody -gpu -benchmark
if errorlevel 1 (
  echo [local-asr-service] CUDA sample failed. Docker GPU compute is not working independently of this service.
  exit /b 1
)

echo.
echo [local-asr-service] Container NVIDIA visibility:
docker compose -f docker-compose.gpu.yml run --rm local-asr-service nvidia-smi
if errorlevel 1 (
  echo [local-asr-service] nvidia-smi failed inside the container.
  echo Check NVIDIA Container Toolkit / Docker GPU runtime.
  exit /b 1
)

echo.
echo [local-asr-service] CTranslate2 compute types inside the container:
docker compose -f docker-compose.gpu.yml run --rm local-asr-service python3.11 scripts/check_gpu_compute_types.py --device cuda
if errorlevel 1 (
  echo [local-asr-service] CTranslate2 CUDA check failed inside the container.
  exit /b 1
)

echo.
echo [local-asr-service] faster-whisper model load diagnostic:
docker compose -f docker-compose.gpu.yml run --rm local-asr-service python3.11 scripts/debug_model_load.py --skip-transcribe
if errorlevel 1 (
  echo [local-asr-service] Model load diagnostic failed inside the container.
  exit /b 1
)

endlocal
