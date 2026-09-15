---

name: footprint-tolerance-check
description: >
  Checks PCB footprint pad parameters against datasheet land pattern specifications.
  Compares theoretical pad dimensions extracted from PDF datasheets with actual pad
  parameters read from Allegro .dra files, using configurable tolerance thresholds.
  Use when the user asks to verify footprint correctness, check pad dimensions,
  compare datasheet vs Allegro, or validate land pattern tolerance for a given
  footprint folder.
license: MIT
compatibility: >
  Requires Python 3.10+, fastmcp, skillbridge, PyMuPDF, pdfplumber, moondream2
  (for local vision extraction), and the layout-check-v2 MCP server running in
  the same Python environment as this skill.
metadata:
  author: layout-team
  version: "1.1.0"
  category: hardware-layout
requires-mcp-servers:
  - name: layout-check-v2
    package: "local"
    description: >
      Local MCP server exposing footprint tolerance checking tools
      (list_folder_files, locate_land_pattern_page, parse_datasheet_land_pattern,
      read_allegro_footprint, validate_land_pattern_json, check_land_pattern_tolerance).
    command: python
    args:
      - "-m"
      - "mcp_server.server"
    env:
      PYTHONPATH: "{{PROJECT_ROOT}}"
    parameters:
      PROJECT_ROOT:
        description: "Absolute path to the project root containing mcp_server/, services/, shared/ and lib_*.py"
        required: true
        default: "."

---

# Footprint Tolerance Check

检查 PCB 封装焊盘参数是否与 datasheet 规格书一致。

## 触发条件

当用户提到以下意图时启用本 Skill：

- “检查封装”、“验证 footprint”、“对比 datasheet 和 Allegro”
- “焊盘尺寸对不对”、“land pattern 公差”
- “帮我看看这个封装文件夹”

## 前置条件

1. **MCP 服务器**：确保 `layout-check-v2` 已配置到客户端（Claude Desktop / Cursor 等）。配置方式见本文件末尾“客户端配置示例”。
2. **目标文件夹结构**：里面应包含：
   - 至少一个 PDF 规格书
   - 至少一个 `.dra` 封装文件（AUTOSAVE 会被自动排除）
   - 可选的 `.pad` 文件
3. **Python 环境**：已安装 `fastmcp`、`skillbridge`、`PyMuPDF`、`pdfplumber`，moondream2 模型可用（路径 A 需要）。

## 工作流程

### 第 1 步：列出文件夹内容

调用 tool `list_folder_files`，参数为 `folder_path="<目标文件夹>"`。

确认 PDF 和 `.dra` 都存在。如果任一缺失，报告用户并停止。

返回字段说明：
- `pdf`：找到的第一个 PDF 绝对路径，或 null
- `dra_files`：所有 .dra 绝对路径（已排除 AUTOSAVE）
- `pad_files`：所有 .pad 绝对路径

### 第 2 步：定位 land pattern 页

调用 tool `locate_land_pattern_page`，参数为 `pdf_file_path="<pdf>"`。

根据返回的 `method` 决定下一步：

| method | 含义 | 行动 |
|---|---|---|
| `primary` | 强关键词命中 | 直接使用返回的 `page` |
| `fallback` | 弱关键词兜底 | 使用 `page`，但提醒用户“这是兜底匹配，建议人工确认页码” |
| `no_match` | 未找到 | 询问用户是否手动指定页码，或跳过 PDF 解析 |

### 第 3 步：提取理论焊盘参数（二选一）

**路径 A：moondream2 引擎（推荐先试）**

调用 tool `parse_datasheet_land_pattern`，参数为：

- `pdf_file_path="<pdf>"`
- `target_page=<page>`
- `render_engine="pymupdf"`（默认）

如果返回 `error`，改用 `render_engine="marker"` 重试一次。

**路径 B：AI 自己读图提取（路径 A 失败时启用）**

1. 读 resource：`datasheet://<pdf_stem>/page/<page>`
2. 应用 prompt `extract_land_pattern`，参数 `pdf_stem="<stem>"`、`page=<page>`
3. 得到你（AI）自己输出的 JSON 后，调用 tool `validate_land_pattern_json`，参数 `raw_json="<你的JSON输出>"`
4. 如果 `valid=false`，根据 `errors` 修正后重试，最多 2 次
5. 用返回的 `normalized` 字段包装成 `{"theoretical_land_params": <normalized>}`

注意：路径 B 消耗更多 token，但更灵活。路径 A 免费、快，但依赖本地 moondream2 模型。

### 第 4 步：读取实际封装参数

对文件夹里每个 `.dra`（已排除 AUTOSAVE）：

调用 tool `read_allegro_footprint`，参数为：

- `dra_file_path="<dra路径>"`
- `pad_file_paths=["<pad1>", "<pad2>", ...]`（可省略）

如果某个 `.dra` 返回 `error`，记录并跳过，继续处理下一个。

### 第 5 步：公差比对

对每个 `.dra`：

调用 tool `check_land_pattern_tolerance`，参数为：

- `theoretical_payload=<第3步的返回>`
- `actual_payload=<第4步的返回>`
- `tolerance` 不传，使用默认值

默认公差：
- `width`：±0.1 mm
- `height`：±0.1 mm
- `spacing_x`：±0.15 mm
- `spacing_y`：±0.15 mm

### 第 6 步：汇总报告

输出格式建议：

    ## 封装检查报告

    文件夹：<folder>

    ### 结果汇总

    | .dra 文件 | 结论 | PASS | FAIL | NA |
    |---|---|---|---|---|
    | <name> | PASS/FAIL/REVIEW | n | n | n |

    ### 失败明细（如有）

    | pin | 维度 | 理论值(mm) | 实际值(mm) | delta(mm) | 公差范围 |
    |---|---|---|---|---|---|
    | 1 | width | 0.30 | 0.45 | +0.15 | [-0.10, +0.10] |

    ### 人工复核提醒

    AI 视觉识别结果必须人工对照 PDF 原始图纸复核，不可直接无条件信任。

结论取值：
- `PASS`：全部比对通过
- `FAIL`：至少一个维度超出公差
- `REVIEW_REQUIRED`：存在 NA 项，需人工确认

## 注意事项

- **AI 提取的数值必须人工复核**。moondream2 和客户端 AI 都可能读错数字。
- **单位统一为 mm**。如果图中标注 mil，工具会自动换算，但建议在报告中注明原始单位。
- **spacing 为 null 时不参与比对**。工具会将其标记为 `NA`，不会导致 FAIL。
- **某个 `.dra` 读取失败时不要中止整个流程**，记录错误后继续处理其他 `.dra`。
- **不要编造数据**。任何一步失败，如实报告错误，让用户决定下一步。
- **PDF 引用支持三种形式**：完整路径、文件名、stem。如果 PDF 名含空格或中文，优先传完整路径。

## 依赖的 MCP 工具一览

| Tool | 用途 | 关键参数 |
|---|---|---|
| `list_folder_files` | 列出 PDF / .dra / .pad | `folder_path` |
| `locate_land_pattern_page` | 定位 land pattern 页 | `pdf_file_path` |
| `parse_datasheet_land_pattern` | moondream2 提取理论参数 | `pdf_file_path`, `target_page`, `render_engine` |
| `read_allegro_footprint` | SkillBridge 读取实际参数 | `dra_file_path`, `pad_file_paths` |
| `validate_land_pattern_json` | 校验 AI 输出的 JSON | `raw_json` |
| `check_land_pattern_tolerance` | 公差比对 | `theoretical_payload`, `actual_payload`, `tolerance` |

## 依赖的 MCP 资源一览

| Resource URI | 用途 |
|---|---|
| `datasheet://{pdf_stem}/page/{page}` | PDF 整页图片（PyMuPDF 渲染，PNG） |
| `datasheet://{pdf_stem}/marker/page/{page}` | PDF marker 版面分析图（JPEG） |
| `datasheet://{pdf_stem}/info` | PDF 元信息（JSON 字符串） |

## 依赖的 MCP 提示一览

| Prompt | 用途 |
|---|---|
| `extract_land_pattern` | 指导 AI 从图片提取参数 |
| `full_footprint_check` | 端到端流程 SOP |

## 客户端配置示例

把下面这段加入 Claude Desktop 或 Cursor 的 MCP 配置文件中：

    {
      "mcpServers": {
        "layout-check-v2": {
          "command": "python",
          "args": ["-m", "mcp_server.server"],
          "cwd": "C:\\Users\\ds245\\Documents\\Project_Layout",
          "env": {
            "PYTHONPATH": "C:\\Users\\ds245\\Documents\\Project_Layout"
          }
        }
      }
    }

字段说明：
- `cwd`：项目根目录，必须包含 `mcp_server/`、`services/`、`shared/` 和 `lib_*.py`
- `env.PYTHONPATH`：确保 `python -m mcp_server.server` 能找到包
- 如果你的 Python 不在系统 PATH 中，把 `command` 换成 python.exe 的绝对路径

---