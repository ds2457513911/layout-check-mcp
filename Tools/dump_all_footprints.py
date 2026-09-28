# -*- coding: utf-8 -*-
"""
Tools/dump_all_footprints.py

扫描 Data/footprint 下所有 .dra，用 footprint_extractor 解析，
把关键信息（pin 名、pad 层名、尺寸、同目录 .pad 文件名）输出到 txt，
供分析 padstack 命名规则。

用法（在项目根跑）:
    uv run python Tools/dump_all_footprints.py

输出:
    Tools/footprint_dump.txt
"""
from __future__ import annotations

import sys
import traceback
from datetime import datetime
from pathlib import Path

# ---- 把项目根加到 sys.path，保证 services 能 import ----
THIS_FILE = Path(__file__).resolve()
PROJECT_ROOT = THIS_FILE.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.footprint_extractor import read_full_footprint  # noqa: E402


DATA_ROOT = PROJECT_ROOT / "Data" / "footprint"
OUT_FILE = PROJECT_ROOT / "Tools" / "footprint_dump.txt"


def _fmt_num(v) -> str:
    """数值格式化：None -> '-'，float 去尾零"""
    if v is None:
        return "-"
    if isinstance(v, float):
        s = f"{v:.4f}".rstrip("0").rstrip(".")
        return s if s else "0"
    return str(v)


def _fmt_size(size) -> str:
    """[w, h] -> '1.9 x 5.7'"""
    if not size or len(size) < 2:
        return "-"
    return f"{_fmt_num(size[0])} x {_fmt_num(size[1])}"


def _fmt_xy(xy) -> str:
    if not xy or len(xy) < 2:
        return "-"
    return f"({_fmt_num(xy[0])}, {_fmt_num(xy[1])})"


def dump_one(dra_path: Path, out) -> None:
    """解析单个 .dra 并写入 out"""
    folder = dra_path.parent

    out.write("=" * 80 + "\n")
    out.write(f"dra: {dra_path.relative_to(PROJECT_ROOT)}\n")

    # 同目录下的 .pad 文件（对比用）
    pad_files = sorted(p.stem for p in folder.glob("*.pad") if p.is_file())
    out.write(f"pad_files_in_folder: {pad_files}\n")

    # ---- 调用解析 ----
    try:
        result = read_full_footprint(dra_path=str(dra_path), pad_paths=[])
    except Exception as e:
        out.write(f"[EXCEPTION] {e}\n")
        out.write(traceback.format_exc())
        out.write("\n\n")
        return

    if result.get("error"):
        out.write(f"[ERROR] {result['error']}\n\n")
        return

    source = result.get("_source", "unknown")
    symbol_name = result.get("symbol_name", "")
    units = result.get("units", "")
    pins = result.get("pins", [])
    layers = result.get("layers", {})
    texts = result.get("texts", [])

    out.write(f"source: {source}\n")
    out.write(f"symbol_name: {symbol_name}\n")
    out.write(f"units: {units}\n")
    out.write(f"pin_count: {len(pins)}\n")

    # ---- pins ----
    out.write("\n--- pins ---\n")
    for pin in pins:
        out.write(
            f"pin {pin.get('number', '?')}  "
            f"padstack_name={pin.get('name', '?')}  "
            f"xy={_fmt_xy(pin.get('xy'))}  "
            f"bbox_size={_fmt_size(pin.get('size'))}\n"
        )
        for pad in pin.get("pads", []):
            out.write(
                f"    pad layer={pad.get('layer', '?'):<28} "
                f"figure={pad.get('figure_name', '?'):<10} "
                f"size={_fmt_size(pad.get('size'))}\n"
            )

    # ---- layers 概览 ----
    out.write("\n--- layers ---\n")
    for key in ("assembly_top", "assembly_bottom",
                "silkscreen_top", "silkscreen_bottom",
                "place_bound_top", "place_bound_bottom"):
        els = layers.get(key) or []
        if not els:
            out.write(f"{key}: 0\n")
            continue
        # 汇总 bbox 尺寸
        bboxes = [e.get("bbox") for e in els if e.get("bbox")]
        if bboxes:
            xs = [b[0][0] for b in bboxes] + [b[1][0] for b in bboxes]
            ys = [b[0][1] for b in bboxes] + [b[1][1] for b in bboxes]
            w = max(xs) - min(xs)
            h = max(ys) - min(ys)
            out.write(
                f"{key}: {len(els)} elements, "
                f"combined_size={_fmt_num(w)} x {_fmt_num(h)}\n"
            )
        else:
            out.write(f"{key}: {len(els)} elements\n")

    # ---- texts（只列文本内容和层）----
    if texts:
        out.write("\n--- texts ---\n")
        for t in texts:
            out.write(
                f"  text={t.get('text', '')!r}  "
                f"layer={t.get('layer', '?')}  "
                f"xy={_fmt_xy(t.get('xy'))}\n"
            )

    out.write("\n\n")


def main() -> int:
    if not DATA_ROOT.is_dir():
        print(f"[ERR] 数据目录不存在: {DATA_ROOT}")
        return 1

    # 收集所有 .dra，排除 AUTOSAVE
    dra_files = sorted(
        p for p in DATA_ROOT.rglob("*.dra")
        if p.is_file() and not p.name.upper().startswith("AUTOSAVE")
    )

    print(f"发现 {len(dra_files)} 个 .dra 文件")
    print(f"输出到: {OUT_FILE}")

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    with OUT_FILE.open("w", encoding="utf-8", newline="\n") as out:
        out.write(f"# footprint dump  generated_at={datetime.now().isoformat(timespec='seconds')}\n")
        out.write(f"# data_root={DATA_ROOT}\n")
        out.write(f"# dra_count={len(dra_files)}\n\n")

        for i, dra in enumerate(dra_files, 1):
            print(f"  [{i}/{len(dra_files)}] {dra.parent.name}\\{dra.name}")
            try:
                dump_one(dra, out)
            except Exception as e:
                out.write(f"[FATAL] {dra}: {e}\n\n")
                print(f"    [FATAL] {e}")

    print(f"\n完成。请打开: {OUT_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())