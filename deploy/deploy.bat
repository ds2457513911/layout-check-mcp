@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
title layout-check-mcp deploy

REM ============================================================
REM  deploy.bat -- layout-check-mcp standalone deployer
REM
REM  This script is self-contained: colleague needs only this file.
REM  On double-click it will:
REM    1) Check / install uv
REM    2) Check / install git
REM    3) Clone the project from GitHub into this script's directory
REM    4) uv sync (install dependencies)
REM    5) Run Tools\install_skillbridge.py
REM    6) Print MCP config + SKILL.md path
REM
REM  Save requirement: ASCII or UTF-8 (no BOM), English-only prompts.
REM  NOTE: never put ( or ) inside "echo" lines that live inside an
REM        "if (...)" block. CMD parses them as block delimiters.
REM ============================================================

REM ---- Script directory (strip trailing backslash) ----
set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"

REM ---- GitHub repo info ----
set "REPO_URL=https://github.com/ds2457513911/layout-check-mcp.git"
set "REPO_NAME=layout-check-mcp"
set "PROJECT_ROOT=%SCRIPT_DIR%\%REPO_NAME%"

echo.
echo ============================================================
echo  layout-check-mcp deployer
echo ============================================================
echo   Work dir : %SCRIPT_DIR%
echo   Project  : %PROJECT_ROOT%
echo.

call :RefreshPath

REM ---- Check winget ----
where winget >nul 2>&1
if errorlevel 1 (
    echo   [X] winget not found.
    echo       Install "App Installer" from Microsoft Store and retry.
    goto :fail
)

REM ============ Step 1: uv ============
echo.
echo [1/6] Check uv
call :FindUv
if not defined UV (
    echo       uv not found, installing via winget...
    winget install astral-sh.uv --accept-source-agreements --accept-package-agreements
    call :RefreshPath
    call :FindUv
)
if not defined UV (
    echo   [X] uv install failed. Run manually: winget install astral-sh.uv
    goto :fail
)
echo   [OK] uv: !UV!

REM ============ Step 2: git ============
echo.
echo [2/6] Check git
where git >nul 2>&1
if errorlevel 1 (
    echo       git not found, installing via winget...
    winget install --id Git.Git -e --source winget --custom "/o:PathOption=CmdTools" --accept-source-agreements --accept-package-agreements
    call :RefreshPath
)
where git >nul 2>&1
if errorlevel 1 (
    echo   [X] git install failed.
    goto :fail
)
echo   [OK] git ready

REM ============ Step 3: clone / pull ============
echo.
echo [3/6] Fetch project

if exist "%PROJECT_ROOT%" (
    if exist "%PROJECT_ROOT%\.git" (
        echo       Project exists, running git pull...
        pushd "%PROJECT_ROOT%"
        git pull
        if errorlevel 1 (
            popd
            echo   [X] git pull failed.
            echo       Possible: local changes, network issue, or proxy needed.
            goto :fail
        )
        popd
        echo   [OK] project updated
    ) else (
        echo   [X] %PROJECT_ROOT% exists but is not a git repo.
        echo       Delete that folder and retry.
        goto :fail
    )
) else (
    echo       Cloning from GitHub, first time may take a while...
    git clone "%REPO_URL%" "%PROJECT_ROOT%"
    if errorlevel 1 (
        echo   [X] git clone failed.
        echo       Possible reasons:
        echo         - Cannot reach GitHub - proxy may be required
        echo         - Repo URL changed
        echo         - Disk permission issue
        goto :fail
    )
    echo   [OK] project downloaded
)

REM ---- Validate project ----
if not exist "%PROJECT_ROOT%\pyproject.toml" (
    echo   [X] %PROJECT_ROOT% is not a valid project - pyproject.toml missing
    goto :fail
)

REM ============ Step 4: uv sync ============
echo.
echo [4/6] Install MCP dependencies
pushd "%PROJECT_ROOT%"
"!UV!" sync
if errorlevel 1 (
    popd
    echo   [X] uv sync failed.
    goto :fail
)
popd
echo   [OK] dependencies installed

REM ============ Step 5: SkillBridge ============
echo.
echo [5/6] Configure Allegro SkillBridge auto-load
if not exist "%PROJECT_ROOT%\Tools\install_skillbridge.py" (
    echo   [X] Tools\install_skillbridge.py not found.
    goto :fail
)
"!UV!" run "%PROJECT_ROOT%\Tools\install_skillbridge.py"
if errorlevel 1 (
    echo   [X] install_skillbridge.py failed.
    goto :fail
)
echo   [OK] SkillBridge configured

REM ============ Step 6: MCP config ============
echo.
echo [6/6] Generate MCP config

REM JSON escape: backslash \ -> \\
set "UV_ESC=!UV:\=\\!"
set "ROOT_ESC=!PROJECT_ROOT:\=\\!"
set "MCP_FILE=%SCRIPT_DIR%\mcp-config.json"

(
echo {
echo   "mcpServers": {
echo     "layout-check-v2": {
echo       "command": "!UV_ESC!",
echo       "args": ["run", "--directory", "!ROOT_ESC!", "layout-check-mcp"]
echo     }
echo   }
echo }
) > "!MCP_FILE!"

REM ---- Locate SKILL.md ----
set "SKILL_DIR="
if exist "%PROJECT_ROOT%\.trae\skills\footprint-tolerance-check\SKILL.md" (
    set "SKILL_DIR=%PROJECT_ROOT%\.trae\skills\footprint-tolerance-check"
) else if exist "%PROJECT_ROOT%\skills\footprint-tolerance-check\SKILL.md" (
    set "SKILL_DIR=%PROJECT_ROOT%\skills\footprint-tolerance-check"
)

echo.
echo ============================================================
echo  Deploy complete
echo ============================================================
echo.
echo [1] MCP config saved to: !MCP_FILE!
echo.
type "!MCP_FILE!"
echo.
echo [2] SKILL.md path
if defined SKILL_DIR (
    echo     !SKILL_DIR!
    echo     Copy the footprint-tolerance-check folder into your Agent's skills dir.
) else (
    echo     [SKILL.md not found - check project structure]
)
echo.
echo [3] Next steps
echo     1. Restart Allegro PCB Editor
echo     2. Verify port: netstat -ano ^| findstr 7777
echo     3. Restart your Agent app, confirm MCP is connected
echo.
pause
exit /b 0


REM ============================================================
REM Subroutines
REM ============================================================

:FindUv
set "UV="
for /f "delims=" %%i in ('where uv 2^>nul') do (
    set "UV=%%i"
    goto :FindUvDone
)
:FindUvDone
if not defined UV if exist "%USERPROFILE%\.local\bin\uv.exe" set "UV=%USERPROFILE%\.local\bin\uv.exe"
if not defined UV if exist "%USERPROFILE%\.cargo\bin\uv.exe" set "UV=%USERPROFILE%\.cargo\bin\uv.exe"
if not defined UV if exist "%LOCALAPPDATA%\Programs\uv\uv.exe" set "UV=%LOCALAPPDATA%\Programs\uv\uv.exe"
exit /b 0

:RefreshPath
REM Non-destructive refresh: keep current session PATH, append common dirs.
REM Never reset PATH from registry (REG_EXPAND_SZ has literal %VAR% strings
REM that cmd does not expand on "set").
set "PATH=%PATH%;%LOCALAPPDATA%\Microsoft\WindowsApps"
set "PATH=%PATH%;%USERPROFILE%\.local\bin"
set "PATH=%PATH%;%USERPROFILE%\.cargo\bin"
set "PATH=%PATH%;%LOCALAPPDATA%\Programs\uv"
set "PATH=%PATH%;C:\Program Files\Git\cmd"
exit /b 0

:fail
echo.
echo   Deploy failed. Check the error above.
pause
exit /b 1