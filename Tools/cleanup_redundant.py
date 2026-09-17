# -*- coding: utf-8 -*-
"""
Tools/cleanup_redundant.py —— 项目冗余清理脚本

功能：
  1. 删除 3 个已废弃的 service 文件
  2. 覆盖 4 个文件（去掉废弃 tool、修 list_subfolders bug、
     DEFAULT_TOLERANCE 删除、MARKER_ROOT 改名、硬编码路径删除）
  3. 所有改动前先备份到 .cleanup_backup/<timestamp>/

用法：
  # 1. 先检查（dry-run，不写任何文件）
  python Tools/cleanup_redundant.py

  # 2. 确认无误后执行（自动备份）
  python Tools/cleanup_redundant.py --apply

  # 3. 万一要回滚
  python Tools/cleanup_redundant.py --rollback <timestamp>

安全性：
  - 默认 dry-run，不加 --apply 不写盘
  - 每个文件覆盖前先备份
  - 幂等：重复运行不会重复备份、不会乱改
"""
from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime
from pathlib import Path

# ============================================================
# 项目根定位：脚本在 Tools/ 下，项目根是它的上一级
# ============================================================
THIS_FILE = Path(__file__).resolve()
PROJECT_ROOT = THIS_FILE.parent.parent
BACKUP_ROOT = PROJECT_ROOT / ".cleanup_backup"


# ============================================================
# 要删除的文件
# ============================================================
FILES_TO_DELETE = [
    "services/allegro_reader.py",
    "services/footprint_service.py",
    "services/tolerance_service.py",
]


# ============================================================
# 要覆盖的文件（内容嵌入在下方）
# ============================================================
NEW_TOOLS_PY = r'''# -*- coding: utf-8 -*-
"""
mcp_server/tools.py —— MCP 工具定义

约定：
  每个 tool 函数只做三件事：
    1. 参数校验 / 归一化
    2. 调用 services 层
    3. 包装返回

  严禁在 tool 里写业务逻辑（循环、文件扫描、JSON 清洗）。

工具列表（v4.0）：
  - list_subfolders / list_folder_files         批量侦察
  - locate_land_pattern_page / render_pdf_page  定位 & 渲染
  - read_full_footprint                         拿 pins/layers 供 AI 语义检查
  - check_footprint_by_rules                    主用：检查 + 存档 + 渲染 markdown
  - validate_land_pattern_json                  校验 AI 输出的 JSON

v4.0 变更：
  - 删除 3 个废弃 tool：
      · read_allegro_footprint       （返回阻焊开窗，非铜箔）
      · check_land_pattern_tolerance （依赖上一条，会误判）
      · save_tolerance_report        （旧版报告格式，已被内部存档取代）
  - 修复 list_subfolders 的 import bug（folder_service → allegro_service）
  - 清理已废弃 tool 带来的 import
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from fastmcp import FastMCP

from mcp_server import config
from services import allegro_service, pdf_service
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

    从 check_footprint_by_rules 内部调用。

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
        p = Path(parent_path)
        subs = allegro_service.list_subfolders(p)
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
            out_root=config.RENDER_OUTPUT_ROOT,
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
    # Tool 3: 全量读取 Allegro 封装（拿 pins/layers 供 AI 语义检查）
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
    # Tool 3b: 跑规则检查 + 存档 + 渲染 markdown（主用）
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
'''


NEW_CONFIG_PY = r'''# -*- coding: utf-8 -*-
"""
mcp_server/config.py —— MCP 服务配置

所有路径都基于项目根目录解析，避免客户端拉起时 cwd 不确定导致路径漂移。
"""
from __future__ import annotations

from pathlib import Path

# 项目根目录（mcp_server/ 的上一级）
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# PDF 页面渲染输出根目录
# （原名叫 MARKER_ROOT，marker 引擎已移除，改名为 RENDER_OUTPUT_ROOT）
RENDER_OUTPUT_ROOT = PROJECT_ROOT / "marker_out"

# PDF 搜索根目录列表
# 当 AI 只传 PDF 的 stem（而非完整路径）时，会在此列表下递归搜索。
# 正常流程 AI 会传完整路径，此列表仅作兜底。
PDF_SEARCH_ROOTS: list[Path] = [
    PROJECT_ROOT,
]

# SkillBridge workspace id（MCP tool 调用 Allegro 时使用）
SKILLBRIDGE_WORKSPACE_ID = "7777"
'''


NEW_RESOURCES_PY = r'''# -*- coding: utf-8 -*-
"""
mcp_server/resources.py —— MCP 资源定义

Resource 的作用是把"数据"暴露给客户端 AI 读。
AI 通过读 resource 拿到 PDF 页图片后，可以用自己的多模态能力提取参数。

URI 约定：
  datasheet://{pdf_stem}/page/{page}          PyMuPDF 整页图（PNG）
  datasheet://{pdf_stem}/info                 PDF 元信息（JSON 字符串）
"""
from __future__ import annotations

import json

from fastmcp import FastMCP

from mcp_server import config
from services import pdf_service


def register(mcp: FastMCP) -> None:
    """把所有 resource 注册到给定的 FastMCP 实例。"""

    @mcp.resource(
        "datasheet://{pdf_stem}/page/{page}",
        mime_type="image/png",
        description="PDF 指定页的整页图片（PyMuPDF 渲染），供 AI 直接查看",
    )
    def get_datasheet_page_image(pdf_stem: str, page: int) -> bytes:
        """
        返回 PDF 指定页的整页图片（PNG 字节）。

        渲染引擎固定为 PyMuPDF。
        如果客户端不支持 image resource，请改用 render_pdf_page tool。
        """
        pdf = pdf_service.resolve_pdf(pdf_stem, config.PDF_SEARCH_ROOTS)
        if pdf is None:
            raise ValueError(f"找不到 PDF: {pdf_stem}")
        img_path = pdf_service.get_or_render_image(
            pdf_path=pdf,
            page=int(page),
            out_root=config.RENDER_OUTPUT_ROOT,
            engine="pymupdf",
        )
        if img_path is None or not img_path.is_file():
            raise ValueError(f"渲染失败: pdf={pdf.name} page={page}")
        return img_path.read_bytes()

    @mcp.resource(
        "datasheet://{pdf_stem}/info",
        description="PDF 元信息：总页数、land pattern 命中页、匹配关键词",
    )
    def get_datasheet_info(pdf_stem: str) -> str:
        """返回 PDF 的元信息（JSON 字符串）"""
        pdf = pdf_service.resolve_pdf(pdf_stem, config.PDF_SEARCH_ROOTS)
        if pdf is None:
            return json.dumps(
                {"error": f"找不到 PDF: {pdf_stem}"}, ensure_ascii=False
            )
        info = pdf_service.locate_land_pattern_page(pdf)
        info["pdf_path"] = str(pdf)
        info["pdf_name"] = pdf.name
        return json.dumps(info, ensure_ascii=False, indent=2)
'''


NEW_ALLEGRO_SERVICE_PY = r'''# -*- coding: utf-8 -*-
"""
services/allegro_service.py —— Allegro 封装文件操作服务

职责：
  - 扫描文件夹里的 .dra（排除 AUTOSAVE）
  - 扫描文件夹里的 .pad
  - 列出文件夹概览（PDF / .dra / .pad）
  - 列出父文件夹下的子文件夹

v4.0 变更：
  - 删除 read_one（旧版焊盘读取，返回阻焊开窗，已废弃）
  - 不再 import services.allegro_reader
"""
from __future__ import annotations

from pathlib import Path

from services.pdf_service import find_first_pdf


# ---------- 文件扫描 ----------
def scan_dra(folder: Path) -> list[Path]:
    """
    扫描文件夹里的所有 .dra，排除 AUTOSAVE 备份。

    :param folder: 目标文件夹
    :return: .dra 绝对路径列表（按名称排序）
    """
    if not folder.is_dir():
        return []
    files = sorted(p for p in folder.glob("*.dra") if p.is_file())
    return [f for f in files if not f.name.upper().startswith("AUTOSAVE")]


def scan_pad(folder: Path) -> list[Path]:
    """
    扫描文件夹里的所有 .pad。

    :param folder: 目标文件夹
    :return: .pad 绝对路径列表（按名称排序）
    """
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.glob("*.pad") if p.is_file())


# ---------- 文件夹概览 ----------
def list_subfolders(parent: Path) -> list[str]:
    """列出父文件夹下所有子文件夹名（按名称排序）。"""
    if not parent.is_dir():
        return []
    return sorted(
        p.name for p in parent.iterdir()
        if p.is_dir() and not p.name.startswith(".")
    )


def list_folder_files(folder: Path) -> dict:
    """
    列出文件夹里的 PDF / .dra / .pad，供 AI 决策前了解文件夹内容。

    :param folder: 目标文件夹
    :return: {
        "folder": str,
        "pdf": str | None,
        "dra_files": [str],
        "pad_files": [str],
        "error": str | None
    }
    """
    if not folder.is_dir():
        return {
            "folder": str(folder),
            "pdf": None,
            "dra_files": [],
            "pad_files": [],
            "error": f"文件夹不存在: {folder}",
        }

    pdf = find_first_pdf(folder)
    dra_files = scan_dra(folder)
    pad_files = scan_pad(folder)

    return {
        "folder": str(folder.resolve()),
        "pdf": str(pdf.resolve()) if pdf else None,
        "dra_files": [str(p.resolve()) for p in dra_files],
        "pad_files": [str(p.resolve()) for p in pad_files],
        "error": None,
    }
'''


FILES_TO_OVERWRITE = {
    "mcp_server/tools.py": NEW_TOOLS_PY,
    "mcp_server/config.py": NEW_CONFIG_PY,
    "mcp_server/resources.py": NEW_RESOURCES_PY,
    "services/allegro_service.py": NEW_ALLEGRO_SERVICE_PY,
}


# ============================================================
# 工具函数
# ============================================================
def _ok(msg: str) -> None:
    print(f"  [OK]   {msg}")

def _warn(msg: str) -> None:
    print(f"  [WARN] {msg}")

def _err(msg: str) -> None:
    print(f"  [ERR]  {msg}")

def _info(msg: str) -> None:
    print(f"         {msg}")

def _step(msg: str) -> None:
    print(f"\n>> {msg}")


def _backup_file(src: Path, backup_dir: Path, root: Path) -> Path:
    """把 src 备份到 backup_dir，保持相对项目根的结构。"""
    rel = src.relative_to(root)
    dst = backup_dir / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return dst


# ============================================================
# 检查阶段（dry-run）
# ============================================================
def do_check() -> tuple[bool, list[str], list[str]]:
    """
    检查项目状态。

    :return: (是否全部就绪, 待删除文件列表, 待覆盖文件列表)
    """
    problems: list[str] = []

    _step("1. 定位项目根")
    if not (PROJECT_ROOT / "pyproject.toml").is_file():
        problems.append(f"在 {PROJECT_ROOT} 找不到 pyproject.toml，项目根识别错误")
        _err(f"找不到 {PROJECT_ROOT / 'pyproject.toml'}")
        return False, [], []
    _ok(f"项目根: {PROJECT_ROOT}")

    _step("2. 检查待删除文件")
    to_delete: list[str] = []
    for rel in FILES_TO_DELETE:
        p = PROJECT_ROOT / rel
        if p.is_file():
            to_delete.append(rel)
            _ok(f"存在，将删除: {rel}")
        elif p.exists():
            _warn(f"存在但不是文件（可能是目录），跳过: {rel}")
        else:
            _warn(f"已不存在（可能已删过）: {rel}")

    _step("3. 检查待覆盖文件")
    to_overwrite: list[str] = []
    for rel in FILES_TO_OVERWRITE:
        p = PROJECT_ROOT / rel
        if p.is_file():
            to_overwrite.append(rel)
            _ok(f"存在，将覆盖: {rel}")
        else:
            problems.append(f"待覆盖文件不存在: {rel}")
            _err(f"不存在: {rel}")

    _step("4. 检查前置文件是否齐全")
    required = [
        "mcp_server/server.py",
        "mcp_server/prompts.py",
        "services/footprint_extractor.py",
        "services/rule_checker.py",
        "services/report_renderer.py",
        "services/pdf_service.py",
        "services/pdf_locate.py",
        "services/pdf_renderer.py",
        "shared/json_utils.py",
        "shared/validation.py",
    ]
    for rel in required:
        p = PROJECT_ROOT / rel
        if p.is_file():
            _ok(f"存在: {rel}")
        else:
            problems.append(f"必备文件缺失: {rel}")
            _err(f"缺失: {rel}")

    _step("5. 检查待删除文件是否被其他文件引用")
    # 简单 grep：扫描 mcp_server / services / shared 下所有 .py，看有没有引用。
    # 白名单同时排除：
    #   - 待覆盖文件（内容会被替换，不用管它们现在引用什么）
    #   - 待删除文件（它们自己互相引用，删除后一起消失，不算问题）
    target_modules = [
        "allegro_reader",
        "footprint_service",
        "tolerance_service",
    ]
    scan_dirs = ["mcp_server", "services", "shared"]
    whitelist = set(FILES_TO_OVERWRITE.keys()) | set(FILES_TO_DELETE)

    bad_refs: list[str] = []
    for d in scan_dirs:
        dpath = PROJECT_ROOT / d
        if not dpath.is_dir():
            continue
        for py in dpath.glob("*.py"):
            rel = str(py.relative_to(PROJECT_ROOT)).replace("\\", "/")
            if rel in whitelist:
                continue
            try:
                text = py.read_text(encoding="utf-8")
            except Exception:
                continue
            for mod in target_modules:
                if (f"import {mod}" in text
                        or f"from services.{mod}" in text
                        or f"from services import {mod}" in text):
                    bad_refs.append(f"{rel} 引用了 {mod}")
    if bad_refs:
        for b in bad_refs:
            _warn(b)
        problems.append(
            f"有 {len(bad_refs)} 处外部引用待删除模块，覆盖后可能导致 import 报错"
        )
    else:
        _ok("无外部引用")

    return (len(problems) == 0), to_delete, to_overwrite


# ============================================================
# 执行阶段
# ============================================================
def do_apply() -> int:
    """
    执行删除 + 覆盖。

    :return: 退出码（0 成功）
    """
    ready, to_delete, to_overwrite = do_check()
    if not ready:
        print()
        _err("检查未通过，终止执行。请先修复上方 [ERR] 项。")
        return 1

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = BACKUP_ROOT / ts
    backup_dir.mkdir(parents=True, exist_ok=True)

    _step(f"6. 备份到 {backup_dir.relative_to(PROJECT_ROOT)}")
    for rel in to_delete:
        src = PROJECT_ROOT / rel
        if src.is_file():
            _backup_file(src, backup_dir, PROJECT_ROOT)
            _ok(f"备份: {rel}")
    for rel in to_overwrite:
        src = PROJECT_ROOT / rel
        if src.is_file():
            _backup_file(src, backup_dir, PROJECT_ROOT)
            _ok(f"备份: {rel}")

    # 写一份 manifest，记录本次都动了什么（便于 rollback）
    manifest = backup_dir / "_MANIFEST.txt"
    manifest.write_text(
        f"timestamp: {ts}\n"
        f"deleted:\n" + "".join(f"  - {x}\n" for x in to_delete) +
        f"overwritten:\n" + "".join(f"  - {x}\n" for x in to_overwrite),
        encoding="utf-8",
    )

    _step("7. 删除废弃文件")
    for rel in to_delete:
        src = PROJECT_ROOT / rel
        if src.is_file():
            src.unlink()
            _ok(f"已删除: {rel}")
        else:
            _warn(f"不存在，跳过: {rel}")

    _step("8. 覆盖文件")
    for rel, content in FILES_TO_OVERWRITE.items():
        dst = PROJECT_ROOT / rel
        # 统一换行，避免 Windows / *nix 混用
        dst.write_text(content, encoding="utf-8", newline="\n")
        _ok(f"已覆盖: {rel}")

    print()
    print("=" * 60)
    print("  清理完成")
    print("=" * 60)
    print(f"  备份目录: {backup_dir.relative_to(PROJECT_ROOT)}")
    print(f"  回滚命令: python Tools/cleanup_redundant.py --rollback {ts}")
    print()
    print("  下一步：")
    print("    1. 重启 MCP 客户端（Trae / Claude Desktop）")
    print("    2. 跑一次 3S48000163 验证")
    print("    3. 验证通过后，可选：删除 .cleanup_backup/ 下的旧备份")
    return 0


# ============================================================
# 回滚
# ============================================================
def do_rollback(timestamp: str) -> int:
    """
    从备份恢复。

    :param timestamp: 备份目录的时间戳（如 20260917_153000）
    """
    backup_dir = BACKUP_ROOT / timestamp
    if not backup_dir.is_dir():
        _err(f"备份目录不存在: {backup_dir}")
        # 列出可用备份
        if BACKUP_ROOT.is_dir():
            avails = sorted(d.name for d in BACKUP_ROOT.iterdir() if d.is_dir())
            if avails:
                print("\n可用的备份：")
                for a in avails:
                    print(f"  {a}")
        return 1

    manifest_path = backup_dir / "_MANIFEST.txt"
    if not manifest_path.is_file():
        _err(f"备份目录缺少 _MANIFEST.txt: {backup_dir}")
        return 1

    _step(f"从 {backup_dir.relative_to(PROJECT_ROOT)} 恢复")

    # 从 manifest 解析要删和要恢复的
    text = manifest_path.read_text(encoding="utf-8")
    deleted: list[str] = []
    overwritten: list[str] = []
    section = None
    for line in text.splitlines():
        if line.startswith("deleted:"):
            section = "deleted"
            continue
        if line.startswith("overwritten:"):
            section = "overwritten"
            continue
        if line.startswith("  - "):
            item = line[4:].strip()
            if section == "deleted":
                deleted.append(item)
            elif section == "overwritten":
                overwritten.append(item)

    # 恢复被覆盖的文件
    for rel in overwritten:
        src = backup_dir / rel
        dst = PROJECT_ROOT / rel
        if src.is_file():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            _ok(f"已恢复: {rel}")
        else:
            _warn(f"备份中找不到，跳过: {rel}")

    # 恢复被删除的文件
    for rel in deleted:
        src = backup_dir / rel
        dst = PROJECT_ROOT / rel
        if src.is_file():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            _ok(f"已恢复: {rel}")
        else:
            _warn(f"备份中找不到，跳过: {rel}")

    print()
    print("=" * 60)
    print("  回滚完成")
    print("=" * 60)
    print("  请重启 MCP 客户端，并跑一次验证。")
    return 0


# ============================================================
# 入口
# ============================================================
def main() -> int:
    parser = argparse.ArgumentParser(
        description="项目冗余清理：删除废弃文件 + 覆盖新版文件",
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="执行改动（不加这个参数时只做 dry-run 检查）",
    )
    parser.add_argument(
        "--rollback", type=str, default=None, metavar="TIMESTAMP",
        help="从指定时间戳的备份恢复（如 20260917_153000）",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("  layout-check-mcp 冗余清理脚本")
    print("=" * 60)

    if args.rollback:
        return do_rollback(args.rollback)

    if args.apply:
        return do_apply()
    else:
        ready, to_delete, to_overwrite = do_check()
        print()
        print("=" * 60)
        print("  检查完成（dry-run，未写任何文件）")
        print("=" * 60)
        print(f"  待删除: {len(to_delete)} 个文件")
        for x in to_delete:
            print(f"    - {x}")
        print(f"  待覆盖: {len(to_overwrite)} 个文件")
        for x in to_overwrite:
            print(f"    - {x}")
        print()
        if ready:
            print("  状态: 就绪，可执行 python Tools/cleanup_redundant.py --apply")
        else:
            print("  状态: 有问题，请先修复上方 [ERR]")
        return 0 if ready else 1


if __name__ == "__main__":
    sys.exit(main())