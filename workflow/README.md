# 模型管理 · 任务栏显示修复工作流

## 现象

双击 `模型管理.exe` 后窗口正常显示，但任务栏没有对应的按钮/图标。
最小化后按钮才出现。

## 根因

主窗口是无边框窗口（`root.overrideredirect(True)`）。Tk 在 Windows 上会创建两层 HWND：

- `winfo_id()` → 内部 `TkChild` 窗口
- `GetParent(winfo_id())` → 顶层 `TkTopLevel` 窗口（任务栏只认这一层）

原程序把 `WS_EX_APPWINDOW` 加到了 `TkChild` 上，而顶层窗口仍带着
`WS_EX_TOOLWINDOW (0x80)`，所以任务栏始终不显示按钮。

另外，仅修改扩展样式还不够：窗口已经显示时，资源管理器不会重新登记按钮，
需要隐藏后重新显示一次。

## 修复方式（只改任务栏，不动界面布局）

`taskbar_fix_hook.py` 作为 PyInstaller 运行时钩子，在应用主脚本之前执行：

1. 只挂接 `tkinter.Tk.overrideredirect`，仅作用于主窗口；
   `Toplevel` 吐司、编辑弹窗不受影响，不会多出任务栏按钮。
2. 对 `GetParent(winfo_id())` 对应的顶层窗口：
   清除 `WS_EX_TOOLWINDOW`，设置 `WS_EX_APPWINDOW`。
3. `withdraw()` → 60ms 后 `deiconify()`，让任务栏重新登记按钮。

窗口尺寸、位置、自定义标题栏、卡片布局、图标、配置文件均未改动。

## 文件说明

| 文件 | 作用 |
| --- | --- |
| `taskbar_fix_hook.py` | 运行时钩子源码 |
| `repack_taskbar_fix.py` | 把钩子注入现有 PyInstaller onefile exe |
| `README.md` | 本说明 |

## 重新生成修复版

在本目录（`windows程序\模型管理`）执行：

```bash
python workflow/repack_taskbar_fix.py "模型管理 - 副本.exe" "模型管理.exe"
```

要求本机 Python 3.12（与原程序打包版本一致）。
脚本只新增一个 `pyi_rth_taskbar_fix` 归档项，其它资源原样保留。

## 验证结果

- 启动后任务栏出现「API模型管理 v1.1.0」按钮；
- 顶层窗口样式：`WS_EX_APPWINDOW=True`、`WS_EX_TOOLWINDOW=False`；
- 主界面布局与修复前一致；
- 最小化 / 恢复后按钮仍在。

## 回滚

用目录中的 `模型管理 - 副本.exe` 覆盖 `模型管理.exe` 即可。
