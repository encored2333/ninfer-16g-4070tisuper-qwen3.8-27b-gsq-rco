@echo off
setlocal enabledelayedexpansion
REM ============================================================
REM NInfer + Qwen3.8-27B (GSQ-RCO IQ3_S) 启动脚本模板
REM   RTX 4070 Ti SUPER 16GB 实测调优值；换显卡/路径自行调整。
REM   详细参数解释见 docs/部署文档.md 第 7 节。
REM
REM   使用前修改下面「路径区」三行为本机实际值。
REM   功能：启动前自动杀死残留 ninfer-serve 实例与端口占用进程。
REM ============================================================

REM ---------- 路径区（按本机修改） ----------
set "ENGINE_DIR=D:\ninfer\runtime\engine"
set "MODEL_FILE=D:\ninfer\converted-models\Qwen3.8-27B-GSQ-RCO-IQ3_S-mtp.ninfer"
set "PORT=8081"

REM ---------- 显卡区 ----------
REM CUDA 默认按 FastestFirst 排序（与 nvidia-smi 总线序相反）！
REM 单 4070 Ti SUPER 用 0；多卡请先用启动日志里的 GPU 名字核对。
set "CUDA_VISIBLE_DEVICES=0"

REM ---------- 杀残留 ----------
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
