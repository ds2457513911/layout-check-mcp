# -*- coding: utf-8 -*-
"""
lib_datasheet_parser.py —— 单个 PDF → 理论焊盘参数 的公共逻辑

支持两种图片渲染引擎（可在 parse_pdf_land_pattern 里切换）：

  - "pymupdf"（默认）: 用 PyMuPDF 整页渲染，输出稳定，适合"文字+表格+图纸混排"页
  - "marker"        : 用 marker_single 做版面分析，输出它识别为 Figure 的图，
                      适合"文字为主、插图独立"的 PDF；混排页可能输出为空

调用示例：
    parse_pdf_land_pattern(pdf, page, marker_root, render_engine="pymupdf")
    parse_pdf_land_pattern(pdf, page, marker_root, render_engine="marker")
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Optional

from services.vision_service import call_moondream_local

# ---------- 公共常量 ----------
DEFAULT_PYMUPDF_DPI = 150     # PyMuPDF 整页渲染 DPI
DEFAULT_MARKER_DPI = "192"    # marker 渲染 DPI（环境变量 IMAGE_DPI）

DEFAULT_RENDER_ENGINE = "pymupdf"   # 默认引擎

VISION_PROMPT = """
                你是硬件datasheet图纸解析助手。读取这张LAND PATTERN焊盘图纸。
                图片可能横向旋转90度，请 mentally旋转图片后读取尺寸，不要识别颠倒数字。
                输出严格JSON，不要额外解释。

                字段：
                {
                "unit": "mm",
                "pads": [ {"pin": 引脚号(int), "width": 焊盘宽度(float, mm), "height": 焊盘高度(float, mm)} ],
                "spacing_x": 横向中心间距(float, mm),
                "spacing_y": 纵向中心间距(float, mm),
                "note": "识别风险备注"
                }

                注意：
                - pin 必须是整数，不要输出 1.0 或 "1"
                - spacing_x / spacing_y 若图中无明确标注则填 null，不要瞎猜
                - 所有数值单位 mm
                只输出JSON。
                """


# ============================================================
# 渲染引擎 1: PyMuPDF（整页原样渲染）
# ============================================================
def _render_page_with_pymupdf(
    pdf_path: Path,
    target_page: int,
    out_root: Path,
    dpi: int = DEFAULT_PYMUPDF_DPI,
) -> dict:
    """
    用 PyMuPDF 把 PDF 指定页渲染成整页 PNG。

    输出路径: <out_root>/<pdf_stem>/pymupdf_pages/page_{n}.png

    :return: {
        "ok": bool,
        "engine": "pymupdf",
        "image_path": str | None,
        "md_path": None,          # PyMuPDF 不产出 markdown
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


# ============================================================
# 渲染引擎 2: marker（版面分析后选择性输出）
# ============================================================
def _marker_find_page_images(out_dir: Path, marker_page: int) -> list[Path]:
    """在 marker 输出目录下找目标页的所有图片（宽松匹配）"""
    candidates: list[Path] = []
    seen: set[str] = set()
    exts = ("jpeg", "jpg", "png", "webp")

    patterns = []
    for ext in exts:
        patterns.append(f"*page_{marker_page}_Figure_*.{ext}")
        patterns.append(f"*page_{marker_page}_*.{ext}")

    search_roots = [out_dir]
    for sub in out_dir.iterdir() if out_dir.is_dir() else []:
        if sub.is_dir():
            search_roots.append(sub)

    for root in search_roots:
        if not root.is_dir():
            continue
        for pat in patterns:
            try:
                for p in root.rglob(pat):
                    if p.is_file() and str(p) not in seen:
                        seen.add(str(p))
                        candidates.append(p)
            except Exception:
                continue
        if candidates:
            break

    return candidates


def _marker_find_md_file(out_dir: Path) -> Optional[Path]:
    """找 marker 输出的 markdown 文件"""
    if not out_dir.is_dir():
        return None
    try:
        for p in out_dir.rglob("*.md"):
            if p.is_file():
                return p
    except Exception:
        pass
    return None


def _render_page_with_marker(
    pdf_path: Path,
    target_page: int,
    out_root: Path,
    image_dpi: str = DEFAULT_MARKER_DPI,
) -> dict:
    """
    用 marker_single 渲染 PDF 指定页。

    输出路径: <out_root>/<pdf_stem>/marker_out/...

    :return: {
        "ok": bool,
        "engine": "marker",
        "image_path": str | None,
        "md_path": str | None,
        "stderr": str,
        "stdout": str,
    }
    """
    out_dir = out_root / pdf_path.stem / "marker_out"
    out_dir.mkdir(parents=True, exist_ok=True)

    marker_page = target_page - 1   # 0-based

    env = os.environ.copy()
    env["IMAGE_DPI"] = image_dpi

    cmd = [
        "marker_single",
        str(pdf_path),
        "--output_dir", str(out_dir),
        "--page_range", f"{marker_page}-{marker_page}",
    ]
    r = subprocess.run(cmd, env=env, capture_output=True, check=False, text=True)

    images = _marker_find_page_images(out_dir, marker_page)
    if not images:
        return {
            "ok": False,
            "engine": "marker",
            "image_path": None,
            "md_path": None,
            "stderr": (r.stderr or "")[-2000:],
            "stdout": (r.stdout or "")[-2000:],
        }

    images.sort(key=lambda p: p.stat().st_size, reverse=True)
    md_file = _marker_find_md_file(out_dir)

    return {
        "ok": True,
        "engine": "marker",
        "image_path": str(images[0]),
        "md_path": str(md_file) if md_file else None,
        "stderr": (r.stderr or "")[-2000:],
        "stdout": (r.stdout or "")[-2000:],
    }


# ============================================================
# 统一渲染入口：按 engine 参数选择
# ============================================================
def _render_page(
    pdf_path: Path,
    target_page: int,
    out_root: Path,
    engine: str = DEFAULT_RENDER_ENGINE,
) -> dict:
    """根据 engine 参数选择渲染后端"""
    if engine == "pymupdf":
        return _render_page_with_pymupdf(pdf_path, target_page, out_root)
    if engine == "marker":
        return _render_page_with_marker(pdf_path, target_page, out_root)
    raise ValueError(f"不支持的渲染引擎: {engine!r}（支持 'pymupdf' / 'marker'）")


# ============================================================
# 公共入口
# ============================================================
def parse_pdf_land_pattern(
    pdf_file_path: str | Path,
    target_page: int,
    marker_root: Path,
    page_span: int = 0,
    source_tag: Optional[dict] = None,
    render_engine: str = DEFAULT_RENDER_ENGINE,
) -> dict:
    """
    公共入口：单个 PDF → 理论焊盘参数。

    :param pdf_file_path: PDF 完整路径
    :param target_page: 人眼 1-based 页码
    :param marker_root: 输出根目录（两种引擎共用，各自建子目录）
    :param page_span: 兼容参数，当前忽略
    :param source_tag: 附加到返回值的溯源信息
    :param render_engine: "pymupdf"（默认） 或 "marker"
    """
    _ = page_span  # 保留参数兼容

    pdf_path = Path(pdf_file_path)
    if not pdf_path.exists():
        return {
            "error": f"PDF 文件不存在: {pdf_path}",
            "datasheet_file": str(pdf_path),
            "theoretical_land_params": None,
            **(source_tag or {}),
        }

    marker_root.mkdir(parents=True, exist_ok=True)

    # ---------- 1. 渲染 ----------
    render_res = _render_page(
        pdf_path=pdf_path,
        target_page=target_page,
        out_root=marker_root,
        engine=render_engine,
    )
    if not render_res["ok"]:
        return {
            "error": f"[{render_engine}] 未渲染出目标页图片 (page={target_page})",
            "datasheet_file": str(pdf_path),
            "target_page_human": target_page,
            "render_engine": render_engine,
            "render_stderr": render_res.get("stderr", ""),
            "render_stdout": render_res.get("stdout", ""),
            "theoretical_land_params": None,
            **(source_tag or {}),
        }

    image_path = render_res["image_path"]
    md_path = render_res.get("md_path")
    page_markdown = ""
    if md_path:
        try:
            page_markdown = Path(md_path).read_text(encoding="utf-8")
        except Exception:
            page_markdown = ""

    # ---------- 2. moondream 提取 ----------
    vision_result = call_moondream_local(
        image_path=image_path,
        prompt=VISION_PROMPT,
    )
    if not vision_result["success"]:
        return {
            "error": vision_result["error"],
            "datasheet_file": str(pdf_path),
            "target_page_human": target_page,
            "render_engine": render_engine,
            "source_image_path": image_path,
            "raw_vision_output": vision_result.get("raw", ""),
            "theoretical_land_params": None,
            **(source_tag or {}),
        }

    return {
        "datasheet_file": str(pdf_path),
        "target_page_human": target_page,
        "render_engine": render_engine,
        "source_image_path": image_path,
        "source_markdown": page_markdown[:2000],
        "ai_extracted_note": "AI视觉识别结果，必须人工对照PDF原始图纸复核，不可直接无条件信任",
        "theoretical_land_params": vision_result["parsed"],
        "raw_vision_output": vision_result.get("raw", ""),
        **(source_tag or {}),
    }