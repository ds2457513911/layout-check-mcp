# -*- coding: utf-8 -*-
"""
install_skillbridge.py —— 一键配置 Allegro 自动加载 SkillBridge

核心功能：
  1. 确保 uv 已安装
  2. 在 ~/.local/share/skillbridge_env 建固定虚拟环境，装 skillbridge
  3. 定位 pythonw.exe 和 python_server.il 的固定路径
  4. 多策略搜索 Allegro 的 pcbenv 目录（环境变量 / 常见路径 / 盘符扫描 / 深度搜索）
  5. 在 allegro.ilinit 里追加"标记块"，不覆盖已有内容
  6. 支持 --uninstall 一键移除

用法：
    uv run install_skillbridge.py                        # 默认搜索
    uv run install_skillbridge.py --deep-search          # 全盘深搜
    uv run install_skillbridge.py --pcbenv "C:/path"     # 手动指定
    uv run install_skillbridge.py --uninstall            # 卸载
    uv run install_skillbridge.py --dry-run              # 预览

注意：
  allegro.ilinit 本身是 SKILL 文件，里面所有内容默认就是 SKILL 语句。
  因此不要写单独的 `skill` 前缀命令，否则会报 "undefined variable - skill"。

关于 pyKillServer：
  pyStartServer 启动的 Python 进程是独立的，Allegro 关闭时不会自动结束它。
  所以在每次启动前先调 pyKillServer，避免反复开关 Allegro 时累积多个进程。
"""
from __future__ import annotations

import argparse
import os
import platform
import re
import shutil
import string
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# ---- 标记，用于在 allegro.ilinit 里定位插入的段落 ----
BEGIN_MARK = ";; ==== SkillBridge Auto-Load BEGIN (do not edit) ===="
END_MARK   = ";; ==== SkillBridge Auto-Load END ===="

# ---- 虚拟环境目录名 ----
ENV_DIR_NAME = "skillbridge_env"

# ---- 判断是否为 pcbenv 的标志文件 ----
PCBENV_MARKER_FILES = ["allegro.ilinit", "allegro.ini", "env", "pcbenv.ini"]


# ============================================================
# 基础工具
# ============================================================
def log(msg: str, level: str = "INFO") -> None:
    prefix = {
        "INFO": "   ",
        "OK":   "✅",
        "WARN": "⚠️",
        "ERR":  "❌",
        "STEP": "▶",
    }[level]
    print(f"{prefix} {msg}")


def which(cmd: str) -> str | None:
    return shutil.which(cmd)


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8",
        errors="replace", **kwargs,
    )


def venv_python_path(env_dir: Path) -> Path:
    if platform.system() == "Windows":
        return env_dir / "Scripts" / "python.exe"
    return env_dir / "bin" / "python"


def venv_pythonw_path(env_dir: Path) -> Path:
    if platform.system() == "Windows":
        pw = env_dir / "Scripts" / "pythonw.exe"
        if pw.is_file():
            return pw
    return venv_python_path(env_dir)


# ============================================================
# 步骤 1：确保 uv
# ============================================================
def ensure_uv() -> str:
    uv = which("uv")
    if uv:
        log(f"uv 已找到: {uv}", "OK")
        return uv

    log("找不到 uv 命令", "ERR")
    print()
    print("请先安装 uv，任选一种方式：")
    print("  Windows:  winget install astral-sh.uv")
    print("  Windows:  powershell -ExecutionPolicy ByPass -c \"irm https://astral.sh/uv/install.ps1 | iex\"")
    print("  macOS:    brew install uv")
    print("  Linux:    curl -LsSf https://astral.sh/uv/install.sh | sh")
    print()
    sys.exit(1)


# ============================================================
# 步骤 2：skillbridge 虚拟环境
# ============================================================
def ensure_skillbridge_env(uv: str, dry_run: bool) -> Path:
    env_dir = Path.home() / ".local" / "share" / ENV_DIR_NAME
    python_exe = venv_python_path(env_dir)

    if python_exe.is_file():
        r = run([str(python_exe), "-c", "import skillbridge"])
        if r.returncode == 0:
            log(f"已存在: {env_dir}", "OK")
            return env_dir

        log("环境存在但缺 skillbridge，补装", "INFO")
        if dry_run:
            log(f"[DRY-RUN] 将执行: {uv} pip install --python {python_exe} skillbridge", "WARN")
            return env_dir
        r = run([uv, "pip", "install", "--python", str(python_exe), "skillbridge"])
        if r.returncode != 0:
            log("补装 skillbridge 失败", "ERR")
            print(r.stdout)
            print(r.stderr)
            sys.exit(1)
        log(f"补装完成: {env_dir}", "OK")
        return env_dir

    log(f"未安装，将创建虚拟环境: {env_dir}")
    if dry_run:
        log(f"[DRY-RUN] 将执行: {uv} venv {env_dir}", "WARN")
        log(f"[DRY-RUN] 将执行: {uv} pip install --python {python_exe} skillbridge", "WARN")
        return env_dir

    env_dir.parent.mkdir(parents=True, exist_ok=True)
    log(f"执行: {uv} venv {env_dir}")
    r = run([uv, "venv", str(env_dir)])
    if r.returncode != 0:
        log("创建虚拟环境失败", "ERR")
        print(r.stdout)
        print(r.stderr)
        sys.exit(1)

    log("执行: uv pip install skillbridge")
    r = run([uv, "pip", "install", "--python", str(python_exe), "skillbridge"])
    if r.returncode != 0:
        log("安装 skillbridge 失败", "ERR")
        print(r.stdout)
        print(r.stderr)
        sys.exit(1)

    log(f"安装完成: {env_dir}", "OK")
    return env_dir


# ============================================================
# 步骤 3：从虚拟环境拿固定路径
# ============================================================
def find_python_exe(env_dir: Path) -> Path:
    for c in [
        env_dir / "Scripts" / "python.exe",
        env_dir / "bin" / "python",
        env_dir / "bin" / "python3",
    ]:
        if c.is_file():
            return c
    raise FileNotFoundError(f"在 {env_dir} 下找不到 python 可执行文件")


def find_python_server_il(env_dir: Path) -> Path:
    hits = list(env_dir.glob("**/skillbridge/server/python_server.il"))
    if not hits:
        raise FileNotFoundError(
            f"在 {env_dir} 下找不到 skillbridge/server/python_server.il"
        )
    return hits[0]


# ============================================================
# 步骤 4：多策略搜索 pcbenv
# ============================================================
def _search_dir_recursive(root: Path, max_depth: int, results: list[Path],
                          visited: set[str]) -> None:
    if max_depth <= 0:
        return
    try:
        key = str(root.resolve()).lower()
    except Exception:
        key = str(root).lower()
    if key in visited:
        return
    visited.add(key)

    skip_names = {
        "windows", "program files", "program files (x86)",
        "$recycle.bin", "system volume information", "recovery",
        "node_modules", ".git", "__pycache__", ".venv", "venv",
        "anaconda3", "miniconda3", "python", "python3",
    }

    try:
        for entry in root.iterdir():
            if not entry.is_dir():
                continue
            lname = entry.name.lower()
            if lname in skip_names:
                continue
            if lname.startswith("."):
                continue

            if lname == "pcbenv":
                results.append(entry)
                continue
            if any((entry / m).is_file() for m in PCBENV_MARKER_FILES):
                results.append(entry)
                continue

            _search_dir_recursive(entry, max_depth - 1, results, visited)
    except (PermissionError, OSError):
        pass


def find_pcbenv_candidates(deep: bool = False) -> list[Path]:
    candidates: list[Path] = []
    system = platform.system()

    if system == "Windows":
        home = Path.home()

        # ---- 策略 1：环境变量 ----
        for env_var in [
            "SPB_Data", "SPB_DATA", "CDS_Data", "CDS_DATA",
            "CDSROOT", "CDS_ROOT", "HOME",
        ]:
            val = os.environ.get(env_var)
            if not val:
                continue
            try:
                p = Path(val)
            except Exception:
                continue
            if (p / "pcbenv").is_dir():
                candidates.append(p / "pcbenv")
            if p.name.lower() == "pcbenv" and p.is_dir():
                candidates.append(p)

        # ---- 策略 2：常见位置 ----
        common = [
            home / "pcbenv",
            home / "AppData" / "Roaming" / "pcbenv",
            Path("C:/SPB_Data/pcbenv"),
            Path("D:/SPB_Data/pcbenv"),
            Path("E:/SPB_Data/pcbenv"),
            Path("C:/Cadence/SPB_Data/pcbenv"),
            Path("D:/Cadence/SPB_Data/pcbenv"),
            Path("E:/Cadence/SPB_Data/pcbenv"),
        ]
        for p in common:
            if p.is_dir():
                candidates.append(p)

        # ---- 策略 3：Roaming 下的 SPB_* ----
        roaming = home / "AppData" / "Roaming"
        if roaming.is_dir():
            try:
                candidates.extend(roaming.glob("SPB_*/pcbenv"))
                candidates.extend(roaming.glob("*/pcbenv"))
            except Exception:
                pass

        # ---- 策略 4：各盘符一级目录 ----
        for drive in string.ascii_uppercase:
            root = Path(f"{drive}:\\")
            if not root.exists():
                continue
            try:
                for sub in root.iterdir():
                    if not sub.is_dir():
                        continue
                    for pattern in [
                        sub / "pcbenv",
                        sub / "SPB_Data" / "pcbenv",
                        sub / "Cadence" / "SPB_Data" / "pcbenv",
                        sub / "Cadence" / "pcbenv",
                    ]:
                        if pattern.is_dir():
                            candidates.append(pattern)
            except (PermissionError, OSError):
                pass

        # ---- 策略 5：全盘深度搜索 ----
        if deep:
            log("启用深度搜索（可能耗时几分钟）...", "INFO")
            visited: set[str] = set()
            for drive in string.ascii_uppercase:
                root = Path(f"{drive}:\\")
                if not root.exists():
                    continue
                _search_dir_recursive(root, max_depth=4, results=candidates,
                                      visited=visited)

    elif system == "Darwin":
        candidates.extend((Path.home() / "cds").glob("*pcbenv"))
        candidates.extend(Path("/Applications").glob("*Cadence*/SPB_Data/pcbenv"))
        candidates.extend(Path.home().glob("pcbenv"))
        if deep:
            _search_dir_recursive(Path.home(), 4, candidates, set())

    else:  # Linux
        candidates.extend(Path.home().glob("cds*/pcbenv"))
        candidates.extend(Path.home().glob("pcbenv"))
        if deep:
            _search_dir_recursive(Path.home(), 4, candidates, set())

    # ---- 去重 ----
    result: list[Path] = []
    seen: set[str] = set()
    for p in candidates:
        try:
            if not p.is_dir():
                continue
        except Exception:
            continue
        try:
            key = str(p.resolve()).lower()
        except Exception:
            key = str(p).lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(p)
    return sorted(result)


def choose_pcbenv(candidates: list[Path], dry_run: bool) -> Path:
    if not candidates:
        print()
        print("=" * 60)
        print("❌ 自动搜索未能找到 Allegro 的 pcbenv 目录")
        print("=" * 60)
        print()
        print("可能的原因：")
        print("  1. Allegro 从未启动过（首次启动才会创建 pcbenv）")
        print("  2. Allegro 装在非常规路径")
        print()
        print("建议按以下顺序尝试：")
        print()
        print("  [A] 启动一次 Allegro PCB Editor，然后重新运行本脚本")
        print()
        print("  [B] 全盘深度搜索（可能耗时几分钟）：")
        print("      uv run install_skillbridge.py --deep-search")
        print()
        print("  [C] 手动指定路径：")
        print("      uv run install_skillbridge.py --pcbenv \"C:/完整/路径/pcbenv\"")
        print()
        print("如何找到 pcbenv 路径？")
        print("  打开 Allegro，在命令窗口输入：getShellEnvVar(\"SPB_Data\")")
        print("  返回值后面拼上 /pcbenv 就是它")
        print()
        sys.exit(1)

    if len(candidates) == 1:
        log(f"找到 pcbenv: {candidates[0]}", "OK")
        return candidates[0]

    print()
    print(f"发现 {len(candidates)} 个 pcbenv 目录：")
    for i, c in enumerate(candidates):
        print(f"  [{i}] {c}")
    print()

    if dry_run:
        log(f"[DRY-RUN] 默认选第一个: {candidates[0]}", "WARN")
        return candidates[0]

    while True:
        try:
            idx = int(input("选择要使用的编号（回车默认 0）：").strip() or "0")
            if 0 <= idx < len(candidates):
                return candidates[idx]
        except (ValueError, KeyboardInterrupt):
            print("输入无效，请重试")


# ============================================================
# 步骤 5：写 allegro.ilinit
# ============================================================
def build_marked_block(python_exe: Path, il_path: Path) -> str:
    """
    生成要插入的 SKILL 段落。

    重要 1：allegro.ilinit 本身就是 SKILL 文件，不要写单独的 `skill` 前缀，
            否则会报 "undefined variable - skill"。

    重要 2：每次启动前先调 pyKillServer，避免反复开关 Allegro 时累积多个
            Python 进程。pyKillServer 在 python_server.il 加载后才可用。
    """
    env_dir = python_exe.parent.parent
    pythonw = venv_pythonw_path(env_dir)
    py = str(pythonw).replace("\\", "/")
    il = str(il_path).replace("\\", "/")
    now = datetime.now().isoformat(timespec="seconds")

    return f"""{BEGIN_MARK}
;; 生成时间: {now}
;; Python:   {py}
;; SKILL:    {il}
;; 卸载: uv run install_skillbridge.py --uninstall
load("{il}")
pyKillServer
pyStartServer ?id "7777" ?python "{py}"
{END_MARK}"""


def remove_marked_block(text: str) -> tuple[str, bool]:
    pattern = re.compile(
        re.escape(BEGIN_MARK) + r".*?" + re.escape(END_MARK) + r"\s*",
        re.DOTALL,
    )
    if not pattern.search(text):
        return text, False
    return pattern.sub("", text), True


def write_ilinit(pcbenv: Path, python_exe: Path, il_path: Path, dry_run: bool) -> Path:
    target = pcbenv / "allegro.ilinit"
    block = build_marked_block(python_exe, il_path)

    if target.is_file():
        old = target.read_text(encoding="utf-8")
        cleaned, removed = remove_marked_block(old)
        if removed:
            log("检测到旧的 SkillBridge 标记块，将替换", "INFO")
        new_content = block + "\n\n" + cleaned.lstrip()
    else:
        new_content = block + "\n"

    if dry_run:
        log(f"[DRY-RUN] 将写入: {target}", "WARN")
        print("--- 预览 ---")
        print(new_content)
        print("------------")
        return target

    if target.is_file():
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = target.with_name(f"allegro.ilinit.bak_{ts}")
        shutil.copy2(target, backup)
        log(f"已备份原文件: {backup.name}", "OK")

    target.write_text(new_content, encoding="utf-8")
    log(f"已写入: {target}", "OK")
    return target


# ============================================================
# 卸载
# ============================================================
def uninstall() -> int:
    candidates = find_pcbenv_candidates(deep=False)
    if not candidates:
        log("找不到任何 pcbenv 目录", "ERR")
        return 1

    found_any = False
    for pcbenv in candidates:
        target = pcbenv / "allegro.ilinit"
        if not target.is_file():
            continue
        old = target.read_text(encoding="utf-8")
        cleaned, removed = remove_marked_block(old)
        if not removed:
            log(f"{target} 未发现标记块，跳过", "WARN")
            continue
        found_any = True
        backup = target.with_name(
            f"allegro.ilinit.uninstall_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        )
        shutil.copy2(target, backup)
        target.write_text(cleaned, encoding="utf-8")
        log(f"已从 {target} 移除标记块（备份: {backup.name}）", "OK")

    print()
    if found_any:
        print("提示：")
        print("  - Allegro 下次启动将不再自动加载 SkillBridge")
        print(f"  - 如需彻底清理虚拟环境: 删除 {Path.home() / '.local' / 'share' / ENV_DIR_NAME}")
    return 0


# ============================================================
# 主流程
# ============================================================
def main():
    parser = argparse.ArgumentParser(
        description="为 Allegro 一键配置 SkillBridge 自动加载"
    )
    parser.add_argument("--uninstall", action="store_true",
                        help="从 allegro.ilinit 里移除 SkillBridge 标记块")
    parser.add_argument("--dry-run", action="store_true",
                        help="预览，不实际写入文件")
    parser.add_argument("--deep-search", action="store_true",
                        help="启用全盘深度搜索 pcbenv（慢，但覆盖最全）")
    parser.add_argument("--pcbenv", type=str, default=None,
                        help="手动指定 pcbenv 目录路径")
    args = parser.parse_args()

    print("=" * 60)
    print(" SkillBridge 自动加载配置工具")
    print("=" * 60)
    print()

    if args.uninstall:
        return uninstall()

    # ---- 步骤 1：uv ----
    log("步骤 1/5：检查 uv")
    uv = ensure_uv()
    print()

    # ---- 步骤 2：skillbridge 环境 ----
    log("步骤 2/5：检查/安装 skillbridge 虚拟环境")
    env_dir = ensure_skillbridge_env(uv, args.dry_run)
    print()

    # ---- 步骤 3：拿路径 ----
    log("步骤 3/5：从虚拟环境定位 Python 和 python_server.il")
    try:
        python_exe = find_python_exe(env_dir)
        il_path = find_python_server_il(env_dir)
    except FileNotFoundError as e:
        log(str(e), "ERR")
        return 1
    pythonw = venv_pythonw_path(env_dir)
    log(f"Python:  {python_exe}", "OK")
    log(f"Pythonw: {pythonw}", "OK")
    log(f"SKILL:   {il_path}", "OK")
    print()

    # ---- 步骤 4：找 pcbenv ----
    log("步骤 4/5：查找 Allegro 的 pcbenv 目录")
    if args.pcbenv:
        pcbenv = Path(args.pcbenv)
        if not pcbenv.is_dir():
            log(f"手动指定的 pcbenv 不存在: {pcbenv}", "ERR")
            return 1
        log(f"使用手动指定的 pcbenv: {pcbenv}", "OK")
    else:
        candidates = find_pcbenv_candidates(deep=args.deep_search)
        pcbenv = choose_pcbenv(candidates, args.dry_run)
    print()

    # ---- 步骤 5：写 allegro.ilinit ----
    log("步骤 5/5：更新 allegro.ilinit")
    target = write_ilinit(pcbenv, python_exe, il_path, args.dry_run)
    print()

    if not args.dry_run:
        print("=" * 60)
        print("✅ 配置完成")
        print("=" * 60)
        print()
        print("下一步：")
        print("  1. 完全关闭 Allegro PCB Editor")
        print("  2. 重新打开")
        print("  3. 观察 CIW 命令窗口是否输出 SkillBridge 启动信息")
        print("  4. 命令行验证端口: netstat -ano | findstr 7777")
        print()
        print("如果出问题：")
        print(f"  - 备份文件目录: {target.parent}")
        print("  - 一键卸载: uv run install_skillbridge.py --uninstall")
    return 0


if __name__ == "__main__":
    sys.exit(main())