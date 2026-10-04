@echo off
setlocal enabledelayedexpansion
REM ============================================================
REM NInfer engine (ISTA GSQ-RCO IQ3_S + MTP) - RTX 4070 Ti SUPER 16GB
REM   sm_89 engine built from source.
REM   Context reality check on THIS card (16GB, strict residency):
REM     upstream claims 128K (S tier) -> does NOT fit here (FATAL)
REM     rk8v4: pool 97,280 tok  -> logical context 97,000  (quality-first, THIS script)
REM     rk4v4: pool ~141,760    -> logical context ~119.5K (KV precision halved)
REM   Measured: decode ~112 tok/s @52K ctx, prefill ~1455 tok/s,
REM   TTFT 0.35s short / 35.7s @52K.
REM   Thinking budget 16384 + max_tokens 0 (until context runs out).
REM   Port 8081. Kill-then-start (stale listener + stray instances).
REM   CUDA_VISIBLE_DEVICES=0 -> RTX 4070 Ti SUPER (CUDA sorts
REM   fastest-first; this is nvidia-smi index 1).
REM   max-context must be a multiple of 128; do not merge caret lines.
REM ============================================================

REM ---------- paths (edit for your machine) ----------
set "ENGINE_DIR=D:\ninfer\runtime\engine"
set "MODEL_FILE=D:\ninfer\converted-models\Qwen3.8-27B-GSQ-RCO-IQ3_S-mtp.ninfer"
set "PORT=8081"

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
echo Starting NInfer engine on 4070 Ti SUPER ...
echo API: http://127.0.0.1:%PORT%/v1

ninfer-serve.exe "%MODEL_FILE%" ^
  --model-id qwen3.8-27b ^
  --max-context 97000 --prefill-chunk 256 ^
  --cuda-memory-policy strict --kv-dtype rk8v4 --host-cache-mib 6144 ^
  --default-max-tokens 0 ^
  --default-thinking-budget 16384 ^
  --spec mtp --draft-tokens 4 --adaptive-mtp --lookup-ngram 31 ^
  --temperature 1 --top-p 0.95 --top-k 20 --min-p 0 ^
  --preserve-thinking --default-reasoning-effort xhigh ^
  --port %PORT% --log-colours off

echo.
echo Engine exited.
pause
