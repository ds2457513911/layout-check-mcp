# diag_pin.py —— 诊断 pin 对象有哪些可用属性
from skillbridge import Workspace
ws = Workspace.open(workspace_id="7777")

# 打开 .dra
import tempfile, shutil, os
src = r"C:\Users\ds245\Documents\工作文档_蓝晨\Layout\footprint\3S48000163\nb_xtal4_3d2x2d5x0d7.dra"
tmp = tempfile.mkdtemp(prefix="diag_")
dst = os.path.join(tmp, "temp.dra")
shutil.copy2(src, dst)

ws["axlOpenDesign"](design=dst, mode="wf")

design = ws["axlDBGetDesign"]()
print("=== design 对象 ===")
print("type:", type(design))

# 拿 pins
pins = None
for attr in ("pins", "Pins", "package", "symbol"):
    try:
        val = getattr(design, attr, None)
        if val is None:
            val = design[attr]
        if val:
            pins = val
            print(f"找到 pins 通过 design.{attr}")
            break
    except Exception as e:
        print(f"  design.{attr} 失败: {e}")

if not pins:
    print("没找到 pins")
else:
    pins_list = list(pins)
    print(f"pins 数量: {len(pins_list)}")
    p = pins_list[0]
    print("\n=== 第一个 pin 对象 ===")
    print("type:", type(p))

    # 试各种访问方式
    print("\n-- 方括号访问 --")
    for attr in ["bBox", "xy", "number", "name", "pad", "pads"]:
        try:
            print(f"  pin['{attr}'] = {p[attr]!r}")
        except Exception as e:
            print(f"  pin['{attr}'] -> {type(e).__name__}: {e}")

    print("\n-- 点号访问 --")
    for attr in ["bBox", "xy", "number", "name", "pad", "pads"]:
        try:
            print(f"  pin.{attr} = {getattr(p, attr)!r}")
        except Exception as e:
            print(f"  pin.{attr} -> {type(e).__name__}: {e}")

    print("\n-- dir(pin) 前 80 个属性 --")
    attrs = [a for a in dir(p) if not a.startswith("_")]
    print(attrs[:80])

shutil.rmtree(tmp, ignore_errors=True)
ws.close()