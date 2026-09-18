## 第一步：环境部署

1. 确保自己能连 GitHub 和 Windows；
2. 确保自己已经安装了Allegro；
3. 在电脑新建一个文件夹，在新建文件夹下打开 CMD；
4. 执行脚本
   ```
   curl -L -o deploy.bat https://raw.githubusercontent.com/ds2457513911/layout-check-mcp/main/deploy/deploy.bat && deploy.bat
   ```
5. 脚本会一键部署 uv、git、Allegro自启动skillbridge服务的配置，最后返回SKILL.md路径和 MCP 的配置;
   ```
   ============================================================
    Deploy complete
   ============================================================
   
   [1] MCP config saved to: C:\Users\ds245\Documents\check_test\mcp-config.json
   
   {
     "mcpServers": {
       "layout-check-v2": {
         "command": "C:\\Users\\ds245\\AppData\\Local\\Microsoft\\WinGet\\Packages\\astral-sh.uv_Microsoft.Winget.Source_8wekyb3d8bbwe\\uv.exe",
         "args": ["run", "--directory", "C:\\Users\\ds245\\Documents\\check_test\\layout-check-mcp", "layout-check-mcp"]
       }
     }
   }
   
   [2] SKILL.md path
       C:\Users\ds245\Documents\check_test\layout-check-mcp\.trae\skills\footprint-tolerance-check
       Copy the footprint-tolerance-check folder into your Agent's skills dir.
   
   [3] Next steps
       1. Restart Allegro PCB Editor
       2. Verify port: netstat -ano | findstr 7777
       3. Restart your Agent app, confirm MCP is connected
   
   Press any key to continue . . .
   
   C:\Users\ds245\Documents\check_test>
   ```
6. 把SKILL.md路径和 MCP 的配置粘贴到你所使用的 Agent 应用;

## 第二步：配置Agent（以workbuddy为例）

配置SKILL(直接选择整个footprint-tolerance-check文件夹)

![截图](attachment:90d69606d6b6889aaf8d8bc075ccd28f)

![截图](attachment:eeaea3ab185e746b1e7bdcdac6922637)

配置 MCP

![截图](attachment:c2f9bd6ea7bf90c1fbba365f32a9f541)

![截图](attachment:c7677966c08ae2b0acb13b4420662195)

## 第三步：测试

> 确保Allegro已经重启并且正在运行；

在对话窗口输入：帮我用检查一下这个 “你的封装路径” 封装，看看 datasheet 和 Allegro 封装是否匹配。

在对话窗口输入：帮我用检查一下 “你的封装路径” 文件夹下的所有封装文件，看看 datasheet 和 Allegro 封装是否匹配。

---

## 备用

> 如果一键部署脚本无法使用, 请按照下面的步骤自己分步部署；

### 第一步：下载Agent工具

### 第二步：装 `uv` 和 `git`

```powershell
winget install astral-sh.uv
winget install --id Git.Git -e --source winget --custom '/o:PathOption=CmdTools'
```

装完验证：

```cmd
uv --version
git --version
```

### 第三步：配置(以 Marvis 为例)

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

{
  "mcpServers": {
    "layout-check-v2": {
      "command": "C:\\Users\\ds245\\.conda\\envs\\env_marker\\python.exe",
      "args": ["-m", "mcp_server.server"],
      "cwd": "C:\\Users\\ds245\\Documents\\Project_Layout",
      "env": {
        "PYTHONPATH": "C:\\Users\\ds245\\Documents\\Project_Layout"
      }
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

在对话窗口输入：帮我用footprint-tolerance-check技能检查一下这个 “你的封装路径” 封装，看看 datasheet 和 Allegro 封装是否匹配。

在对话窗口输入：帮我用footprint-tolerance-check技能检查一下 “你的封装路径” 文件夹下的所有封装文件，看看 datasheet 和 Allegro 封装是否匹配。

---
