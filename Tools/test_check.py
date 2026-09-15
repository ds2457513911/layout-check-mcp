import asyncio
import json
from fastmcp import Client


def _extract_dict(result):
    """兼容不同 fastmcp 版本，从 CallToolResult 里提取 dict"""
    if hasattr(result, "data") and result.data is not None:
        return result.data
    if hasattr(result, "content") and result.content:
        item = result.content[0]
        text = getattr(item, "text", None) or str(item)
        try:
            return json.loads(text)
        except Exception:
            return {"raw_text": text}
    return {"raw": str(result)}


async def main():
    async with Client("layout_chect_mcp.py") as client:
        # ---------- 1. 解析 datasheet 理论值 ----------
        theo_res = await client.call_tool(
            "parse_datasheet_land_pattern",
            {
                "pdf_file_path": r"C:\Users\ds245\Desktop\marker_out\test\3S48000163产品规格书_20220916_S1.pdf",
                "target_page": 4,
            },
        )
        theo = _extract_dict(theo_res)
        print("=== 理论值 ===")
        print(json.dumps(theo, ensure_ascii=False, indent=2))

        # ---------- 2. 读 Allegro 实际值（走 MCP）----------
        actual_res = await client.call_tool(
            "read_allegro_footprint",
            {
                "dra_file_path": r"C:\Users\ds245\Documents\工作文档_蓝晨\Layout\footprint\3S48000163\nb_xtal4_3d2x2d5x0d7.dra",
                "pad_file_path": r"C:\Users\ds245\Documents\工作文档_蓝晨\Layout\footprint\3S48000163\r1d4x1d2.pad",
            },
        )
        actual = _extract_dict(actual_res)
        print("=== 实际值 ===")
        print(json.dumps(actual, ensure_ascii=False, indent=2))

        # ---------- 3. 公差比对 ----------
        tol_res = await client.call_tool(
            "check_land_pattern_tolerance",
            {
                "theoretical_payload": theo,
                "actual_payload": actual,
                "tolerance": {
                    "width":     {"min": -0.1,  "max": 0.1},
                    "height":    {"min": -0.1,  "max": 0.1},
                    "spacing_x": {"min": -0.15, "max": 0.15},
                    "spacing_y": {"min": -0.15, "max": 0.15},
                },
            },
        )
        result = _extract_dict(tol_res)
        print("=== 比对结果 ===")
        print(f"结论: {result.get('conclusion')}")
        print(f"汇总: {result.get('summary')}")
        for c in result.get("comparisons", []):
            print(
                f"  [{c['status']}] pin={c['pin']} {c['dimension']}: "
                f"理论={c['theoretical_mm']} 实际={c['actual_mm']} "
                f"delta={c['delta_mm']} tol=[{c['tol_min_mm']},{c['tol_max_mm']}]"
                + (f" ({c['reason']})" if c.get("reason") else "")
            )


if __name__ == "__main__":
    asyncio.run(main())