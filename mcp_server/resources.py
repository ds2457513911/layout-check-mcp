# -*- coding: utf-8 -*-
"""
mcp_server/resources.py —— MCP 资源定义

Resource 的作用是把"数据"暴露给客户端 AI 读。
AI 通过读 resource 拿到 PDF 页图片后，可以用自己的多模态能力提取参数。

URI 约定：
  datasheet://{pdf_stem}/page/{page}          PyMuPDF 整页图（PNG）
  datasheet://{pdf_stem}/marker/page/{page}   marker 版面分析图（JPEG）
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

        渲染引擎固定为 PyMuPDF（快、无外部依赖）。
        如果客户端不支持 image resource，请改用 render_pdf_page tool 拿路径。
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

    # # 在 mcp_server/resources.py 中，修改 get_datasheet_page_image 函数
    # @mcp.resource(
    #     "datasheet://{pdf_stem}/page/{page}",
    #     mime_type="text/plain",  # 将类型改为文本
    #     description="返回 PDF 指定页图片的本地绝对路径，供 AI 读取解析",
    # )
    # def get_datasheet_page_image_path(pdf_stem: str, page: int) -> str:
    #     """
    #     返回 PDF 指定页图片的本地绝对路径。
    #     """
    #     pdf = pdf_service.resolve_pdf(pdf_stem, config.PDF_SEARCH_ROOTS)
    #     if pdf is None:
    #         raise ValueError(f"找不到 PDF: {pdf_stem}")
        
    #     img_path = pdf_service.get_or_render_image(
    #         pdf_path=pdf,
    #         page=int(page),
    #         out_root=config.MARKER_ROOT,
    #         engine="pymupdf",
    #     )
    #     if img_path is None or not img_path.is_file():
    #         raise ValueError(f"渲染失败: pdf={pdf.name} page={page}")
        
    #     # 返回文件的绝对路径字符串
    #     return str(img_path.resolve())

    @mcp.resource(
        "datasheet://{pdf_stem}/marker/page/{page}",
        mime_type="image/jpeg",
        description="PDF 指定页的 marker 版面分析图（含 markdown 输出）",
    )
    def get_datasheet_marker_image(pdf_stem: str, page: int) -> bytes:
        """
        返回 PDF 指定页的 marker 版面分析图（JPEG 字节）。

        marker 会把图纸裁成独立 Figure，适合"文字为主、插图独立"的 PDF；
        混排页可能输出为空，此时改用 pymupdf resource。
        """
        pdf = pdf_service.resolve_pdf(pdf_stem, config.PDF_SEARCH_ROOTS)
        if pdf is None:
            raise ValueError(f"找不到 PDF: {pdf_stem}")
        img_path = pdf_service.get_or_render_image(
            pdf_path=pdf,
            page=int(page),
            out_root=config.MARKER_ROOT,
            engine="marker",
        )
        if img_path is None or not img_path.is_file():
            raise ValueError(f"marker 渲染失败: pdf={pdf.name} page={page}")
        return img_path.read_bytes()

    @mcp.resource(
        "datasheet://{pdf_stem}/info",
        description="PDF 元信息：总页数、land pattern 命中页、匹配关键词",
    )
    def get_datasheet_info(pdf_stem: str) -> str:
        """返回 PDF 的元信息（JSON 字符串）"""
        pdf = pdf_service.resolve_pdf(pdf_stem, config.PDF_SEARCH_ROOTS)
        if pdf is None:
            return json.dumps({"error": f"找不到 PDF: {pdf_stem}"}, ensure_ascii=False)
        info = pdf_service.locate_land_pattern_page(pdf)
        info["pdf_path"] = str(pdf)
        info["pdf_name"] = pdf.name
        return json.dumps(info, ensure_ascii=False, indent=2)
