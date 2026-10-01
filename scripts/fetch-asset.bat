@echo off
setlocal
rem args: %1 = download url, %2 = destination file
set "URL=%~1"
set "DST=%~2"
set "PROXY=http://127.0.0.1:7897"

rem first try: direct via local proxy
curl.exe -sL --retry 1 --connect-timeout 15 -m 900 -x %PROXY% -o "%DST%.part" "%URL%"
if not errorlevel 1 (
  for %%A in ("%DST%.part") do if %%~zA gtr 100 (
    move /y "%DST%.part" "%DST%" >nul 2>&1
    exit /b 0
  )
)

rem second try: gh-proxy mirror
curl.exe -sL --retry 1 --connect-timeout 15 -m 900 -o "%DST%.part" "https://gh-proxy.com/%URL%"
if not errorlevel 1 (
  for %%A in ("%DST%.part") do if %%~zA gtr 100 (
    move /y "%DST%.part" "%DST%" >nul 2>&1
    exit /b 0
  )
)

rem third try: direct without proxy
curl.exe -sL --retry 1 --connect-timeout 15 -m 900 -o "%DST%.part" "%URL%"
if not errorlevel 1 (
  for %%A in ("%DST%.part") do if %%~zA gtr 100 (
    move /y "%DST%.part" "%DST%" >nul 2>&1
    exit /b 0
  )
)

if exist "%DST%.part" del /q "%DST%.part" >nul 2>&1
exit /b 1
