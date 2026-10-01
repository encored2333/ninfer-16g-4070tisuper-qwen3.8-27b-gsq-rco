@echo off
setlocal enabledelayedexpansion
REM ============================================================
REM NInfer + Qwen3.8-27B (GSQ-RCO IQ3_S) start script template
REM   Tuned on RTX 4070 Ti SUPER 16GB. See docs/deployment guide
REM   section 7 for every parameter.
REM
REM   NOTE: keep this file ASCII-only! Chinese comments saved as
REM   UTF-8 get shredded by cmd (GBK codepage) and break set/cd
REM   lines silently. Edit the "paths" block below.
REM   Behavior: kills stale ninfer-serve instances and any listener
REM   on the port before starting.
REM ============================================================

REM ---------- paths (edit for your machine) ----------
set "ENGINE_DIR=D:\ninfer\runtime\engine"
set "MODEL_FILE=D:\ninfer\converted-models\Qwen3.8-27B-GSQ-RCO-IQ3_S-mtp.ninfer"
set "PORT=8081"

REM ---------- GPU ----------
REM CUDA sorts devices fastest-first (REVERSE of nvidia-smi order)!
REM Single 4070 Ti SUPER -> 0. Verify via the GPU name in startup log.
set "CUDA_VISIBLE_DEVICES=0"

REM ---------- kill stale instances ----------
taskkill /F /IM ninfer-serve.exe >nul 2>&1
set "PORTBUSY="
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":%PORT% .*LISTENING"') do set "PORTBUSY=%%P"
if defined PORTBUSY (
  echo Killing stale listener on port %PORT%, pid !PORTBUSY! ...
  taskkill /F /PID !PORTBUSY! >nul 2>&1
  timeout /t 2 /nobreak >nul
)

cd /d "%ENGINE_DIR%"
echo Starting NInfer engine ...
echo API: http://127.0.0.1:%PORT%/v1

REM strict = verified VRAM residency; TEXT-ONLY (see vision template
REM for the image/video build, which must use default policy).
ninfer-serve.exe "%MODEL_FILE%" ^
  --model-id qwen3.8-27b ^
  --max-context 81920 --prefill-chunk 256 ^
  --cuda-memory-policy strict --kv-dtype rk8v4 --host-cache-mib 6144 ^
  --default-max-tokens 0 ^
  --spec mtp --draft-tokens 4 --adaptive-mtp --lookup-ngram 31 ^
  --temperature 1 --top-p 0.95 --top-k 20 --min-p 0 ^
  --preserve-thinking --default-reasoning-effort xhigh ^
  --port %PORT% --log-colours off

echo.
echo Engine exited.
pause
