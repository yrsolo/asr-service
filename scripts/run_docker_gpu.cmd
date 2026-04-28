@echo off
setlocal

cd /d "%~dp0\.."

if not exist ".env" (
  echo [local-asr-service] .env not found. Creating it from .env.example...
  copy ".env.example" ".env" >nul
  echo [local-asr-service] Edit .env before production use:
  echo   - LOCAL_ASR_DEFAULT_MODEL
  echo   - NVIDIA_VISIBLE_DEVICES
  echo   - LOCAL_ASR_CUDA_DEVICE_INDEX
  echo   - LOCAL_ASR_API_KEY for LAN mode
  echo.
)

echo [local-asr-service] GPUs visible on this host:
nvidia-smi --query-gpu=index,uuid,name,memory.total --format=csv
echo.

echo [local-asr-service] Building and starting Docker GPU container...
docker compose -f docker-compose.gpu.yml up --build -d
if errorlevel 1 (
  echo.
  echo [local-asr-service] Docker start failed.
  echo Check Docker, NVIDIA Container Toolkit, and .env GPU settings.
  exit /b 1
)

echo.
echo [local-asr-service] Container status:
docker compose -f docker-compose.gpu.yml ps

echo.
echo [local-asr-service] Open:
echo   http://127.0.0.1:8765/
echo   http://127.0.0.1:8765/docs
echo.
echo [local-asr-service] Logs:
echo   docker compose -f docker-compose.gpu.yml logs -f local-asr-service

endlocal
