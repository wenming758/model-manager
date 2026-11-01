# 模型管理 · 改包工作流

本目录记录在不改动原程序布局的前提下，对已打包的 `模型管理.exe` 做增量改造的完整流程：

- 任务栏显示修复（v1.1.0）
- 新图标：exe 文件图标、窗口/任务栏图标、标题栏图标（v1.1.1）
- 卡通壁纸背景 + 加深配色（v1.1.2）
- Gitee 在线更新：全量下载 + 校验 + 覆盖重启（v1.1.2）
- 增量更新：归档条目级补丁，只下载变化的条目（v1.1.3）
- 启动自动检测更新、最大化自适应布局、壁纸跟随缩放、更新覆盖加固（v1.1.4）

所有改动通过 PyInstaller 运行时钩子注入，不反编译、不重建原程序。

## 一、任务栏不显示

### 根因

主窗口是无边框窗口（`root.overrideredirect(True)`）。Tk 在 Windows 上会创建两层 HWND：

- `winfo_id()` → 内部 `TkChild` 窗口
- `GetParent(winfo_id())` → 顶层 `TkTopLevel` 窗口（任务栏只认这一层）

原程序把 `WS_EX_APPWINDOW` 加到了 `TkChild` 上，而顶层窗口仍带着
`WS_EX_TOOLWINDOW (0x80)`，所以任务栏始终不显示按钮。

只改扩展样式还不够：窗口已经显示时资源管理器不会重新登记按钮，需要隐藏后重新显示一次。

### 修复

`update_hook.py` 只挂接 `tkinter.Tk.overrideredirect`（仅主窗口，`Toplevel` 弹窗不受影响）：

1. 对 `GetParent(winfo_id())` 对应的顶层窗口清除 `WS_EX_TOOLWINDOW`、设置 `WS_EX_APPWINDOW`；
2. `SetWindowPos(..., SWP_FRAMECHANGED)` 刷新；
3. `withdraw()` → 60ms 后 `deiconify()`，让任务栏重新登记按钮；
4. 重显时补上标题栏图标、检测更新按钮和壁纸。

## 二、图标

- 素材：`assets/icon_128.png`（窗口/任务栏）、`assets/icon_title.png`（标题栏），
  多尺寸 `../model_manager.ico`（16/24/32/48/64/128/256）。
- 运行时：`iconphoto(True, ...)` 设置任务栏与 Alt-Tab 图标；标题栏图标插在标题文字左侧。
- 文件图标：`apply_exe_icon.py` 用 Win32 资源 API 重写 `RT_ICON` / `RT_GROUP_ICON`。
  **注意**：`UpdateResource` 会截断 PyInstaller 追加在 exe 末尾的归档，脚本会先保存 overlay，
  更新资源后再原样接回。

## 三、卡通主题

- 配色：`repack_taskbar_fix.py` 中的 `THEME` 表，把主脚本里的浅色常量替换为加深的天空蓝系；
  只替换颜色常量，不动任何布局与控件结构。
- 壁纸：钩子找到主内容区最大的 Canvas，把壁纸作为最底层 image item 插入，
  并每 150ms 跟随滚动固定在视口顶部；卡片、工具栏背景不变。
- 缩放（v1.1.4）：Canvas `<Configure>` 防抖 220ms、尺寸变化 ≥16px 时，用 GDI+ 的
  HighQualityBicubic + `PixelOffsetMode` 重新采样原图，按 cover 模式裁剪填充视口，
  保持宽高比、不留白，`PhotoImage` 只保留当前这一张。

## 三之二、最大化自适应（v1.1.4）

- `_install_card_flow` 定位内容 Canvas → window item → 卡片容器（子项最多的 grid 容器）。
- 列数 = `可用宽度 // 248`（原布局卡片宽 232 + 间距 16），最少 4 列、最多卡片数；
  行宽通过 `canvas.itemconfigure(item, width=...)` 拉满，卡片统一 `weight=1` 平分。
- 8 张卡片实测：1100 宽 4 列、1600 宽 6 列、1920 宽 7 列，卡片右边缘不越界；
  窗口缩回原尺寸时恢复原始 4 列与自动宽度。
- 用 500ms 轮询 + `<Configure>` 双保险，兼容拖动缩放和系统最大化。

## 四、在线更新

- 更新源：Gitee Releases 最新版
  `https://gitee.com/api/v5/repos/wenming760/model-manager/releases/latest`
- 发布物需要三个附件：`model-manager-v<版本>.exe`、`model-manager-v<版本>.json`、
  `model-manager-v<版本>.patch`（增量补丁，跨版本升级时为可选）。
- 补丁原理：PyInstaller onefile 的末尾是 CArchive，由 PE 前缀 + 条目区 + TOC + cookie 组成。
  `make_update_manifest.py --base <上一版 exe>` 对比两版归档条目，只把变化的条目
  （主脚本、运行时钩子等）打进 `.patch`，其余条目客户端直接复用本地 exe，再重建 TOC 与 cookie。
  2026-11-01 的 v1.1.3 → v1.1.4 只有 2/958 个条目变化，补丁 476 KB（全量 11 MB）。
- 客户端流程：
  1. 请求 latest，比较 `tag_name` 与内置版本；
  2. 本地 exe SHA-256 与清单 `base_sha256` 一致时下载 `.patch`，校验补丁 SHA-256 后拼装；
  3. 校验整包 SHA-256；补丁缺失、基准版本不同或校验失败则回退全量下载并再次校验；
  4. 生成临时 `.bat`：等待进程退出 → 复制为 `目标.new` → PowerShell 校验 SHA-256 →
     `move /Y` 原子改名覆盖（失败重试 60 次）→ 启动新版 → 清理自身；
     校验不通过时绝不覆盖，重试耗尽则直接启动旧版本；
  5. 只覆盖 exe，`api_keys.json` 保留。
- 覆盖加固（v1.1.4）：旧流程直接 `copy /Y` 到目标，进程退出瞬间可能只写入半截文件，
  下次启动就会报 `Failed to load Python DLL ... 找不到指定的模块`。现在改为
  "先写 `.new` + 哈希校验 + 同目录原子改名"，目标文件要么是完整旧版、要么是完整新版，
  不会出现半截文件被当成新版启动。
- 启动自动检查（v1.1.4）：`_reshow` 完成后 2.5 秒调用 `_check_update(window, True)`，
  `_mm_auto_checked` 保证每个进程只自动检查一次；无更新或网络失败时完全静默。
- 注意：Gitee 的下载 CDN 不支持 HTTP `Range`（实测返回 200 + 完整文件），
  因此不能按字节区间做分块增量，必须走"条目级补丁 + 全量兜底"。
- 下载使用系统自带的 `curl.exe`（HTTPS / 重定向），无 curl 时回退 PowerShell。

## 五、构建命令

要求本机 Python 3.12（与原程序打包版本一致）。

```bash
# 1. 注入钩子 + 改版本号 + 加深配色（基于原始 exe）
python workflow/repack_taskbar_fix.py "模型管理 - 副本.exe" "模型管理.exe" --version 1.1.4

# 2. 替换 exe 图标（保留 PyInstaller 归档）
python workflow/apply_exe_icon.py "模型管理.exe" "model_manager.ico"

# 3. 生成更新清单 + 相对上一版的增量补丁（发布用）
python workflow/make_update_manifest.py "model-manager-v1.1.4.exe" "1.1.4"     "model-manager-v1.1.4.json" "model-manager-v1.1.4.patch" --base "model-manager-v1.1.3.exe"
```

`--no-theme` 可跳过配色替换；`--version` 会同时同步主脚本版本号与钩子里的版本常量。

## 六、验证

- 启动后任务栏出现机器人图标与「API模型管理 v1.1.4」按钮；
- 标题栏左侧有机器人图标，右侧有「⟳ 检测更新」，点击应弹出「当前已是最新版本」或新版说明；
- 增量链路：用上一版 exe + `.patch` 在本地拼装，结果应与新 exe 的 SHA-256 完全一致；
- 补丁损坏 / base 不匹配时应静默回退全量下载，不会写入未校验的文件。
- 启动 3 秒后无更新时不弹窗；存在新版时弹出说明并可一键更新；
- 最大化后卡片自动增加列数并铺满，壁纸随窗口缩放且不变形；恢复原尺寸回到 4 列；
- 主界面布局、卡片结构、搜索/分类/编辑弹窗保持原样；
- 最小化 / 恢复后任务栏按钮仍在。

## 七、回滚

用目录中的 `模型管理 - 副本.exe` 覆盖 `模型管理.exe` 即可。
