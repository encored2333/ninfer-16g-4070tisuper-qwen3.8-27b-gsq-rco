@echo off
setlocal enabledelayedexpansion
REM ============================================================
REM Qwen3.8-27B NInfer engine (ISTA GSQ-RCO IQ3_S + MTP) - 4070 Ti SUPER
REM   sm_89 engine built from source. Weights 11.3GB, KV pool
REM   (strict residency, rk4v4), logical context 146K.
REM   NOTE: max-context must be a multiple of 128, and the caret ^
REM   line continuations must stay at line ends (do not merge lines).
REM   Measured: decode ~112 tok/s @52K ctx, prefill ~1455 tok/s,
REM   TTFT 0.35s short / 35.7s @52K.
REM   Port 8081. If occupied, the stale listener is killed first.
REM   NOTE: CUDA_VISIBLE_DEVICES=0 -> 4070 Ti SUPER (CUDA sorts
REM   fastest-first; this is nvidia-smi index 1).
REM ============================================================

rem -- kill stray ninfer-serve instances (they hold all 16GB VRAM)
taskkill /F /IM ninfer-serve.exe >nul 2>&1

rem -- kill anything still listening on 8081
set "PORTBUSY="
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":8081 .*LISTENING"') do set "PORTBUSY=%%P"
if defined PORTBUSY (
  echo Killing stale listener on port 8081, pid !PORTBUSY! ...
  taskkill /F /PID !PORTBUSY! >nul 2>&1
  timeout /t 2 /nobreak >nul
)

cd /d D:\ninfer\runtime\engine

set "CUDA_VISIBLE_DEVICES=0"
echo Starting NInfer engine on 4070 Ti SUPER ...
echo API: http://127.0.0.1:8081/v1

ninfer-serve.exe "D:\ninfer\converted-models\Qwen3.8-27B-GSQ-RCO-IQ3_S-mtp.ninfer" ^
  --model-id qwen3.8-27b ^
  --max-context 97000 --prefill-chunk 256 ^
  --cuda-memory-policy strict --kv-dtype rk8v4 --host-cache-mib 6144 ^
  --default-max-tokens 0 ^
  --default-thinking-budget 16384 ^
  --spec mtp --draft-tokens 4 --adaptive-mtp --lookup-ngram 31 ^
  --temperature 1 --top-p 0.95 --top-k 20 --min-p 0 ^
  --preserve-thinking --default-reasoning-effort xhigh ^
  --port 8081 --log-stats-interval-ms 1000 --log-colours off ^
  --request-log-jsonl D:\ninfer\logs\requests-ninfer.jsonl --request-log-max-mib 64
REM --reasoning_effort: "medium"

echo.
echo Engine exited.
pause
