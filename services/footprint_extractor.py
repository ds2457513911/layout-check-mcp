# -*- coding: utf-8 -*-
"""
services/footprint_extractor.py —— .dra 数据提取分发器

优先级（v3，extracta 视图已修复）：
  1. extracta（Cadence 自带，不需要 Allegro 运行，快）—— 主路径
  2. SkillBridge（需要 Allegro 正在运行）—— 保底

extracta 数据完整性校验：
  如果 extracta 返回的 pins 没有 pads 或 layers 全空，视为失败，
  自动回退到 SkillBridge。

调试开关（环境变量 LAYOUT_CHECK_FORCE_SOURCE）：
  extracta     强制只用 extracta
  skillbridge  强制只用 SkillBridge
  不设置       走默认逻辑（extracta → skillbridge）
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


def _log(msg: str) -> None:
    print(f"[footprint_extractor] {msg}", file=sys.stderr)


def _is_extracta_result_complete(result: Dict[str, Any]) -> bool:
    """校验 extracta 返回的数据是否够用。"""
    pins = result.get("pins") or []
    if not pins:
        return False
    with_pads = sum(1 for p in pins if p.get("pads"))
    if with_pads == 0:
        return False
    layers = result.get("layers") or {}
    for key in ("assembly_top", "silkscreen_top", "place_bound_top"):
        if layers.get(key):
            return True
    return False


def read_full_footprint(
    dra_path: str,
    pad_paths: Optional[List[str]] = None,
    workspace_id: Optional[str] = None,
    include_layers: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    读取 .dra 全量封装数据。

    默认顺序：extracta → SkillBridge
    """
    force = os.environ.get("LAYOUT_CHECK_FORCE_SOURCE", "").strip().lower()

    if force == "extracta":
        from services import extracta_reader
        return extracta_reader.read_via_extracta(dra_path)

    if force == "skillbridge":
        from services import skillbridge_reader
        return skillbridge_reader.read_full_footprint(
            dra_path=dra_path, pad_paths=pad_paths,
            workspace_id=workspace_id, include_layers=include_layers,
        )

    # ---------- 默认：extracta 优先 ----------
    extracta_error = None
    try:
        from services import extracta_reader
        result = extracta_reader.read_via_extracta(dra_path)
        if not result.get("error"):
            if _is_extracta_result_complete(result):
                _log(f"[extracta] OK: {Path(dra_path).name}")
                return result
            extracta_error = "extracta 返回的数据不完整（pins 无 pads 或 layers 全空）"
            _log(f"[extracta] incomplete: {extracta_error}")
        else:
            extracta_error = result.get("error", "unknown")
            _log(f"[extracta] failed: {extracta_error}")
    except Exception as e:
        extracta_error = f"extracta exception: {e}"
        _log(extracta_error)

    # 回退 SkillBridge
    _log(f"[fallback] trying SkillBridge for {Path(dra_path).name}")
    try:
        from services import skillbridge_reader
        result = skillbridge_reader.read_full_footprint(
            dra_path=dra_path, pad_paths=pad_paths,
            workspace_id=workspace_id, include_layers=include_layers,
        )
        if not result.get("error"):
            _log(f"[skillbridge] OK: {Path(dra_path).name}")
            return result
        return {
            "error": (
                f"两个数据源都失败：\n"
                f"  extracta: {extracta_error}\n"
                f"  skillbridge: {result.get('error')}"
            ),
            "pins": [], "texts": [], "layers": {},
        }
    except Exception as e:
        return {
            "error": (
                f"两个数据源都失败：\n"
                f"  extracta: {extracta_error}\n"
                f"  skillbridge: {e}"
            ),
            "pins": [], "texts": [], "layers": {},
        }


if __name__ == "__main__":
    import json
    _this = Path(__file__).resolve()
    _root = _this.parent.parent
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))
    if len(sys.argv) < 2:
        print("用法: python services/footprint_extractor.py <dra路径> [pad路径1] ...")
        sys.exit(1)
    dra = sys.argv[1]
    pads = sys.argv[2:] if len(sys.argv) > 2 else []
    result = read_full_footprint(dra_path=dra, pad_paths=pads)
    print(json.dumps(result, ensure_ascii=False, indent=2))