# -*- coding: utf-8 -*-
"""
mcp_server/tools.py —— MCP 工具定义

约定：
  每个 tool 函数只做三件事：
    1. 参数校验 / 归一化
    2. 调用 services 层
    3. 包装返回

  严禁在 tool 里写业务逻辑（循环、文件扫描、JSON 清洗）。

说明：
  - 已移除 parse_datasheet_land_pattern（moondream 引擎路径）
  - 理论参数由客户端 AI 从 PDF 图片中读取
"""
from __future__ import annotations

from pathlib import Path

from fastmcp import FastMCP

from mcp_server import config
from services import allegro_service, footprint_service, pdf_service
from shared.json_utils import coerce_numeric, extract_json_body
from shared.validation import validate_land_pattern


def register(mcp: FastMCP) -> None:
    """把所有 tool 注册到给定的 FastMCP 实例。"""

    # ============================================================
    # Tool 0: 列出父文件夹下的子文件夹（批量模式侦察用）
    # ============================================================
    @mcp.tool()
    def list_subfolders(parent_path: str) -> dict:
        """
        列出父文件夹下的所有子文件夹，供批量模式侦察。

        :param parent_path: 父文件夹路径
        :return: {"parent": str, "subfolders": [str], "count": int}
        """
        from services.folder_service import list_subfolders as _ls
        p = Path(parent_path)
        subs = _ls(p)
        return {
            "parent": str(p.resolve()),
            "subfolders": subs,
            "count": len(subs),
        }

    # ============================================================
    # Tool 1: 列出文件夹内容
    # ============================================================
    @mcp.tool()
    def list_folder_files(folder_path: str) -> dict:
        """
        列出封装文件夹里的 PDF / .dra / .pad 文件。

        这是 AI 决策的第一步：了解文件夹里有什么，再决定后续怎么处理。

        :param folder_path: 目标文件夹路径
        :return: {
            "folder": str,
            "pdf": str | None,
            "dra_files": [str],
            "pad_files": [str],
            "error": str | None
        }
        """
        return allegro_service.list_folder_files(Path(folder_path))

    # ============================================================
    # Tool 2: 定位 land pattern 页
    # ============================================================
    @mcp.tool()
    def locate_land_pattern_page(pdf_file_path: str) -> dict:
        """
        定位 PDF 规格书中包含 land pattern（推荐焊盘）的页码。

        先用强关键词（LAND PATTERN、RECOMMENDED PAD 等）匹配；
        失败则用弱关键词（PAD、DIMENSION、SOLDER 等）兜底。

        :param pdf_file_path: 规格书 PDF 路径（完整路径或 stem 均可）
        :return: {
            "page": 页码(1-based) 或 null,
            "matched": [命中的关键词],
            "score": 匹配得分,
            "total_pages": 总页数,
            "method": "primary" | "fallback" | "no_match"
        }
        """
        pdf = pdf_service.resolve_pdf(pdf_file_path, config.PDF_SEARCH_ROOTS)
        if pdf is None:
            return {"error": f"找不到 PDF: {pdf_file_path}", "page": None}
        return pdf_service.locate_land_pattern_page(pdf)

    # ============================================================
    # Tool 3: 读取 Allegro 实际封装
    # ============================================================
    @mcp.tool()
    def read_allegro_footprint(
        dra_file_path: str,
        pad_file_paths: list[str] | None = None,
    ) -> dict:
        """
        通过 SkillBridge 读取 Allegro .dra 封装的实际焊盘参数。

        :param dra_file_path: .dra 文件完整路径
        :param pad_file_paths: 可选的 .pad 文件路径列表（仅用于溯源记录）
        :return: 适配 check_land_pattern_tolerance 的 actual_payload
        """
        return allegro_service.read_one(
            dra_path=dra_file_path,
            pad_paths=pad_file_paths,
        )

    # ============================================================
    # Tool 4: 校验 AI 输出的 JSON
    # ============================================================
    @mcp.tool()
    def validate_land_pattern_json(raw_json: str) -> dict:
        """
        校验 AI 输出的 land pattern JSON 是否符合预期 schema，并规范化。

        建议在 AI 自己读图提取参数之后、调 check_land_pattern_tolerance 之前
        先调这个 tool 做守门员，避免格式漂移导致比对失败。

        校验项：
          - unit 是否为 mm 或 mil
          - pads 是否为列表，每个 pad 的 pin/width/height 是否合法
          - spacing_x / spacing_y 是否为数字或 null
          - 数值是否在合理范围（0.001 ~ 100 mm）
          - 剥离 ```json 围栏、全角转半角、字符串数字转 float

        :param raw_json: AI 输出的原始 JSON 字符串
        :return: {
            "valid": bool,
            "errors": [str],
            "normalized": dict
        }
        """
        try:
            parsed = extract_json_body(raw_json)
        except Exception as e:
            return {
                "valid": False,
                "errors": [f"JSON 解析失败: {e}"],
                "normalized": None,
            }
        parsed = coerce_numeric(parsed)
        valid, errors, normalized = validate_land_pattern(parsed)
        return {"valid": valid, "errors": errors, "normalized": normalized}

    # ============================================================
    # Tool 5: 公差比对
    # ============================================================
    @mcp.tool()
    def check_land_pattern_tolerance(
        theoretical_payload: dict,
        actual_payload: dict,
        tolerance: dict | None = None,
    ) -> dict:
        """
        理论焊盘参数 vs Allegro 实际封装参数 公差比对。

        :param theoretical_payload: 形如 {theoretical_land_params: {...}} 的完整结构
        :param actual_payload: 来自 read_allegro_footprint 的返回
        :param tolerance: 公差配置；不传则用默认
                         （width/height ±0.1，spacing ±0.15）
        :return: PASS/FAIL/NA + 逐 pin 明细 + 汇总 + conclusion
        """
        return footprint_service.check_tolerance(
            theoretical_payload=theoretical_payload,
            actual_payload=actual_payload,
            tolerance=tolerance,
        )

    # ============================================================
    # Tool 6: 保存 JSON 报告
    # ============================================================
    @mcp.tool()
    def save_tolerance_report(
        comparison_result: dict,
        theoretical_payload: dict | None = None,
        actual_payload: dict | None = None,
        output_dir: str | None = None,
        filename: str | None = None,
    ) -> dict:
        """
        把一次封装检查的结果写成 JSON 文件，方便后期人工复查。

        默认写到 .dra 所在目录，文件名带时间戳：
        tolerance_report_YYYYMMDD_HHMMSS.json。

        :param comparison_result: check_land_pattern_tolerance 的完整返回
        :param theoretical_payload: 可选，理论 payload
        :param actual_payload: 可选，实际 payload
        :param output_dir: 输出目录；不传时自动用 .dra 所在目录
        :param filename: 文件名；不传时自动带时间戳
        :return: {"ok": bool, "path": str, "error": str}
        """
        return footprint_service.save_report(
            comparison_result=comparison_result,
            theoretical_payload=theoretical_payload,
            actual_payload=actual_payload,
            output_dir=output_dir,
            filename=filename,
        )
