# test_moondream.py
import os
os.environ["HF_HUB_OFFLINE"] = "1"  # 强制离线，只用本地缓存
os.environ["TRANSFORMERS_OFFLINE"] = "1"

from moondream_engine import call_moondream_local
r = call_moondream_local(
    r"C:\Users\ds245\Desktop\marker_out\test\3S48000163产品规格书_20220916_S1\_page_4_Figure_4.jpeg",
    '请描述这张图的内容，并以 JSON 格式输出，格式为 {"description": "这里写描述"}'
)
print(r["success"], r["parsed"] if r["success"] else r["error"])

