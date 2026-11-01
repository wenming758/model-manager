# 模型管理

卡通风格的 Windows AI API Key 管理工具：把各家大模型的 API Key、Base URL、模型名集中到一张张卡片里，
搜索、分类、复制、分享、导入导出都在一个窗口完成。单文件绿色版，配置保存在 exe 同目录的 `api_keys.json`，
拷走整个文件夹就能换电脑使用。

当前版本：**v1.1.2**（在线更新 + 卡通主题版）

![主界面](docs/screenshot-main.png)

## 功能

- **服务卡片**：名称、模型、Base URL、密钥掩码、备注一目了然
- **搜索**：按服务名称 / 模型 / URL 实时筛选
- **分类**：全部、国内模型、国际模型，可自定义分类并管理
- **服务管理**：新建、编辑、删除，多选批量删除、批量分享
- **复制与分享**：一键复制密钥，一键分享到微信
- **导入导出**：JSON 配置备份与迁移
- **置顶**：单张卡片置顶、窗口置顶
- **检测更新**：标题栏右上角一键检查，Gitee 更新源，增量下载后覆盖自身并重启
- **卡通主题**：加深的天空蓝配色 + 卡通壁纸背景 + 机器人图标
- **绿色单文件**：数据与程序同目录，不写注册表

## 本版更新（v1.1.2）

- **新增「检测更新」**：读取 Gitee Releases 最新版本，发现新版本后按分块清单只下载变化的块，
  拼装完成后用 SHA-256 校验，校验通过才覆盖当前 exe，并自动重启；配置 `api_keys.json` 不受影响。
  更新源不可用时全程只读，不会改动本地文件。
- **卡通主题**：整体配色加深（天空蓝底、深蓝主色、更清晰的边框），内容区铺卡通壁纸，
  标题栏加入机器人图标。
- 界面布局、窗口尺寸、卡片结构、配置格式均保持不变。

## 更新方式

程序内：点击标题栏右上角「⟳ 检测更新」→ 有新版会提示版本号与更新说明 → 确认后自动下载并校验 →
重启即可完成覆盖更新。

手动：到下方 Releases 下载最新 exe，直接覆盖旧文件，`api_keys.json` 保留。

## 下载

- GitHub Releases：<https://github.com/wenming758/model-manager/releases>
- Gitee Releases：<https://gitee.com/wenming760/model-manager/releases>

运行环境：Windows 10 / 11 64 位，无需安装 Python。

## 目录说明

| 路径 | 说明 |
| --- | --- |
| `模型管理.exe` | 单文件主程序 |
| `workflow/update_hook.py` | 运行时钩子：任务栏、图标、卡通背景、在线更新 |
| `workflow/repack_taskbar_fix.py` | 把钩子注入现有 PyInstaller exe，并改写版本号与主题配色 |
| `workflow/apply_exe_icon.py` | 替换 exe 的 RT_ICON / RT_GROUP_ICON（保留 PyInstaller 归档） |
| `workflow/make_update_manifest.py` | 生成增量更新清单（分块 SHA-1 + 整包 SHA-256） |
| `workflow/assets/` | 图标与壁纸素材 |
| `workflow/README.md` | 构建、更新机制与回滚说明 |
| `api_keys.example.json` | 配置示例（不含真实密钥） |
| `docs/screenshot-main.png` | 界面截图 |

> 发布物为单文件 exe，仓库不包含原始 Python 工程；`workflow/` 提供可复现的改包流程。

## 数据安全

- 真实密钥只保存在本机 `api_keys.json`，该文件已加入 `.gitignore`，不会上传。
- 界面默认对密钥做掩码显示，分享前请再次确认。
- 更新只覆盖 exe，不读取、不上传本地配置。

## 更新日志

- **v1.1.2**：新增 Gitee 在线更新（增量下载、SHA-256 校验、覆盖重启）；卡通壁纸与加深配色；修复标题栏图标。
- **v1.1.1**：启用新机器人图标（exe 文件图标、任务栏、窗口与标题栏）。
- **v1.1.0**：修复启动后任务栏不显示；界面布局保持不变。
