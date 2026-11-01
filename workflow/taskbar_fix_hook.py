"""PyInstaller 运行时钩子：让无边框 Tk 主窗口显示在任务栏。

只处理 Tk 根窗口（主窗口），不影响 Toplevel 吐司/弹窗。
"""
import ctypes


def _fix_taskbar_style(window):
    try:
        window.update_idletasks()
        user32 = ctypes.windll.user32
        hwnd = user32.GetParent(window.winfo_id()) or window.winfo_id()
        GWL_EXSTYLE = -20
        WS_EX_TOOLWINDOW = 0x00000080
        WS_EX_APPWINDOW = 0x00040000
        ex_style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        user32.SetWindowLongW(
            hwnd, GWL_EXSTYLE, (ex_style & ~WS_EX_TOOLWINDOW) | WS_EX_APPWINDOW
        )
        user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0004 | 0x0020)
        # 任务栏按钮只在窗口重新显示时登记
        window.withdraw()

        def _reshow():
            try:
                window.deiconify()
            except Exception:
                pass

        window.after(60, _reshow)
    except Exception:
        pass


try:
    import tkinter

    _orig_overrideredirect = tkinter.Tk.overrideredirect

    def _overrideredirect(self, flag=None):
        result = _orig_overrideredirect(self, flag)
        if flag:
            _fix_taskbar_style(self)
        return result

    tkinter.Tk.overrideredirect = _overrideredirect
except Exception:
    pass
