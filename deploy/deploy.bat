@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
title layout-check-mcp 一键部署

REM ============================================================
REM  deploy.bat —— layout-check-mcp 独立部署引导器
REM
REM  本脚本是"自包含"的：同事只需要这一个文件。
REM  双击运行后会自动：
REM    1) 检查 / 安装 uv
REM    2) 检查 / 安装 git
REM    3) 从 GitHub clone 项目到本脚本所在目录
REM    4) uv sync 预装依赖
REM    5) 运行 Tools\install_skillbridge.py
REM    6) 输出 MCP 配置 + SKILL.md 路径
REM
REM  保存要求：UTF-8 with BOM（不是 UTF-8 无 BOM）
REM ============================================================

REM ---- 脚本所在目录（去掉末尾反斜杠）----
set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"

REM ---- GitHub 仓库信息 ----
set "REPO_URL=https://github.com/ds2457513911/layout-check-mcp.git"
set "REPO_NAME=layout-check-mcp"
set "PROJECT_ROOT=%SCRIPT_DIR%\%REPO_NAME%"

echo.
echo ============================================================
echo  layout-check-mcp 一键部署
echo ============================================================
echo   工作目录: %SCRIPT_DIR%
echo   项目目录: %PROJECT_ROOT%
echo.

call :RefreshPath

REM ---- 检查 winget ----
where winget >nul 2>&1
if errorlevel 1 (
    echo   [X] 未检测到 winget
    echo       请从 Microsoft Store 安装 App Installer 后重试
    goto :fail
)

REM ============ 步骤 1：uv ============
echo.
echo [1/6] 检查 uv
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
echo [2/6] 检查 git
where git >nul 2>&1
if errorlevel 1 (
    echo       未检测到 git，使用 winget 安装（含 Unix 工具集）...
    winget install --id Git.Git -e --source winget --custom "/o:PathOption=CmdTools" --accept-source-agreements --accept-package-agreements
    call :RefreshPath
)
where git >nul 2>&1
if errorlevel 1 (
    echo   [X] git 安装失败
    goto :fail
)
echo   [OK] git 已安装

REM ============ 步骤 3：clone / pull ============
echo.
echo [3/6] 下载 / 更新项目

if exist "%PROJECT_ROOT%" (
    if exist "%PROJECT_ROOT%\.git" (
        echo       项目已存在，执行 git pull 更新...
        pushd "%PROJECT_ROOT%"
        git pull
        if errorlevel 1 (
            popd
            echo   [X] git pull 失败
            echo       可能原因：本地有改动、网络问题、或需要代理
            goto :fail
        )
        popd
        echo   [OK] 项目已更新
    ) else (
        echo   [X] 目录 %PROJECT_ROOT% 已存在但不是 git 仓库
        echo       请手动删除该目录后重试
        goto :fail
    )
) else (
    echo       从 GitHub 克隆（首次可能较慢，请耐心等待）...
    git clone "%REPO_URL%" "%PROJECT_ROOT%"
    if errorlevel 1 (
        echo   [X] git clone 失败
        echo       可能原因：
        echo         - 网络无法访问 GitHub（需要代理）
        echo         - 仓库地址变更
        echo         - 磁盘权限问题
        goto :fail
    )
    echo   [OK] 项目已下载
)

REM ---- 校验项目完整性 ----
if not exist "%PROJECT_ROOT%\pyproject.toml" (
    echo   [X] %PROJECT_ROOT% 不是有效项目（缺 pyproject.toml）
    goto :fail
)

REM ============ 步骤 4：uv sync ============
echo.
echo [4/6] 预装 MCP 依赖
pushd "%PROJECT_ROOT%"
"!UV!" sync
if errorlevel 1 (
    popd
    echo   [X] uv sync 失败
    goto :fail
)
popd
echo   [OK] 依赖安装完成

REM ============ 步骤 5：SkillBridge ============
echo.
echo [5/6] 配置 Allegro SkillBridge 自动加载
if not exist "%PROJECT_ROOT%\Tools\install_skillbridge.py" (
    echo   [X] 找不到 Tools\install_skillbridge.py
    goto :fail
)
"!UV!" run "%PROJECT_ROOT%\Tools\install_skillbridge.py"
if errorlevel 1 (
    echo   [X] install_skillbridge.py 执行失败
    goto :fail
)
echo   [OK] SkillBridge 配置完成

REM ============ 步骤 6：生成 MCP 配置 ============
echo.
echo [6/6] 生成 MCP 配置

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

REM ---- 定位 SKILL.md（兼容 .trae/skills 与 skills 两种布局）----
set "SKILL_DIR="
if exist "%PROJECT_ROOT%\.trae\skills\footprint-tolerance-check\SKILL.md" (
    set "SKILL_DIR=%PROJECT_ROOT%\.trae\skills\footprint-tolerance-check"
) else if exist "%PROJECT_ROOT%\skills\footprint-tolerance-check\SKILL.md" (
    set "SKILL_DIR=%PROJECT_ROOT%\skills\footprint-tolerance-check"
)

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
if defined SKILL_DIR (
    echo     !SKILL_DIR!
    echo     把整个 footprint-tolerance-check 文件夹复制到 Agent 的 skills 目录
) else (
    echo     [未找到 SKILL.md，请检查项目结构]
)
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