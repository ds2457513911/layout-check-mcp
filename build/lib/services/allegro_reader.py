# -*- coding: utf-8 -*-
"""
lib_allegro_reader.py —— 通过 Allegro SkillBridge 读取 .dra 封装参数
输出格式适配 job_compare_all.py / lib_tolerance_check 的 check_dimension_tolerance 工具

支持：
  - 中文路径（自动复制到临时英文目录）
  - 单位启发式校验（不盲信 axlDBGetDesignUnits）
  - 一个 .dra 对应多个 .pad（全部作为溯源信息记录）
"""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from skillbridge import Workspace
except ImportError:
    raise ImportError("请先安装 skillbridge: pip install skillbridge")

# ---------- 单位换算常量 ----------
MIL_TO_MM = 0.0254

# 备选层名（按优先级），用于 axlDBGetPad 兜底
PAD_LAYERS = ["TOP", "PIN/TOP", "BOTTOM", "PIN/BOTTOM"]


def _has_non_ascii(s: str) -> bool:
    if not s:
        return False
    try:
        s.encode("ascii")
        return False
    except UnicodeEncodeError:
        return True


def _get_db_units(ws: Workspace) -> str:
    """读取当前设计数据库的单位 (mil 或 mm)"""
    try:
        units = ws["axlDBGetDesignUnits"]()
        units_str = str(units).strip().lower()
        if "mil" in units_str:
            return "mil"
        if "mm" in units_str or "millimeter" in units_str:
            return "mm"
        return "mil"
    except Exception:
        return "mil"


def _sanitize_unit(unit: str, pads: List[Dict[str, float]]) -> str:
    """
    启发式单位校验：
      - unit == "mil" 但所有 width < 5  →  强制 mm
      - unit == "mm"  但所有 width > 200 → 强制 mil
    """
    widths = [p["width"] for p in pads if p.get("width") is not None]
    if not widths:
        return unit
    max_w = max(widths)
    if unit == "mil" and max_w < 5:
        return "mm"
    if unit == "mm" and max_w > 200:
        return "mil"
    return unit


def _bbox_to_dims(bbox: Any) -> Optional[Dict[str, float]]:
    """
    把 bBox 转成 width/height/x/y。
    支持：
      1) [[x1, y1], [x2, y2]]   —— Allegro pin["bBox"] 的实际格式
      2) [left, bottom, right, top]
    """
    if bbox is None:
        return None

    try:
        # 格式 1: [[x1, y1], [x2, y2]]
        if (
            len(bbox) == 2
            and hasattr(bbox[0], "__len__")
            and hasattr(bbox[1], "__len__")
            and len(bbox[0]) >= 2
            and len(bbox[1]) >= 2
        ):
            x1, y1 = float(bbox[0][0]), float(bbox[0][1])
            x2, y2 = float(bbox[1][0]), float(bbox[1][1])
            left, right = min(x1, x2), max(x1, x2)
            bottom, top = min(y1, y2), max(y1, y2)
            width = right - left
            height = top - bottom
            if width <= 0 or height <= 0:
                return None
            return {
                "width": width,
                "height": height,
                "x": (left + right) / 2,
                "y": (bottom + top) / 2,
            }

        # 格式 2: [left, bottom, right, top]
        if len(bbox) >= 4:
            left, bottom, right, top = [float(v) for v in bbox[:4]]
            width = abs(right - left)
            height = abs(top - bottom)
            if width <= 0 or height <= 0:
                return None
            return {
                "width": width,
                "height": height,
                "x": (left + right) / 2,
                "y": (bottom + top) / 2,
            }
    except (TypeError, ValueError, IndexError):
        return None
    return None


def _get_pin_dims_from_bbox(pin: Any) -> Optional[Dict[str, float]]:
    """优先方式：直接读 pin["bBox"]"""
    try:
        bbox = pin["bBox"]
    except Exception:
        try:
            bbox = pin.b_box
        except Exception:
            return None
    return _bbox_to_dims(bbox)


def _get_pin_dims_from_pad(ws: Workspace, pin: Any) -> Optional[Dict[str, float]]:
    """兜底方式：遍历 pin.pads 或 axlDBGetPad"""
    try:
        pads = pin["pads"]
        if pads:
            for pad in pads:
                try:
                    bbox = pad["bBox"]
                    dims = _bbox_to_dims(bbox)
                    if dims:
                        return dims
                except Exception:
                    continue
    except Exception:
        pass

    for layer in PAD_LAYERS:
        try:
            pad = ws["axlDBGetPad"](pin, layer, "regular")
            if pad is None:
                continue
            bbox = pad["bBox"]
            dims = _bbox_to_dims(bbox)
            if dims:
                return dims
        except Exception:
            continue
    return None


def _get_pin_position_from_xy(pin: Any) -> Optional[Dict[str, float]]:
    try:
        loc = pin["xy"]
        if loc is not None and len(loc) >= 2:
            return {"x": float(loc[0]), "y": float(loc[1])}
    except Exception:
        pass
    return None


def _derive_spacing(pads: List[Dict[str, float]]) -> Dict[str, Optional[float]]:
    """从多引脚坐标推算中心间距 spacing_x / spacing_y"""
    if len(pads) < 2:
        return {"spacing_x": None, "spacing_y": None}

    xs = sorted(set(round(p["x"], 3) for p in pads))
    ys = sorted(set(round(p["y"], 3) for p in pads))

    def min_gap(vals):
        if len(vals) < 2:
            return None
        return min(vals[i + 1] - vals[i] for i in range(len(vals) - 1))

    return {"spacing_x": min_gap(xs), "spacing_y": min_gap(ys)}


def _copy_pad_files_to_temp(pad_paths: List[str], temp_dir: str) -> List[str]:
    """把 pad 文件复制到临时英文目录，返回新路径列表"""
    new_paths = []
    for i, p in enumerate(pad_paths):
        try:
            pad_name = os.path.basename(p)
            if _has_non_ascii(pad_name):
                pad_name = f"temp_pad_{i}.pad"
            new_p = os.path.join(temp_dir, pad_name)
            shutil.copy2(p, new_p)
            new_paths.append(new_p)
        except Exception:
            new_paths.append(p)  # 复制失败时保留原路径
    return new_paths


def read_dra_package(
    dra_path: str,
    pad_paths: Optional[List[str]] = None,
    workspace_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    通过 SkillBridge 读取 .dra 封装，返回符合 check_dimension_tolerance 所需的 actual_payload。

    :param dra_path: .dra 文件完整路径
    :param pad_paths: 可选的 .pad 文件路径列表（多个），仅用于溯源记录
    :param workspace_id: SkillBridge 工作区 ID，None 表示使用默认 7777
    :return: {
        "source_file": 原始 .dra 路径,
        "pad_files": [原始 .pad 路径列表],
        "unit": "mil" or "mm",
        "pads": [{"pin": str, "width": float, "height": float}],
        "spacing_x": float or None,
        "spacing_y": float or None,
        "raw_pin_count": int,
        "valid_dimension_count": int,
        "reference_mm": {...}   # 仅当 unit == "mil" 时附带
    }
    """
    pad_paths = pad_paths or []

    _original_dra = dra_path
    _original_pads = list(pad_paths)
    _temp_dir = None

    # ---------- 校验输入 ----------
    if not os.path.isfile(_original_dra):
        return {
            "error": f".dra 文件不存在: {_original_dra}",
            "pads": [],
            "unit": "mil",
            "pad_files": _original_pads,
        }
    for p in _original_pads:
        if not os.path.isfile(p):
            return {
                "error": f".pad 文件不存在: {p}",
                "pads": [],
                "unit": "mil",
                "pad_files": _original_pads,
            }

    # ---------- 中文路径处理 ----------
    dra_path = _original_dra
    pad_paths = list(_original_pads)

    if _has_non_ascii(_original_dra) or any(_has_non_ascii(p) for p in _original_pads):
        try:
            _temp_dir = tempfile.mkdtemp(prefix="allegro_tmp_")

            # 复制 .dra
            dra_name = os.path.basename(_original_dra)
            if _has_non_ascii(dra_name):
                dra_name = "temp_footprint.dra"
            temp_dra = os.path.join(_temp_dir, dra_name)
            shutil.copy2(_original_dra, temp_dra)
            dra_path = temp_dra

            # 复制所有 .pad
            pad_paths = _copy_pad_files_to_temp(_original_pads, _temp_dir)
        except Exception as e:
            if _temp_dir and os.path.isdir(_temp_dir):
                shutil.rmtree(_temp_dir, ignore_errors=True)
            return {
                "error": f"中文路径复制到临时目录失败: {e}",
                "source_file": _original_dra,
                "pad_files": _original_pads,
                "pads": [],
                "unit": "mil",
            }

    # ---------- 连接 SkillBridge ----------
    ws = Workspace.open(workspace_id=workspace_id or "7777")

    try:
        # ---------- 1. 打开 .dra ----------
        try:
            result = ws["axlOpenDesign"](design=dra_path, mode="wf")
            if not result:
                return {
                    "error": f"axlOpenDesign 返回失败: {dra_path}",
                    "source_file": _original_dra,
                    "pad_files": _original_pads,
                    "pads": [],
                    "unit": "mil",
                }
        except Exception as e:
            return {
                "error": f"无法打开 .dra 文件: {e}",
                "source_file": _original_dra,
                "pad_files": _original_pads,
                "pads": [],
                "unit": "mil",
            }

        # ---------- 2. 获取设计单位 ----------
        unit = _get_db_units(ws)

        # ---------- 3. 获取所有引脚 ----------
        design = ws["axlDBGetDesign"]()
        if design is None:
            return {
                "error": "axlDBGetDesign 返回空",
                "source_file": _original_dra,
                "pad_files": _original_pads,
                "pads": [],
                "unit": unit,
            }

        pins = None
        for attr in ("pins", "Pins"):
            try:
                val = getattr(design, attr, None)
                if val is None:
                    val = design[attr]
                if val:
                    pins = val
                    break
            except Exception:
                continue

        if not pins:
            return {
                "error": ".dra 文件中未找到任何引脚",
                "source_file": _original_dra,
                "pad_files": _original_pads,
                "pads": [],
                "unit": unit,
            }

        try:
            pins = list(pins)
        except TypeError:
            pass

        # ---------- 4. 遍历引脚 ----------
        pads = []
        for idx, pin in enumerate(pins):
            pin_name = None
            try:
                pin_name = str(pin["number"] or pin["name"] or f"pin_{idx + 1}")
            except Exception:
                pin_name = f"pin_{idx + 1}"

            dims = _get_pin_dims_from_bbox(pin)
            if dims is None:
                dims = _get_pin_dims_from_pad(ws, pin)

            if dims is None:
                pads.append({
                    "pin": pin_name,
                    "width": None,
                    "height": None,
                    "x": None,
                    "y": None,
                })
                continue

            pos = _get_pin_position_from_xy(pin)
            if pos is None:
                pos = {"x": dims["x"], "y": dims["y"]}

            pads.append({
                "pin": pin_name,
                "width": dims["width"],
                "height": dims["height"],
                "x": pos["x"],
                "y": pos["y"],
            })

        # ---------- 5. 推算中心间距 ----------
        valid_pads = [p for p in pads if p["x"] is not None and p["y"] is not None]
        spacing = _derive_spacing(valid_pads)

        # ---------- 6. 单位校验 ----------
        unit = _sanitize_unit(unit, pads)

        # ---------- 7. 组装返回 ----------
        result = {
            "source_file": os.path.abspath(_original_dra),
            "pad_files": [os.path.abspath(p) for p in _original_pads],
            "unit": unit,
            "pads": [
                {
                    "pin": p["pin"],
                    "width": p["width"],
                    "height": p["height"],
                }
                for p in pads
            ],
            "spacing_x": spacing["spacing_x"],
            "spacing_y": spacing["spacing_y"],
            "raw_pin_count": len(pads),
            "valid_dimension_count": sum(1 for p in pads if p["width"] is not None),
        }

        if unit == "mil":
            result["reference_mm"] = {
                "pads": [
                    {
                        "pin": p["pin"],
                        "width_mm": round(p["width"] * MIL_TO_MM, 4) if p["width"] else None,
                        "height_mm": round(p["height"] * MIL_TO_MM, 4) if p["height"] else None,
                    }
                    for p in pads
                    if p["width"] is not None
                ],
                "spacing_x_mm": round(spacing["spacing_x"] * MIL_TO_MM, 4) if spacing["spacing_x"] else None,
                "spacing_y_mm": round(spacing["spacing_y"] * MIL_TO_MM, 4) if spacing["spacing_y"] else None,
            }

        return result

    finally:
        try:
            ws.close()
        except Exception:
            pass
        if _temp_dir and os.path.isdir(_temp_dir):
            try:
                shutil.rmtree(_temp_dir, ignore_errors=True)
            except Exception:
                pass


# ---------- 命令行入口 ----------
if __name__ == "__main__":
    import json
    import sys

    if len(sys.argv) < 2:
        print("用法: python lib_allegro_reader.py <dra路径> [pad路径1] [pad路径2] ...")
        sys.exit(1)

    dra = sys.argv[1]
    pads = sys.argv[2:] if len(sys.argv) > 2 else []
    result = read_dra_package(dra_path=dra, pad_paths=pads)
    print(json.dumps(result, ensure_ascii=False, indent=2))