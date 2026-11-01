# 模型管理

卡通风格的 Windows AI API Key 管理工具：把各家大模型的 API Key、Base URL、模型名集中到一张张卡片里，
搜索、分类、复制、分享、导入导出都在一个窗口完成。单文件绿色版，配置保存在 exe 同目录的 `api_keys.json`，
拷走整个文件夹就能换电脑使用。

当前版本：**v1.1.0**（任务栏显示修复版）

![主界面](docs/screenshot-main.png)

## 功能

- **服务卡片**：名称、模型、Base URL、密钥掩码、备注一目了然
- **搜索**：按服务名称 / 模型 / URL 实时筛选
- **分类**：全部、国内模型、国际模型，可自定义分类并管理
- **服务管理**：新建、编辑、删除，多选批量删除、批量分享
- **复制与分享**：一键复制密钥，一键分享到微信
- **导入导出**：JSON 配置备份与迁移
- **置顶**：单张卡片置顶、窗口置顶
- **绿色单文件**：数据与程序同目录，不写注册表

## 本版更新（v1.1.0）

- **修复启动后任务栏不显示。** 主窗口是无边框窗口，Tk 会创建两层 HWND：内层 `TkChild` 和外层
  `TkTopLevel`，任务栏只认外层。原程序把 `WS_EX_APPWINDOW` 加到了内层，外层仍带
  `WS_EX_TOOLWINDOW (0x80)`，所以任务栏一直没有按钮。现在改为对外层设置 `WS_EX_APPWINDOW`、
  清除 `WS_EX_TOOLWINDOW`，并做一次隐藏/重显，让资源管理器登记按钮。
- 界面布局、窗口尺寸、图标、配置格式均未改动。

## 下载

- GitHub Releases：<https://github.com/wenming758/model-manager/releases>
- Gitee Releases：<https://gitee.com/wenming760/model-manager/releases>

运行环境：Windows 10 / 11 64 位，无需安装 Python。

## 目录说明

| 路径 | 说明 |
| --- | --- |
| `模型管理.exe` | 单文件主程序 |
| `workflow/taskbar_fix_hook.py` | 任务栏修复运行时钩子（源码） |
| `workflow/repack_taskbar_fix.py` | 把钩子注入现有 PyInstaller exe 的脚本 |
| `workflow/README.md` | 修复原理与复现步骤 |
| `api_keys.example.json` | 配置示例（不含真实密钥） |
| `docs/screenshot-main.png` | 界面截图 |

> 发布物为单文件 exe，仓库不包含原始 Python 工程；`workflow/` 提供本次修复的可复现流程。

## 数据安全

- 真实密钥只保存在本机 `api_keys.json`，该文件已加入 `.gitignore`，不会上传。
- 界面默认对密钥做掩码显示，分享前请再次确认。

## 更新日志

- **v1.1.0**：修复启动后任务栏不显示；界面布局保持不变。
