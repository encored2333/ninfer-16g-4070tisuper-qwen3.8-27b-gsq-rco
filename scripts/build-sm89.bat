@echo off
setlocal enabledelayedexpansion
rem ===== NInfer sm_89 build chain (4070 Ti SUPER) =====
set "VSVARS=D:\ai_models\tools\VS2022\VC\Auxiliary\Build\vcvars64.bat"
set "CMAKE=D:\ninfer\tools\cmake443\bin\cmake.exe"
set "NVCC=C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v13.4\bin\nvcc.exe"
set "NVPRUNE=C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v13.4\bin\nvprune.exe"
set "CUDA_ROOT=C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v13.4"
set "CLPATH=D:\ai_models\tools\VS2022\VC\Tools\MSVC\14.44.35207\bin\Hostx64\x64\cl.exe"
set "NINJA=%LOCALAPPDATA%\Programs\Python\Python311\Scripts\ninja.exe"
set "SRC=D:\ninfer\src"
set "BUILD=D:\ninfer\build"
set "VCPKG=D:\ninfer\vcpkg"
set "JOBS=22"

call "%VSVARS%" -vcvars_ver=14.44 >nul 2>&1
if errorlevel 1 ( echo [ERR] vcvars64 failed & exit /b 1 )
set "PATH=%CMAKE%\..\bin;%PATH%"
if not exist "%BUILD%" mkdir "%BUILD%"

echo [1/4] CMake configure (sm_89)...
"%CMAKE%" -S "%SRC%" -B "%BUILD%" -G Ninja ^
  "-DCMAKE_TOOLCHAIN_FILE=%VCPKG%\scripts\buildsystems\vcpkg.cmake" ^
  -DVCPKG_TARGET_TRIPLET=x64-windows -DVCPKG_MANIFEST_MODE=OFF ^
  -DCMAKE_MAKE_PROGRAM="%NINJA%" ^
  -DVCPKG_APPLOCAL_DEPS=OFF ^
  -DCMAKE_BUILD_TYPE=Release -DCMAKE_CUDA_ARCHITECTURES=89 ^
  -DNINFER_BUILD_APPS=ON -DBUILD_TESTING=OFF -DNINFER_BUILD_BENCHMARKS=OFF ^
  -DNINFER_DIRECTSTORAGE=OFF -DNINFER_D3D12_RESIDENCY=OFF ^
  "-DCUDAToolkit_ROOT=%CUDA_ROOT%" ^
  "-DCMAKE_CUDA_COMPILER=%NVCC%" ^
  "-DCMAKE_CUDA_HOST_COMPILER=%CLPATH%" ^
  "-DCMAKE_C_COMPILER=%CLPATH%" "-DCMAKE_CXX_COMPILER=%CLPATH%" ^
  > "%BUILD%\configure.log" 2>&1
if errorlevel 1 ( echo [ERR] configure failed, see configure.log & exit /b 2 )
echo [OK] configured.

echo [2/4] Building ninfer_ops (CUDA kernels)...
"%CMAKE%" --build "%BUILD%" --target ninfer_ops -j %JOBS% >> "%BUILD%\build.log" 2>&1
if errorlevel 1 ( echo [ERR] ninfer_ops failed, see build.log & exit /b 3 )
echo [OK] ninfer_ops done.

echo [3/4] nvprune sm_89 (strip PTX)...
if not exist "%BUILD%\archive-backup" mkdir "%BUILD%\archive-backup"
copy /y "%BUILD%\src\ops\ninfer_ops.lib" "%BUILD%\archive-backup\" >nul
"%NVPRUNE%" -arch sm_89 "%BUILD%\src\ops\ninfer_ops.lib" -o "%BUILD%\src\ops\ninfer_ops.pruned.lib"
if errorlevel 1 ( echo [WARN] nvprune failed, keep original archive ) else (
  move /y "%BUILD%\src\ops\ninfer_ops.pruned.lib" "%BUILD%\src\ops\ninfer_ops.lib" >nul
)
echo [OK] prune stage done.

echo [4/4] Linking ninfer-serve...
"%CMAKE%" --build "%BUILD%" --target ninfer-serve -j %JOBS% >> "%BUILD%\build.log" 2>&1
if errorlevel 1 ( echo [ERR] link failed, see build.log & exit /b 4 )
echo [DONE] ninfer-serve built:
dir /b "%BUILD%\ninfer-serve.exe" 2>nul
exit /b 0
