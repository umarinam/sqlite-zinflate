@echo off
rem Builds out\zinflate.dll (x64) with MSVC. zlib's inflate sources and the SQLite headers are
rem vendored in third_party\, so the Visual C++ build tools are the only requirement.
rem
rem Run it from an "x64 Native Tools Command Prompt for VS". From any other prompt it locates
rem Visual Studio (or the Build Tools) with vswhere and sets up the x64 environment itself.
setlocal
cd /d "%~dp0"

where cl >nul 2>nul && goto build

set "VSWHERE=%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe"
if not exist "%VSWHERE%" goto nocl
set "VSROOT="
for /f "usebackq delims=" %%i in (`"%VSWHERE%" -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath`) do set "VSROOT=%%i"
if not defined VSROOT goto nocl
rem vcvars64.bat runs vswhere itself and prints an error when its folder is not on PATH.
set "PATH=%PATH%;%ProgramFiles(x86)%\Microsoft Visual Studio\Installer"
call "%VSROOT%\VC\Auxiliary\Build\vcvars64.bat" >nul || exit /b 1

:build
if not exist out\obj mkdir out\obj
cl /nologo /O2 /MT /LD /W3 /Ithird_party\sqlite /Ithird_party\zlib ^
   /D_CRT_SECURE_NO_DEPRECATE /D_CRT_NONSTDC_NO_DEPRECATE ^
   /Fo:out\obj\ /Fe:out\zinflate.dll ^
   src\zinflate.c ^
   third_party\zlib\adler32.c third_party\zlib\crc32.c third_party\zlib\inffast.c ^
   third_party\zlib\inflate.c third_party\zlib\inftrees.c third_party\zlib\zutil.c ^
   /link /IMPLIB:out\obj\zinflate.lib || exit /b 1
echo.
echo Built out\zinflate.dll
exit /b 0

:nocl
echo cl.exe not found. Install the Visual C++ build tools, or run this script from an
echo "x64 Native Tools Command Prompt for VS".
exit /b 1
