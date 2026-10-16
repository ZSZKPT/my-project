# 布序 v5 · 数码印花裁片本地排料

Windows 下载：[BuxuNesting.exe](https://github.com/ZSZKPT/my-project/releases/download/buxu-desktop-v5/BuxuNesting.exe)。双击运行，所有操作在软件窗口内完成。无需安装Python或Node.js，图片只在本机处理。Windows10/11需要微软WebView2运行时；缺少时会明确提示。

## 使用

1. 导入所有原始JPG文件，默认110 DPI；每张自动识别左右两片，不设置数量、不逐片确认。请勿用聊天缩放截图替代原始文件。
2. 同图左右片固定原始相对位置，整组移动、整组0/180°旋转，取消单片上下错位。二维码、连接条、尺码牌保留并参与占用及间距检查。
3. 门幅默认1580mm，左右预留各10mm，轮廓净间距默认3mm，均可调整。每个占用外轮廓之间保持3mm，并非两片各留3mm。
4. 点击智能排料。算法自由调整组顺序，按真实占用轮廓并集搜索位置，进行横向/纵向压紧、尾部回填及多起点优化。选择精细模式可增加计算时间。停止时保留当前最佳完整可行方案。
5. 预览展示完整排料，可滚动到最后一片，支持缩放。拖动或输入坐标会移动整组；锁定任一片会固定整组。手动修改后复核冲突，可撤销、重做。
6. 点击“导出方案”→“生产JPG · 110 DPI”，**先选择保存位置**，随后后台独立复核、分块绘制、编码并保存。显示进度，可关闭导出框继续查看排料。取消在当前步骤结束后生效，取消或失败不覆盖原文件。生成中不要退出软件。
7. 输出一张完整JPG，白底、110DPI、质量100、无色度抽样，保留原图标签，不输出界面辅助标签。预览缩放不会改变生产尺寸。
8. 保存项目可保留原始素材、轮廓、数量、坐标、方向和设置。旧版错位项目打开后需重新排料；若有错位锁定组，先解除锁定。

排料为启发式搜索，显示“当前找到的最佳方案”，不保证数学最优。实际节料效果必须以原始素材测试；仅凭截图不能复现准确尺寸和节料比例。合成测试对比及验证范围见 [VALIDATION.md](VALIDATION.md)。

## 长图与生产范围

超过2400万像素的单张JPG采用临时磁盘RGBX分块绘制及映射编码，避免创建完整可变大画布；分块共用一次复核结果。需要足够系统临时磁盘空间。最终编码阶段进度显示85%，完成后更新，取消须等待当前编码结束。

JPEG单边上限65000像素（110DPI约15米），超出会报错，不缩小尺寸。可主动选择分段JPG ZIP，清单记录连续像素坐标、无重叠。支持毫米1:1 SVG、分段SVG ZIP、坐标CSV及带非生产标记的低分辨率PNG预览。

生产JPG支持JPG/PNG素材；SVG素材请用矢量输出。DXF、PDF、TIFF未实现。不执行ICC色彩转换，不自动生成缝份或缺失出血。打印关闭自动适应页面/缩放，先验证100mm尺寸、二维码可读性和色彩。未连接用户打印机或验证实际RIP兼容性。

默认导入上限20百万像素/图、24MB/图、500片/项目、100MB请求；超过时分批处理。白底识别必须有明确闭合外轮廓，识别不到两个主体会报错，不会静默删片。可主动打开素材编辑检查轮廓。印花内部白色/透明区域不作为套排孔洞。

## 源码开发

需要Python3.12+。使用仓库现有检出目录，无需创建额外worktree。

```sh
cd nesting
python -m venv .venv
.venv/bin/python -m pip install -r requirements-desktop.txt
.venv/bin/python desktop_launcher.py
```

Windows解释器路径替换为 `.venv\Scripts\python.exe`。桌面模式使用pywebview，Windows使用Edge WebView2。开发HTTP模式可运行 `python server.py --port 8765`；仅绑定本机，不向公网暴露。Windows日志：`%LOCALAPPDATA%\BuxuNesting\desktop.log`。

```sh
.venv/bin/python -m unittest discover -s tests -v
```

可选Chromium测试：`npm ci`，安装Playwright Chromium后运行 `npm run test:browser`；也可设置 `CHROMIUM_PATH`、`NESTING_URL` 和 `PLAYWRIGHT_MODULE`。`tests/background-browser.cjs`检查全图预览、先选位置、后台生成及取消；Python原生桥测试检查实际110DPI保存和原文件保护。

Windows打包由 `.github/workflows/buxu-windows.yml` 执行。自动化测试、编译后EXE的 `--self-test` 以及实际内嵌WebView2窗口 `--window-test` 全部通过后，才上传Release和二进制分支。源码ZIP不是EXE。

## 实现与精度

几何使用Shapely/GEOS毫米坐标和STRtree索引；轮廓顶点接触加水平候选采样，不是完整NFP或全局最优求解。目标按长度、纵向面积矩、横向面积矩排序，每次改进完整复核。固定种子在相同版本、完整执行相同轮数且未触及时间限制时可复现；机器速度影响超时位置。

轮廓间距以占用区域计算，包含出血及轮廓保守余量。几何距离容差0.000001mm，像素输出取整误差约半像素。SVG曲线离散并预留0.1mm；禁止外部资源、脚本和动态SVG。JPG含EXIF旋转时应先真正应用方向再导入。

`assets.py`导入；`geometry.py`独立复核；`engine.py`整组排料；`exporting.py`生产输出；`native_bridge.py`原生保存与后台导出；`desktop_launcher.py`桌面启动；`web/`中文界面；`tests/`测试；`examples/`明确标注的虚构样本。
