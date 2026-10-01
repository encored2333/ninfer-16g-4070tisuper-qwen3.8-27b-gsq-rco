@echo off
setlocal enabledelayedexpansion
REM ============================================================
REM NInfer + Qwen3.8-27B (GSQ-RCO IQ3_S) - VISION build template
REM   Model converted with --components text,mtp,vision
REM   (--source vision=mmproj.gguf). See docs/conversion guide.
REM
REM   IMPORTANT engine constraint discovered in testing:
REM   --cuda-memory-policy mixed/strict is TEXT-ONLY - the engine
REM   rejects it whenever --vision is set, regardless of where the
REM   vision tower runs. The vision build therefore uses default
REM   policy + auto KV + headroom.
REM
REM   This template: --vision-residency cpu (tower on CPU threads,
REM   zero extra VRAM, context 48K in our 16GB testing; image
REM   encoding is slower on CPU).
REM   Faster alternative: --vision-residency resident (tower on
REM   GPU, ~1GB) - image encoding much faster, but context drops
REM   to ~40K on a 16GB card and there is no residency guarantee.
REM
REM   Same port / model id as the text template: run INSTEAD of
REM   start_qwen3_8_27b_ninfer.bat, client config unchanged.
REM   Keep this file ASCII-only (see note in the text template).
REM ============================================================

REM ---------- paths (edit for your machine) ----------
set "ENGINE_DIR=D:\ninfer\runtime\engine"
set "MODEL_FILE=D:\ninfer\converted-models\Qwen3.8-27B-GSQ-RCO-IQ3_S-mtp-vision.ninfer"
set "PORT=8081"

REM ---------- GPU ----------
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
