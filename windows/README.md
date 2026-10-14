# Windows 浏览器连接

此启动器在你的 Windows 电脑上打开 已安装的 Google Chrome（独立登录目录），不连接已有 Chrome，也不需要开启远程调试端口。当前只实现打开浏览器与保存本机登录状态，尚不包含自动复制、填写、保存或发布。

1. 安装 Python 3.12 或更高版本（来自 https://www.python.org/downloads/windows/），启用 Python Launcher，并安装 Google Chrome。
2. 将整个项目下载或复制到电脑，保留目录结构，例如 `C:\temu-tool`。不要仅下载启动脚本。
3. 双击 `windows\start-browser.cmd`。首次会创建 `.venv`、安装 Playwright；使用电脑上已安装的 Google Chrome，需要联网。
4. 在新打开的浏览器中手动登录 Temu，完成验证码。不要使用你日常 Chrome 窗口执行这一流程。
5. 在这个专用窗口打开草稿链接 `https://agentseller.temu.com/goods/edit?productDraftId=9091908599&from=productDraftList`。

如果 PowerShell 的脚本策略禁止运行，请遵循你的电脑管理策略。无需更改策略也可在项目目录的命令提示符中依次运行：

```bat
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install -r windows\requirements.txt
.venv\Scripts\python.exe windows\browser.py
```

后续直接运行最后一条即可，不必重复安装。关闭窗口结束连接；不要同时启动两个使用同一登录目录的实例。登录状态在 `data\chrome-profile`，不要上传、共享或加入 Git；删除此目录可清除本工具的登录状态。

若要直接打开草稿：

```bat
.venv\Scripts\python.exe windows\browser.py --url "https://agentseller.temu.com/goods/edit?productDraftId=9091908599&from=productDraftList"
```

云端助手不会因本机启动器运行而获得浏览器控制权。本机自动化逻辑尚需开发和验证。后续从草稿页确认真实字段，再添加填表执行器，首轮停在保存或发布前。

## Chromium 提示账号异常时

更新项目后，关闭之前启动的工具浏览器，再运行 `windows\start-browser.cmd`。新版本默认使用安装的 Google Chrome，创建独立的 `data\chrome-profile`，不会读取、复制或修改日常 Chrome 的登录目录。请在新窗口手动登录。

这只是更换浏览器发行版，不能保证消除 Temu 的账号或风控限制，也不会隐藏自动化标识。如果仍提示账号异常，停止反复登录并联系官方客服。需要使用 Chromium 时，先运行 `python -m playwright install chromium`，再给启动器添加 `--browser chromium`。

## 本地图片排序和素材图

解压用户图片压缩包后，在 PowerShell 中执行（输出目录必须不存在）：

```powershell
.\windows\prepare-images.ps1 -Source "C:\图片\新建文件夹 (51)" -Output "C:\图片\整理结果" -Size 800
```

支持 JPG/PNG，按货号目录处理。含“前”的文件排在前面，同组按名称排序；原文件复制后增加序号。第一张图居中裁成正方形，再缩放为指定大小。原文件不会覆盖。裁切可能去掉人物头部或脚部，需核对构图。当前官方导入说明要求素材图大于800×800；正式导入可改用 `-Size 1000`。脚本未在 Windows 实机验证。
