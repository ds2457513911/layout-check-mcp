# -*- coding: utf-8 -*-
"""
mcp_server/tools.py —— MCP 工具定义

约定：
  每个 tool 函数只做三件事：
    1. 参数校验 / 归一化
    2. 调用 services 层
    3. 包装返回

  严禁在 tool 里写业务逻辑（循环、文件扫描、JSON 清洗）。

工具列表（v3.1）：
  - list_subfolders / list_folder_files
  - locate_land_pattern_page / render_pdf_page
  - read_allegro_footprint（旧，废弃）
  - read_full_footprint（主流程用：拿 pins/layers 供 AI 语义检查）
  - check_footprint_by_rules（主用：内部自动存档 + 渲染 markdown）
  - validate_land_pattern_json
  - check_land_pattern_tolerance（旧，废弃）
  - save_tolerance_report（旧，废弃）

v3.1 变更：
  - check_footprint_by_rules 新增 semantic_result / save_report 两个参数
    内部自动：保存 JSON 报告 + 渲染固定 markdown
  - 删除独立 render_report tool
    （原因：MCP tool 之间不共享变量，13KB 大对象无法可靠传递）
  - 删除独立 save_checklist_report tool（功能已内联进 check_footprint_by_rules）
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from fastmcp import FastMCP

from mcp_server import config
from services import allegro_service, footprint_service, pdf_service
from services import footprint_extractor, rule_checker, report_renderer
from shared.json_utils import coerce_numeric, extract_json_body
from shared.validation import validate_land_pattern


# ============================================================
# 模块级辅助：保存 checklist JSON 报告
# ============================================================
def _write_checklist_json(
    result: dict,
    dra_file_path: str | None = None,
    output_dir: str | None = None,
    filename: str | None = None,
) -> dict:
    """
    把一次清单检查的结果写成 JSON 文件。

    从 check_footprint_by_rules 内部调用，也可被独立调试脚本复用。

    :param result: check_footprint_by_rules 的结果（含 conclusion/summary/items）
    :param dra_file_path: .dra 路径；None 时从 result.footprint_data 推断
    :param output_dir: 输出目录；None 时用 .dra 所在目录
    :param filename: 文件名；None 时带时间戳
    :return: {"ok": bool, "path": str, "error": str}
    """
    if not isinstance(result, dict):
        return {"ok": False, "path": "", "error": "result 不是 dict"}

    # 推断输出目录
    if output_dir is None:
        if dra_file_path is None:
            fp_data = result.get("footprint_data") or {}
            dra_file_path = fp_data.get("source_file")
        if dra_file_path:
            output_dir = Path(dra_file_path).parent
        else:
            return {
                "ok": False,
                "path": "",
                "error": "无法推断输出目录，请显式传 output_dir 或 dra_file_path",
            }

    out_dir = Path(output_dir)
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        return {"ok": False, "path": str(out_dir), "error": f"创建目录失败: {e}"}

    if filename is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"checklist_report_{ts}.json"

    out_path = out_dir / filename

    fp_data = result.get("footprint_data") or {}
    report = {
        "report_version": "3.0",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "dra_file": fp_data.get("source_file"),
        "symbol_name": fp_data.get("symbol_name"),
        "component_type": result.get("component_type"),
        "conclusion": result.get("conclusion"),
        "summary": result.get("summary"),
        "items": result.get("items"),
        "failed": result.get("failed"),
        "warned": result.get("warned"),
    }

    try:
        out_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        return {"ok": False, "path": str(out_path), "error": f"写文件失败: {e}"}

    return {"ok": True, "path": str(out_path.resolve()), "error": ""}


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
    # Tool 2.1: 渲染 PDF 页
    # ============================================================
    @mcp.tool()
    def render_pdf_page(
        pdf_file_path: str,
        page: int,
        render_engine: str = "pymupdf",
    ) -> dict:
        """
        把 PDF 指定页渲染成 PNG 图片，返回图片的本地路径。

        用途：当客户端不支持读 MCP resource `datasheet://...` 时，
        AI 可以通过这个 tool 拿到图片路径，再用自己的图片分析能力读图。

        :param pdf_file_path: PDF 路径（完整路径或 stem）
        :param page: 人眼 1-based 页码
        :param render_engine: "pymupdf"（默认）
        :return: {
            "ok": bool,
            "image_path": str,       # 图片的本地绝对路径
            "out_dir": str,
            "engine": str,
            "error": str,
        }
        """
        pdf = pdf_service.resolve_pdf(pdf_file_path, config.PDF_SEARCH_ROOTS)
        if pdf is None:
            return {"ok": False, "error": f"找不到 PDF: {pdf_file_path}"}
        img_path = pdf_service.get_or_render_image(
            pdf_path=pdf,
            page=page,
            out_root=config.MARKER_ROOT,
            engine=render_engine,
        )
        if img_path is None:
            return {"ok": False, "error": "渲染失败"}
        return {
            "ok": True,
            "image_path": str(img_path),
            "out_dir": str(img_path.parent),
            "engine": render_engine,
            "error": "",
        }

    # ============================================================
    # Tool 3: 读取 Allegro 实际封装（旧版：只读焊盘）
    # ============================================================
    @mcp.tool()
    def read_allegro_footprint(
        dra_file_path: str,
        pad_file_paths: list[str] | None = None,
    ) -> dict:
        """
        【已废弃】通过 SkillBridge 读取 Allegro .dra 封装的实际焊盘参数（简化版）。

        只返回焊盘尺寸 + 间距。返回的是 pin.b_box（阻焊开窗），非铜箔尺寸。
        焊盘尺寸比对请使用 check_footprint_by_rules。

        :param dra_file_path: .dra 文件完整路径
        :param pad_file_paths: 可选的 .pad 文件路径列表（仅用于溯源记录）
        :return: 适配 check_land_pattern_tolerance 的 actual_payload
        """
        return allegro_service.read_one(
            dra_path=dra_file_path,
            pad_paths=pad_file_paths,
        )

    # ============================================================
    # Tool 3b: 全量读取 Allegro 封装（主流程用：拿 pins/layers 供语义检查）
    # ============================================================
    @mcp.tool()
    def read_full_footprint(
        dra_file_path: str,
        pad_file_paths: list[str] | None = None,
    ) -> dict:
        """
        从 .dra 全量提取封装数据（不做规则判断）。

        主流程用途：把 pins / layers / symbol_name 交给 AI 做语义检查
        （命名语义、pin number、极性标识），产出 semantic_result 供
        check_footprint_by_rules 使用。

        调试用途：需要看 .dra 原始分层数据时直接调用。

        :param dra_file_path: .dra 文件完整路径
        :param pad_file_paths: 可选的 .pad 文件路径列表
        :return: {
            "source_file": str,
            "symbol_name": str,
            "units": "mm" | "mil",
            "design_bbox": {...},
            "pins": [...],       # 每个 pin 的 number/xy/bbox/pads
            "texts": [...],
            "layers": {...},     # assembly_top / silkscreen_top / place_bound_top 等
            "raw_pin_count": int,
        }
        """
        return footprint_extractor.read_full_footprint(
            dra_path=dra_file_path,
            pad_paths=pad_file_paths or [],
            workspace_id=config.SKILLBRIDGE_WORKSPACE_ID,
        )

    # ============================================================
    # Tool 3c: 跑规则检查 + 存档 + 渲染 markdown（主用）
    # ============================================================
    @mcp.tool()
    def check_footprint_by_rules(
        dra_file_path: str,
        theoretical_payload: dict | None = None,
        pad_file_paths: list[str] | None = None,
        custom_rules: dict | None = None,
        semantic_result: dict | None = None,
        save_report: bool = True,
    ) -> dict:
        """
        从 .dra 提取封装数据，跑完整的数值规则检查，并自动保存 JSON 报告、
        渲染固定格式的 Markdown 报告。

        覆盖 Excel 规范的 6 大项（数值部分）：
          - 1. 封装命名规范（前缀、小数点、数字）
          - 2. 焊盘尺寸（与命名一致性、阻焊/钢网外扩）
          - 3. 间距与原点（pitch、pitch vs datasheet、最小间距、原点居中）
          - 5. Place_Bound（存在、覆盖、外扩量）
          - 6. Assembly / Silkscreen（存在、1 脚标识、重叠）

        返回里的 `markdown` 字段是最终报告，AI 应**原样贴出**。

        :param dra_file_path: .dra 文件完整路径
        :param theoretical_payload: 可选，datasheet 理论参数（用于 pitch 对比）
        :param pad_file_paths: 可选的 .pad 文件路径列表
        :param custom_rules: 可选，自定义规则（覆盖默认）
        :param semantic_result: AI 产出的语义检查结果，结构：
            {
              "naming": {"type_match": bool, "pin_count_match": bool,
                         "dimension_match": bool, "pitch_match": bool},
              "pin_number": {"dra_pin_count": int, "datasheet_pin_count": int,
                             "count_match": bool, "pin_numbers_match": bool},
              "polarity": {"required": bool, "pin1_marker_assembly": bool,
                           "pin1_marker_silkscreen": bool}
            }
            缺字段或 None 时，渲染层会跳过对应行，不崩。
        :param save_report: 是否保存 JSON + 渲染 markdown；默认 True
        :return: {
            "conclusion": "PASS" | "FAIL" | "REVIEW_REQUIRED",
            "component_type": "ic" | "chip" | "connector" | "unknown",
            "summary": {...},
            "items": [...],
            "failed": [...],
            "warned": [...],
            "footprint_data": {...},
            "markdown": str,       # 最终报告，AI 原样贴出
            "report_path": str,    # JSON 报告路径（save_report=False 时为空）
            "save_error": str,     # 存档失败原因（成功时为空）
            "render_error": str,   # 渲染失败原因（成功时为空）
        }
        """
        # 1. 提取数据
        fp_data = footprint_extractor.read_full_footprint(
            dra_path=dra_file_path,
            pad_paths=pad_file_paths or [],
            workspace_id=config.SKILLBRIDGE_WORKSPACE_ID,
        )
        if fp_data.get("error"):
            return {
                "conclusion": "FAIL",
                "error": fp_data["error"],
                "footprint_data": fp_data,
                "markdown": "",
                "report_path": "",
                "save_error": "",
                "render_error": "",
            }

        # 2. 跑规则检查
        result = rule_checker.run_numeric_checks(
            footprint_data=fp_data,
            theoretical=theoretical_payload,
            rules=custom_rules,
        )

        # 3. 附上原始提取数据
        result["footprint_data"] = fp_data

        # 4. 存档 + 渲染（容错：任一失败不影响检查结果返回）
        markdown = ""
        report_path = ""
        save_error = ""
        render_error = ""

        if save_report:
            # 4a. 保存 JSON 报告
            try:
                save_res = _write_checklist_json(result, dra_file_path=dra_file_path)
                report_path = save_res.get("path", "")
                save_error = save_res.get("error", "")
            except Exception as e:
                save_error = str(e)

            # 4b. 渲染 markdown
            try:
                report_name = Path(report_path).name if report_path else None
                markdown = report_renderer.render_markdown(
                    numeric_result=result,
                    semantic_result=semantic_result,
                    report_filename=report_name,
                )
            except Exception as e:
                render_error = str(e)

        result["markdown"] = markdown
        result["report_path"] = report_path
        result["save_error"] = save_error
        result["render_error"] = render_error
        return result

    # ============================================================
    # Tool 4: 校验 AI 输出的 JSON
    # ============================================================
    @mcp.tool()
    def validate_land_pattern_json(raw_json: str) -> dict:
        """
        校验 AI 输出的 land pattern JSON 是否符合预期 schema，并规范化。

        建议在 AI 自己读图提取参数之后、调 check_footprint_by_rules 之前
        先调这个 tool 做守门员，避免格式漂移导致比对失败。

        :param raw_json: AI 输出的原始 JSON 字符串
        :return: {"valid": bool, "errors": [str], "normalized": dict}
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
    # Tool 5: 公差比对（旧版，保留兼容）
    # ============================================================
    @mcp.tool()
    def check_land_pattern_tolerance(
        theoretical_payload: dict,
        actual_payload: dict,
        tolerance: dict | None = None,
    ) -> dict:
        """
        【已废弃】理论焊盘参数 vs Allegro 实际封装参数 公差比对。

        废弃原因：依赖 read_allegro_footprint 的数据（阻焊开窗），
        会与 datasheet 的铜箔尺寸比对出假 delta，导致 FAIL 误判。
        请使用 check_footprint_by_rules。

        :param theoretical_payload: 形如 {theoretical_land_params: {...}} 的完整结构
        :param actual_payload: 来自 read_allegro_footprint 的返回
        :param tolerance: 公差配置；不传则用默认
        :return: PASS/FAIL/NA + 逐 pin 明细 + 汇总 + conclusion
        """
        return footprint_service.check_tolerance(
            theoretical_payload=theoretical_payload,
            actual_payload=actual_payload,
            tolerance=tolerance,
        )

    # ============================================================
    # Tool 6: 保存公差报告（旧版，保留兼容）
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
        【已废弃】把一次焊盘公差检查的结果写成 JSON 文件。

        已被 check_footprint_by_rules 内部的自动存档取代。

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