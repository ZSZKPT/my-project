# 飞凡印花设计 v0.4 开发版

版型、模特模板与印花分离；本地多部件套图和批量 JPG 可运行，**不是全部 V1–V3 验收完成版**。

- [下载 Windows EXE 包（构建与桌面自检通过后发布）](https://github.com/ZSZKPT/my-project/raw/refs/heads/main/downloads/FeifanPrintStudio-v0.4-Windows.zip)
- [Windows构建记录与校验值](../FeifanPrintStudio-v0.4-build.json)
- [下载 Python 源码包](https://github.com/ZSZKPT/my-project/raw/refs/heads/main/downloads/FeifanPrintStudio-v0.4-Source.zip)
- [使用说明](../../print_studio/FASHION_STUDIO.md)
- [逐项验收记录](../../print_studio/FASHION_ACCEPTANCE.md)
- [技术测试模板与结果 ZIP](https://github.com/ZSZKPT/my-project/raw/refs/heads/main/downloads/fashion-studio-v04/technical-examples.zip)
- [技术检查图](technical-proof.png)
- [机器可读测试报告](acceptance-report.json)

Windows 包解压后运行“飞凡印花设计.exe”。本地 JPG 模式无需安装 Photoshop；原来的案例67及各尺码裁片仍在右上角“原套版 / 裁片工作台”。新版模板库采用独立格式，不把旧单蒙版冒充多部件样机。

23 个服装版型预设和三类**技术绘图**示例已包含在包中。技术示例不是实际商品照片，不能拿来证明发丝边缘识别、真实褶皱或 Photoshop 智能对象通过验收。导入技术模板ZIP后核对批准，再导入示例印花即可试用。

Photoshop 当前未安装，原生 PSD 创建/编辑/重开等待目标 Photoshop 实测。AI 视觉接口可配置，但没有真实API凭据实测；当前多边形建议不是像素级自动分割。详细边界见验收记录，不声称全自动商业生产已完成。
