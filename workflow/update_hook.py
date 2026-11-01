"""PyInstaller 运行时钩子：任务栏图标、标题栏图标、卡通背景、在线更新。

只处理 Tk 根窗口（主窗口），不影响 Toplevel 弹窗的内容布局。
占位符 __APP_VERSION__ / __ICON_PNG_B64__ / __ICON_TITLE_B64__ / __BG_PNG_B64__
由 workflow/repack_taskbar_fix.py 在打包时替换。
"""
import base64
import ctypes
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time

_APP_VERSION = "__APP_VERSION__"
_ICON_PNG_B64 = "__ICON_PNG_B64__"
_ICON_TITLE_B64 = "__ICON_TITLE_B64__"
_BG_PNG_B64 = "__BG_PNG_B64__"

_REPO = "wenming760/model-manager"
_REPO_PAGE = "https://gitee.com/" + _REPO
_API_LATEST = "https://gitee.com/api/v5/repos/" + _REPO + "/releases/latest"
_UA = "ModelManager-Update/" + _APP_VERSION
_NO_WINDOW = 0x08000000
_CHUNK = 512 * 1024


def _photo(window, data_b64, cache_name):
    photo = getattr(window, cache_name, None)
    if photo is not None:
        return photo
    import tkinter
    photo = tkinter.PhotoImage(master=window, data=base64.b64decode(data_b64))
    setattr(window, cache_name, photo)
    return photo


def _set_window_icon(window):
    try:
        window.iconphoto(True, _photo(window, _ICON_PNG_B64, "_mm_window_icon"))
    except Exception:
        pass


def _find_title_label(window):
    import tkinter
    title = ""
    try:
        title = window.title()
    except Exception:
        pass
    best = [None, ""]

    def walk(widget):
        for child in widget.winfo_children():
            if isinstance(child, tkinter.Label):
                try:
                    text = child.cget("text")
                except Exception:
                    text = ""
                if text and (text == title or title.startswith(text)) and len(text) > len(best[1]):
                    best[0] = child
                    best[1] = text
            walk(child)

    walk(window)
    return best[0]


def _insert_title_icon(window):
    try:
        if getattr(window, "_mm_title_logo", None) is not None:
            return
        title_label = _find_title_label(window)
        if title_label is None:
            return
        import tkinter
        bar = title_label.master
        photo = _photo(window, _ICON_TITLE_B64, "_mm_title_icon_photo")
        logo = tkinter.Label(bar, image=photo, bd=0, highlightthickness=0,
                             bg=bar.cget("bg"))
        logo.pack(side=tkinter.LEFT, before=title_label, padx=(12, 0))
        window._mm_title_logo = logo
    except Exception:
        pass


def _install_background(window):
    """把卡通壁纸铺在最大画布的最底层，并跟随滚动固定在视口顶部。"""
    try:
        import tkinter
        if getattr(window, "_mm_bg_item", None) is not None:
            return
        best = [None, 0]

        def walk(widget):
            for child in widget.winfo_children():
                if child.winfo_class() == "Canvas":
                    area = child.winfo_width() * child.winfo_height()
                    if child.winfo_width() > 500 and child.winfo_height() > 200 and area > best[1]:
                        best[0] = child
                        best[1] = area
                walk(child)

        walk(window)
        canvas = best[0]
        if canvas is None:
            tries = getattr(window, "_mm_bg_tries", 0)
            if tries < 20:
                window._mm_bg_tries = tries + 1
                window.after(250, lambda: _install_background(window))
            return
        photo = _photo(window, _BG_PNG_B64, "_mm_bg_photo")
        item = canvas.create_image(0, 0, anchor="nw", image=photo)
        canvas.tag_lower(item)
        window._mm_bg_item = item

        def keep():
            try:
                if not canvas.winfo_exists():
                    return
                canvas.coords(item, 0, int(canvas.canvasy(0)))
                window.after(150, keep)
            except Exception:
                pass

        keep()
    except Exception:
        pass


# ---------------------------------------------------------------- 在线更新

def _run(cmd, timeout=60):
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          timeout=timeout, creationflags=_NO_WINDOW)


def _curl():
    found = shutil.which("curl")
    if found:
        return found
    cand = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "curl.exe")
    return cand if os.path.exists(cand) else None


def _curl_json(url):
    exe = _curl()
    if exe:
        out = _run([exe, "-sSL", "--fail", "--max-time", "20", "-A", _UA, url], timeout=30)
        if out.returncode == 0 and out.stdout.strip():
            return json.loads(out.stdout.decode("utf-8", "replace"))
        raise RuntimeError("更新源无响应")
    script = ("$ProgressPreference='SilentlyContinue';"
              "(Invoke-RestMethod -UseBasicParsing -Uri '" + url + "' "
              "-Headers @{'User-Agent'='" + _UA + "'} -TimeoutSec 20) | ConvertTo-Json -Depth 6")
    out = _run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script], timeout=40)
    if out.returncode != 0 or not out.stdout.strip():
        raise RuntimeError("更新源无响应")
    return json.loads(out.stdout.decode("utf-8-sig", "replace"))


def _latest_release():
    data = _curl_json(_API_LATEST)
    tag = str(data.get("tag_name") or "")
    assets = data.get("assets") or []
    exe = manifest = None
    for a in assets:
        name = str(a.get("name") or "")
        url = str(a.get("browser_download_url") or "")
        if not url.startswith("https://"):
            continue
        if name.lower().endswith(".exe"):
            exe = url
        elif name.lower().endswith(".json"):
            manifest = url
    return tag, str(data.get("name") or ""), str(data.get("body") or ""), exe, manifest


def _version_tuple(text):
    nums = []
    cur = ""
    for ch in str(text or ""):
        if ch.isdigit():
            cur += ch
        elif cur:
            nums.append(int(cur))
            cur = ""
    if cur:
        nums.append(int(cur))
    while len(nums) < 3:
        nums.append(0)
    return tuple(nums[:3])


def _download_full(url, path):
    exe = _curl()
    if exe:
        if os.path.exists(path):
            os.remove(path)
        out = _run([exe, "-L", "--fail", "--retry", "2", "--max-time", "600",
                    "-A", _UA, "-o", path, url], timeout=620)
        if out.returncode != 0 or not os.path.exists(path):
            raise RuntimeError("下载失败")
        return
    script = ("$ProgressPreference='SilentlyContinue';"
              "Invoke-WebRequest -UseBasicParsing -Uri '" + url + "' -OutFile '" + path + "' "
              "-Headers @{'User-Agent'='" + _UA + "'} -TimeoutSec 600")
    out = _run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script], timeout=620)
    if out.returncode != 0 or not os.path.exists(path):
        raise RuntimeError("下载失败")


def _download_range(url, start, end):
    exe = _curl()
    if not exe:
        return None
    out = _run([exe, "-sSL", "--fail", "--max-time", "120", "-A", _UA,
                "-r", "%d-%d" % (start, end), url], timeout=130)
    if out.returncode != 0:
        return None
    return out.stdout


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _delta_download(local_exe, manifest, url, dest, progress):
    """按分块哈希只下载变化的部分；失败返回 False 交给全量下载。"""
    size = int(manifest.get("size") or 0)
    chunk = int(manifest.get("chunk") or 0)
    hashes = manifest.get("chunks") or []
    if size <= 0 or chunk <= 0 or not hashes or not os.path.exists(local_exe):
        return False
    try:
        with open(local_exe, "rb") as f:
            data = f.read()
    except Exception:
        return False
    if len(data) != size or len(hashes) != (size + chunk - 1) // chunk:
        return False
    need = [i for i, h in enumerate(hashes)
            if hashlib.sha1(data[i * chunk:min(size, (i + 1) * chunk)]).hexdigest() != h]
    if not need:
        with open(dest, "wb") as f:
            f.write(data)
        return True
    total = sum(min(size, (i + 1) * chunk) - i * chunk for i in need)
    done = 0
    buf = bytearray(data)
    for i in need:
        start, end = i * chunk, min(size, (i + 1) * chunk)
        piece = _download_range(url, start, end - 1)
        if piece is None or len(piece) != end - start:
            return False
        buf[start:end] = piece
        done += end - start
        progress(done, total)
    with open(dest, "wb") as f:
        f.write(bytes(buf))
    return True


def _update_batch(stage, target, pid):
    bat = os.path.join(tempfile.gettempdir(), "mm_update_%d.bat" % int(time.time()))
    body = f"""@echo off
chcp 65001 >nul
:wait
tasklist /FI "PID eq {pid}" 2>nul | find "{pid}" >nul
if not errorlevel 1 (
  timeout /t 1 /nobreak >nul
  goto wait
)
set n=0
:copy
copy /Y "{stage}" "{target}" >nul 2>&1
if not errorlevel 1 goto run
set /a n+=1
if %n% geq 40 goto run
timeout /t 1 /nobreak >nul
goto copy
:run
start "" "{target}"
del "{stage}" >nul 2>&1
del "%~f0" >nul 2>&1
"""
    with open(bat, "w", encoding="utf-8", newline="\r\n") as f:
        f.write(body)
    subprocess.Popen(["cmd", "/c", bat], creationflags=_NO_WINDOW, close_fds=True)


def _apply_update(window, new_exe):
    import tkinter
    from tkinter import messagebox
    target = sys.executable if getattr(sys, "frozen", False) else None
    if not target:
        messagebox.showinfo("更新完成", "新版本已下载到：\n" + new_exe, parent=window)
        return
    try:
        stage = os.path.join(os.path.dirname(target), ".mm_update.exe")
        shutil.copyfile(new_exe, stage)
    except Exception:
        stage = new_exe
    _update_batch(stage, target, os.getpid())
    window.destroy()
    os._exit(0)


def _center(top, parent):
    parent.update_idletasks()
    top.update_idletasks()
    w, h = top.winfo_width(), top.winfo_height()
    x = parent.winfo_rootx() + (parent.winfo_width() - w) // 2
    y = parent.winfo_rooty() + (parent.winfo_height() - h) // 3
    top.geometry("+%d+%d" % (max(x, 0), max(y, 0)))


def _run_update(window, version, url, manifest_url, info):
    import tkinter
    from tkinter import messagebox, ttk

    top = tkinter.Toplevel(window)
    top.title("正在更新")
    top.configure(bg="#FFFFFF")
    top.resizable(False, False)
    top.geometry("400x160")
    top.transient(window)
    tkinter.Label(top, text="正在获取 v%s 更新包…" % version, bg="#FFFFFF", fg="#16233A",
                  font=("Microsoft YaHei UI", 10)).pack(pady=(24, 10))
    bar = ttk.Progressbar(top, length=330, mode="determinate", maximum=100)
    bar.pack(pady=4)
    hint = tkinter.Label(top, text="", bg="#FFFFFF", fg="#566E8A",
                         font=("Microsoft YaHei UI", 9))
    hint.pack(pady=4)
    _center(top, window)

    tmp_dir = os.path.join(tempfile.gettempdir(), "mm_update")
    try:
        os.makedirs(tmp_dir, exist_ok=True)
    except Exception:
        pass
    dest = os.path.join(tmp_dir, "model-manager-v%s.exe" % version)

    def ui(fn):
        try:
            window.after(0, fn)
        except Exception:
            pass

    def progress(done, total):
        pct = 100 if total <= 0 else min(100, int(done * 100 / total))
        def show():
            try:
                bar["value"] = pct
                hint.config(text="%d%%  ·  %.1f MB / %.1f MB" % (pct, done / 1048576, total / 1048576))
            except Exception:
                pass
        ui(show)

    def work():
        try:
            manifest = None
            if manifest_url:
                try:
                    manifest = _curl_json(manifest_url)
                except Exception:
                    manifest = None
            ok = False
            if manifest and isinstance(manifest, dict):
                want = int(manifest.get("size") or 0)
                ui(lambda: hint.config(text="正在比对本地文件…"))
                ok = _delta_download(sys.executable, manifest, url, dest, progress)
            if not ok:
                ui(lambda: hint.config(text="正在下载完整更新包…"))
                _download_full(url, dest)
                progress(os.path.getsize(dest), os.path.getsize(dest))
            if manifest and manifest.get("sha256"):
                ui(lambda: hint.config(text="正在校验更新包…"))
                if _sha256(dest) != str(manifest["sha256"]).lower():
                    _download_full(url, dest)
                    if _sha256(dest) != str(manifest["sha256"]).lower():
                        raise RuntimeError("更新包校验失败")

            def finish():
                try:
                    top.destroy()
                except Exception:
                    pass
                if messagebox.askyesno("更新已就绪", "新版本 v%s 下载完成并已校验。\n\n现在重启并覆盖安装吗？" % version,
                                       parent=window):
                    _apply_update(window, dest)
                else:
                    messagebox.showinfo("已跳过", "更新包已保存在：\n" + dest, parent=window)

            ui(finish)
        except Exception as exc:
            def fail():
                try:
                    top.destroy()
                except Exception:
                    pass
                messagebox.showerror("更新失败", "无法完成更新：\n%s\n\n请稍后重试。" % exc, parent=window)
            ui(fail)

    threading.Thread(target=work, daemon=True).start()


def _check_update(window):
    import tkinter
    from tkinter import messagebox

    if getattr(window, "_mm_update_busy", False):
        return
    window._mm_update_busy = True
    btn = getattr(window, "_mm_update_btn", None)
    if btn is not None:
        try:
            btn.config(text="检测中…")
        except Exception:
            pass

    def done():
        window._mm_update_busy = False
        if btn is not None:
            try:
                btn.config(text="⟳ 检测更新")
            except Exception:
                pass

    def work():
        try:
            tag, name, body, url, manifest_url = _latest_release()
        except Exception as exc:
            def fail():
                done()
                messagebox.showerror("检测更新失败", "无法连接 Gitee 更新源。\n\n%s" % exc, parent=window)
            window.after(0, fail)
            return
        newest = _version_tuple(tag)
        current = _version_tuple(_APP_VERSION)
        if not tag or newest <= current:
            def up_to_date():
                done()
                messagebox.showinfo("检测更新", "当前已是最新版本 v%s。" % _APP_VERSION, parent=window)
            window.after(0, up_to_date)
            return
        if not url:
            def no_asset():
                done()
                messagebox.showwarning("检测更新", "发现新版本 %s，但更新源缺少安装包。" % tag, parent=window)
            window.after(0, no_asset)
            return
        notes = (body or "").strip()
        if len(notes) > 400:
            notes = notes[:400] + "…"
        text = "发现新版本 %s（当前 v%s）。\n\n%s\n\n是否立即下载并覆盖更新？" % (tag, _APP_VERSION, notes)
        def ask():
            done()
            if messagebox.askyesno("发现新版本", text, parent=window):
                _run_update(window, tag.lstrip("vV"), url, manifest_url, (tag, name, notes))
        window.after(0, ask)

    threading.Thread(target=work, daemon=True).start()


def _install_update_button(window):
    try:
        import tkinter
        if getattr(window, "_mm_update_btn", None) is not None:
            return
        title_label = _find_title_label(window)
        if title_label is None:
            return
        bar = title_label.master
        bg = bar.cget("bg")
        btn = tkinter.Label(bar, text="⟳ 检测更新", bg=bg, fg="#0B5FA8",
                            font=("Microsoft YaHei UI", 9), cursor="hand2",
                            bd=0, highlightthickness=0, padx=10)
        btn.pack(side=tkinter.RIGHT, padx=(0, 10))

        def enter(_):
            try:
                btn.config(fg="#C24E00")
            except Exception:
                pass

        def leave(_):
            try:
                btn.config(fg="#0B5FA8")
            except Exception:
                pass

        btn.bind("<Enter>", enter)
        btn.bind("<Leave>", leave)
        btn.bind("<Button-1>", lambda _e: _check_update(window))
        window._mm_update_btn = btn

    except Exception:
        pass


# ---------------------------------------------------------------- 任务栏修复

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
            _insert_title_icon(window)
            _install_update_button(window)
            _install_background(window)
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
            _set_window_icon(self)
            _fix_taskbar_style(self)
        return result

    tkinter.Tk.overrideredirect = _overrideredirect
except Exception:
    pass
