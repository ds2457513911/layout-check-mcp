#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cleanup_moondream_marker.py —— 路线 A：删除 marker 和 moondream，精简项目

做的事：
  1. 备份所有将被修改或删除的文件到 .cleanup_backup/<时间戳>/
  2. 删除以下文件（moondream / marker 相关）：
     - services/vision_service.py
     - lib_moondream_engine.py
  3. 重写以下文件（去 moondream、去 marker）：
     - services/pdf_renderer.py
     - services/footprint_service.py
     - mcp_server/tools.py
     - mcp_server/resources.py
  4. 扫描残留引用，报告给用户手动确认

用法：
    python cleanup_moondream_marker.py --dry-run    # 预览
    python cleanup_moondream_marker.py              # 执行（默认备份）
    python cleanup_moondream_marker.py --restore    # 从最近备份恢复
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path


BACKUP_ROOT_NAME = ".cleanup_backup"
PROJECT_ROOT = Path(__file__).resolve().parent


# ============================================================
# 要删除的文件
# ============================================================
FILES_TO_DELETE = [
    "services/vision_service.py",
    "lib_moondream_engine.py",
]


# ============================================================
# 要重写的文件（完整新内容）
# ============================================================
NEW_PDF_RENDERER = r'''# -*- coding: utf-8 -*-
"""
services/pdf_renderer.py —— PDF 单页渲染（PyMuPDF）

被 services/pdf_service.py 用于把 PDF 指定页渲染成图片，
供 MCP resource 层把图片暴露给客户端 AI 读取。

说明：
  - 已移除 marker 引擎（版面分析）
  - 已移除 moondream 调用（视觉提取由客户端 AI 完成）
  - 只保留 PyMuPDF 整页渲染
"""
from __future__ import annotations

from pathlib import Path

# 默认渲染 DPI
DEFAULT_PYMUPDF_DPI = 150


def _render_page_with_pymupdf(
    pdf_path: Path,
    target_page: int,
    out_root: Path,
    dpi: int = DEFAULT_PYMUPDF_DPI,
) -> dict:
    """
    用 PyMuPDF 把 PDF 指定页渲染成整页 PNG。

    输出路径: <out_root>/<pdf_stem>/pymupdf_pages/page_{n}.png

    :param pdf_path: PDF 绝对路径
    :param target_page: 人眼 1-based 页码
    :param out_root: 输出根目录
    :param dpi: 渲染 DPI
    :return: {
        "ok": bool,
        "engine": "pymupdf",
        "image_path": str | None,
        "md_path": None,
        "stderr": str,
        "stdout": str,
    }
    """
    try:
        import fitz  # PyMuPDF
    except ImportError:
        return {
            "ok": False,
            "engine": "pymupdf",
            "image_path": None,
            "md_path": None,
            "stderr": "PyMuPDF 未安装，请运行: pip install PyMuPDF",
            "stdout": "",
        }

    out_dir = out_root / pdf_path.stem / "pymupdf_pages"
    out_dir.mkdir(parents=True, exist_ok=True)

    img_path = out_dir / f"page_{target_page}.png"

    try:
        doc = fitz.open(str(pdf_path))
    except Exception as e:
        return {
            "ok": False,
            "engine": "pymupdf",
            "image_path": None,
            "md_path": None,
            "stderr": f"PyMuPDF 打开 PDF 失败: {e}",
            "stdout": "",
        }

    try:
        page_index = target_page - 1
        if page_index < 0 or page_index >= len(doc):
            return {
                "ok": False,
                "engine": "pymupdf",
                "image_path": None,
                "md_path": None,
                "stderr": f"页码越界: page={target_page}, total={len(doc)}",
                "stdout": "",
            }
        page = doc[page_index]
        pix = page.get_pixmap(dpi=dpi)
        pix.save(str(img_path))
    except Exception as e:
        return {
            "ok": False,
            "engine": "pymupdf",
            "image_path": None,
            "md_path": None,
            "stderr": f"PyMuPDF 渲染失败: {e}",
            "stdout": "",
        }
    finally:
        doc.close()

    if not img_path.is_file():
        return {
            "ok": False,
            "engine": "pymupdf",
            "image_path": None,
            "md_path": None,
            "stderr": "PyMuPDF 渲染后图片文件不存在",
            "stdout": "",
        }

    return {
        "ok": True,
        "engine": "pymupdf",
        "image_path": str(img_path),
        "md_path": None,
        "stderr": "",
        "stdout": "",
    }


def _render_page(
    pdf_path: Path,
    target_page: int,
    out_root: Path,
    engine: str = "pymupdf",
) -> dict:
    """
    统一渲染入口。当前只支持 "pymupdf"。

    保留 engine 参数是为了向后兼容旧调用方；传入其他值会返回错误。
    """
    if engine != "pymupdf":
        return {
            "ok": False,
            "engine": engine,
            "image_path": None,
            "md_path": None,
            "stderr": (
                f"不支持的渲染引擎: {engine!r}"
                f"（已移除 marker，只支持 'pymupdf'）"
            ),
            "stdout": "",
        }
    return _render_page_with_pymupdf(pdf_path, target_page, out_root)
'''


NEW_FOOTPRINT_SERVICE = r'''# -*- coding: utf-8 -*-
"""
services/footprint_service.py —— 封装检查业务编排

职责：
  - 执行理论 vs 实际的公差比对
  - 把检查结果写成 JSON 报告

说明：
  - 已移除 extract_theoretical（moondream 引擎路径）
  - 理论参数由客户端 AI 从 PDF 图片中读取，通过 MCP resource 传递

这一层不感知 MCP，可被批处理脚本、单元测试、MCP tool 复用。
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from services.tolerance_service import check_dimension_tolerance


def check_tolerance(
    theoretical_payload: dict,
    actual_payload: dict,
    tolerance: Optional[dict] = None,
) -> dict:
    """
    公差比对：理论焊盘参数 vs 实际封装参数。

    :param theoretical_payload: 包含 theoretical_land_params 的完整 payload
    :param actual_payload: services.allegro_reader 返回的 actual_payload
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
'''


NEW_TOOLS = r'''# -*- coding: utf-8 -*-
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
'''


NEW_RESOURCES = r'''# -*- coding: utf-8 -*-
"""
mcp_server/resources.py —— MCP 资源定义

Resource 的作用是把"数据"暴露给客户端 AI 读。
AI 通过读 resource 拿到 PDF 页图片后，可以用自己的多模态能力提取参数。

说明：
  - 已移除 marker image resource（marker 引擎已删除）
  - 只保留 PyMuPDF 整页图 resource 和 PDF 元信息 resource

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
        如果客户端不支持 image resource，请改用其他方式获取图片路径。
        """
        pdf = pdf_service.resolve_pdf(pdf_stem, config.PDF_SEARCH_ROOTS)
        if pdf is None:
            raise ValueError(f"找不到 PDF: {pdf_stem}")
        img_path = pdf_service.get_or_render_image(
            pdf_path=pdf,
            page=int(page),
            out_root=config.MARKER_ROOT,
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


REWRITE_MAP: dict[str, str] = {
    "services/pdf_renderer.py":    NEW_PDF_RENDERER,
    "services/footprint_service.py": NEW_FOOTPRINT_SERVICE,
    "mcp_server/tools.py":         NEW_TOOLS,
    "mcp_server/resources.py":     NEW_RESOURCES,
}


# ============================================================
# 残留引用扫描关键词
# ============================================================
STALE_PATTERNS = [
    r"\bmoondream\b",
    r"\bvision_service\b",
    r"\bparse_pdf_land_pattern\b",
    r"\bextract_theoretical\b",
    r"\bparse_datasheet_land_pattern\b",
    r"\bmarker\b",
    r"\bmarker_out\b",
    r"\bcall_moondream_local\b",
    r"\bload_moondream\b",
]

# 扫描范围（相对项目根）
SCAN_DIRS = ["services", "mcp_server", "shared"]


def log(msg: str, level: str = "INFO") -> None:
    prefix = {
        "INFO": "   ",
        "OK":   "✅",
        "WARN": "⚠️",
        "ERR":  "❌",
        "SKIP": "⏭️",
    }[level]
    print(f"{prefix} {msg}")


class Cleanup:
    def __init__(self, root: Path, dry_run: bool, do_backup: bool):
        self.root = root
        self.dry_run = dry_run
        self.do_backup = do_backup
        self.backup_dir: Path | None = None
        self.deleted: list[Path] = []
        self.rewritten: list[Path] = []

    def backup(self, path: Path) -> None:
        if not self.do_backup or self.dry_run:
            return
        if self.backup_dir is None:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.backup_dir = self.root / BACKUP_ROOT_NAME / ts
            self.backup_dir.mkdir(parents=True, exist_ok=True)
        rel = path.relative_to(self.root)
        dst = self.backup_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dst)

    def step1_delete(self) -> None:
        log("步骤 1/3：删除 moondream / marker 相关文件")
        for rel in FILES_TO_DELETE:
            p = self.root / rel
            if not p.is_file():
                log(f"{rel} 不存在，跳过", "SKIP")
                continue
            if self.dry_run:
                log(f"[DRY-RUN] 将删除 {rel}")
            else:
                self.backup(p)
                p.unlink()
                self.deleted.append(p)
                log(f"已删除 {rel}", "OK")

    def step2_rewrite(self) -> None:
        log("步骤 2/3：重写以下文件（去 moondream、去 marker）")
        for rel, new_content in REWRITE_MAP.items():
            p = self.root / rel
            if not p.is_file():
                log(f"{rel} 不存在，跳过", "SKIP")
                continue
            old = p.read_text(encoding="utf-8")
            if old == new_content:
                log(f"{rel} 内容未变，跳过", "SKIP")
                continue
            if self.dry_run:
                log(f"[DRY-RUN] 将重写 {rel}（{len(old)} → {len(new_content)} 字节）")
            else:
                self.backup(p)
                p.write_text(new_content, encoding="utf-8")
                self.rewritten.append(p)
                log(f"已重写 {rel}", "OK")

    def step3_scan(self) -> None:
        log("步骤 3/3：扫描残留引用")
        regex = re.compile("|".join(STALE_PATTERNS), re.IGNORECASE)
        leftovers: list[tuple[Path, int, list[str]]] = []

        for scan_dir in SCAN_DIRS:
            d = self.root / scan_dir
            if not d.is_dir():
                continue
            for py in d.rglob("*.py"):
                try:
                    src = py.read_text(encoding="utf-8")
                except Exception:
                    continue
                hits = regex.findall(src)
                if hits:
                    unique = sorted(set(h.strip() for h in hits))
                    leftovers.append((py, len(hits), unique))

        if leftovers:
            log(f"发现 {len(leftovers)} 个文件仍引用已删/已改模块：", "WARN")
            for py, n, names in leftovers:
                print(f"      {py.relative_to(self.root)} ({n} 处): {', '.join(names)}")
            print()
            print("  请手动检查这些文件，可能需要调整 import 或业务逻辑。")
        else:
            log("没有残留，MCP 层已彻底与 moondream / marker 解耦", "OK")

    def run(self) -> int:
        print(f"项目根目录：{self.root}")
        print(f"模式：{'DRY-RUN（不修改文件）' if self.dry_run else '执行'}")
        print(f"备份：{'开启' if self.do_backup and not self.dry_run else '关闭'}")
        print()

        self.step1_delete()
        print()
        self.step2_rewrite()
        print()
        self.step3_scan()
        print()

        if not self.dry_run:
            print("=" * 60)
            print(f"删除文件：{len(self.deleted)}")
            for f in self.deleted:
                print(f"  - {f.relative_to(self.root)}")
            print(f"重写文件：{len(self.rewritten)}")
            for f in self.rewritten:
                print(f"  ~ {f.relative_to(self.root)}")
            if self.backup_dir:
                print(f"备份位置：{self.backup_dir.relative_to(self.root)}")
        return 0


def cmd_restore(root: Path) -> int:
    backup_root = root / BACKUP_ROOT_NAME
    if not backup_root.is_dir():
        print(f"❌ 备份目录不存在：{backup_root}", file=sys.stderr)
        return 1
    snapshots = sorted(p for p in backup_root.iterdir() if p.is_dir())
    if not snapshots:
        print("❌ 没有找到任何备份快照", file=sys.stderr)
        return 1
    latest = snapshots[-1]
    print(f"从 {latest.relative_to(root)} 恢复...")
    for src in latest.rglob("*"):
        if not src.is_file():
            continue
        rel = src.relative_to(latest)
        dst = root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        print(f"  {rel}")
    print("✅ 恢复完成")
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="路线 A：删除 marker 和 moondream，精简项目"
    )
    parser.add_argument("--dry-run", action="store_true", help="预览，不修改文件")
    parser.add_argument("--no-backup", action="store_true", help="不备份（危险）")
    parser.add_argument("--restore", action="store_true", help="从最近一次备份恢复")
    parser.add_argument(
        "--root", type=Path, default=Path.cwd(),
        help="项目根目录（默认当前目录）",
    )
    args = parser.parse_args()

    root = args.root.resolve()
    if not (root / "services").is_dir() or not (root / "mcp_server").is_dir():
        print(
            f"❌ 在 {root} 下找不到 services/ 或 mcp_server/，请用 --root 指定项目根目录",
            file=sys.stderr,
        )
        return 1

    if args.restore:
        return cmd_restore(root)

    c = Cleanup(
        root=root,
        dry_run=args.dry_run,
        do_backup=not args.no_backup,
    )
    return c.run()


if __name__ == "__main__":
    sys.exit(main())