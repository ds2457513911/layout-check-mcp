@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
title layout-check-mcp 一键部署

REM ============================================================
REM  deploy\deploy.bat —— layout-check-mcp 一键部署
REM
REM  本脚本位于 <项目根>\deploy\ 下，双击即可运行。
REM  自动识别项目根（= 脚本所在目录的上一级）。
REM
REM  流程：
REM    1) 检查 / 安装 uv
REM    2) 检查 / 安装 git
REM    3) 运行 Tools\install_skillbridge.py
REM    4) uv sync 预装依赖
REM    5) 输出 MCP 配置 + SKILL.md 路径
REM ============================================================

REM ---- 脚本所在目录（去掉末尾反斜杠） ----
set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"

REM ---- 项目根 = 脚本目录的上一级（规范化，去掉 ".."） ----
for %%i in ("%SCRIPT_DIR%\..") do set "PROJECT_ROOT=%%~fi"

echo.
echo ============================================================
echo  layout-check-mcp 一键部署
echo ============================================================
echo   脚本目录:   %SCRIPT_DIR%
echo   项目根目录: %PROJECT_ROOT%
echo.

REM ---- 校验项目根是否找对 ----
if not exist "%PROJECT_ROOT%\pyproject.toml" (
    echo   [X] 未在 %PROJECT_ROOT% 找到 pyproject.toml
    echo       请确认本脚本位于 <项目根>\deploy\ 下
    goto :fail
)

call :RefreshPath

where winget >nul 2>&1
if errorlevel 1 (
    echo   [X] 未检测到 winget，无法自动安装 uv / git
    echo       请从 Microsoft Store 安装 App Installer 后重试
    goto :fail
)

REM ============ 步骤 1：uv ============
echo.
echo [1/5] 检查 uv
call :FindUv
if not defined UV (
    echo       未检测到 uv，使用 winget 安装...
    winget install astral-sh.uv --accept-source-agreements --accept-package-agreements
    call :RefreshPath
    call :FindUv
)
if not defined UV (
    echo   [X] uv 安装失败，请手动：winget install astral-sh.uv
    goto :fail
)
echo   [OK] uv: !UV!

REM ============ 步骤 2：git ============
echo.
echo [2/5] 检查 git
where git >nul 2>&1
if errorlevel 1 (
    echo       未检测到 git，使用 winget 安装（含 Unix 工具集）...
    winget install --id Git.Git -e --source winget --custom "/o:PathOption=CmdTools" --accept-source-agreements --accept-package-agreements
    call :RefreshPath
)
where git >nul 2>&1
if errorlevel 1 (
    echo   [!] git 未安装或未加入 PATH（只用本地代码跑 MCP 时可忽略）
) else (
    echo   [OK] git 已安装
)

REM ============ 步骤 3：SkillBridge ============
echo.
echo [3/5] 配置 Allegro SkillBridge 自动加载
if not exist "%PROJECT_ROOT%\Tools\install_skillbridge.py" (
    echo   [X] 找不到 %PROJECT_ROOT%\Tools\install_skillbridge.py
    goto :fail
)
"!UV!" run "%PROJECT_ROOT%\Tools\install_skillbridge.py"
if errorlevel 1 (
    echo   [X] install_skillbridge.py 执行失败
    goto :fail
)
echo   [OK] SkillBridge 配置完成

REM ============ 步骤 4：uv sync ============
echo.
echo [4/5] 预装 MCP 依赖
pushd "%PROJECT_ROOT%"
"!UV!" sync
if errorlevel 1 (
    popd
    echo   [X] uv sync 失败
    goto :fail
)
popd
echo   [OK] 依赖安装完成

REM ============ 步骤 5：生成配置 ============
echo.
echo [5/5] 生成 MCP 配置

REM JSON 转义：反斜杠 \ 变 \\
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

echo.
echo ============================================================
echo  部署完成
echo ============================================================
echo.
echo 【1】MCP 配置（已保存到 !MCP_FILE!）
echo.
type "!MCP_FILE!"
echo.
echo 【2】SKILL.md 路径
echo     %PROJECT_ROOT%\skills\footprint-tolerance-check\SKILL.md
echo     把整个 footprint-tolerance-check 文件夹复制到 Agent 的 skills 目录
echo.
echo 【3】下一步
echo     1. 重启 Allegro PCB Editor
echo     2. 验证端口: netstat -ano ^| findstr 7777
echo     3. 重启 Agent 软件，确认 MCP 已连接
echo.
pause
exit /b 0


REM ============================================================
REM 子程序
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
for /f "usebackq tokens=2,*" %%a in (`reg query "HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Environment" /v Path 2^>nul`) do set "SysPath=%%b"
for /f "usebackq tokens=2,*" %%a in (`reg query "HKCU\Environment" /v Path 2^>nul`) do set "UserPath=%%b"
set "PATH=!SysPath!;!UserPath!"
exit /b 0

:fail
echo.
echo   部署失败，请检查上方错误信息
pause
exit /b 1