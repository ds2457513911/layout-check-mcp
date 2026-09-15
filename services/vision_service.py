# -*- coding: utf-8 -*-
"""
lib_moondream_engine.py —— 本地视觉模型 moondream2 调用引擎
模型: vikhyatk/moondream2 (transformers + trust_remote_code)
能力: 模型全局单例加载 / 读图 / 视觉问答 VQA / 输出清洗 / JSON结构化 / 失败重试

关键参数：
  MAX_NEW_TOKENS = 384
    moondream2 文本模型最大上下文 = 2048 token。
    图片 token (~700) + prompt token (~200) 已占去近 900，
    给生成留 ~384 已经足够输出 JSON（一般 < 300 字符）。
    原来 1024 会导致 pos 超出 2048 → CUDA kernel 崩溃。
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Optional

import torch
from PIL import Image
from transformers import AutoModelForCausalLM

# ---------- 全局单例 ----------
_MODEL: Optional[Any] = None
_MODEL_META: dict = {}

DEFAULT_MODEL_ID = "vikhyatk/moondream2"
DEFAULT_REVISION = "2025-01-09"

os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

# 生成 token 上限（给图片 + prompt 留出空间，避免超出 2048）
MAX_NEW_TOKENS = 384


def _pick_device(device: str) -> str:
    if device == "auto":
        return "cuda" if torch.cuda.is_available() else "cpu"
    return device


def load_moondream(
    model_id: str = DEFAULT_MODEL_ID,
    revision: str = DEFAULT_REVISION,
    device: str = "auto",
    use_4bit: bool = False,
) -> Any:
    """加载 moondream2 模型（幂等，重复调用直接返回已有实例）"""
    global _MODEL, _MODEL_META
    if _MODEL is not None:
        return _MODEL

    dev = _pick_device(device)
    kwargs: dict = dict(
        trust_remote_code=True,
        revision=revision,
        device_map=dev,
    )
    if use_4bit:
        from transformers import BitsAndBytesConfig
        kwargs["quantization_config"] = BitsAndBytesConfig(
            load_in_4bit=True, bnb_4bit_compute_dtype=torch.bfloat16
        )
    else:
        kwargs["torch_dtype"] = torch.bfloat16

    _MODEL = AutoModelForCausalLM.from_pretrained(model_id, **kwargs).eval()
    _MODEL_META = {
        "model_id": model_id,
        "revision": revision,
        "device": dev,
        "quantized": use_4bit,
    }
    return _MODEL


def _extract_json(raw: str) -> dict:
    """从模型输出里稳健提取 JSON 对象"""
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError(f"输出中找不到JSON对象: {raw[:300]!r}")
    body = text[start:end + 1]
    body = body.replace("，", ",").replace("：", ":").replace("；", ";")
    body = re.sub(r"\bNaN\b", "null", body)
    return json.loads(body)


def _coerce_numeric(obj: Any) -> Any:
    """递归把字符串型数字转 float"""
    if isinstance(obj, dict):
        return {k: _coerce_numeric(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_coerce_numeric(x) for x in obj]
    if isinstance(obj, str):
        s = obj.strip()
        try:
            return float(s)
        except ValueError:
            return obj
    return obj


def call_moondream_local(
    image_path: str,
    prompt: str,
    model_id: str = DEFAULT_MODEL_ID,
    revision: str = DEFAULT_REVISION,
    device: str = "auto",
    use_4bit: bool = False,
    max_retries: int = 2,
) -> dict:
    """
    调用本地 moondream2 识别图纸，返回结构化结果（带溯源 + 原始输出）。

    返回:
      success=True : {"success": True, "parsed": dict, "raw": str,
                      "model": dict, "retry_count": int}
      success=False: {"success": False, "error": str, "raw": str, "model": dict}
    """
    p = Path(image_path)
    if not p.exists():
        return {
            "success": False,
            "error": f"图片不存在: {image_path}",
            "raw": "",
            "model": _MODEL_META,
        }

    model = load_moondream(model_id, revision, device, use_4bit)
    image = Image.open(p).convert("RGB")

    raw = ""
    last_err: Optional[Exception] = None
    for attempt in range(max_retries + 1):
        try:
            temp = 0.0 if attempt == 0 else 0.2 * attempt
            settings = {
                "temperature": temp,
                "max_tokens": MAX_NEW_TOKENS,   # ← 关键：384，避免超出 2048
                "top_p": 0.3,
            }
            out = model.query(image, prompt, settings=settings)
            raw = out["answer"] if isinstance(out, dict) else str(out)

            parsed = _coerce_numeric(_extract_json(raw))
            return {
                "success": True,
                "parsed": parsed,
                "raw": raw,
                "model": _MODEL_META,
                "retry_count": attempt,
            }
        except (json.JSONDecodeError, ValueError) as e:
            last_err = e
        except RuntimeError as e:
            # CUDA 相关崩溃无法通过重试恢复，直接返回
            msg = str(e)
            if "CUDA" in msg or "device-side assert" in msg or "out of bounds" in msg:
                return {
                    "success": False,
                    "error": f"CUDA 推理崩溃（可能是上下文超长）: {msg[:300]}",
                    "raw": raw,
                    "model": _MODEL_META,
                }
            last_err = e
        except Exception as e:
            last_err = e

    return {
        "success": False,
        "error": f"JSON解析失败(已重试{max_retries}次): {last_err}",
        "raw": raw,
        "model": _MODEL_META,
    }