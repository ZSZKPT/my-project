# 店小秘 Excel 导入

依据用户提供的 `import_created_product_pddkj (2).xlsx` 模板生成，每尺码一行，同款使用相同标题。产品货号填文件夹货号，SKU 填货号-尺码。表中没有单独的 SKC 字段，实际平台映射需在店小秘导入后验证。此方法创建新商品，不复制现有商品的类目、属性或尺码表；上传后须核对并补齐页面要求，导入不代表发布成功。

Windows 项目目录命令提示符运行：

```bat
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install -r import_tools\requirements.txt
.venv\Scripts\python.exe import_tools\dianxiaomi.py --template "import_created_product_pddkj (2).xlsx" --config data\config.json --products data\products.csv --output data\店小秘导入.xlsx
```

将官方模板放到项目根目录。复制 `config.example.json` 和 `products.example.csv` 到 `data` 文件夹并改名。模板配置需真实标题规则、颜色、描述、各尺码申报价、包装长宽高与重量；示例 null 值必须填写，不猜测商品参数。

商品 CSV 按如下表头填写（可用 Excel 编辑后另存 CSV UTF-8）：

- `sku`：图片文件夹货号。
- `print_name`：手动填写印花名称。
- `carousel_urls`：公开可访问的商品图片链接，多张以 `|` 分隔，最多10张。
- `material_url`：素材图链接，必须 1:1 且大于800×800像素。
- `preview_url`：SKU 预览图链接；留空则使用第一张轮播图。

图片必须先通过店小秘支持的图片空间或你自己的图片存储获得外网可访问的链接，不能填写 C:\ 本地路径或本机服务地址。工具校验 URL 形式，不会上传图片，也未验证远端可访问性和尺寸。不要填写需要登录才能访问的链接。

生成表后先在店小秘导入一个商品核对：商品分组、尺码、货号、价格单位、图片、类目属性及尺码表。保留官方模板原有工作表和表头，工具只填“导入模板”。输出文件已存在时不会覆盖。
