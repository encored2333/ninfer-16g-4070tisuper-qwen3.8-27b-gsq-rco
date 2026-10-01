@echo off
setlocal enabledelayedexpansion
rem ===== resume ninfer_ops + prune + link, low parallelism to avoid OOM =====
set "VSVARS=D:\ai_models\tools\VS2022\VC\Auxiliary\Build\vcvars64.bat"
set "CMAKE=D:\ninfer\tools\cmake443\bin\cmake.exe"
set "NVPRUNE=C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v13.4\bin\nvprune.exe"
set "BUILD=D:\ninfer\build"
set "JOBS=8"

call "%VSVARS%" -vcvars_ver=14.44 >nul 2>&1
if errorlevel 1 ( echo [ERR] vcvars64 failed & exit /b 1 )
if not exist "%BUILD%\CMakeCache.txt" ( echo [ERR] build dir not configured & exit /b 1 )

echo [1/3] Resume ninfer_ops (-j %JOBS%)...
"%CMAKE%" --build "%BUILD%" --target ninfer_ops -j %JOBS% > "%BUILD%\resume-ops.log" 2>&1
if errorlevel 1 ( echo [ERR] ninfer_ops still failed, see resume-ops.log & exit /b 2 )
echo [OK] ninfer_ops built.

echo [2/3] nvprune sm_89...
if not exist "%BUILD%\archive-backup" mkdir "%BUILD%\archive-backup"
copy /y "%BUILD%\src\ops\ninfer_ops.lib" "%BUILD%\archive-backup\" >nul
"%NVPRUNE%" -arch sm_89 "%BUILD%\src\ops\ninfer_ops.lib" -o "%BUILD%\src\ops\ninfer_ops.pruned.lib"
if errorlevel 1 (
  echo [WARN] nvprune failed, keep original archive
) else (
  move /y "%BUILD%\src\ops\ninfer_ops.pruned.lib" "%BUILD%\src\ops\ninfer_ops.lib" >nul
)

echo [3/3] Link ninfer-serve (-j %JOBS%)...
"%CMAKE%" --build "%BUILD%" --target ninfer-serve -j %JOBS% >> "%BUILD%\resume-ops.log" 2>&1
if errorlevel 1 ( echo [ERR] link failed & exit /b 3 )
echo [DONE]
dir "%BUILD%\ninfer-serve.exe" | findstr ninfer-serve
exit /b 0
