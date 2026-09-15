---

name: footprint-tolerance-check
description: >
  Checks PCB footprint pad parameters against datasheet land pattern specifications.
  Supports both single-footprint and batch mode (multiple footprints in a parent folder).
  Use when the user asks to verify footprint correctness, check pad dimensions,
  compare datasheet vs Allegro, or validate land pattern tolerance. If the user
  provides a folder containing multiple footprint subfolders, use batch mode.
license: MIT
compatibility: >
  Requires Python 3.10+, fastmcp, skillbridge, PyMuPDF, pdfplumber, and the
  layout-check-v2 MCP server. Vision extraction is performed by the client LLM.
metadata:
  author: layout-team
  version: "1.3.0"
  category: hardware-layout
requires-mcp-servers:
  - name: layout-check-v2
    package: "local"
    description: >
      Local MCP server exposing footprint tolerance checking tools.
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

检查 PCB 封装焊盘参数是否与 datasheet 规格书一致。

## 触发条件

当用户提到以下意图时启用本 Skill：

- “检查封装”、“验证 footprint”、“对比 datasheet 和 Allegro”
- “焊盘尺寸对不对”、“land pattern 公差”
- 给出一个文件夹路径，要求检查里面的封装

## 核心原则

1. **理论参数由你自己从图纸中读取**，不依赖本地 moondream2。
2. **只处理用户明确指定的文件夹**，不要擅自扩大范围。
3. **单封装处理是原子操作**：定位 → 读图 → 提取 → 校验 → 读 Allegro → 比对 → 报告，一气呵成，不与其他封装交叉。
4. **每个封装独立报告**，不要攒到最后一起输出。
5. **失败不阻断**：某个封装失败时，记录原因，继续下一个，最后汇总。
6. **主动汇报进度**：批任务中每完成若干个封装主动汇报，让用户有机会接管。

## 工作模式判定

**第一步：判断用户给的是单封装还是批量。**

用户给的路径可能是：

- **单封装文件夹**：里面直接有 PDF / `.dra` / `.pad` 文件 → 走 **模式 A（单封装）**
- **批量父文件夹**：里面是多个子文件夹，每个子文件夹里才有 PDF / `.dra` / `.pad` → 走 **模式 B（批量）**

**如何判断：**

1. 调用 tool `list_folder_files(folder_path="<用户给的路径>")`。
2. 如果返回的 `pdf` 或 `dra_files` 有内容 → 单封装 → 模式 A。
3. 如果返回的 `pdf` 和 `dra_files` 都为空，但文件夹下有明显子文件夹 → 批量 → 模式 B。

如果判定不了，直接问用户："你给的路径是单个封装，还是包含多个封装的父文件夹？"

---

## 模式 A：单封装检查

按下方“单封装工作流程”执行，输出该封装的报告。

---

## 模式 B：批量检查

批量任务的核心风险是：**上下文爆炸、任务超时、AI 后半段偷懒、错误累积**。模式 B 通过“侦察 → 规划 → 分步执行 → 汇总”四个阶段规避这些问题。

### B0. 侦察阶段

**目标：先摸清有多少个封装，每个封装里有什么。**

1. 列出用户给的父文件夹下所有子文件夹。
   - 优先调用 MCP tool `list_subfolders(parent_path="<父文件夹>")`（如果存在）。
   - 如果不存在该 tool，用客户端自己的文件系统能力列目录。
2. 对每个子文件夹，调用 `list_folder_files(subfolder_path)`，记录：
   - 子文件夹名
   - 是否有 PDF
   - 有几个 `.dra`
   - 有几个 `.pad`
3. **输出一份侦察清单**：

   | # | 封装子文件夹 | PDF | .dra | .pad | 状态 |
   |---|---|---|---|---|---|
   | 1 | 3S48000163 | ✅ | 1 | 1 | 可检查 |
   | 2 | AOZ22559QI | ✅ | 1 | 0 | 可检查 |
   | 3 | CSTJ-421-1010BG | ✅ | 2 | 3 | 可检查 |
   | 4 | XXX | ❌ | 1 | 0 | ⚠️ 无 PDF，将跳过 |
   | 5 | YYY | ✅ | 0 | 0 | ⚠️ 无 .dra，将跳过 |

4. 告诉用户：**共有 N 个可检查的封装，M 个将跳过（附原因）**。

### B1. 规划阶段

**目标：根据数量决定执行策略，并告知用户。**

根据可检查封装的数量，选择策略：

| 封装数 | 策略 |
|---|---|
| 1~3 | 一次性全部完成 |
| 4~8 | 一次性全部完成，但**每完成一个立即输出报告** |
| 9~15 | 建议**分批**，每批 5 个，每批结束后暂停等用户确认 |
| 16+ | 必须分批，每批 5 个，每批结束后暂停 |

**输出规划建议**，例如：

> 共 13 个可检查封装。建议分 3 批执行：
> - 第 1 批：#1~#5
> - 第 2 批：#6~#10
> - 第 3 批：#11~#13
> 
> 是否按此规划执行？还是你希望一次性做完？

**如果用户没有明确回复，默认按上述策略执行**，不再等待。

### B2. 执行阶段

**核心要求：**

1. **维护一份进度表**，在每个封装完成后更新，格式如下：

   | # | 封装名 | 状态 | 结论 | 备注 |
   |---|---|---|---|---|
   | 1 | 3S48000163 | ✅ 完成 | PASS | |
   | 2 | AOZ22559QI | ✅ 完成 | FAIL | width 超差 |
   | 3 | CSTJ-421-1010BG | ⏳ 进行中 | | |
   | 4 | XXX | ⏸️ 待处理 | | |
   | 5 | YYY | ❌ 失败 | | Allegro 读取超时 |

   状态符号统一：✅ 完成 / ⏳ 进行中 / ⏸️ 待处理 / ❌ 失败 / ⏭️ 跳过。

2. **对每个封装，完整执行“单封装工作流程”（见下文），中间不插入其他封装的步骤。**

3. **每个封装完成后，立即输出该封装的报告**（格式见“报告格式”），不要攒到最后。

4. **遇到失败时**：
   - 记录失败发生在哪一步（定位 / 读图 / 读 Allegro / 比对）
   - 记录失败原因（简短，一两句话）
   - **不要重试超过 2 次**，超过就标记为失败，继续下一个
   - 在进度表里标注 ❌，在汇总中单独列出

5. **每完成 5 个封装后，主动汇报进度**：

   > 📊 进度：已完成 5/13。本批结论：#1 PASS，#2 FAIL，#3 PASS，#4 SKIP，#5 PASS。
   > 继续执行下一批？

   如果用户在 5 个内没有回复，继续执行；如果用户明确说“暂停”，停下。

6. **不要在同一对话里长期堆叠历史细节**。每个封装报告输出后，后续不需要再引用它的细节，除非用户问起。

### B3. 汇总阶段

所有可检查封装处理完毕后，输出**批量汇总报告**：

```
## 批量封装检查汇总

**父文件夹：** <path>
**检查时间：** <timestamp>
**总数：** 13 个可检查 / 2 个跳过

### 结论分布

| 结论 | 数量 | 封装 |
|---|---|---|
| PASS | 8 | #1, #3, #5, #6, #8, #9, #11, #13 |
| FAIL | 3 | #2, #7, #10 |
| REVIEW_REQUIRED | 1 | #4 |
| FAILED（工具失败） | 1 | #12 |
| SKIPPED（缺文件） | 2 | - |

### 失败明细

**#2 AOZ22559QI**
- width: 理论 0.30 / 实际 0.40 / delta +0.10 / 公差 ±0.03

**#7 XXX**
- height: 理论 0.60 / 实际 0.75 / delta +0.15 / 公差 ±0.05

**#10 YYY**
- spacing_x: 理论 0.50 / 实际 0.52 / delta +0.02 / 公差 ±0.05

### 工具失败项

**#12 ZZZ**：Allegro 读取超时 3 次，建议人工检查 .dra 文件完整性。

### 跳过项

**#13 WWW**：文件夹里没有 PDF。
**#14 VVV**：文件夹里没有 .dra。

### 建议下一步

- 3 个 FAIL 封装需要人工复核 datasheet 与 Allegro 差异。
- 1 个 REVIEW_REQUIRED 封装需要确认图纸上模糊的尺寸标注。
- 1 个工具失败封装需要手动排查 .dra 文件。
```

---

## 单封装工作流程

（模式 A 和模式 B 都使用这一流程处理单个封装。）

### 第 1 步：列出文件夹内容

调用 tool `list_folder_files(folder_path="<封装文件夹>")`。

从返回结果中提取：
- `pdf`：PDF 完整路径
- `pdf_stem`：文件名去掉 `.pdf` 后缀
- `dra_files`：所有 `.dra` 路径
- `pad_files`：所有 `.pad` 路径

如果 `pdf` 为 null 或 `dra_files` 为空，记录原因，跳过该封装（在模式 B 里）。

### 第 2 步：定位 land pattern 页

调用 tool `locate_land_pattern_page(pdf_file_path="<pdf>")`。

根据 `method` 决定：
- `primary` / `fallback`：使用返回的 `page`
- `no_match`：尝试渲染所有页自己找；找不到就记录失败

### 第 3 步：你亲自读图提取理论参数

1. 读 resource 图片：`datasheet://<pdf_stem>/page/<page>`
   - 如果读不到图，改用 resource `datasheet://<pdf_stem>/marker/page/<page>`
   - 如果都读不到，记录失败
2. 按下方“提取规则”读图，输出严格 JSON（包含 `tolerance` 字段）
3. 调用 tool `validate_land_pattern_json(raw_json="<JSON字符串>")`
   - `valid=true`：取 `normalized`，包装成 `{"theoretical_land_params": <normalized>}`
   - `valid=false`：根据 `errors` 修正后重试，最多 2 次
   - 连续失败：记录并跳过

### 第 4 步：读取实际封装参数

对每个 `.dra` 调用 `read_allegro_footprint(dra_file_path="<dra>", pad_file_paths=<pads>)`。

失败时记录原因，不重试超过 2 次。

### 第 5 步：公差比对

调用 `check_land_pattern_tolerance`：
- `theoretical_payload`：第 3 步返回
- `actual_payload`：第 4 步返回
- `tolerance`：从第 3 步 JSON 里的 `tolerance` 字段取；没有则传 null（走默认）

### 第 6 步：输出封装报告

格式见“报告格式”。

### 第 7 步：保存 JSON 报告（每个封装完成后立即执行）

调用 tool `save_tolerance_report`：

- `comparison_result` = 第 5 步的返回
- `theoretical_payload` = 第 3 步的返回
- `actual_payload` = 第 4 步的返回
- `output_dir` 不传（自动写到 .dra 所在目录）
- `filename` 不传（自动带时间戳）

返回后，在报告中注明：`已保存报告到 <path>`。

批任务（模式 B）中，**每个封装完成后都要调这个 tool**，不要等整批做完再一起保存。

---

## 提取规则

- **图片可能旋转 90 度**。先在心里旋转，确认图纸方向后再读数。
- **只读 land pattern / recommended pad / 推荐焊盘区域**，不要读器件外形尺寸。
- **区分"器件尺寸"和"焊盘尺寸"**：
  - 器件尺寸是元件本体长宽，通常在器件俯视/侧视图上。
  - 焊盘尺寸是 PCB 上的铜箔尺寸，通常在 LAND PATTERN 区域。
  - **你只要焊盘尺寸**。
- **pin 号必须是整数**，不要输出 "1" 或 1.0。
- **单位统一为 mm**。如果图中标注 mil，换算：1 mil = 0.0254 mm。
- **spacing_x / spacing_y** 是相邻焊盘中心间距，不是外边缘间距。无标注填 null，不猜。
- **数值合理性检查**：
  - 单个焊盘尺寸通常在 0.2 ~ 5 mm 之间。小于 0.1 或大于 10，几乎肯定是误读。
  - 中心间距应 ≥ 焊盘尺寸，且通常与器件尺寸同量级。
- **图纸模糊或无法识别**：在 note 里说明，不编造数值。

### 公差提取规则

- 图纸明确写 `0.30±0.03` → tolerance = `{"min": -0.03, "max": 0.03}`
- 图纸写 `0.30 +0.03/-0.01` → tolerance = `{"min": -0.01, "max": 0.03}`
- 图纸只写名义值（如 `1.4`）没有 ± → 该维度 tolerance 填 `null`
- 图纸公差区域模糊、看不清 → 该维度填 `null`，在 note 里说明
- **图纸没标公差 ≠ 数据不可用**。只写名义值也是合法输入，正常提取名义值，tolerance 填 null
- **不要给没看到 ± 的尺寸编造公差**
- **tolerance 整体可以为 null**，表示所有维度都用默认公差

### 输出格式

    {
      "unit": "mm",
      "pads": [
        {"pin": 1, "width": 0.30, "height": 0.90}
      ],
      "spacing_x": 0.50,
      "spacing_y": null,
      "tolerance": {
        "width":     {"min": -0.03, "max": 0.03},
        "height":    {"min": -0.03, "max": 0.03},
        "spacing_x": {"min": -0.05, "max": 0.05},
        "spacing_y": null
      },
      "note": "spacing_y 图纸未标注"
    }

---

## 报告格式

### 单封装报告

    ## 封装检查报告

    **封装：** <封装文件夹名>
    **路径：** <完整路径>

    ### 数据来源

    - PDF：<pdf_name>（第 <page> 页，method=<method>）
    - 理论值提取：客户端 LLM 读图
    - Allegro：<dra_name>

    ### 结果

    | .dra | 结论 | PASS | FAIL | NA |
    |---|---|---|---|---|
    | <dra_name> | PASS/FAIL/REVIEW_REQUIRED | n | n | n |

    ### 失败明细

    | pin | 维度 | 理论值 | 实际值 | delta | 公差 | 公差来源 |
    |---|---|---|---|---|---|---|
    | 1 | width | 0.30 | 0.40 | +0.10 | ±0.03 | 图纸 |

    ### 通过项

    （简要列出，不需要逐行）

    ### 人工复核提醒

    理论值由 AI 读图提取，建议人工对照 PDF 原始图纸复核。

### 批量汇总报告

见 B3 阶段。

---

## 注意事项

- **优先相信自己的读图结果**，moondream2 只作兜底。
- **不要跳过 `validate_land_pattern_json`**。
- **数值合理性自检**：提取完 JSON 后快速判断量级，异常就重新看图。
- **单位统一为 mm**。
- **spacing 为 null 时不参与比对**，标记 NA，不算 FAIL。
- **某个 `.dra` 读取失败时不要中止**，记录后继续。
- **不要编造数据**。任何一步失败，如实报告。
- **批任务中，每个封装独立报告**，不要交叉引用其他封装的细节。
- **批任务中每 5 个封装主动汇报进度**。
- **不要无限重试**。同一操作失败 2 次就跳过。

---

## 依赖的 MCP 工具一览

| Tool | 用途 |
|---|---|
| `list_folder_files` | 列出文件夹里的 PDF / .dra / .pad |
| `list_subfolders`（如存在） | 列出父文件夹下的子文件夹，供批量模式侦察 |
| `locate_land_pattern_page` | 定位 land pattern 页 |
| `read_allegro_footprint` | 读取实际封装参数 |
| `validate_land_pattern_json` | 校验 AI 输出的 JSON |
| `check_land_pattern_tolerance` | 公差比对 |
| `parse_datasheet_land_pattern` | moondream2 兜底（非默认） |
| `save_tolerance_report` | 把单个封装检查结果写成 JSON 文件 |

## 依赖的 MCP 资源一览

| Resource URI | 用途 |
|---|---|
| `datasheet://{pdf_stem}/page/{page}` | PDF 整页图片（PyMuPDF PNG） |
| `datasheet://{pdf_stem}/marker/page/{page}` | PDF marker 图 |
| `datasheet://{pdf_stem}/info` | PDF 元信息 |

## 依赖的 MCP 提示一览

| Prompt | 用途 |
|---|---|
| `extract_land_pattern` | 单页提取提示模板 |
| `full_footprint_check` | 端到端流程 SOP |


