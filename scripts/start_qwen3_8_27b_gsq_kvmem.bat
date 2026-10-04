@echo off
setlocal enabledelayedexpansion
REM ============================================================
REM NInfer + KVMem ring build - Qwen3.8-27B (GSQ-RCO IQ3_S+mtp)
REM   Decouples "VRAM pool = logical context": device pool holds
REM   only the working set (window + prefill chunk); overflow KV
REM   pages live in pinned host RAM; each turn retrieves relevant
REM   pages by content scoring; unrestored pages are masked.
REM   -> logical context up to 262,144 on a 16GB card.
REM
REM   THE FIVE RING ENV VARS ARE ONE CONFIG - all five required
REM   (partial setup starts fine but silently answers wrong).
REM   KV dtype k8v4: mask wiring validated only on k8v4 for this
REM   artifact family (fp8 also green; rk*/int8 untested here).
REM   --max-shared-prefixes 0 is mandatory (shared-prefix + same
REM   prompt resend can 503-poison the instance).
REM   MTP + host-backed reuse TOGETHER: engine patched locally
REM   (request_plan.cpp) to degrade an unmaterializable MTP checkpoint
REM   to a full re-prefill instead of failing the request. Safe reuse
REM   (in-pool prefixes, response replay) still hits; over-pool host
REM   checkpoints fall back to re-prefill under MTP.
REM   --prefill-chunk 256 (NOT 1024): chunk 1024 wedges the ring on
REM   over-pool prefills (random prefill stall, zero-error; upstream
REM   pitfall table prescribes chunk 256 with small pools).
REM   Runs INSTEAD of the other start bats (same port 8081 /
REM   model id qwen3.8-27b). Kill-then-start behavior.
REM   Keep this file ASCII-only (GBK codepage pitfall).
REM ============================================================

REM ---------- paths (edit for your machine) ----------
set "ENGINE_DIR=D:\ninfer\runtime\engine-kvmem"
set "MODEL_FILE=D:\ninfer\converted-models\Qwen3.8-27B-GSQ-RCO-IQ3_S-mtp.ninfer"
set "PORT=8081"

REM ---------- GPU ----------
set "CUDA_VISIBLE_DEVICES=0"

REM ---------- KVMem ring: the five (one config, all required) ----------
set "NINFER_KV_WINDOW=32768"
set "NINFER_KV_RETRIEVE=8192"
set "NINFER_KV_RING=1"
set "NINFER_HOST_PAGEABLE=1"
set "NINFER_KV_REUSE_HOSTBACKED=1"

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
echo Starting NInfer engine (KVMem ring) ...
echo API: http://127.0.0.1:%PORT%/v1

REM Expected startup lines (all three must appear):
REM   [ring] content scoring ON by default (the ring is configured): ...
REM   engine ready | ... 
REM   capacity | KV 17,920 tokens, k8v4, explicit | pages 280/4,096 | ...

ninfer-serve.exe "%MODEL_FILE%" ^
  --model-id qwen3.8-27b ^
  --max-context 262144 --kv-capacity 75776 --kv-dtype k8v4 --host-kv-mib 12288 ^
  --prefill-chunk 256 ^
  --spec mtp --draft-tokens 4 --adaptive-mtp --lookup-ngram 31 ^
  --max-shared-prefixes 0 --auto-long-anchors ^
  --temperature 0.7 --top-p 0.8 --top-k 20 --min-p 0 --presence-penalty 0 ^
  --default-reasoning-effort xhigh --default-thinking-budget 8192 ^
  --port %PORT% --log-colours off

echo.
echo Engine exited.
pause
