@echo off
setlocal enabledelayedexpansion
REM ============================================================
REM Qwen3.8-27B NInfer engine - VISION build (image/video input)
REM   Converted with --components text,mtp,vision (includes mmproj).
REM   NOTE: strict residency policy is TEXT-ONLY (engine rejects it
REM   with --vision regardless of residency). Vision build therefore
REM   uses default policy + auto KV + headroom; context 64K.
REM   To trade context for speed: --vision-residency resident +
REM   --max-context 40960 (still default policy).
REM   Runs INSTEAD of start_qwen3_8_27b_gsq_ninfer.bat (same port
REM   8081 / same model id qwen3.8-27b). Kill-then-start behavior.
REM ============================================================

REM ---------- paths (edit for your machine) ----------
set "ENGINE_DIR=D:\ninfer\runtime\engine"
set "MODEL_FILE=D:\ninfer\converted-models\Qwen3.8-27B-GSQ-RCO-IQ3_S-mtp-vision.ninfer"
set "PORT=8081"

REM CUDA sorts fastest-first: 0 = RTX 4070 Ti SUPER here
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
echo Starting NInfer engine (VISION) ...
echo API: http://127.0.0.1:%PORT%/v1

ninfer-serve.exe "%MODEL_FILE%" ^
  --model-id qwen3.8-27b ^
  --vision --vision-residency cpu ^
  --max-context 49152 --prefill-chunk 256 ^
  --cuda-memory-policy default --kv-capacity auto --kv-headroom-mib 768 --kv-dtype rk8v4 --host-cache-mib 6144 ^
  --default-max-tokens 0 ^
  --spec mtp --draft-tokens 4 --adaptive-mtp --lookup-ngram 31 ^
  --temperature 1 --top-p 0.95 --top-k 20 --min-p 0 ^
  --preserve-thinking --default-reasoning-effort xhigh ^
  --port %PORT% --log-colours off

echo.
echo Engine exited.
pause
