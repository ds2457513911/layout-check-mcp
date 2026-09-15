# -*- coding: utf-8 -*-
"""
diag_marker.py —— 诊断 marker_single 对指定 PDF 的输出结构

用法:
    python diag_marker.py "<PDF 完整路径>" <target_page>
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

if len(sys.argv) < 3:
    print("用法: python diag_marker.py <PDF路径> <页码(1-based)>", file=sys.stderr)
    sys.exit(1)

pdf_path = Path(sys.argv[1])
target_page = int(sys.argv[2])

if not pdf_path.is_file():
    print(f"PDF 不存在: {pdf_path}", file=sys.stderr)
    sys.exit(1)

marker_page = target_page - 1
out_dir = Path(r"C:\Users\ds245\Documents\Project_Layout\marker_out") / pdf_path.stem
out_dir.mkdir(parents=True, exist_ok=True)

env = os.environ.copy()
env["IMAGE_DPI"] = "192"

cmd = [
    "marker_single",
    str(pdf_path),
    "--output_dir", str(out_dir),
    "--page_range", f"{marker_page}-{marker_page}",
]

print("=" * 70)
print(f"PDF: {pdf_path}")
print(f"target_page (人眼): {target_page}")
print(f"marker_page (0-based): {marker_page}")
print(f"out_dir: {out_dir}")
print(f"命令: {' '.join(cmd)}")
print("=" * 70)

r = subprocess.run(cmd, env=env, capture_output=True, check=False, text=True)

print("\n--- marker stdout ---")
print(r.stdout[-3000:] if r.stdout else "(空)")
print("\n--- marker stderr ---")
print(r.stderr[-3000:] if r.stderr else "(空)")
print(f"\nreturncode: {r.returncode}")

print("\n--- out_dir 下的所有文件/目录 ---")
if out_dir.is_dir():
    for p in sorted(out_dir.rglob("*")):
        rel = p.relative_to(out_dir)
        if p.is_dir():
            print(f"  [DIR]  {rel}/")
        else:
            print(f"  [FILE] {rel}  ({p.stat().st_size} bytes)")

    images_dir = out_dir / "images"
    print(f"\n--- images 目录是否存在: {images_dir.is_dir()} ---")
    if images_dir.is_dir():
        all_files = list(images_dir.iterdir())
        print(f"文件总数: {len(all_files)}")
        for p in sorted(all_files):
            print(f"  {p.name}  ({p.stat().st_size} bytes)")

        print("\n--- 匹配 page_{n}_* 的文件 ---")
        matched = list(images_dir.glob(f"page_{marker_page}_*"))
        print(f"匹配数: {len(matched)}")
        for p in matched:
            print(f"  {p.name}")

        print("\n--- 匹配任意含 page_{n} 的文件（更宽松） ---")
        matched2 = [p for p in all_files if f"page_{marker_page}" in p.name]
        print(f"匹配数: {len(matched2)}")
        for p in matched2:
            print(f"  {p.name}")
else:
    print("  (out_dir 不存在)")