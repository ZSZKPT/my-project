# Windows 浏览器连接

此启动器在你的 Windows 电脑上打开 Playwright 专用 Chromium，不连接已有 Chrome，也不需要开启远程调试端口。当前只实现打开浏览器与保存本机登录状态，尚不包含自动复制、填写、保存或发布。

1. 安装 Python 3.12 或更高版本（来自 https://www.python.org/downloads/windows/），启用 Python Launcher。
2. 将整个项目下载或复制到电脑，保留目录结构，例如 `C:\temu-tool`。不要仅下载启动脚本。
3. 双击 `windows\start-browser.cmd`。首次会创建 `.venv`、安装 Playwright 和下载 Chromium，需要联网。
4. 在新打开的浏览器中手动登录 Temu，完成验证码。不要使用你日常 Chrome 窗口执行这一流程。
5. 在这个专用窗口打开草稿链接 `https://agentseller.temu.com/goods/edit?productDraftId=9091908599&from=productDraftList`。

如果 PowerShell 的脚本策略禁止运行，请遵循你的电脑管理策略。无需更改策略也可在项目目录的命令提示符中依次运行：

```bat
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install -r windows\requirements.txt
.venv\Scripts\python.exe -m playwright install chromium
.venv\Scripts\python.exe windows\browser.py
```

后续直接运行最后一条即可，不必重复安装。关闭窗口结束连接；不要同时启动两个使用同一登录目录的实例。登录状态在 `data\browser-profile`，不要上传、共享或加入 Git；删除此目录可清除本工具的登录状态。

若要直接打开草稿：

```bat
.venv\Scripts\python.exe windows\browser.py --url "https://agentseller.temu.com/goods/edit?productDraftId=9091908599&from=productDraftList"
```

云端助手不会因本机启动器运行而获得浏览器控制权。本机自动化逻辑尚需开发和验证。后续从草稿页确认真实字段，再添加填表执行器，首轮停在保存或发布前。
