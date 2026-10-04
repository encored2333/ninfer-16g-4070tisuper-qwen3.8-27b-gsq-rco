# NInfer sm_89 engine (RTX 40-series) — prebuilt for Qwen3.8-27B GSQ-RCO

Drop-in engine for the deployment in this repository. Built from source with
`CMAKE_CUDA_ARCHITECTURES=89` (mma.sync compatibility path), nvpruned to sm_89 SASS.

## Contents

`engine/` — `ninfer-serve.exe` (1.07 GB) + full DLL set (cuBLAS 13 / cudart 13 / VC runtime /
vcpkg deps), ready to run.

## Quick use

1. Unzip anywhere, e.g. `D:\ninfer\runtime\engine`
2. Convert the model per `docs/模型转换指南.md` (or reuse an existing `.ninfer` — weights are GPU-architecture independent)
3. Start with `scripts/start_qwen3_8_27b_ninfer.bat` (edit the paths block first)

Tested on RTX 4070 Ti SUPER 16GB: decode 112 tok/s @52K ctx. See `docs/性能实测.md`.

Works on any sm_89 card (RTX 4070 / 4070 Ti / 4070 Ti SUPER / 4080 / 4090) — re-run device
calibration on first start (automatic, ~20–60 s). RTX 50-series should use the upstream
sm_120a package instead; RTX 30-series must rebuild with `CMAKE_CUDA_ARCHITECTURES=86`.

SHA256 (engine-sm89-4070tisuper.zip): see release notes below after upload.
