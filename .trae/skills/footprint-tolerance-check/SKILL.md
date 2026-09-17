---

name: footprint-tolerance-check
description: >
  Checks PCB footprint pad parameters against datasheet land pattern specifications.
  Compares theoretical pad dimensions extracted from PDF datasheets with actual pad
  parameters read from Allegro .dra files. Covers 6 major categories of checks:
  naming convention, pad dimensions, spacing & origin, pin number, place-bound,
  assembly/silkscreen. Use when the user asks to verify footprint correctness,
  check pad dimensions, compare datasheet vs Allegro, or validate land pattern.
license: MIT
compatibility: >
  Requires Python 3.10+, fastmcp, skillbridge, PyMuPDF, pdfplumber, and the
  layout-check-v2 MCP server. Vision extraction is performed by the client LLM.
metadata:
  author: layout-team
  version: "2.0.0"
  category: hardware-layout
requires-mcp-servers:
  - name: layout-check-v2
    package: "local"
    description: >
      Local MCP server exposing footprint checking tools.
    command: python
    args:
      - "-m"
      - "mcp_server.server"
    env:
      PYTHONPATH: "{{PROJECT_ROOT}}"
    parameters:
      PROJECT_ROOT:
        description: "Absolute path to the project root"
        required: true
        default: "."

---

# Footprint Tolerance Check

检查 PCB 封装是否符合设计规范（datasheet 与 Allegro 封装是否一致）。

## 触发条件

当用户提到以下意图时启用：

- “检查封装”、“验证 footprint”、“对比 datasheet 和 Allegro”
- “焊盘尺寸对不对”、“land pattern 公差”
- 给出一个封装文件夹路径，要求检查

## 核心原则

**数值由 MCP 计算，语义由 AI 判断。**

| 类型 | 谁负责 | 覆盖范围 |
|---|---|---|
| **数值** | MCP（Python） | 焊盘尺寸、pitch、间距、原点、外框尺寸、重叠检测 |
| **语义** | AI | 命名含义、pin 功能对应、极性标识识别、元件类型判断 |

**分界线**：凡是能用数字精确算的，交给 MCP；凡是需要"看懂图纸"的，交给 AI。

## 前置条件

1. **MCP 服务器**：`layout-check-v2` 已连接。
2. **目标文件夹**：包含 PDF 规格书、`.dra` 封装、可选的 `.pad`。
3. **路径要求**：**封装文件夹路径里不能有中文**。Allegro 不支持非 ASCII 路径。

## 工作模式判定

**第一步：判断用户给的是单封装还是批量。**

1. 调用 `list_folder_files(folder_path="<用户给的路径>")`。
2. 如果 `pdf` 或 `dra_files` 有内容 → **模式 A（单封装）**。
3. 如果都为空但文件夹下有子文件夹 → **模式 B（批量）**。
4. 无法判断 → 直接问用户。

---

## 模式 A：单封装检查

按下方“单封装工作流程”执行。

## 模式 B：批量检查

批量任务分 4 阶段：**侦察 → 规划 → 执行 → 汇总**。

### B0. 侦察
调用 `list_subfolders(parent_path)` 列出所有子文件夹，对每个子文件夹调用 `list_folder_files` 记录 PDF/.dra/.pad 情况。输出侦察清单（哪些可检查、哪些跳过）。

### B1. 规划
根据可检查封装数分批：

| 封装数 | 策略 |
|---|---|
| 1~3 | 一次性完成 |
| 4~8 | 一次性完成，每个封装独立报告 |
| 9~15 | 分 2~3 批，每批 5 个，批间暂停等用户确认 |
| 16+ | 必须分批，每批 5 个 |

### B2. 执行
- 维护进度表（✅ 完成 / ⏳ 进行中 / ⏸️ 待处理 / ❌ 失败）
- 每个封装完成后**立即输出报告**，不要攒到最后
- 失败不阻断：记录原因，继续下一个
- **每完成 5 个主动汇报进度**

### B3. 汇总
所有封装完成后，输出：
- 结论分布表（PASS / FAIL / REVIEW_REQUIRED / FAILED / SKIPPED）
- 失败明细
- 跳过项及原因
- 建议下一步

---

## 单封装工作流程

### 第 1 步：列出文件夹内容

调用 `list_folder_files(folder_path="<封装文件夹>")`。

从返回里提取：
- `pdf`：PDF 完整路径
- `pdf_stem`：PDF 文件名去掉 `.pdf`
- `dra_files`：所有 .dra
- `pad_files`：所有 .pad

如果 `pdf` 为 null 或 `dra_files` 为空，报告并停止。

### 第 2 步：定位 land pattern 页

调用 `locate_land_pattern_page(pdf_file_path="<pdf>")`。

根据 `method` 决定：
- `primary` / `fallback` → 使用返回的 `page`
- `no_match` → 尝试渲染所有页自己找；找不到就报告，用第 1 页兜底

### 第 3 步：AI 读图提取 datasheet 理论参数

1. 读 resource `datasheet://<pdf_stem>/page/<page>` 拿到 PDF 该页图片
2. 按下方"提取规则"读图，输出 JSON
3. 调用 `validate_land_pattern_json` 校验
4. 校验通过 → 包装成 `{"theoretical_land_params": <normalized>}`
5. 校验失败 → 根据 errors 修正后重试，最多 2 次

#### 提取规则

- 图片可能旋转 90 度，先在心里旋转再读数
- 只读 **land pattern / recommended pad / 推荐焊盘** 区域，不读器件外形尺寸
- 区分"器件尺寸"（3.2×2.5 是器件本体）和"焊盘尺寸"（1.4×1.2 是铜箔）——**只要焊盘尺寸**
- pin 号必须是整数，不要输出 "1" 或 1.0
- 单位统一 mm；mil 换算：1 mil = 0.0254 mm
- spacing_x / spacing_y 是焊盘中心间距，无标注填 null
- 数值合理性自检：单个焊盘通常 0.2~5mm；小于 0.1 或大于 10 肯定误读
- 图纸模糊 → note 里说明，不编造

#### 公差提取规则

- 图纸写 `0.30±0.03` → tolerance = `{"min": -0.03, "max": 0.03}`
- 图纸写 `0.30 +0.03/-0.01` → tolerance = `{"min": -0.01, "max": 0.03}`
- 图纸只写名义值（如 `1.4`）→ 该维度 tolerance 填 null
- 公差区域模糊 → 填 null，note 里说明
- **图纸没标公差 ≠ 数据不可用**，正常提取名义值

#### 输出格式

输出严格 JSON：

    {
      "unit": "mm",
      "pads": [{"pin": 1, "width": 1.4, "height": 1.2}],
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

### 第 4 步：跑 .dra 数值规则检查（MCP 负责）

调用 `check_footprint_by_rules`：

- `dra_file_path` = `<dra>`
- `theoretical_payload` = 第 3 步的返回
- `pad_file_paths` = `<pads>`

返回 17 项数值检查结果，覆盖 6 大项里的**可量化部分**：

| 大项 | 数值检查内容 |
|---|---|
| 1. 命名规范 | 前缀、小数点、数字 |
| 2. 焊盘尺寸 | 与 padstack 命名一致性、阻焊外扩、钢网等大 |
| 3. 间距与原点 | pin pitch、最小间距、原点居中 |
| 5. Place_Bound | 存在、覆盖焊盘、外扩量 |
| 6. Assembly / Silkscreen | 存在、1 脚标识、不与焊盘重叠 |

**这一步骤返回的 `footprint_data` 字段包含 `.dra` 的原始数据**，第 5 步需要用到。

### 第 5 步：AI 语义检查（AI 负责）

数值做不了的语义判断，由 AI 做。**分 3 个子步骤**。

#### 5.1 命名规范语义检查

**任务**：检查封装名字是否符合规范，并与 datasheet 对比。

**输入**：
- 封装名字：`footprint_data.symbol_name`
- datasheet 图片：`datasheet://<pdf_stem>/page/<page>`

**检查项**：

1. **类型对比**：名字里的封装类型标识（如 SOD-323、QFN48、HDMI19、FPC10）与 datasheet 实际类型是否一致？
2. **引脚数对比**：名字里的数字是否包含 datasheet 的引脚数？
3. **尺寸对比**：名字里的尺寸（如 2D7X1D4X0D75 = 2.7×1.4×0.75 mm）与 datasheet 外形尺寸是否一致？
4. **pitch 对比**：名字里的 pitch（如 0D5 = 0.5mm）与 datasheet 是否一致？

**输出 JSON**：

    {
      "type_match": true,
      "pin_count_match": true,
      "dimension_match": true,
      "pitch_match": true,
      "parsed_name": {
        "prefix": "nb_",
        "type": "SOD-323",
        "pin_count": 2,
        "dimensions": [2.7, 1.4, 0.75],
        "pitch": null,
        "special": null
      },
      "datasheet_actual": {
        "type": "SOD-323",
        "pin_count": 2,
        "dimensions": [2.7, 1.4, 0.75],
        "pitch": null
      },
      "issues": [],
      "note": ""
    }

**注意**：datasheet 没写的字段填 null，issues 里说明"datasheet 未提供"。

#### 5.2 pin number 语义检查

**任务**：对比 datasheet 的 pin 定义和 `.dra` 里的 pin 列表。

**输入**：
- datasheet 图片：`datasheet://<pdf_stem>/page/<page>`
- `.dra` 的 pins：`footprint_data.pins`（JSON 字符串）

**检查项**：

1. **pin 数量**：datasheet 声明的 pin 数与 `.dra` 是否一致？
2. **pin 编号**：每个 pin 编号是否一致？缺号/重号/多余？
3. **pin 功能**：如果 datasheet 有 pin function 表（GND/VCC/NC/IO 等），顺序是否对应正确？

**输出 JSON**：

    {
      "dra_pin_count": 2,
      "datasheet_pin_count": 2,
      "count_match": true,
      "pin_numbers_match": true,
      "missing_pins": [],
      "extra_pins": [],
      "renumbered_pins": [],
      "function_mismatches": [],
      "issues": [],
      "note": ""
    }

#### 5.3 极性标识检查

**任务**：检查 Assembly / Silkscreen 层的 1 脚标识和极性标识。

**输入**：
- datasheet 图片：`datasheet://<pdf_stem>/page/<page>`
- Assembly / Silkscreen 层元素：`footprint_data.layers`（JSON 字符串）

**检查项**：

1. **1 脚标识**：Assembly 和 Silkscreen 是否都有？（三角形、圆圈、斜杠、数字 "1" 等）
2. **极性标识**（有极性元件：二极管、电解电容、IC）：
   - 二极管：竖线端为负极（K），或有 +/- 标识
   - 电解电容：+ 号标识
   - IC：pin 1 标识足够
3. **层一致性**：Assembly 和 Silkscreen 的标识方向一致吗？

**输出 JSON**：

    {
      "pin1_marker": {
        "assembly": true,
        "silkscreen": true,
        "evidence": "Assembly 层有三角形 1 脚标识"
      },
      "polarity_marker": {
        "required": false,
        "assembly": null,
        "silkscreen": null,
        "evidence": ""
      },
      "issues": [],
      "note": ""
    }

**注意**：
- datasheet 显示是无极性元件（电阻、普通电容）→ `polarity_marker.required = false`
- datasheet 显示有极性元件但 `.dra` 没标识 → issues 里说明

### 第 6 步：合并报告

把数值检查（17 项）和语义检查（3 组）合并。

**结论优先级**：

| 情况 | 结论 |
|---|---|
| 任一 FAIL | **FAIL** |
| 有 NA | **REVIEW_REQUIRED** |
| 只有 WARN | **PASS**（附警告） |
| 全 PASS | **PASS** |

**关键规则**：
- **数值检查的结论优先信 Python**——AI 不要凭感觉推翻
- **AI 语义检查和 Python 结果冲突时，以 Python 为准**
- **不要编造数据**——datasheet 里没有的信息如实说"未提供"

### 第 7 步：保存 JSON 报告

调用 `save_checklist_report`：

- `checklist_result` = 第 6 步合并后的结果
- `dra_file_path` = `<dra>`
- `output_dir` 不传（自动写到 `.dra` 所在目录）

返回后，在报告里注明"已保存报告到 `<path>`"。

---

## 报告格式

### 单封装报告

    ## 封装检查报告

    **封装：** <symbol_name>
    **路径：** <dra 完整路径>
    **元件类型：** IC / chip / connector / unknown

    ### 1. 封装命名规范

    - [PASS] 前缀 NB_
    - [WARN] 前缀大小写（实际 nb_，规范要求 NB_）
    - [PASS] 小数点用 d 代替
    - [PASS] 类型与 datasheet 一致（SOD-323）

    ### 2. 焊盘尺寸

    - [PASS] 焊盘尺寸与命名一致性（±0.05mm）
    - [PASS] 阻焊开窗外扩 0.05mm
    - [PASS] 钢网与焊盘等大

    ### 3. 间距与原点

    - [PASS] pin pitch = 1.9mm
    - [PASS] 焊盘不重叠
    - [FAIL] 原点偏移 0.3mm（中心 = [-0.3, 0]）

    ### 4. pin number

    - [PASS] pin 数量一致（2 个）
    - [PASS] pin 编号一致

    ### 5. Place_Bound

    - [PASS] 存在
    - [PASS] 覆盖所有焊盘
    - [WARN] 外扩量 x=2.465, y=2.11（超出 [0.5, 2.5]）

    ### 6. Assembly 和 Silkscreen

    - [PASS] Assembly 存在（7 个元素）
    - [PASS] Silkscreen 存在（7 个元素）
    - [PASS] 1 脚标识齐全
    - [PASS] 不与焊盘重叠

    ### 汇总

    - 数值检查：17 项（15 PASS / 1 FAIL / 1 WARN）
    - 语义检查：3 组（2 PASS / 1 WARN）
    - **结论：FAIL**
    - 主要问题：原点偏移 0.3mm

    ### 人工复核提醒

    AI 视觉识别结果必须对照 PDF 原始图纸复核。

    ### 报告文件

    已保存报告到 `<path>`

---

## 注意事项

- **数值 vs 语义分工清楚**：数值问题让 Python 判定，语义问题让 AI 判断
- **不要给没看到 ± 的尺寸编造公差**
- **单位统一 mm**
- **spacing 为 null 时不参与比对**（NA，不算 FAIL）
- **不要编造数据**：任何一步失败如实报告
  - **MCP tool 返回 error 时，必须停止当前封装的检查，明确报告错误信息，不得继续输出报告**
  - **不得根据理论值、公差、经验推断"实测值"**
  - **不得用"推算"、"大概"、"应该"等词语生成任何数据**
  - **只能报告 MCP tool 实际返回的值**
  - 如果某个 tool 挂了，如实说明"该步骤未执行"，不补充任何数据
- **批量任务中每个封装独立报告**，不要交叉引用其他封装的细节
- **不要无限重试**：同一操作失败 2 次就跳过
- **路径含中文时提醒用户**：Allegro 不支持非 ASCII 路径，封装文件应放在英文路径下

## 依赖的 MCP 工具一览

| Tool | 用途 | 关键参数 |
|---|---|---|
| `list_subfolders` | 列出父文件夹的子文件夹 | `parent_path` |
| `list_folder_files` | 列出 PDF / .dra / .pad | `folder_path` |
| `locate_land_pattern_page` | 定位 land pattern 页 | `pdf_file_path` |
| `read_allegro_footprint` | 简化版：只读焊盘 | `dra_file_path` |
| `read_full_footprint` | 全量提取 .dra 数据 | `dra_file_path` |
| `check_footprint_by_rules` | 跑 6 大项数值规则检查 | `dra_file_path`, `theoretical_payload` |
| `validate_land_pattern_json` | 校验 AI 输出的 JSON | `raw_json` |
| `check_land_pattern_tolerance` | 焊盘公差比对（旧版） | `theoretical_payload`, `actual_payload` |
| `save_tolerance_report` | 保存焊盘公差报告 | `comparison_result` |
| `save_checklist_report` | 保存 6 大项清单报告 | `checklist_result` |

## 依赖的 MCP 资源一览

| Resource URI | 用途 |
|---|---|
| `datasheet://{pdf_stem}/page/{page}` | PDF 整页图片（PyMuPDF PNG） |
| `datasheet://{pdf_stem}/info` | PDF 元信息（JSON 字符串） |

## 依赖的 MCP 提示一览

| Prompt | 用途 |
|---|---|
| `extract_land_pattern` | 单页 datasheet 提取参数 |
| `check_naming_semantic` | 命名规范语义检查 |
| `check_pin_number_semantic` | pin number 对照检查 |
| `check_polarity_marker` | 极性标识检查 |
| `full_footprint_check` | 端到端流程 SOP |

**注意**：如果你的客户端（如 Trae）不支持调用 MCP prompt，直接按本文档"第 5 步"里的语义检查内容执行即可，无需调用 prompt。

---

## 客户端配置示例

    {
      "mcpServers": {
        "layout-check-v2": {
          "command": "python",
          "args": ["-m", "mcp_server.server"],
          "cwd": "C:\\path\\to\\project_root",
          "env": {
            "PYTHONPATH": "C:\\path\\to\\project_root"
          }
        }
      }
    }

