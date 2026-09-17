# -*- coding: utf-8 -*-
"""
mcp_server/server.py —— MCP 服务入口

启动方式：
    python -m mcp_server.server

说明：
  - cwd 必须设置为项目根目录，这样 `-m mcp_server.server` 才能找到包。
  - 所有路径配置见 mcp_server/config.py。
  - 本文件在注册 tool 前，用装饰器包装 mcp.tool()，
    每次 tool 调用后把耗时写入 mcp_timing.log。
    计时是纯附加功能，不影响 tool 返回值，也不影响 AI 行为。
"""
from __future__ import annotations

import functools
import logging
import time
from pathlib import Path

from fastmcp import FastMCP

# 项目根（用于放日志文件）
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ------------------------------------------------------------
# 计时日志：单独走一个 logger，输出到文件
#   - 用 FileHandler，不 print，不污染 MCP 的 stdio 协议通道
#   - propagate=False，避免往 root logger 冒泡
# ------------------------------------------------------------
_timing_logger = logging.getLogger("layout-check-mcp-timing")
_timing_logger.setLevel(logging.INFO)
_timing_logger.propagate = False
if not _timing_logger.handlers:
    _handler = logging.FileHandler(
        PROJECT_ROOT / "mcp_timing.log",
        encoding="utf-8",
    )
    _handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    _timing_logger.addHandler(_handler)


# 创建 MCP 实例
mcp = FastMCP("layout-check-mcp-v2")


# ============================================================
# 包装 mcp.tool() 装饰器：为每个 tool 加上耗时记录
# ============================================================
def _install_timing_decorator() -> bool:
    """
    把 mcp.tool 替换为带计时的版本。

    装饰顺序：
      原始调用：  @mcp.tool()  →  函数
      包装后：    @mcp.tool()  →  _timed_wrapper  →  原函数
      _timed_wrapper 内部计时，调用真正的函数。

    返回 True 表示安装成功；False 表示 FastMCP 版本不兼容，
    此时退化为无计时（服务仍能正常启动）。
    """
    try:
        _original_tool = mcp.tool
    except AttributeError:
        return False

    def _timed_tool(*args, **kwargs):
        # 先拿到原始装饰器（处理 @mcp.tool() 和 @mcp.tool 两种写法）
        decorator = _original_tool(*args, **kwargs)

        def wrap(fn):
            @functools.wraps(fn)
            def timed(*a, **kw):
                t0 = time.perf_counter()
                err = None
                try:
                    return fn(*a, **kw)
                except Exception as e:
                    err = e
                    raise
                finally:
                    dt_ms = (time.perf_counter() - t0) * 1000
                    flag = " [ERR]" if err else ""
                    _timing_logger.info(f"{fn.__name__} {dt_ms:.0f}ms{flag}")

            return decorator(timed)

        return wrap

    try:
        mcp.tool = _timed_tool
        return True
    except Exception:
        return False


_timing_ok = _install_timing_decorator()


# 注册 tool / resource / prompt
# 注意：注册函数接收 mcp 作为参数，避免模块间循环导入。
from mcp_server.tools import register as register_tools
from mcp_server.resources import register as register_resources
from mcp_server.prompts import register as register_prompts

register_tools(mcp)
register_resources(mcp)
register_prompts(mcp)


def main():
    # 计时安装失败也不阻断服务，只记一行日志
    if not _timing_ok:
        _timing_logger.info("[WARN] timing decorator not installed; "
                            "tool timings will not be recorded")
    mcp.run()


if __name__ == "__main__":
    main()