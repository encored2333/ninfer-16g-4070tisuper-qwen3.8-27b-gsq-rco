@echo off
setlocal
rem ============================================================
rem Build the tool-call parser probes against an engine source tree.
rem
rem   usage:  build-repo.bat <engine-source-root>
rem   example: build-repo.bat D:\ninfer\src-kvmem
rem
rem Prerequisites:
rem   * Visual Studio 2022 (v143) with the C++ workload. Point VSVARS at
rem     vcvars64.bat if it is not in the default location.
rem   * The engine source tree must be complete (third_party/ present).
rem
rem The probes do not need CUDA, CMake or a GPU: they compile the parser
rem translation unit directly, so they run in seconds.
rem ============================================================

set "ROOT=%~1"
if "%ROOT%"=="" (
  echo usage: build-repo.bat ^<engine-source-root^>
  exit /b 1
)
if not exist "%ROOT%\src\models\qwen3_5\frontend\tool_call_parser.cpp" (
  echo [ERR] %ROOT% does not look like an engine source root
  exit /b 1
)

if "%VSVARS%"=="" set "VSVARS=D:\ai_models\tools\VS2022\VC\Auxiliary\Build\vcvars64.bat"
if not exist "%VSVARS%" (
  echo [ERR] vcvars64.bat not found: %VSVARS%
  echo       set VSVARS to its full path and retry.
  exit /b 1
)
call "%VSVARS%" >nul
if errorlevel 1 (echo [ERR] vcvars failed & exit /b 1)

set "PARSER=%ROOT%\src\models\qwen3_5\frontend\tool_call_parser.cpp"
set INC=/I"%ROOT%\src" /I"%ROOT%\include" /I"%ROOT%\third_party" /I"%ROOT%\third_party\xgrammar\include" /I"%ROOT%\third_party\xgrammar\3rdparty\picojson" /I"%ROOT%\third_party\xgrammar\3rdparty\dlpack\include"

if not exist obj\probe mkdir obj\probe
if not exist obj\ae mkdir obj\ae
if not exist obj\g3 mkdir obj\g3

echo === probe.exe (51 shape cases)
cl /nologo /std:c++20 /EHsc /O2 /MD /DNDEBUG %INC% probe.cpp "%PARSER%" /Fe:probe.exe /Fo:obj\probe\
if errorlevel 1 exit /b 1

echo === probe_ae.exe (A class + E class + safety negatives)
cl /nologo /std:c++20 /EHsc /O2 /MD /DNDEBUG %INC% probe_ae.cpp "%PARSER%" /Fe:probe_ae.exe /Fo:obj\ae\
if errorlevel 1 exit /b 1

echo === probe_g3.exe (streaming byte fidelity)
cl /nologo /std:c++20 /EHsc /O2 /MD /DNDEBUG %INC% probe_g3.cpp "%PARSER%" /Fe:probe_g3.exe /Fo:obj\g3\
if errorlevel 1 exit /b 1

echo === build ok
