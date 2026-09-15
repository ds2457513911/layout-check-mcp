# -*- coding: utf-8 -*-
"""
mcp_server/prompts.py —— MCP 提示模板

Prompt 是给客户端 AI 看的"操作说明书"。
本模块只包含字符串模板，不 import 任何业务模块，方便单独复制到 SKILL.md。
"""
from __future__ import annotations

from fastmcp import FastMCP


def register(mcp: FastMCP) -> None:
    """把所有 prompt 注册到给定的 FastMCP 实例。"""

    @mcp.prompt()
    def extract_land_pattern(pdf_stem: str, page: int) -> str:
        """指导 AI 从规格书某页图片中提取焊盘参数。"""
        return f"""你是一个硬件封装参数提取助手。请读取以下资源：

- 图片：datasheet://{pdf_stem}/page/{page}
- 如果图片不够清晰，可以改用：datasheet://{pdf_stem}/marker/page/{page}
- 元信息：datasheet://{pdf_stem}/info

任务：从这张 land pattern 图纸中提取焊盘参数。

注意事项：
- 图片可能旋转 90 度，请先在心里旋转再读数。
- pin 号必须是整数，不要输出 "1" 或 1.0。
- 所有尺寸统一为 mm；如果图中标注 mil，请换算（1 mil = 0.0254 mm）。
- spacing_x / spacing_y 若图中无明确标注，填 null，不要猜测。
- 如果图纸模糊或无法识别，在 note 字段说明，不要编造数值。

输出严格 JSON，不要额外解释：
{{
  "unit": "mm",
  "pads": [
    {{"pin": 1, "width": 0.3, "height": 0.6}}
  ],
  "spacing_x": 0.5,
  "spacing_y": null,
  "tolerance": {
    "width":     {"min": -0.03, "max": 0.03},
    "height":    {"min": -0.03, "max": 0.03},
    "spacing_x": {"min": -0.05, "max": 0.05},
    "spacing_y": null
  },
  "note": ""
}}

输出后，请立即调用 validate_land_pattern_json 校验你的 JSON，
如果 valid=false，根据 errors 修正后重试。
"""

    @mcp.prompt()
    def full_footprint_check(folder_path: str) -> str:
        """端到端流程 SOP：告诉 AI 如何完成一个文件夹的封装公差检查。"""
        return f"""请对文件夹 `{folder_path}` 执行完整的封装公差检查。

步骤：

1. 调 tool `list_folder_files(folder_path="{folder_path}")`
   获取 PDF / .dra / .pad 列表。如果没有 PDF 或没有 .dra，报告并停止。

2. 调 tool `locate_land_pattern_page(pdf_file_path=<pdf>)`
   定位 land pattern 页。
   - method="primary"：直接使用该 page。
   - method="fallback"：仍使用该 page，但提醒用户这是兜底匹配。
   - method="no_match"：报告无法定位，建议人工指定页码。

3. 提取理论焊盘参数，二选一：
   A. 引擎路径（快速、免费、本地）：
      调 tool `parse_datasheet_land_pattern(pdf_file_path=<pdf>, target_page=<page>)`
   B. AI 路径（更灵活、消耗 token）：
      应用 prompt `extract_land_pattern(pdf_stem=<stem>, page=<page>)`
      先读 resource 里的图片，自己输出 JSON，
      然后调 `validate_land_pattern_json` 校验。

   建议：先用 A，如果 A 返回 error 或 moondream2 识别明显异常，再用 B。

4. 对每个 .dra：
   调 tool `read_allegro_footprint(dra_file_path=<dra>, pad_file_paths=<pads>)`

5. 对每个 .dra 调 tool `check_land_pattern_tolerance`：
   - theoretical_payload = 第 3 步的返回（如果走 AI 路径，
     用 validate_land_pattern_json 的 normalized 包装成
     {{"theoretical_land_params": <normalized>}}）
   - actual_payload = 第 4 步的返回
   - tolerance 不传，用默认

6. 汇总所有 .dra 的 conclusion，输出报告。如果任一 .dra 为 FAIL，
   给出失败的 pin / 维度 / delta 明细。

注意：
- AI 视觉识别结果必须提醒用户人工对照 PDF 原始图纸复核。
- 某一步失败时不要编造数据，报告错误并继续处理其他 .dra。
- 最终结论请用中文自然语言总结，同时保留原始 JSON 供用户查阅。
"""
