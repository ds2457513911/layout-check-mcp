# -*- coding: utf-8 -*-
"""
services/footprint_service.py —— 封装检查业务编排

职责：
  - 提取理论焊盘参数（调 services.pdf_renderer）
  - 执行理论 vs 实际的公差比对（调 services.tolerance_service）
  - 把检查结果写成 JSON 报告，方便后期人工复查

这一层不感知 MCP，可被批处理脚本、单元测试、MCP tool 复用。
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from services.pdf_renderer import parse_pdf_land_pattern
from services.tolerance_service import check_dimension_tolerance


def extract_theoretical(
    pdf_path: Path,
    page: int,
    out_root: Path,
    render_engine: str = "pymupdf",
    source_tag: Optional[dict] = None,
) -> dict:
    """
    用 moondream2 引擎从 PDF 指定页提取理论焊盘参数。

    :param pdf_path: PDF 绝对路径
    :param page: 人眼 1-based 页码
    :param out_root: marker / pymupdf 渲染输出根目录
    :param render_engine: "pymupdf"（默认）或 "marker"
    :param source_tag: 附加到返回值的溯源信息
    :return: parse_pdf_land_pattern 的原始返回
    """
    return parse_pdf_land_pattern(
        pdf_file_path=pdf_path,
        target_page=page,
        marker_root=out_root,
        render_engine=render_engine,
        source_tag=source_tag,
    )


def check_tolerance(
    theoretical_payload: dict,
    actual_payload: dict,
    tolerance: Optional[dict] = None,
) -> dict:
    """
    公差比对：理论焊盘参数 vs 实际封装参数。

    :param theoretical_payload: 包含 theoretical_land_params 的完整 payload
    :param actual_payload: lib_allegro_reader 返回的 actual_payload
    :param tolerance: 公差配置；None 时由 tolerance_service 按维度回落默认
    :return: check_dimension_tolerance 的原始返回
    """
    return check_dimension_tolerance(
        theoretical_payload,
        actual_payload,
        tolerance,
    )


def save_report(
    comparison_result: dict,
    theoretical_payload: Optional[dict] = None,
    actual_payload: Optional[dict] = None,
    output_dir: Optional[str | Path] = None,
    filename: Optional[str] = None,
) -> dict:
    """
    把一个封装检查的结果写成 JSON 文件。

    :param comparison_result: check_dimension_tolerance 的完整返回
    :param theoretical_payload: 可选，理论 payload（用于报告里保留原始提取结果）
    :param actual_payload: 可选，实际 payload（用于报告里保留 Allegro 原始数据）
    :param output_dir: 输出目录；None 时用 .dra 所在目录
    :param filename: 文件名；None 时默认 "tolerance_report_<时间戳>.json"
    :return: {"ok": bool, "path": str, "error": str}
    """
    if not isinstance(comparison_result, dict):
        return {"ok": False, "path": "", "error": "comparison_result 不是 dict"}

    # ---- 决定输出目录 ----
    if output_dir is None:
        meta = comparison_result.get("metadata") or {}
        actual_src = meta.get("actual_source") or {}
        dra_path = actual_src.get("source_file") or ""
        if dra_path:
            output_dir = Path(dra_path).parent
        else:
            return {
                "ok": False,
                "path": "",
                "error": "无法从 comparison_result 推断输出目录，请显式传 output_dir",
            }

    out_dir = Path(output_dir)
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        return {"ok": False, "path": str(out_dir), "error": f"创建目录失败: {e}"}

    # ---- 决定文件名 ----
    if filename is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"tolerance_report_{ts}.json"

    out_path = out_dir / filename

    # ---- 组装报告 ----
    report = {
        "report_version": "1.0",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "conclusion": comparison_result.get("conclusion"),
        "summary": comparison_result.get("summary"),
        "metadata": comparison_result.get("metadata"),
        "comparisons": comparison_result.get("comparisons"),
        "failed": comparison_result.get("failed"),
        "theoretical_land_params": None,
        "actual_payload": None,
    }

    # 可选溯源信息
    if isinstance(theoretical_payload, dict):
        report["theoretical_land_params"] = theoretical_payload.get(
            "theoretical_land_params"
        )

    if isinstance(actual_payload, dict):
        report["actual_payload"] = {
            "source_file": actual_payload.get("source_file"),
            "unit": actual_payload.get("unit"),
            "pads": actual_payload.get("pads"),
            "spacing_x": actual_payload.get("spacing_x"),
            "spacing_y": actual_payload.get("spacing_y"),
        }

    # ---- 写文件 ----
    try:
        out_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        return {"ok": False, "path": str(out_path), "error": f"写文件失败: {e}"}

    return {"ok": True, "path": str(out_path.resolve()), "error": ""}