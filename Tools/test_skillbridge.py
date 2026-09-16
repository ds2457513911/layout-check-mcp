# -*- coding: utf-8 -*-
"""
test_skillbridge.py —— SkillBridge + Allegro 本地连通性测试 (v3)

不经过 MCP、不经过 AI，直接在本机验证：
  1. skillbridge 包能否 import
  2. 能否连上 Allegro 的 SkillBridge 服务（默认 7777）
  3. 能否打开一个 .dra 文件
  4. 能否读出引脚信息（bbox / 位置 / 单位）
  5. 如果项目里有 services.allegro_reader，顺便调用它做端到端对比

v3 关键改动：
  - **总是**把 .dra / .psm / .pad 复制到临时英文目录再打开
    理由：
      a. 中文路径会触发 SKILL 解析器的 unicode 转义报错
      b. 文件锁：用户手动用 Allegro 开着同一个 .dra 时会生成 .lck，
         直接打开原件会卡死（等待 Allegro 弹窗）
  - 顺带复制同名的 .psm（Allegro 打开 .dra 时会找它）

用法：
    # 最简：只测连接
    python test_skillbridge.py

    # 测试读某个 .dra
    python test_skillbridge.py "C:\\path\\to\\your.dra"

    # 测试读 .dra + 同目录的 .pad
    python test_skillbridge.py "C:\\path\\to\\your.dra" "C:\\path\\pad1.pad" "C:\\path\\pad2.pad"

    # 指定 workspace_id（默认 7777）
    python test_skillbridge.py "C:\\path\\to\\your.dra" --id 7777

    # 保留临时目录（排查用）
    python test_skillbridge.py "C:\\path\\to\\your.dra" --keep-temp
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# 保证能从项目根目录 import services.*
_THIS_FILE = Path(__file__).resolve()
_PROJECT_ROOT = _THIS_FILE.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ============================================================
# 日志
# ============================================================
def log(msg: str, level: str = "INFO") -> None:
    prefix = {
        "INFO": "   ",
        "OK":   "✅",
        "WARN": "⚠️",
        "ERR":  "❌",
        "STEP": "▶",
        "DBG":  "  ·",
    }[level]
    print(f"{prefix} {msg}", flush=True)


def section(title: str) -> None:
    print()
    print("=" * 64)
    print(f" {title}")
    print("=" * 64)


# ============================================================
# 路径处理
# ============================================================
def _has_non_ascii(s: str) -> bool:
    """字符串里是否有非 ASCII 字符（中文、日文等）"""
    try:
        s.encode("ascii")
        return False
    except UnicodeEncodeError:
        return True


def copy_to_temp(
    dra_path: Path, pad_paths: list[Path]
) -> tuple[Path, list[Path], Path, list[str]]:
    """
    总是把 .dra、同名 .psm、所有 .pad 复制到临时英文目录。

    目的：
      1. 规避中文路径（SKILL 解析器对非 ASCII 路径支持不好）
      2. 规避文件锁（Allegro 打开 .dra 时会生成 .lck）

    :return: (新 dra 路径, 新 pad 路径列表, 临时目录, 复制清单)
    """
    temp_dir = Path(tempfile.mkdtemp(prefix="skillbridge_test_"))
    copied: list[str] = []

    # ---- 1. .dra ----
    dra_name = dra_path.name
    if _has_non_ascii(dra_name):
        dra_name = "temp_footprint.dra"
    new_dra = temp_dir / dra_name
    shutil.copy2(dra_path, new_dra)
    copied.append(f"{dra_path.name} -> {new_dra.name}")

    # ---- 2. 同名 .psm（Allegro 打开 .dra 时会找它）----
    new_stem = new_dra.stem
    for ext in (".psm",):
        src_psm = dra_path.with_suffix(ext)
        if src_psm.is_file():
            new_psm = temp_dir / (new_stem + ext)
            shutil.copy2(src_psm, new_psm)
            copied.append(f"{src_psm.name} -> {new_psm.name}")

    # ---- 3. 所有 .pad ----
    new_pads: list[Path] = []
    for i, p in enumerate(pad_paths):
        try:
            pad_name = p.name
            if _has_non_ascii(pad_name):
                pad_name = f"temp_pad_{i}.pad"
            new_p = temp_dir / pad_name
            shutil.copy2(p, new_p)
            new_pads.append(new_p)
            copied.append(f"{p.name} -> {new_p.name}")
        except Exception as e:
            log(f"复制 {p} 失败：{e}", "WARN")
            new_pads.append(p)

    return new_dra, new_pads, temp_dir, copied


def cleanup_temp(temp_dir: Path | None) -> None:
    if temp_dir and temp_dir.is_dir():
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
            log(f"已清理临时目录: {temp_dir}", "INFO")
        except Exception:
            pass


# ============================================================
# 环境探测
# ============================================================
def detect_environment() -> dict:
    info = {
        "python": sys.executable,
        "python_version": sys.version.split()[0],
        "platform": platform.platform(),
        "cwd": os.getcwd(),
    }

    try:
        import skillbridge
        info["skillbridge_ok"] = True
        info["skillbridge_path"] = getattr(skillbridge, "__file__", "?")
    except Exception as e:
        info["skillbridge_ok"] = False
        info["skillbridge_error"] = str(e)

    try:
        import fitz  # noqa: F401
        info["pymupdf_ok"] = True
    except Exception:
        info["pymupdf_ok"] = False

    return info


def check_port(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (OSError, socket.timeout):
        return False


def find_allegro_process() -> list[str]:
    if platform.system() != "Windows":
        return []
    try:
        r = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq allegro.exe"],
            capture_output=True, text=True, timeout=5,
        )
        return [l for l in r.stdout.splitlines() if "allegro" in l.lower()]
    except Exception:
        return []


# ============================================================
# 测试 1：环境
# ============================================================
def test_environment(workspace_id: str) -> dict:
    section("测试 1/5：环境探测")
    info = detect_environment()

    log(f"Python:        {info['python']}")
    log(f"Python 版本:   {info['python_version']}")
    log(f"平台:          {info['platform']}")
    log(f"工作目录:      {info['cwd']}")
    log(f"项目根:        {_PROJECT_ROOT}")

    if info["skillbridge_ok"]:
        log(f"skillbridge:   已找到 ({info['skillbridge_path']})", "OK")
    else:
        log(f"skillbridge:   未找到 -> {info['skillbridge_error']}", "ERR")
        return info

    if info.get("pymupdf_ok"):
        log("PyMuPDF:       已找到", "OK")
    else:
        log("PyMuPDF:       未找到（不影响 SkillBridge 测试）", "WARN")

    allegro_procs = find_allegro_process()
    if allegro_procs:
        log("Allegro 进程：", "OK")
        for l in allegro_procs:
            print(f"      {l.strip()}")
    else:
        log("Allegro 进程：  未检测到（可能还没启动）", "WARN")

    log(f"检测端口 {workspace_id} ...")
    if check_port("127.0.0.1", int(workspace_id)):
        log(f"端口 {workspace_id} 已在监听", "OK")
        info["port_listening"] = True
    else:
        log(f"端口 {workspace_id} 未监听", "WARN")
        info["port_listening"] = False

    return info


# ============================================================
# 测试 2：连接 Workspace
# ============================================================
def test_connect(workspace_id: str):
    section(f"测试 2/5：连接 SkillBridge Workspace (id={workspace_id})")

    try:
        from skillbridge import Workspace
    except Exception as e:
        log(f"无法 import skillbridge: {e}", "ERR")
        return None

    log(f"尝试打开 workspace id={workspace_id} ...")
    t0 = time.time()
    try:
        ws = Workspace.open(workspace_id=workspace_id)
        dt = time.time() - t0
        log(f"连接成功（耗时 {dt:.2f}s）", "OK")
        return ws
    except Exception as e:
        dt = time.time() - t0
        log(f"连接失败（耗时 {dt:.2f}s）：{type(e).__name__}: {e}", "ERR")
        return None


# ============================================================
# 测试 3：打开 .dra
# ============================================================
def test_open_dra(ws, dra_path: Path) -> bool:
    section("测试 3/5：打开 .dra 文件")

    log(f"路径: {dra_path}")
    if not dra_path.is_file():
        log(".dra 文件不存在", "ERR")
        return False

    log(f"文件大小: {dra_path.stat().st_size} bytes")

    log("调用 axlOpenDesign ...")
    t0 = time.time()
    try:
        result = ws["axlOpenDesign"](design=str(dra_path), mode="wf")
        dt = time.time() - t0
        if result:
            log(f"axlOpenDesign 返回: {result!r}（耗时 {dt:.2f}s）", "OK")
            return True
        else:
            log(f"axlOpenDesign 返回空（耗时 {dt:.2f}s）", "ERR")
            return False
    except Exception as e:
        dt = time.time() - t0
        log(f"打开失败（耗时 {dt:.2f}s）：{type(e).__name__}: {e}", "ERR")
        return False


# ============================================================
# 测试 4：读引脚
# ============================================================
def test_read_pins(ws) -> dict:
    section("测试 4/5：读取引脚信息")

    try:
        log("调用 axlDBGetDesign ...")
        design = ws["axlDBGetDesign"]()
        if design is None:
            log("axlDBGetDesign 返回 None", "ERR")
            return {}
        log("axlDBGetDesign 成功", "OK")
    except Exception as e:
        log(f"axlDBGetDesign 失败：{type(e).__name__}: {e}", "ERR")
        return {}

    try:
        units = ws["axlDBGetDesignUnits"]()
        log(f"设计单位: {units}", "OK")
    except Exception as e:
        units = "?"
        log(f"读取单位失败：{e}", "WARN")

    pins = None
    method = None
    for attr in ("pins", "Pins"):
        try:
            val = getattr(design, attr, None)
            if val is None:
                try:
                    val = design[attr]
                except Exception:
                    pass
            if val:
                pins = val
                method = f"design.{attr}"
                break
        except Exception:
            continue

    if not pins:
        log("design.pins 为空，尝试 axlDBGetSymbol ...", "WARN")
        try:
            symbol = ws["axlDBGetSymbol"]()
            if symbol is not None:
                for attr in ("pins", "Pins"):
                    try:
                        val = getattr(symbol, attr, None)
                        if val:
                            pins = val
                            method = f"symbol.{attr}"
                            break
                    except Exception:
                        continue
        except Exception as e:
            log(f"axlDBGetSymbol 失败：{e}", "WARN")

    if not pins:
        log("未通过任何途径找到引脚列表", "ERR")
        log(f"design 类型: {type(design)}", "DBG")
        log(f"design 可用属性: {[a for a in dir(design) if not a.startswith('_')][:30]}", "DBG")
        return {"unit": str(units), "pin_count": 0, "pins": []}

    try:
        pins = list(pins)
    except TypeError:
        pass

    log(f"引脚来源: {method}", "INFO")
    log(f"引脚总数: {len(pins)}", "OK")

    result_pins = []
    for i, pin in enumerate(pins[:20]):
        try:
            pin_name = str(pin["number"] or pin["name"] or f"pin_{i+1}")
        except Exception:
            pin_name = f"pin_{i+1}"

        dims = None
        bbox_raw = None
        try:
            bbox_raw = pin["bBox"]
        except Exception:
            try:
                bbox_raw = pin.b_box
            except Exception:
                pass

        if bbox_raw is not None:
            try:
                x1, y1 = float(bbox_raw[0][0]), float(bbox_raw[0][1])
                x2, y2 = float(bbox_raw[1][0]), float(bbox_raw[1][1])
                w = abs(x2 - x1)
                h = abs(y2 - y1)
                dims = {"width": w, "height": h}
            except Exception as e:
                dims = {"error": str(e)}

        pos = None
        try:
            loc = pin["xy"]
            if loc is not None and len(loc) >= 2:
                pos = {"x": float(loc[0]), "y": float(loc[1])}
        except Exception:
            pass

        entry = {"pin": pin_name, "bbox_raw": bbox_raw, "dims": dims, "pos": pos}
        result_pins.append(entry)
        log(f"  pin {pin_name}: dims={dims} pos={pos}")

    return {
        "unit": str(units),
        "pin_count": len(pins),
        "pins": result_pins,
    }


# ============================================================
# 测试 5：调用项目的 read_dra_package（端到端）
# ============================================================
def test_project_reader(dra_path: Path, pad_paths: list[Path]) -> dict:
    section("测试 5/5：调用项目里的 read_dra_package（端到端）")

    try:
        from services.allegro_reader import read_dra_package
        log("成功 import services.allegro_reader.read_dra_package", "OK")
    except Exception as e:
        log(f"无法 import 项目模块：{type(e).__name__}: {e}", "WARN")
        log("跳过（请在项目根目录运行，或确保 services 包可导入）", "WARN")
        return {}

    log(f"dra: {dra_path}")
    log(f"pads: {[str(p) for p in pad_paths]}")

    t0 = time.time()
    try:
        result = read_dra_package(
            dra_path=str(dra_path),
            pad_paths=[str(p) for p in pad_paths],
        )
        dt = time.time() - t0
        log(f"read_dra_package 返回（耗时 {dt:.2f}s）", "OK")
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return result
    except Exception as e:
        dt = time.time() - t0
        log(f"read_dra_package 失败（耗时 {dt:.2f}s）：{type(e).__name__}: {e}", "ERR")
        import traceback
        traceback.print_exc()
        return {}


# ============================================================
# 主流程
# ============================================================
def main():
    parser = argparse.ArgumentParser(
        description="SkillBridge + Allegro 本地连通性测试 (v3)"
    )
    parser.add_argument("dra", nargs="?", default=None,
                        help=".dra 文件路径（不传则只测连接）")
    parser.add_argument("pads", nargs="*", default=[],
                        help="可选的 .pad 文件路径")
    parser.add_argument("--id", type=str, default="7777",
                        help="workspace id / 端口，默认 7777")
    parser.add_argument("--skip-project", action="store_true",
                        help="跳过测试 5（不调项目的 read_dra_package）")
    parser.add_argument("--keep-temp", action="store_true",
                        help="保留临时目录，方便排查")
    args = parser.parse_args()

    print()
    print("╔" + "═" * 62 + "╗")
    print("║  SkillBridge + Allegro 本地连通性测试 (v3)".ljust(56) + " ║")
    print("╚" + "═" * 62 + "╝")

    temp_dir: Path | None = None
    exit_code = 0

    try:
        # 1. 环境
        env_info = test_environment(args.id)

        if not env_info.get("skillbridge_ok"):
            log("环境不完整，测试终止", "ERR")
            return 1

        # 2. 连接
        ws = test_connect(args.id)
        if ws is None:
            log("连接失败，后续测试无法继续", "ERR")
            print()
            print("建议：")
            print("  1. 打开 Allegro PCB Editor")
            print(f"  2. 在 CIW 里执行：pyStartServer ?id \"{args.id}\"")
            print(f"  3. 确认端口监听：netstat -ano | findstr {args.id}")
            return 2

        # 无 dra 参数：测到连接为止
        if not args.dra:
            log("未提供 .dra 路径，测试到连接为止", "OK")
            log("如需测试读封装，请把 .dra 路径作为参数传入", "INFO")
            return 0

        dra_path = Path(args.dra).resolve()
        pad_paths = [Path(p).resolve() for p in args.pads]

        # ---------- 总是复制到临时目录 ----------
        section("路径处理：复制到临时英文目录")
        if _has_non_ascii(str(dra_path)):
            log("检测到中文/非 ASCII 路径", "WARN")
        log("总是复制（规避中文路径 + 规避文件锁）", "INFO")

        dra_path, pad_paths, temp_dir, copied = copy_to_temp(dra_path, pad_paths)
        log(f"临时目录: {temp_dir}", "OK")
        for c in copied:
            log(f"  {c}", "INFO")

        # 3. 打开
        ok = test_open_dra(ws, dra_path)
        if not ok:
            log("打开 .dra 失败", "ERR")
            return 3

        # 4. 读引脚
        pins_info = test_read_pins(ws)

        # 5. 项目端到端
        if not args.skip_project:
            test_project_reader(dra_path, pad_paths)

        # 汇总
        section("测试汇总")
        log(f"Python 环境:    {'OK' if env_info.get('skillbridge_ok') else 'FAIL'}")
        log(f"端口 {args.id}:    {'OK' if env_info.get('port_listening') else 'FAIL'}")
        log(f"Workspace 连接: OK")
        log(f"打开 .dra:      {'OK' if ok else 'FAIL'}")
        log(f"读到引脚数:     {pins_info.get('pin_count', 0)}")
        print()

        if pins_info.get("pin_count", 0) == 0:
            log("引脚数为 0，请检查：", "WARN")
            log("  1. .dra 是否真的是封装（而不是空文件）", "INFO")
            log("  2. Allegro 是否真的打开了它（看 Allegro 窗口）", "INFO")
            log("  3. 是否有 .psm 缺失（测试 1 里已自动复制）", "INFO")
            exit_code = 4
        else:
            log("测试完成", "OK")
            exit_code = 0

        return exit_code

    finally:
        if not args.keep_temp:
            cleanup_temp(temp_dir)
        else:
            if temp_dir:
                log(f"保留临时目录: {temp_dir}", "INFO")


if __name__ == "__main__":
    sys.exit(main())