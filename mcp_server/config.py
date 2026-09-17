# -*- coding: utf-8 -*-
"""
mcp_server/config.py —— MCP 服务配置

所有路径都基于项目根目录解析，避免客户端拉起时 cwd 不确定导致路径漂移。
"""
from __future__ import annotations

from pathlib import Path

# 项目根目录（mcp_server/ 的上一级）
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# marker / pymupdf 渲染输出根目录
MARKER_ROOT = PROJECT_ROOT / "marker_out"

# PDF 搜索根目录列表
# - 第一个是项目根目录，方便放几个测试 PDF
# - 后续可追加你的 footprint 目录
PDF_SEARCH_ROOTS: list[Path] = [
    PROJECT_ROOT,
    Path(r"C:\Users\ds245\Documents\工作文档_蓝晨\Layout\footprint"),
]

# 默认公差配置（与 job_compare_all.py 保持一致）
DEFAULT_TOLERANCE = {
    "width":     {"min": -0.1,  "max": 0.1},
    "height":    {"min": -0.1,  "max": 0.1},
    "spacing_x": {"min": -0.15, "max": 0.15},
    "spacing_y": {"min": -0.15, "max": 0.15},
}

# SkillBridge workspace id（MCP tool 调用 Allegro 时使用）
SKILLBRIDGE_WORKSPACE_ID = "7777"
