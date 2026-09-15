# -*- coding: utf-8 -*-
"""
tolerance_service.py —— 理论焊盘参数 vs 实际封装参数 公差比对

理论: AI 从 datasheet 读取 / moondream 解析 (theoretical_land_params)
实际: SkillBridge 从 Allegro .dra/.pad 读出 (actual_payload)

所有数值统一换算成 mm 后再比对，避免 mm/mil 混用错误。

公差解析规则（按优先级）：
  1. 调用方显式传入的 tolerance 优先
  2. 否则用 theoretical_payload 里的 tolerance 字段
  3. 都没有 → 按维度回落默认（width/height ±0.1，spacing ±0.15）

每个维度的公差可以是：
  - None                → 该维度用默认
  - 数字 v              → 对称 ±v
  - {"min": a, "max": b} → 非对称
  - {"value": v}        → 对称 ±v
  - {"type": "percent", "value": p} → 理论值 ±p%
"""
from __future__ import annotations

from typing import Any, Optional

# ---------- 单位换算 ----------
_UNIT_TO_MM = {
    "mm": 1.0, "millimeter": 1.0, "millimeters": 1.0,
    "millimetre": 1.0, "millimetres": 1.0,
    "mil": 0.0254, "mils": 0.0254, "thou": 0.0254,
    "um": 0.001, "µm": 0.001, "micron": 0.001, "microns": 0.001,
    "nm": 1e-6, "nanometer": 1e-6, "nanometers": 1e-6,
    "inch": 25.4, "in": 25.4, '"': 25.4,
}

# pad 字典里各维度的字段别名
_DIM_ALIASES = {
    "width":  ["width", "w", "size_x", "x_size"],
    "height": ["height", "h", "size_y", "y_size"],
    "dia":    ["dia", "diameter"],
}

DEFAULT_DIMENSIONS = ["width", "height"]
SPACING_DIMS = ["spacing_x", "spacing_y"]

# ---------- 按维度的默认公差（mm） ----------
_DEFAULT_TOL = {
    "width":     (-0.1,  0.1),
    "height":    (-0.1,  0.1),
    "spacing_x": (-0.15, 0.15),
    "spacing_y": (-0.15, 0.15),
}

# 判定前统一 round 的位数，用于消除浮点误差
_ROUND_DIGITS = 6


def _default_tol_for(dim: str) -> tuple[float, float]:
    """按维度返回默认公差；未知维度用 ±0.1"""
    return _DEFAULT_TOL.get(dim, (-0.1, 0.1))


def _to_mm(value: float, unit: str) -> float:
    key = str(unit).strip().lower()
    factor = _UNIT_TO_MM.get(key)
    if factor is None:
        raise ValueError(f"不支持的单位: {unit}，支持 {list(_UNIT_TO_MM)}")
    return float(value) * factor


def _norm_pin(pin: Any, fallback_idx: int = 0) -> str:
    """pin 号归一化；None 用 idx 兜底，避免多个 None 互相覆盖"""
    if pin is None or pin == "":
        return f"__no_pin_{fallback_idx}"
    return str(pin).strip().lower()


def _extract_pads(payload: Any) -> tuple[list[dict], str]:
    """兼容两种输入形态：dict 带 pads 字段，或直接是 pad 列表"""
    if isinstance(payload, dict):
        unit = payload.get("unit") or payload.get("units") or "mm"
        pads = payload.get("pads")
        if pads is None:
            pads = []
    elif isinstance(payload, list):
        unit = "mm"
        pads = payload
    else:
        return [], "mm"

    if not isinstance(pads, list):
        pads = []
    return pads, unit


def _pick_dim(pad: dict, dim: str) -> Optional[float]:
    """从单个 pad 字典取维度数值，兼容别名；取不到返回 None"""
    if not isinstance(pad, dict):
        return None
    for key in _DIM_ALIASES.get(dim, [dim]):
        if key in pad and pad[key] is not None:
            try:
                return float(pad[key])
            except (TypeError, ValueError):
                continue
    return None


def _resolve_tolerance(tol: Any, dim: str, theo_mm: float) -> tuple[float, float, str]:
    """
    解析公差配置，返回 (tol_min, tol_max, source)。

    source 取值：
      - "pdf"     : 用了显式传入或 payload 里的公差
      - "default" : 回落到了默认公差

    回落规则：
      1. tol 本身是 None          → 按 dim 回落默认
      2. tol 是数字               → 对称 ±值，source="pdf"
      3. tol 是 dict，dim 显式为 None → 按 dim 回落默认
      4. tol 是 dict，dim 有配置   → 用该配置，source="pdf"
      5. tol 是 dict，无该 dim    → 按 dim 回落默认
      6. tol 是 dict，顶层有 min/max 或 value → 用顶层，source="pdf"
      7. 无法识别                 → 按 dim 回落默认
    """
    # 1. tol 本身为 None
    if tol is None:
        return (*_default_tol_for(dim), "default")

    # 2. 数字：对称公差
    if isinstance(tol, (int, float)):
        v = float(tol)
        return -v, v, "pdf"

    # 非 dict 的异常输入：回落默认
    if not isinstance(tol, dict):
        return (*_default_tol_for(dim), "default")

    # 3. percent 模式
    if tol.get("type") == "percent":
        pct = float(tol.get("value", 0.1))
        return -abs(theo_mm) * pct, abs(theo_mm) * pct, "pdf"

    # 4/5. 按维度取值
    if dim in tol:
        cfg = tol[dim]
        # 4. 该维度显式为 null：回落默认
        if cfg is None:
            return (*_default_tol_for(dim), "default")
        # dict 形式
        if isinstance(cfg, dict):
            if "min" in cfg and "max" in cfg:
                return float(cfg["min"]), float(cfg["max"]), "pdf"
            if "value" in cfg:
                v = float(cfg["value"])
                return -v, v, "pdf"
        # 数字形式
        if isinstance(cfg, (int, float)):
            v = float(cfg)
            return -v, v, "pdf"
        # 其他异常：回落默认
        return (*_default_tol_for(dim), "default")

    # 6. 顶层 min/max 或 value
    if "min" in tol and "max" in tol:
        return float(tol["min"]), float(tol["max"]), "pdf"
    if "value" in tol:
        v = float(tol["value"])
        return -v, v, "pdf"

    # 7. 都无法识别：回落默认
    return (*_default_tol_for(dim), "default")


def _make_na_row(pin: str, dim: str, src_theo, src_act, reason: str = "") -> dict:
    if not reason:
        reason = "理论端缺失" if src_theo is None else "实际端缺失"
    return {
        "pin": pin, "dimension": dim,
        "theoretical_mm": src_theo, "actual_mm": src_act,
        "delta_mm": None, "tol_min_mm": None, "tol_max_mm": None,
        "tol_source": None,
        "status": "NA",
        "reason": reason,
    }


def check_dimension_tolerance(
    theoretical_payload: dict,
    actual_payload: dict,
    tolerance: Any = None,
    dimensions: Optional[list] = None,
    include_spacing: bool = True,
) -> dict:
    """
    逐 pin 逐维度比对理论值与实际值，输出 PASS/FAIL/NA + 汇总 + 结论。
    spacing 只比对一次（不再按 pin 重复）。

    :param theoretical_payload: 包含 theoretical_land_params 的完整 payload
    :param actual_payload:      lib_allegro_reader 返回的 actual_payload
    :param tolerance:           公差配置；None 时用 theoretical_payload 里的 tolerance，
                                再 None 时按维度回落默认
    :param dimensions:          要比对的维度，默认 ["width", "height"]
    :param include_spacing:     是否比对 spacing_x / spacing_y，默认 True
    """
    if not isinstance(theoretical_payload, dict):
        raise ValueError("theoretical_payload 必须是 dict")
    theo = theoretical_payload.get("theoretical_land_params")
    if not isinstance(theo, dict) or not theo:
        raise ValueError(
            "theoretical_payload 中缺少 theoretical_land_params（或为空）。"
            "请传入 parse_datasheet_land_pattern 的完整返回，而不是内层字典。"
        )

    theo_pads, theo_unit = _extract_pads(theo)
    actual_pads, actual_unit = _extract_pads(actual_payload)

    # 公差来源优先级：显式传入 > payload 内 tolerance > 默认（由 _resolve_tolerance 回落）
    if tolerance is None:
        tolerance = theo.get("tolerance")
    # 到这里如果仍为 None，_resolve_tolerance 会按维度回落默认，不再抛错

    dims = list(dimensions or DEFAULT_DIMENSIONS)
    if include_spacing:
        dims += SPACING_DIMS

    # pin 映射（带 idx 兜底，避免 None 冲突）
    theo_map = {
        _norm_pin(p.get("pin"), i): p
        for i, p in enumerate(theo_pads) if isinstance(p, dict)
    }
    actual_map = {
        _norm_pin(p.get("pin"), i): p
        for i, p in enumerate(actual_pads) if isinstance(p, dict)
    }
    all_pins = sorted(set(theo_map) | set(actual_map), key=str)

    comparisons: list[dict] = []
    failed: list[dict] = []

    def _append_row(pin, dim, src_theo, src_act):
        # 任一端缺失 → NA
        if src_theo is None or src_act is None:
            comparisons.append(_make_na_row(pin, dim, src_theo, src_act))
            return

        # 单位换算
        try:
            theo_mm = _to_mm(src_theo, theo_unit)
            act_mm = _to_mm(src_act, actual_unit)
        except (TypeError, ValueError) as e:
            comparisons.append(_make_na_row(
                pin, dim, src_theo, src_act,
                reason=f"单位换算失败: {e}",
            ))
            return

        # 先 round 到固定精度，消除浮点误差带来的边界误判
        # 例如 1.5 - 1.4 = 0.09999999999999987 → round 后是 0.1
        delta = round(act_mm - theo_mm, _ROUND_DIGITS)

        tol_min, tol_max, tol_source = _resolve_tolerance(tolerance, dim, theo_mm)
        tol_min = round(tol_min, _ROUND_DIGITS)
        tol_max = round(tol_max, _ROUND_DIGITS)

        # 闭区间判定：delta 落在 [tol_min, tol_max] 内即为 PASS
        # 边界值（delta == tol_min 或 tol_max）算 PASS
        status = "PASS" if tol_min <= delta <= tol_max else "FAIL"

        row = {
            "pin": pin, "dimension": dim,
            "theoretical_mm": round(theo_mm, 4),
            "actual_mm": round(act_mm, 4),
            "delta_mm": round(delta, 4),
            "tol_min_mm": round(tol_min, 4),
            "tol_max_mm": round(tol_max, 4),
            "tol_source": tol_source,
            "status": status,
            "reason": "",
        }
        comparisons.append(row)
        if status == "FAIL":
            failed.append(row)

    # -------- 1) 逐 pin 比对 width/height --------
    for pin in all_pins:
        for dim in [d for d in dims if not d.startswith("spacing_")]:
            src_theo = _pick_dim(theo_map.get(pin, {}), dim)
            src_act = _pick_dim(actual_map.get(pin, {}), dim)
            _append_row(pin, dim, src_theo, src_act)

    # -------- 2) spacing 只比对一次 --------
    if include_spacing:
        for dim in SPACING_DIMS:
            if dim not in dims:
                continue
            src_theo = theo.get(dim)
            src_act = actual_payload.get(dim) if isinstance(actual_payload, dict) else None
            _append_row("ALL", dim, src_theo, src_act)

    # -------- 汇总 --------
    n_total = len(comparisons)
    n_pass = sum(1 for c in comparisons if c["status"] == "PASS")
    n_fail = sum(1 for c in comparisons if c["status"] == "FAIL")
    n_na = n_total - n_pass - n_fail

    # 按公差来源统计（帮助用户判断有多少是用了默认值）
    by_tol_source = {"pdf": 0, "default": 0, "na": 0}
    for c in comparisons:
        src = c.get("tol_source")
        if c["status"] == "NA":
            by_tol_source["na"] += 1
        elif src == "pdf":
            by_tol_source["pdf"] += 1
        else:
            by_tol_source["default"] += 1

    if n_fail > 0:
        conclusion = "FAIL"
    elif n_na > 0:
        conclusion = "REVIEW_REQUIRED"
    else:
        conclusion = "PASS"

    return {
        "metadata": {
            "theoretical_source": {
                "datasheet_file": theoretical_payload.get("datasheet_file"),
                "target_page": theoretical_payload.get("target_page_human"),
                "source_image_path": theoretical_payload.get("source_image_path"),
            },
            "actual_source": {
                "source_file": (actual_payload or {}).get("source_file")
                               or (actual_payload or {}).get("dra_file"),
            },
            "unit": "mm",
            "tolerance_config": tolerance,
            "dimensions": dims,
            "ai_extracted_note": theoretical_payload.get("ai_extracted_note")
                                 or "AI视觉识别结果，必须人工对照PDF原始图纸复核",
            "human_review_required": True,
        },
        "comparisons": comparisons,
        "summary": {
            "total": n_total,
            "pass": n_pass,
            "fail": n_fail,
            "na": n_na,
            "pass_rate": round(n_pass / n_total, 4) if n_total else 0.0,
            "by_tol_source": by_tol_source,
        },
        "failed": failed,
        "conclusion": conclusion,
    }