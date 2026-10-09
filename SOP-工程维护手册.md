# layout-check-mcp 工程维护手册（部署 / 排障 / 变更）

> 本文面向**部署者与维护者**，是 `SOP.md`（使用说明与效果汇报，给汇报用）的底层细节。
> 汇报时不需要看本文；遇到部署失败、报错、要改规则时再来翻。
> 配套的另外两份：`README.md`（一键部署）、`SOP.md`（使用与效果）。

> 适用对象：使用本工具检查封装的硬件/Layout 工程师，以及维护本仓库的开发者。
> 事实来源：本仓库代码、`.trae/skills/footprint-tolerance-check/SKILL.md`、README.md。
> 凡标注 **【建议】** 的条目是本文档补充的操作建议，不是代码里已有的硬约束。

| 项 | 内容 |
|---|---|
| 用途 | 比对 datasheet 的 land pattern 与 Allegro `.dra` 封装，输出 6 大项检查报告 |
| 交付形态 | 一个 MCP 服务（`layout-check-v2`） + 一个 Agent Skill（`footprint-tolerance-check`） |
| 运行环境 | Windows + Cadence Allegro PCB Editor（SPB 17.2+），Python 3.10~3.12 |
| 上游仓库 | https://github.com/ds2457513911/layout-check-mcp |

---

## 1. 系统概览

### 1.1 三层分工

| 层 | 位置 | 职责 |
|---|---|---|
| Agent（客户端） | WorkBuddy / Trae / Claude Desktop 等 | 承载 Skill 流程，调用 MCP 工具，**负责语义判断**（命名含义、pin 功能、极性标识） |
| MCP 服务 | `mcp_server/` | 暴露 7 个 tool + 2 个 resource + 4 个 prompt，**负责数值计算**（尺寸、pitch、间距、原点、外扩、重叠） |
| 数据提取 | `services/` | 从 `.dra` 提取原始数据（extracta 主、SkillBridge 备），解析/渲染 PDF |

核心原则：**数值由 MCP 计算，语义由 AI 判断。** 凡能用数字精确算的走 Python，凡是要"看懂图纸"的走 AI。

### 1.2 数据源（重要，与 README 口径不同）

| 数据源 | 是否需要 Allegro 运行 | 说明 |
|---|---|---|
| **extracta.exe**（主） | **不需要** | Cadence 自带工具，从安装目录自动定位（CDSROOT），不需要 Allegro 启动 |
| SkillBridge（备） | **需要** | 需要 Allegro 正在运行 + `pcbenv\allegro.ilinit` 已注入启动段 + 端口 7777 监听 |

→ README 里"必须验证 7777 端口"是**旧口径**（deploy.bat v5 及以前）。从 v6 起 SkillBridge 是**可选**步骤，extracta 才是主路径。详见 §7.4。

回退逻辑（`services/footprint_extractor.py`）：extracta 失败 **或** 返回数据不完整（pins 无 pads 且 assembly/silkscreen/place_bound 三层全空）→ 自动回退 SkillBridge；两者都失败才报错。

调试开关：环境变量 `LAYOUT_CHECK_FORCE_SOURCE=extracta|skillbridge` 可强制指定数据源。

---

## 2. 术语与结论口径

| 术语 | 含义 |
|---|---|
| land pattern | 规格书里的"推荐焊盘图形"，本流程的比对基准 |
| ETCH/TOP | 铜箔焊盘层。**与 datasheet 比对只认这一层** |
| PIN/SOLDERMASK_TOP | 阻焊开窗，通常比铜箔单边大 0.05mm，**不参与理论比对** |
| PIN/PASTEMASK_TOP | 钢网，通常与铜箔等大 |

**结论判定**（`services/rule_checker.py`）：

| 结论 | 触发条件 |
|---|---|
| `PASS` | 无 FAIL 且无 NA |
| `REVIEW_REQUIRED` | 无 FAIL，但有 NA（数据不足，需人工复核） |
| `FAIL` | 存在至少一条 FAIL |
| `FAILED` / `SKIPPED` | 批量模式下的执行状态（工具报错 / 缺 PDF 或缺 .dra 而跳过） |

**元件分类**（影响阈值取值）：`ic` / `chip` / `connector`，由 `_classify_component()` 按封装名推断。

---

## 3. 部署 SOP

### 3.1 前置条件

| # | 条件 | 校验方式 |
|---|---|---|
| 1 | Windows + 已安装 Cadence Allegro PCB Editor | 能启动 Allegro（仅 SkillBridge 路线需要） |
| 2 | 能访问 GitHub（一键部署走 https 下载脚本 + clone） | 浏览器打开仓库地址 |
| 3 | 有 winget（Windows 应用安装器） | `where winget` |
| 4 | 目标盘有 ≥2GB 空间、路径**不含中文** | — |

### 3.2 一键部署（推荐）

1. 新建一个**空文件夹**（例如 `C:\Users\<用户名>\Documents\check_test`），**不要**在已有 `layout-check-mcp` 目录里执行——脚本会把仓库克隆到当前目录的 `layout-check-mcp\` 子目录。
2. 在该文件夹下打开 CMD，执行：

```
curl -L -o deploy.bat https://raw.githubusercontent.com/ds2457513911/layout-check-mcp/main/deploy/deploy.bat && deploy.bat
```

3. 脚本 7 步（`deploy/deploy.bat` v6）：

| 步 | 动作 | 失败是否中断 |
|---|---|---|
| 1 | 检查/安装 `uv`（winget，装完**真跑一次 `where uv`** 校验） | 是 |
| 2 | 检查/安装 `git` | 是 |
| 3 | `git clone`（首次）或 `git pull`（已存在） | 是 |
| 4 | 删除旧版 `~/.local/share/skillbridge_env` | 否 |
| 5 | `uv sync` 建 `<项目>\.venv`；若 venv 的 Python ≥3.13 则重建（与 skillbridge 不兼容） | 是 |
| 6 | 配置 Allegro SkillBridge 自启动（**可选**，失败只告警） | 否 |
| 7 | 生成 `mcp-config.json` 到**当前目录**，打印 SKILL.md 路径 | — |

4. 收尾输出三样东西：MCP 配置 JSON、SKILL.md 目录路径、下一步提示。**照抄前两项到 §4。**

> winget 的坑：winget 返回 0 不代表安装成功（底层 installer 可能 exit 1）。脚本已内置"装完真跑一次 `where` 校验 + 失败重试 3 次 + 修源（source update/reset）"。仍失败时看 `%TEMP%\winget_install_*.log` 最后 30 行。

### 3.3 部署后验收清单

按顺序做完，全绿才算部署完成：

| # | 检查项 | 命令 / 动作 | 期望 |
|---|---|---|---|
| 1 | uv / git 可用 | `uv --version` `git --version` | 均输出版本号 |
| 2 | venv Python 版本 | `<项目>\.venv\Scripts\python.exe -c "import sys;print(sys.version)"` | 3.10~3.12（本机实测 3.10.11） |
| 3 | 依赖已装 | 检查 `.venv\Lib\site-packages` 下有 `fastmcp`、`skillbridge`、`fitz`(PyMuPDF)、`pdfplumber` | 均存在 |
| 4 | 仓库完整 | `<项目>\pyproject.toml` 存在 | 存在 |
| 5 | MCP 配置生成 | 打开生成的 `mcp-config.json` | `command` 指向真实 uv.exe 路径，`--directory` 指向真实项目根 |
| 6 | Agent 已连上 | 重启 Agent 应用，MCP 列表里 `layout-check-v2` 显示为已连接 | 工具可见 |
| 7 | Skill 已加载 | 见 §4.2 | Agent 能识别 `footprint-tolerance-check` |
| 8 | **端到端冒烟** | 见下 | 拿到一份非空的 markdown 报告 |

**端到端冒烟（必做）**：准备一个已知可查的封装文件夹（含 PDF + `.dra`），在 Agent 里说：

```
用 footprint-tolerance-check 检查一下这个 "<封装文件夹绝对路径>" 封装
```

判定标准：返回一份完整的 markdown 报告表格。若返回 `error` 且含"两个数据源都失败"→ 转 §6 排障。

### 3.4 分步部署（一键脚本不可用时的备选）

```powershell
# 1) 装 uv 和 git
winget install astral-sh.uv
winget install --id Git.Git -e --source winget --scope user

# 2) 拉代码
git clone https://github.com/ds2457513911/layout-check-mcp.git
cd layout-check-mcp

# 3) 装依赖
uv sync

# 4)（可选）配置 SkillBridge
uv run python Tools/install_skillbridge.py
```

手工写 MCP 配置（等价于一键脚本生成的那份）：

```json
{
  "mcpServers": {
    "layout-check-v2": {
      "command": "<uv.exe 绝对路径>",
      "args": ["run", "--directory", "<项目根绝对路径>", "layout-check-mcp"]
    }
  }
}
```

SKILL.md 位置：`<项目根>\.trae\skills\footprint-tolerance-check\SKILL.md`（把整个 `footprint-tolerance-check` 文件夹拷进 Agent 的 skills 目录）。

> 仓库的 git remote 是 **SSH**（`git@github.com:...`）：贡献者 push 需要配 SSH key；使用者 clone 走 https，不需要。

### 3.5 升级与重装

| 场景 | 动作 |
|---|---|
| 拉最新代码 | 在部署目录重跑 `deploy.bat`（会自动 `git pull` + `uv sync`），然后**重启 Agent 应用** |
| 依赖没更新 / 环境坏掉 | 删掉 `<项目>\.venv` 后重跑 `deploy.bat`（会重建） |
| 本地改过代码导致 `git pull` 失败 | 先提交或 stash；**不要**在工作副本里长期留未提交改动 |

### 3.6 卸载 SkillBridge（可选步骤的回滚）

```
uv run python Tools/install_skillbridge.py --uninstall
```

会移除 `pcbenv\allegro.ilinit` 里的标记块并自动备份。卸载后 Allegro 不再自启 SkillBridge（extracta 路线不受影响）。安装时会备份为 `allegro.ilinit.bak_<时间戳>`。

---

## 4. 配置 Agent

### 4.1 配置 MCP

把 `mcp-config.json` 内容粘进 Agent 的 MCP 配置（或指向该文件）。服务名 **`layout-check-v2`**。

### 4.2 配置 Skill

把 `<项目根>\.trae\skills\footprint-tolerance-check` **整个文件夹**复制/导入到 Agent 的 skills 目录。

### 4.3 开发调试配置（改代码时用，无缓存）

```json
{
  "mcpServers": {
    "layout-check-v2": {
      "command": "<项目根>\\.venv\\Scripts\\python.exe",
      "args": ["-m", "mcp_server.server"],
      "cwd": "<项目根>",
      "env": { "PYTHONPATH": "<项目根>" }
    }
  }
}
```

优点：改代码后只重启客户端即可生效，不用清 uv 缓存。
注意：`command` 必须指向装了 fastmcp/skillbridge 的解释器（用项目自己的 `.venv`，别用系统 Python）。

---

## 5. 日常使用 SOP

### 5.1 数据准备（约束）

| 约束 | 说明 |
|---|---|
| **路径必须全 ASCII** | Allegro/extracta 不支持非 ASCII 路径，含中文会失败 |
| 文件夹内容 | 至少 1 个 PDF（规格书）+ 1 个 `.dra`；`.pad` 可选（`.dra` 自带 padstack 副本） |
| `.dra` 扫描规则 | 自动排除 `AUTOSAVE*` |
| 报告落盘 | `checklist_report_<时间戳>.json` 写在 **`.dra` 所在目录**（即被检查的封装文件夹里） |

### 5.2 模式判定

Agent 先调 `list_folder_files(folder_path)`：

| 返回 | 模式 |
|---|---|
| `pdf` 或 `dra_files` 非空 | **模式 A：单封装** |
| 两者都空、但有子文件夹 | **模式 B：批量** |
| 无法判定 | 问用户 |

### 5.3 模式 A：单封装 7 步

| 步 | 调用 | 要点 |
|---|---|---|
| 1 | `list_folder_files` | 取 `pdf` / `pdf_stem` / `dra_files` / `pad_files`；缺 PDF 或缺 `.dra` → 停止 |
| 2 | `locate_land_pattern_page` | `method` = primary/fallback 用返回页；`no_match` 自行翻页找 |
| 3 | 读 resource `datasheet://<pdf_stem>/page/<page>` | **AI 读图**提取理论值 → 调 `validate_land_pattern_json` 校验（失败最多重试 2 次）。客户端不支持 resource 时改用 `render_pdf_page` 拿图片路径 |
| 4 | `read_full_footprint` | 拿 `symbol_name` / `pins` / `layers` 供语义检查；**返回 error 就停止，不许自己写 Python 替代** |
| 5 | AI 语义判断 | 三组：5.1 命名语义（类型/引脚数/尺寸/pitch）、5.2 pin number（数量/编号/功能）、5.3 极性标识（1 脚标识、极性符号、层一致性）→ 组装 `semantic_result` |
| 6 | `check_footprint_by_rules` | 传 `dra_file_path` / `theoretical_payload` / `pad_file_paths` / `semantic_result`；默认 `save_report=True`、`compact=True` |
| 7 | 输出 | **原样贴出返回的 `markdown` 字段**，禁止改写、补充、加前后缀 |

**读图提取规则（给执行者）**：只读 land pattern / recommended pad 区域；区分器件本体尺寸与焊盘尺寸（只取焊盘）；单位统一 mm（1 mil = 0.0254 mm）；pin 号必须是整数；单焊盘通常 0.2~5mm（<0.1 或 >10 视为误读）；`0.30±0.03` → `{min:-0.03,max:0.03}`，只写名义值 → tolerance 填 null。

### 5.4 模式 B：批量

4 阶段：**侦察 → 规划 → 执行 → 汇总**

| 阶段 | 动作 |
|---|---|
| B0 侦察 | `list_subfolders` 列子目录，逐个 `list_folder_files` 记录 PDF/.dra/.pad 情况，输出"可检查 / 跳过"清单 |
| B1 规划 | 1~3 个一次做完；4~8 个一次做完但每个独立报告；9~15 个分 2~3 批（每批 5 个，批间等确认）；16+ 必须每批 5 个 |
| B2 执行 | 维护进度表（✅/⏳/⏸️/❌）；**每个封装完成后立即出报告**，不攒到最后；单个失败不阻断；每完成 5 个主动汇报 |
| B3 汇总 | 结论分布表（PASS/FAIL/REVIEW_REQUIRED/FAILED/SKIPPED）+ 失败明细 + 跳过项及原因 + 下一步建议 |

### 5.5 产物说明

| 产物 | 位置 | 说明 |
|---|---|---|
| Markdown 报告 | 由 MCP 返回，AI 原样贴出 | 精简版，展示 6 大项结论 |
| JSON 报告 | `<.dra 目录>\checklist_report_<YYYYMMDD_HHMMSS>.json` | 完整明细（items / failed / warned），排障与复核看这个 |
| PDF 渲染图 | `<项目根>\marker_out\` | PyMuPDF 渲染缓存，被 gitignore，可随时删（会自动重建） |

需要逐项明细时：调 `check_footprint_by_rules(..., compact=False)`，或直接读 JSON 报告。

---

## 6. 排障手册

| # | 现象 | 原因 | 处理 |
|---|---|---|---|
| 1 | 一键脚本报 "winget not found" | 缺 Microsoft Store 的"应用安装器" | 装应用安装器后重试 |
| 2 | uv/git 装完仍 `where` 不到 | winget 假成功 / PATH 未刷新 | 看 `%TEMP%\winget_install_*.log` 后 30 行；手动 `winget install` 后**重开 CMD** |
| 3 | `git clone` 失败 | 网络/代理/权限 | 换网络或配代理；确认能访问 GitHub；注意部署用 https，不需要 SSH key |
| 4 | `git pull` 失败 | 工作副本有本地改动 | 提交或 stash 后再跑；不要长期在部署副本里留改动 |
| 5 | `uv sync` 失败 | 网络 / Python 版本不满足 | 检查 `requires-python`（>=3.10,<3.13）；必要时 `uv python install 3.12` |
| 6 | venv Python ≥3.13 | 与 skillbridge 不兼容 | 脚本会自动重建 venv；手工场景删 `.venv` 重跑 |
| 7 | 第 6 步"SkillBridge 未配置"（告警） | pcbenv 找不到 | **可接受**（extracta 是主路径）。要用 SkillBridge：先启动一次 Allegro 生成 pcbenv，或 `uv run python Tools/install_skillbridge.py --pcbenv "<路径>"`（路径可在 Allegro 命令窗用 `getShellEnvVar("SPB_Data")` 查，后面拼 `\pcbenv`） |
| 8 | `netstat -ano \| findstr 7777` 无结果 | Allegro 没重启 / ilinit 没生效 | 用 extracta 路线则可忽略；否则完全关闭并重启 Allegro，看 CIW 是否有 SkillBridge 启动信息 |
| 9 | extracta 报 `0xC0000409` | 退出码**不可信**——extracta 收尾必崩，但输出文件可能完整 | 判成败看**输出文件**，不看退出码 |
| 10 | extracta 真失败 / 找不到 | CDSROOT 定位错（缺 `cdsCommon.dll` 或 `share\pcb\text\views`） | `set LAYOUT_CHECK_CDSROOT_DEBUG=1` 后跑 `uv run python services/cdsroot_locator.py` 看扫描过程 |
| 11 | `read_full_footprint` 返回"两个数据源都失败" | extracta 与 SkillBridge 都不可用 | 返回里会分别列出两者的 error，按 #9/#10 和 #7/#8 分别排查 |
| 12 | 结果数值明显偏大 ~0.1mm | 用错层（阻焊开窗 vs 铜箔） | 确认走的是 `check_footprint_by_rules`，**禁止**用废弃的 `read_allegro_footprint` |
| 13 | 封装路径含中文导致失败 | Allegro 不支持非 ASCII | 把封装搬到纯英文路径再检查 |
| 14 | Agent 里看不到 MCP 工具 | 客户端没重启 / 配置路径写错 | 核对 `mcp-config.json` 的 uv 路径与 `--directory`；**重启 Agent 应用** |
| 15 | 改了代码但行为没变 | MCP 进程没重启 | 重启客户端；调试用 §4.3 配置（直接读磁盘代码，无缓存） |
| 16 | 报告 markdown 为空 | 渲染失败 | 看返回的 `render_error`；如实报告"报告渲染失败：<原因>"，**不要自己拼表** |

### 6.1 诊断工具

| 工具 | 用途 |
|---|---|
| `uv run python services/cdsroot_locator.py` | 独立诊断 CDSROOT 定位（配合 `LAYOUT_CHECK_CDSROOT_DEBUG=1`） |
| `Tools\dump_all_footprints.py` | 批量导出 `Data/footprint` 下所有 `.dra` 的 pin/pad/层信息到 `Tools\footprint_dump.txt`，用于分析 padstack 命名规则 |
| `Tools\debug\test_skillbridge.py` | SkillBridge 连通性测试（**该目录被 gitignore，clone 下来的仓库里没有**） |
| `Tools\diag_extracta.ps1` | extracta 手工调用探针（内含硬编码本机路径，用前需改） |
| `Tools\log\` | 历史运行日志（gitignore） |

---

## 7. 维护与变更 SOP

### 7.1 改哪里 → 影响什么

| 改什么 | 文件 | 影响 |
|---|---|---|
| 检查阈值/规则 | `services/rule_checker.py` 的 `DEFAULT_RULES` | 全部检查项的判定口径 |
| 报告版式 | `services/report_renderer.py` | 最终 markdown 表格 |
| 增删/改 tool 签名 | `mcp_server/tools.py`（**只做参数校验+转发，不写业务逻辑**） | Skill 流程与 Agent 调用 |
| 数据源优先级/回退 | `services/footprint_extractor.py` | 全链路取数 |
| Skill 流程（AI 侧的 SOP） | `.trae/skills/footprint-tolerance-check/SKILL.md` | Agent 行为 |
| PDF 定位/渲染 | `services/pdf_locate.py` / `pdf_renderer.py` / `pdf_service.py` | 第 2~3 步 |

默认阈值速查（`DEFAULT_RULES`）：

| 组 | 关键值 |
|---|---|
| naming | 前缀 `NB_`（大小写敏感）、不含 `.` |
| pad | 尺寸容差 0.05mm、最小间距 0.20mm、阻焊单边外扩 0.05mm、钢网=焊盘 |
| origin | 中心偏移容差 0.05mm（连接器放宽到 20mm） |
| place_bound | 外扩 ic 0.35 / chip 0.15 / connector 0.85，容差 0.05mm |
| silkscreen | 最小线宽 0.10mm、距焊盘间距 0.20mm |
| assembly | 尺寸容差 0.05mm |

### 7.2 发布流程

1. 本地改代码 → 按需跑诊断脚本验证（§6.1）。
2. 提交并推送到 GitHub（remote 是 SSH，需 SSH key）。
3. 通知使用者：重跑 `deploy.bat`（`git pull` + `uv sync`）→ **重启 Agent 应用**。
4. 使用者按 §3.3 第 8 项做端到端冒烟。

### 7.3 版本核验（注意与 SKILL.md 的说法不一致）

SKILL.md 的"维护提示"说改代码后要更新 `mcp_server/config.py` 里的 `MCP_VERSION` —— **当前 config.py 里没有这个字段**（实际只有四个：`PROJECT_ROOT`、`RENDER_OUTPUT_ROOT`、`PDF_SEARCH_ROOTS`、`SKILLBRIDGE_WORKSPACE_ID`）。

→ **【建议】** 验证"改的代码是否生效"不要依赖版本号，直接用行为验证：改一处可观察的输出（例如报告里的某个值），跑一次冒烟看结果。这是当前唯一可靠的核验方式；是否补一个 `MCP_VERSION` 由维护者决定。

### 7.4 已知文档偏差（维护时一并修）

| 文档 | 说法 | 现状 |
|---|---|---|
| README.md | 把 7777 端口验证列为必做 | deploy.bat v6 起 SkillBridge 是可选步骤，extracta 为主数据源 |
| README.md 备用章节 | `uv run ./Tools/test_skillbridge.py` | 实际在 `Tools/debug/` 下，且该目录被 gitignore，clone 后不存在 |
| README.md 备用章节 | 提到 `install_skillbridge.py` 从 GitHub 单独 curl | 该文件已在仓库 `Tools/` 里，`uv run python Tools/install_skillbridge.py` 即可 |
| SKILL.md 维护提示 | 更新 `MCP_VERSION` | 该字段不存在（见 §7.3） |

---

## 8. 硬约束（执行者必须遵守）

来自 `.trae/skills/footprint-tolerance-check/SKILL.md` 的铁律，违反会导致检查结果不可信：

1. **所有数值必须来自 MCP tool 的实际返回**——不得自己写 Python 替代，不得凭历史记忆推断工具会失败。
2. **每次调用 tool 后必须读返回**；返回 error 就**如实贴出 error 字符串**，停止当前封装检查。
3. **禁止调用废弃 tool**：`read_allegro_footprint`、`check_land_pattern_tolerance`、`save_tolerance_report`（旧版流程，返回阻焊开窗尺寸，会误判）。
4. **禁止用 Python 直接解析 PDF 内部结构**（`get_images()` / `get_drawings()` 等），PDF 只能走 MCP resource 或 `render_pdf_page`。
5. **不得由理论值+公差反推"实测值"**，不得用"推算/大概/应该"生成数据。
6. **最终报告原样贴出 `markdown` 字段**，不得改写表格字符、不得加"结论/建议/已保存到"等前后缀、不得输出过程性文字。
7. **路径含中文时提醒用户**改用英文路径。
8. 批量任务中每个封装独立报告，不交叉引用；同一操作失败 2 次就跳过。

---

## 9. 附录

### 9.1 MCP 工具速查

| Tool | 用途 |
|---|---|
| `list_folder_files` | 列出文件夹里的 PDF / .dra / .pad（决策第一步） |
| `list_subfolders` | 批量模式侦察子目录 |
| `locate_land_pattern_page` | 定位 land pattern 页 |
| `render_pdf_page` | 渲染 PDF 页为 PNG（客户端不支持 resource 时用） |
| `validate_land_pattern_json` | 校验 AI 输出的 JSON |
| `read_full_footprint` | 提取 .dra 的 pins/layers 供语义检查 |
| **`check_footprint_by_rules`** | **主用**：6 大项数值检查 + 存档 + 渲染 markdown |

Resource：`datasheet://{pdf_stem}/page/{page}`（PNG）、`datasheet://{pdf_stem}/info`（JSON）。
Prompt：`extract_land_pattern` / `check_naming_semantic` / `check_pin_number_semantic` / `check_polarity_marker` / `full_footprint_check`（客户端不支持 prompt 时按 SKILL.md 第 5 步手工执行即可）。

### 9.2 目录说明

| 路径 | 内容 |
|---|---|
| `mcp_server/` | FastMCP 入口与 tool/resource/prompt 定义；`config.py` 集中路径配置 |
| `services/` | 业务层：数据提取、PDF 处理、规则检查、报告渲染 |
| `shared/` | 通用工具（JSON 清洗、schema 校验） |
| `deploy/` | `deploy.bat`（一键部署，v6）、`deploy_skillbridge.bat`（v5 旧版，SkillBridge 为必选） |
| `Tools/` | `install_skillbridge.py`（Allegro 配置/卸载）、`dump_all_footprints.py`、`cleanup_redundant.py`；`debug/`、`log/` 为本地调试产物 |
| `.trae/skills/footprint-tolerance-check/` | 交付给 Agent 的 Skill |
| `.venv/` | uv 建的项目虚拟环境（gitignore） |
| `marker_out/` | PDF 渲染缓存（gitignore，可随时删） |
| `.trash/`、`.cleanup_backup/` | 历史隔离/备份（gitignore） |
| `mcp-config.json` | 部署生成的 MCP 配置（gitignore） |

### 9.3 关键环境变量

| 变量 | 作用 |
|---|---|
| `LAYOUT_CHECK_FORCE_SOURCE` | `extracta` / `skillbridge` 强制指定数据源 |
| `LAYOUT_CHECK_CDSROOT_DEBUG` | `1` 时输出 CDSROOT 扫描过程到 stderr |
| `CDSROOT` | extracta 运行根（由 `cdsroot_locator` 自动注入，一般无需手设） |

---

**文档版本**：v1.0 · 2026-10-08
**下次更新触发**：数据源策略变更、tool 签名变更、阈值调整、deploy.bat 升版。
