# 模型管理 · 改包工作流

本目录记录在不改动原程序布局的前提下，对已打包的 `模型管理.exe` 做增量改造的完整流程：

- 任务栏显示修复（v1.1.0）
- 新图标：exe 文件图标、窗口/任务栏图标、标题栏图标（v1.1.1）
- 卡通壁纸背景 + 加深配色（v1.1.2）
- Gitee 在线更新：全量下载 + 校验 + 覆盖重启（v1.1.2）
- 增量更新：归档条目级补丁，只下载变化的条目（v1.1.3）
- 启动自动检测更新、最大化自适应布局、壁纸跟随缩放、更新覆盖加固（v1.1.4）
- 整窗壁纸 + 标题栏版本号 + 圆角窗口（v1.1.5）
- 标题栏贴合壁纸 + 版本号移到右上角 + 无边框窗口拖拽 + 流畅最大化（v1.1.6）

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
- 整窗铺满（v1.1.5）：改为**一张按窗口尺寸缩放的图**贯穿整个窗口——
  - 根窗口放一张同尺寸 Label 兜底，四个边框区域（标题栏/工具栏/内容区/状态栏）各放
    一张同样的 Label，用负的 `place(x, y)` 偏移对齐，视觉上拼成一张连续壁纸；
  - 内容 Canvas 用 `GdipCloneBitmapAreaI` 从窗口图上裁出画布矩形，避免 image item
    的负坐标把 `scrollregion` 撑大；
  - 缓存文件名带壁纸内容 SHA-1 前缀，换图后自动失效，不会读到旧图；
  - `resized` 只在窗口尺寸变化 ≥16px 时重建，避免自己的贴图触发的 Configure 把防抖
    定时器反复重置。
- 异步缩放（v1.1.6）：GDI+ 缩放在工作线程里完成并写出 `background_<sig>_<w>x<h>.png`，
  线程只写文件、不碰 Tk；220ms 的 `keep()` 轮询 `_mm_bg_ready` 拿到结果后再在主线程重建
  PhotoImage。缩放期间沿用上一张图，最大化不再白屏。
- 标题栏贴合（v1.1.6）：`_tint_titlebar` 对标题栏底色 Label、机器人图标 Label、标题 Label、
  版本 Label、「⟳ 检测更新」和三个控制按钮，各取所在矩形中心附近的 3×2 个像素点求平均色，
  设为控件 `bg`（Button 同时改 `activebackground`、`highlightbackground`）；
  `<Enter>` 变亮 14、`<Leave>` 还原。窗口重显、每次壁纸重建、宽度变化时都会重刷，
  避免在 `withdraw` 期间（子控件 1×1）取不到色而留下浅色块。

## 三之二、最大化自适应（v1.1.4）

- `_install_card_flow` 定位内容 Canvas → window item → 卡片容器（子项最多的 grid 容器）。
- 列数 = `可用宽度 // 248`（原布局卡片宽 232 + 间距 16），最少 4 列、最多卡片数；
  行宽通过 `canvas.itemconfigure(item, width=...)` 拉满，卡片统一 `weight=1` 平分。
- 8 张卡片实测：1100 宽 4 列、1600 宽 6 列、1920 宽 7 列，卡片右边缘不越界；
  窗口缩回原尺寸时恢复原始 4 列与自动宽度。
- 用 600ms 轮询 + `<Configure>`（280ms 防抖）双保险，兼容拖动缩放和系统最大化。
- 流畅化（v1.1.6）：原程序把 Canvas `<Configure>` 绑到 `_refresh_cards_safe`，
  每次尺寸变化都会销毁并重建全部卡片（8 张约 0.8 秒），最大化时肉眼可见卡顿。
  `_install_card_flow` 在接管布局时 `unbind("<Configure>")` 掉这个回调——启动时
  `__init__` 已经直接调用过 `_refresh_cards()`，取消绑定不影响首屏；
  重排时先 `itemconfigure(window item, state="hidden")`，网格改完再显示，减少撕裂。
  实测最大化耗时从约 1.1 秒降到 0.19 秒。

## 三之三、标题栏（v1.1.5 → v1.1.6）

- 版本号：v1.1.5 是把标题 Label 的文本改成「API模型管理  v<版本>」，结果
  `_find_title_label`（按文本匹配）找不到标题、`_install_update_button` 直接返回，
  「⟳ 检测更新」按钮消失。v1.1.6 改为**不动标题文本**：
  - `_find_title_label` 找到后缓存到 `window._mm_title_label`，后续复用；
  - `_install_version_label` 另建一个 Label（`text="v<版本>"`）`pack(side=RIGHT)`，
    与「⟳ 检测更新」同排在右上角，顺序为 `… ⟳ 检测更新 | v1.1.6 | ─ □ ✕`。
    版本号取钩子里的 `_APP_VERSION`。
- 圆角：Win10 没有 DWM 圆角属性，`_round_window` 对顶层 HWND 调用
  `SetWindowRgn` + `CreateRoundRectRgn(0, 0, w+1, h+1, 28, 28)`（直径 28 = 半径 14）；
  窗口尺寸达到屏幕大小（最大化）时换成矩形区域，保持直角。
- 圆角不再拖慢缩放（v1.1.6）：尺寸一变就套旧的圆角区域，新露出的部分会被裁掉不重绘，
  看起来就是撕裂/残影。现在尺寸变化时先套一个**整矩形**区域（`bRedraw=False`，
  让新区域能画出来），停稳 300ms 后再套圆角（`bRedraw=True`）。
- `<Configure>` 会派发给所有子控件（Tk bindtags 含顶层路径），处理器只在窗口尺寸真正
  变化时重新应用区域，避免频繁刷 `SetWindowRgn`。
- 拖拽（v1.1.6）：`_install_drag` 在**顶层**绑 `<ButtonPress-1>` / `<B1-Motion>` /
  `<ButtonRelease-1>`。因为无边框窗口没有系统标题栏，原程序也没做拖动，用户只能靠
  最大化/还原间接挪窗口。现在按住标题栏（或标题栏里除按钮外的文字区域）即可拖动：
  - 起点在标题栏内，且控件不是 Button / Entry / TCombobox / TEntry / Checkbutton /
    TSpinbox / Scrollbar（「⟳ 检测更新」与版本 Label 被显式加入白名单，可以拖）；
  - 仅非最大化状态生效；电机用 `event.x_root` 累加，`geometry("+x+y")` 直接定位。

## 四、在线更新

- 更新源：Gitee Releases 最新版
  `https://gitee.com/api/v5/repos/wenming760/model-manager/releases/latest`
- 发布物需要三个附件：`model-manager-v<版本>.exe`、`model-manager-v<版本>.json`、
  `model-manager-v<版本>.patch`（增量补丁，跨版本升级时为可选）。
- 补丁原理：PyInstaller onefile 的末尾是 CArchive，由 PE 前缀 + 条目区 + TOC + cookie 组成。
  `make_update_manifest.py --base <上一版 exe>` 对比两版归档条目，只把变化的条目
  （主脚本、运行时钩子等）打进 `.patch`，其余条目客户端直接复用本地 exe，再重建 TOC 与 cookie。
  2026-11-01 的 v1.1.4 → v1.1.5 只有 2/958 个条目变化，补丁 1.0 MB（全量 11.6 MB，壁纸变大所致）；
  v1.1.5 → v1.1.6 同样是 2/958 个条目（主脚本、钩子），补丁 1.0 MB。
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
# 1. 注入钩子 + 改版本号 + 加深配色（基于原始 exe，首次改造用）
python workflow/repack_taskbar_fix.py "模型管理 - 副本.exe" "模型管理.exe" --version 1.1.6

# 1'. 基于上一版发布 exe 升级（原始 exe 丢失时用 --replace：
#     原位替换已有的 pyi_rth_taskbar_fix 条目，跳过配色替换）
python workflow/repack_taskbar_fix.py "model-manager-v1.1.5.exe" "模型管理.exe" --version 1.1.6 --replace

# 2. 替换 exe 图标（保留 PyInstaller 归档）
python workflow/apply_exe_icon.py "模型管理.exe" "model_manager.ico"

# 3. 生成更新清单 + 相对上一版的增量补丁（发布用）
python workflow/make_update_manifest.py "model-manager-v1.1.6.exe" "1.1.6" \
    "model-manager-v1.1.6.json" "model-manager-v1.1.6.patch" --base "model-manager-v1.1.5.exe"
```

`--no-theme` 可跳过配色替换；`--version` 会同时同步主脚本版本号与钩子里的版本常量。
`--replace` 用于在已注入钩子的 exe 上做原位升级：不重复插入条目、不重跑配色替换，
只替换钩子字节与版本号。

## 六、验证

- 启动后任务栏出现机器人图标与「API模型管理 v1.1.6」按钮，标题栏显示「API模型管理」，
  右上角依次为「⟳ 检测更新」、「v1.1.6」、最小化/最大化/关闭；
- 标题栏左侧有机器人图标；点「⟳ 检测更新」应弹出「当前已是最新版本」或新版说明；
- 标题栏底色、图标底色、版本号底色、三个控制按钮底色与背后壁纸同色系，悬停略亮、
  移开还原，看不到浅色方块；
- 非最大化时按住标题栏可拖动窗口，拖动时最大化/关闭按钮不触发；最大化状态下拖动无效；
- 增量链路：用上一版 exe + `.patch` 在本地拼装，结果应与新 exe 的 SHA-256 完全一致；
- 补丁损坏 / base 不匹配时应静默回退全量下载，不会写入未校验的文件。
- 启动 3 秒后无更新时不弹窗；存在新版时弹出说明并可一键更新；
- 最大化后卡片自动增加列数并铺满，壁纸铺满整个窗口且与工具栏/状态栏连续；恢复原尺寸回到 4 列；
- 普通尺寸四角为圆角，最大化后为直角；最大化/还原过程不卡顿（实测 0.19 秒）、不长时间白屏；
  截图 `_tmp/v116_final_start.png`、`_tmp/v116_final_max.png` 可核对；
- 主界面布局、卡片结构、搜索/分类/编辑弹窗保持原样；
- 最小化 / 恢复后任务栏按钮仍在。

## 七、回滚

用目录中的 `模型管理 - 副本.exe` 覆盖 `模型管理.exe` 即可。
