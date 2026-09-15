# debug_moondream.py
# 获取当前文件所在目录的父目录（即 Project_Layout）
import os
import sys
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(parent_dir)
# -*- coding: utf-8 -*-
"""官方最简复现代码"""
from transformers import AutoModelForCausalLM
from PIL import Image

print("加载模型...")
model = AutoModelForCausalLM.from_pretrained(
    "vikhyatk/moondream2",
    revision="2025-01-09",
    trust_remote_code=True,
    device_map={"": "cuda"},
    torch_dtype=None,     # ← 用默认精度，不强制 bfloat16
)
print("模型加载完成")

img_path = r"C:\Users\ds245\Documents\Project_Layout\marker_out\130-221-100003-W3G--FPC 0.5-10P 翻盖下接 H=1.5 编带\130-221-100003-W3G--FPC 0.5-10P 翻盖下接 H=1.5 编带\_page_0_Figure_0.jpeg"
image = Image.open(img_path).convert("RGB")

print("推理中...")
out = model.query(image, "Describe this image.")["answer"]
print(f"输出长度: {len(out)}")
print(f"输出内容: {repr(out[:500])}")