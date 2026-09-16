### 第一步：下载Agent工具

下载 Marvis

### 第二步：装 `uv`

```powershell
winget install astral-sh.uv
```

装完验证：

```cmd
uv --version
```

### 第三步：把配置贴进 Marvis

打开配置界面

<img width="1824" height="1014" alt="244262e2b0cabb8cf16c7739970831d7" src="https://github.com/user-attachments/assets/23efd505-86ae-4c49-ac23-0af72135813c" />

在里面拖入SKILL.md

<img width="1824" height="1014" alt="2c8db9e4b20be8b263b13510532b4024" src="https://github.com/user-attachments/assets/958d2482-a3cc-470b-b325-9716cc81f056" />

在里面粘贴MCP

<img width="1824" height="1014" alt="e21d47a253ffc2afbf07348b9467c803" src="https://github.com/user-attachments/assets/de377098-eb40-4648-98ae-57460f5b0109" />


```
# 本地没有MCP, 但是有git
{
  "mcpServers": {
    "layout-check-v2": {
      "args": [
        "--from",
        "git+https://github.com/ds2457513911/layout-check-mcp.git",
        "layout-check-mcp"
      ],
      "command": "uvx"
    }
  }
}

# 本地有MCP
{
  "mcpServers": {
    "layout-check-v2": {
      "args": [
        "--from",
        "D:/software/Project_Layout",
        "layout-check-mcp"
      ],
      "command": "uvx"
    }
  }
}
```

### 第四步：配置 SkillBridge

在 cmd 里输入:

```
# 从 GitHub 拉脚本并运行（uv run 会自带到 Python）
curl -O https://raw.githubusercontent.com/ds2457513911/layout-check-mcp/main/install_skillbridge.py
uv run install_skillbridge.py
```

重启Allegro；

在命令行测试服务，输出OK就是没问题：

```
python -c "from skillbridge import Workspace; ws = Workspace.open(workspace_id='7777'); print('OK')"
或者
netstat -ano | findstr :7777
或者
uv run ./Tools/test_skillbridge.py
```

### 第五步：测试

在对话窗口输入：帮我用检查一下这个 “你的封装路径” 封装，看看 datasheet 和 Allegro 封装是否匹配。

在对话窗口输入：帮我用检查一下 “你的封装路径” 文件夹下的所有封装文件，看看 datasheet 和 Allegro 封装是否匹配。

---
