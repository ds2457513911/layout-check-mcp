# -*- coding: utf-8 -*-
"""
rename_project.py —— 一键重命名项目文件 + 自动修正 import 语句

使用方法：
  1. 把这个脚本放到项目根目录（和要改名的文件同级）
  2. 先运行一次带 --dry-run 看预览
  3. 确认无误后，去掉 --dry-run 真正执行

特性：
  - 只替换 import 语句里的模块名，不动注释 / 字符串 / 其他标识符
  - 每个被改内容的文件生成 .bak 备份
  - 支持 --dry-run 预览
  - 支持 --skip-imports 只改名不修 import
"""
from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path

# ---------- 改名映射表（旧名 -> 新名，含 .py） ----------
RENAME_MAP = {
    "moondream_engine.py":       "lib_moondream_engine.py",
    "tolerance_check.py":        "lib_tolerance_check.py",
    "allegro_reader.py":         "lib_allegro_reader.py",
    "layout_chect_mcp.py":       "srv_layout_check_mcp.py",
    "batch_read_allegro.py":     "job_read_allegro.py",
    "batch_read_datasheet.py":   "job_read_datasheet.py",
    "compare_all.py":            "job_compare_all.py",
    "chect_test.py":             "test_check.py",
}

# 旧模块名 -> 新模块名（用于替换 import 语句）
MODULE_MAP = {
    "moondream_engine":     "lib_moondream_engine",
    "tolerance_check":      "lib_tolerance_check",
    "allegro_reader":       "lib_allegro_reader",
    "layout_chect_mcp":     "srv_layout_check_mcp",
    "batch_read_allegro":   "job_read_allegro",
    "batch_read_datasheet": "job_read_datasheet",
    "compare_all":          "job_compare_all",
    "chect_test":           "test_check",
}

# 不改名的文件（避免误伤自己）
SKIP_FILES = {"rename_project.py"}


def fix_imports_in_file(path: Path, dry_run: bool = False) -> tuple[bool, list[str]]:
    """
    只修正 import 语句，不动注释、字符串、其他标识符。

    匹配三种情况：
      1. from <old_mod> import ...
      2. import <old_mod> as ...
      3. import <old_mod>          （单独一行）
    """
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return False, [f"  ⚠️ 跳过（非 UTF-8）: {path.name}"]

    original = text
    changes = []

    for old_mod, new_mod in MODULE_MAP.items():
        old_esc = re.escape(old_mod)

        # 三种 import 语句的正则
        patterns = [
            # from old_mod import ...
            (re.compile(rf"^(\s*from\s+){old_esc}(\s+import\s+)", re.MULTILINE),
             rf"\g<1>{new_mod}\g<2>"),
            # import old_mod as xxx
            (re.compile(rf"^(\s*import\s+){old_esc}(\s+as\s+)", re.MULTILINE),
             rf"\g<1>{new_mod}\g<2>"),
            # import old_mod （单独一行）
            (re.compile(rf"^(\s*import\s+){old_esc}(\s*$)", re.MULTILINE),
             rf"\g<1>{new_mod}\g<2>"),
        ]

        for pat, repl in patterns:
            matches = pat.findall(text)
            if matches:
                n = len(matches)
                text = pat.sub(repl, text)
                changes.append(f"  {old_mod} → {new_mod}  ({n} 处 import)")

    if text != original:
        if not dry_run:
            backup = path.with_suffix(path.suffix + ".bak")
            if not backup.exists():
                shutil.copy2(path, backup)
            path.write_text(text, encoding="utf-8")
        return True, changes

    return False, []


def rename_files(dry_run: bool = False) -> dict[str, str]:
    """重命名物理文件，返回 {旧名: 新名} 实际生效的映射"""
    root = Path(__file__).parent
    applied = {}

    for old_name, new_name in RENAME_MAP.items():
        old_path = root / old_name
        new_path = root / new_name

        if not old_path.exists():
            print(f"  ⏭️ 跳过（不存在）: {old_name}")
            continue

        if new_path.exists():
            print(f"  ⚠️ 跳过（目标已存在）: {new_name}")
            continue

        if not dry_run:
            old_path.rename(new_path)
            applied[old_name] = new_name
            print(f"  ✅ {old_name}  →  {new_name}")
        else:
            applied[old_name] = new_name
            print(f"  📝 [DRY-RUN] {old_name}  →  {new_name}")

    return applied


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="只预览，不实际改")
    parser.add_argument("--skip-imports", action="store_true", help="只改名，不改 import")
    args = parser.parse_args()

    dry_run = args.dry_run
    root = Path(__file__).parent

    print("=" * 70)
    print(f"{'[DRY-RUN 预览]' if dry_run else '[实际执行]'} 项目改名")
    print("=" * 70)

    # ---------- 第一步：改名文件 ----------
    print("\n【第一步】重命名文件")
    applied = rename_files(dry_run=dry_run)

    # ---------- 第二步：修正 import ----------
    if args.skip_imports:
        print("\n【第二步】跳过 import 修正（--skip-imports）")
    else:
        print("\n【第二步】修正 import 语句")
        changed_files = []
        for py_file in sorted(root.glob("*.py")):
            if py_file.name in SKIP_FILES or py_file.name.endswith(".bak"):
                continue
            changed, changes = fix_imports_in_file(py_file, dry_run=dry_run)
            if changed:
                changed_files.append((py_file.name, changes))

        if changed_files:
            print(f"\n  共 {len(changed_files)} 个文件内容被改动：")
            for fname, changes in changed_files:
                print(f"\n  📄 {fname}")
                for c in changes:
                    print(c)
        else:
            print("  （无文件需要改动 import）")

    # ---------- 总结 ----------
    print("\n" + "=" * 70)
    print("完成！" if not dry_run else "预览完成（未实际改动，去掉 --dry-run 执行）")
    print("=" * 70)
    if not dry_run:
        print("\n提示：所有被改动的 .py 文件都生成了 .bak 备份，")
        print("      确认无误后可手动删除 .bak 文件。")


if __name__ == "__main__":
    main()