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
  Requires Python 3.10+, fastmcp, skillbridge, PyMuPDF, pdfplumber, and the
  layout-check-v2 MCP server running in the same Python environment as this skill.
  The vision extraction is performed by the client LLM itself (no local vision
  model dependency). moondream2 is optional and only used as fallback.
metadata:
  author: layout-team
  version: "1.2.0"
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

## 核心原则

**理论参数由你自己（客户端 LLM）从图纸中读取，不依赖本地 moondream2 模型。**

理由：moondream2 是参数量很小的本地视觉模型，在复杂工程图纸上误读率较高（例如把标注线、外框误认为焊盘尺寸）。你的多模态视觉能力远强于它，因此默认由你亲自读图。

## 前置条件

1. **MCP 服务器**：确保 `layout-check-v2` 已连接。
2. **目标文件夹结构**：里面应包含：
   - 至少一个 PDF 规格书
   - 至少一个 `.dra` 封装文件（AUTOSAVE 会被自动排除）
   - 可选的 `.pad` 文件
3. **环境**：Python 环境已安装 `fastmcp`、`skillbridge`、`PyMuPDF`、`pdfplumber`。

## 工作流程

### 第 1 步：列出文件夹内容

调用 tool `list_folder_files`，参数为 `folder_path="<目标文件夹>"`。

从返回结果中提取：
- `pdf`：PDF 的完整绝对路径
- `pdf_stem`：PDF 文件名去掉 `.pdf` 后缀，**后续 resource URI 要用到它**
- `dra_files`：所有 .dra 绝对路径
- `pad_files`：所有 .pad 绝对路径

如果 `pdf` 为 null 或 `dra_files` 为空，报告用户并停止。

示例：如果 `pdf` 是 `C:\...\3S48000163产品规格书_20220916_S1.pdf`，
那么 `pdf_stem` 是 `3S48000163产品规格书_20220916_S1`。

### 第 2 步：定位 land pattern 页

调用 tool `locate_land_pattern_page`，参数为 `pdf_file_path="<pdf>"`。

根据返回的 `method` 决定下一步：

| method | 含义 | 行动 |
|---|---|---|
| `primary` | 强关键词命中 | 直接使用返回的 `page` |
| `fallback` | 弱关键词兜底 | 使用 `page`，但提醒用户“这是兜底匹配，建议人工确认页码” |
| `no_match` | 未找到 | 询问用户是否手动指定页码，或跳过 PDF 解析 |

### 第 3 步：你亲自读图提取理论参数

**默认路径：你自己读图。**

1. **读 resource 图片**：`datasheet://<pdf_stem>/page/<page>`
   这会返回 PDF 该页的整页 PNG 图片，你能直接看到它。

2. **按下方"提取规则"读图，输出严格 JSON**。

3. **调用 tool `validate_land_pattern_json`**，参数为 `raw_json="<你刚输出的JSON字符串>"`。
   - 如果返回 `valid=true`，取 `normalized` 字段，包装成 `{"theoretical_land_params": <normalized>}`，进入第 4 步。
   - 如果返回 `valid=false`，根据 `errors` 修正后重试，**最多 2 次**。
   - 如果连续失败，进入"兜底路径"。

4. **兜底路径（仅在你自己读图连续失败时启用）**：
   - 调用 tool `parse_datasheet_land_pattern(pdf_file_path="<pdf>", target_page=<page>, render_engine="marker")`。
   - 这是本地 moondream2 引擎，精度较低，只作为最后手段。
   - 拿到结果后同样调 `validate_land_pattern_json` 校验。

#### 提取规则

- **图片可能旋转 90 度**。请先在心里旋转，确认图纸方向后再读数。
- **只读 land pattern / recommended pad / 推荐焊盘区域**，不要读器件外形尺寸（如 3.2×2.5mm）。
- **区分"器件尺寸"和"焊盘尺寸"**：
  - 器件尺寸是元件本体的长宽，通常标注在器件俯视/侧视图上。
  - 焊盘尺寸是 PCB 上要画的铜箔尺寸，通常标注在 LAND PATTERN 区域。
  - **你只要焊盘尺寸**。
- **pin 号必须是整数**，不要输出 "1" 或 1.0。
- **单位统一为 mm**。如果图中标注 mil，换算：1 mil = 0.0254 mm。
- **spacing_x / spacing_y** 是相邻焊盘中心的间距，不是焊盘外边缘间距。若图中无明确标注，填 null，不要猜测。
- **数值合理性检查**：
  - 单个焊盘尺寸通常在 0.2 ~ 5 mm 之间。如果读出的值小于 0.1 mm 或大于 10 mm，几乎肯定是误读，重新看图。
  - 中心间距应大于等于焊盘尺寸，且通常与器件尺寸同量级。
- **如果图纸模糊或无法识别，在 note 字段说明**，不要编造数值。
- **tolerance 字段的默认规则**：
  - `tolerance` 里任一维度为 `null` 时，后续比对会在该维度使用默认公差（width/height ±0.1，spacing ±0.15）。
  - `tolerance` 整体也可以为 `null`，表示所有维度都用默认公差。
  - **不要给没看到 ± 的尺寸编造公差。** 没看到就填 null，让下游走默认。

#### 输出格式

输出严格 JSON，不要额外解释：

    {
      "unit": "mm",
      "pads": [
        {"pin": 1, "width": 0.9, "height": 1.3},
        {"pin": 2, "width": 0.9, "height": 1.3}
      ],
      "spacing_x": 2.2,
      "spacing_y": 1.7,
      "tolerance": {
        "width":     {"min": -0.03, "max": 0.03},
        "height":    {"min": -0.03, "max": 0.03},
        "spacing_x": {"min": -0.05, "max": 0.05},
        "spacing_y": null
      },
      "note": ""
    }

### 第 4 步：读取实际封装参数

对文件夹里每个 `.dra`：

调用 tool `read_allegro_footprint`，参数为：

- `dra_file_path="<dra路径>"`
- `pad_file_paths=["<pad1>", "<pad2>", ...]`（可省略）

如果某个 `.dra` 返回 `error`，记录并跳过，继续处理下一个。

### 第 5 步：公差比对

对每个 `.dra`：

调用 tool `check_land_pattern_tolerance`，参数为：

- `theoretical_payload=<第3步的返回，形如 {"theoretical_land_params": {...}}>`
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

    ### 数据来源

    - PDF 规格书：<pdf_name>（第 <page> 页，method=<method>）
    - 理论值提取方式：客户端 LLM 读图 / moondream2 兜底
    - Allegro 封装：<dra_name>

    ### 结果汇总

    | .dra 文件 | 结论 | PASS | FAIL | NA |
    |---|---|---|---|---|
    | <name> | PASS/FAIL/REVIEW | n | n | n |

    ### 失败明细（如有）

    | pin | 维度 | 理论值(mm) | 实际值(mm) | delta(mm) | 公差范围 |
    |---|---|---|---|---|---|
    | 1 | width | 0.90 | 0.95 | +0.05 | [-0.10, +0.10] |

    ### 人工复核提醒

    理论值由 AI 读图提取，建议人工对照 PDF 原始图纸快速复核。

结论取值：
- `PASS`：全部比对通过
- `FAIL`：至少一个维度超出公差
- `REVIEW_REQUIRED`：存在 NA 项，需人工确认

## 注意事项

- **优先相信你自己的读图结果**，moondream2 只作兜底。
- **不要跳过 `validate_land_pattern_json`**。它是防格式漂移的守门员。
- **数值合理性自检**：提取完 JSON 后，先自己快速判断一次（0.2~5mm 量级、间距≥焊盘尺寸），发现异常就重新看图。
- **单位统一为 mm**。mil 要换算。
- **spacing 为 null 时不参与比对**，工具会标记为 `NA`，不会导致 FAIL。
- **某个 `.dra` 读取失败时不要中止整个流程**，记录错误后继续。
- **不要编造数据**。任何一步失败，如实报告错误，让用户决定下一步。
- **resource URI 里的中文/空格**：如果 PDF 名含中文或空格，resource 读取可能失败。此时可直接向用户报告，并回退到 `parse_datasheet_land_pattern` 兜底。

## 依赖的 MCP 工具一览

| Tool | 用途 | 关键参数 |
|---|---|---|
| `list_folder_files` | 列出 PDF / .dra / .pad | `folder_path` |
| `locate_land_pattern_page` | 定位 land pattern 页 | `pdf_file_path` |
| `read_allegro_footprint` | SkillBridge 读取实际参数 | `dra_file_path`, `pad_file_paths` |
| `validate_land_pattern_json` | 校验 AI 输出的 JSON | `raw_json` |
| `check_land_pattern_tolerance` | 公差比对 | `theoretical_payload`, `actual_payload`, `tolerance` |
| `parse_datasheet_land_pattern` | moondream2 兜底引擎（非默认） | `pdf_file_path`, `target_page`, `render_engine` |

## 依赖的 MCP 资源一览

| Resource URI | 用途 |
|---|---|
| `datasheet://{pdf_stem}/page/{page}` | PDF 整页图片（PyMuPDF 渲染，PNG），**主路径依赖** |
| `datasheet://{pdf_stem}/marker/page/{page}` | PDF marker 版面分析图（JPEG），备用 |
| `datasheet://{pdf_stem}/info` | PDF 元信息（JSON 字符串） |

## 依赖的 MCP 提示一览

| Prompt | 用途 |
|---|---|
| `extract_land_pattern` | 单页提取提示模板 |
| `full_footprint_check` | 端到端流程 SOP |

## 客户端配置示例

把下面这段加入 Claude Desktop 或 Cursor 的 MCP 配置文件中：

    {
      "mcpServers": {
        "layout-check-v2": {
          "command": "C:\\Users\\<用户名>\\.conda\\envs\\env_marker\\python.exe",
          "args": ["-m", "mcp_server.server"],
          "cwd": "C:\\Users\\<用户名>\\Documents\\Project_Layout",
          "env": {
            "PYTHONPATH": "C:\\Users\\<用户名>\\Documents\\Project_Layout"
          }
        }
      }
    }

字段说明：
- `command`：必须指向安装了 `fastmcp`、`skillbridge`、`PyMuPDF` 的 Python 解释器绝对路径。用 `where python` 在你激活的环境里查。
- `cwd`：项目根目录，必须包含 `mcp_server/`、`services/`、`shared/` 和 `lib_*.py`。
- `env.PYTHONPATH`：确保 `python -m mcp_server.server` 能找到包。

