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
import struct
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
_MEI_MAGIC = b"MEI\014\013\012\013\016"
_PATCH_MAGIC = b"MMP1"
_BG_SIG = hashlib.sha1(_BG_PNG_B64.encode("ascii", "ignore")).hexdigest()[:12]
_BG_PURGED = [False]
_gdip_lock = threading.Lock()


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
    cached = getattr(window, "_mm_title_label", None)
    if cached is not None:
        try:
            if cached.winfo_exists():
                return cached
        except Exception:
            pass
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
    if best[0] is not None:
        window._mm_title_label = best[0]
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


class _GdipStartup(ctypes.Structure):
    _fields_ = [("GdiplusVersion", ctypes.c_uint),
                ("DebugEventCallback", ctypes.c_void_p),
                ("SuppressBackgroundThread", ctypes.c_int),
                ("SuppressExternalCodecs", ctypes.c_int)]


class _GdipGuid(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_uint32), ("Data2", ctypes.c_uint16),
                ("Data3", ctypes.c_uint16), ("Data4", ctypes.c_ubyte * 8)]


_gdip = [None]


def _gdiplus():
    """加载 GDI+，用于把壁纸按窗口尺寸高质量缩放。"""
    if _gdip[0] is not None:
        return _gdip[0]
    try:
        lib = ctypes.WinDLL("gdiplus")
        lib.GdiplusStartup.argtypes = [ctypes.POINTER(ctypes.c_size_t),
                                       ctypes.POINTER(_GdipStartup), ctypes.c_void_p]
        lib.GdiplusStartup.restype = ctypes.c_int
        token = ctypes.c_size_t()
        start = _GdipStartup()
        start.GdiplusVersion = 1
        if lib.GdiplusStartup(ctypes.byref(token), ctypes.byref(start), None) != 0:
            return None
        for name, args in (
                ("GdipCreateBitmapFromFile", [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_void_p)]),
                ("GdipCreateBitmapFromScan0", [ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                               ctypes.c_int, ctypes.c_void_p,
                                               ctypes.POINTER(ctypes.c_void_p)]),
                ("GdipGetImageGraphicsContext", [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]),
                ("GdipSetInterpolationMode", [ctypes.c_void_p, ctypes.c_int]),
                ("GdipSetPixelOffsetMode", [ctypes.c_void_p, ctypes.c_int]),
                ("GdipSetClipRectI", [ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
                                      ctypes.c_int, ctypes.c_int, ctypes.c_int]),
                ("GdipGraphicsClear", [ctypes.c_void_p, ctypes.c_uint]),
                ("GdipDrawImageRectI", [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int,
                                        ctypes.c_int, ctypes.c_int, ctypes.c_int]),
                ("GdipSaveImageToFile", [ctypes.c_void_p, ctypes.c_wchar_p,
                                         ctypes.POINTER(_GdipGuid), ctypes.c_void_p]),
                ("GdipGetImageWidth", [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int)]),
                ("GdipGetImageHeight", [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int)]),
                ("GdipCloneBitmapAreaI", [ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                          ctypes.c_int, ctypes.c_int, ctypes.c_void_p,
                                          ctypes.POINTER(ctypes.c_void_p)]),
                ("GdipDisposeImage", [ctypes.c_void_p]),
                ("GdipDeleteGraphics", [ctypes.c_void_p])):
            fn = getattr(lib, name)
            fn.argtypes = args
            fn.restype = ctypes.c_int
        clsid = _GdipGuid()
        raw = __import__("uuid").UUID("{557cf406-1a04-11d3-9a73-0000f81ef32e}").bytes_le
        clsid.Data1 = int.from_bytes(raw[0:4], "little")
        clsid.Data2 = int.from_bytes(raw[4:6], "little")
        clsid.Data3 = int.from_bytes(raw[6:8], "little")
        for i in range(8):
            clsid.Data4[i] = raw[8 + i]
        _gdip[0] = (lib, token, clsid)
        return _gdip[0]
    except Exception:
        return None


def _scale_png(src, dst, width, height):
    with _gdip_lock:
        return _scale_png_impl(src, dst, width, height)


def _scale_png_impl(src, dst, width, height):
    """等比铺满（cover）并居中裁切。"""
    g = _gdiplus()
    if g is None:
        return False
    lib, _token, clsid = g
    try:
        width = max(64, min(int(width), 3840))
        height = max(64, min(int(height), 2160))
        bmp = ctypes.c_void_p()
        if lib.GdipCreateBitmapFromFile(src, ctypes.byref(bmp)) != 0:
            return False
        try:
            iw, ih = ctypes.c_int(), ctypes.c_int()
            lib.GdipGetImageWidth(bmp, ctypes.byref(iw))
            lib.GdipGetImageHeight(bmp, ctypes.byref(ih))
            if iw.value <= 0 or ih.value <= 0:
                return False
            out = ctypes.c_void_p()
            if lib.GdipCreateBitmapFromScan0(width, height, 0, 0x26200A,
                                             None, ctypes.byref(out)) != 0:
                return False
            try:
                gr = ctypes.c_void_p()
                lib.GdipGetImageGraphicsContext(out, ctypes.byref(gr))
                try:
                    lib.GdipSetInterpolationMode(gr, 7)
                    lib.GdipSetPixelOffsetMode(gr, 2)
                    lib.GdipGraphicsClear(gr, 0xFFCFE2F2)
                    lib.GdipSetClipRectI(gr, 0, 0, width, height, 1)
                    ratio = max(1.0 * width / iw.value, 1.0 * height / ih.value)
                    dw = max(1, int(iw.value * ratio + 0.5))
                    dh = max(1, int(ih.value * ratio + 0.5))
                    lib.GdipDrawImageRectI(gr, bmp, (width - dw) // 2, (height - dh) // 2, dw, dh)
                finally:
                    lib.GdipDeleteGraphics(gr)
                if lib.GdipSaveImageToFile(out, dst, ctypes.byref(clsid), None) != 0:
                    return False
            finally:
                lib.GdipDisposeImage(out)
        finally:
            lib.GdipDisposeImage(bmp)
        return os.path.exists(dst) and os.path.getsize(dst) > 0
    except Exception:
        return False


def _crop_png(src, dst, x, y, width, height):
    with _gdip_lock:
        return _crop_png_impl(src, dst, x, y, width, height)


def _crop_png_impl(src, dst, x, y, width, height):
    g = _gdiplus()
    if g is None:
        return False
    lib, _token, clsid = g
    try:
        bmp = ctypes.c_void_p()
        if lib.GdipCreateBitmapFromFile(src, ctypes.byref(bmp)) != 0:
            return False
        try:
            iw, ih = ctypes.c_int(), ctypes.c_int()
            lib.GdipGetImageWidth(bmp, ctypes.byref(iw))
            lib.GdipGetImageHeight(bmp, ctypes.byref(ih))
            x = max(0, min(int(x), max(iw.value - 1, 0)))
            y = max(0, min(int(y), max(ih.value - 1, 0)))
            width = max(1, min(int(width), iw.value - x))
            height = max(1, min(int(height), ih.value - y))
            out = ctypes.c_void_p()
            if lib.GdipCloneBitmapAreaI(x, y, width, height, 0x26200A, bmp,
                                        ctypes.byref(out)) != 0:
                return False
            try:
                if lib.GdipSaveImageToFile(out, dst, ctypes.byref(clsid), None) != 0:
                    return False
            finally:
                lib.GdipDisposeImage(out)
        finally:
            lib.GdipDisposeImage(bmp)
        return os.path.exists(dst) and os.path.getsize(dst) > 0
    except Exception:
        return False


def _bg_cache_dir():
    cache = os.path.join(tempfile.gettempdir(), "mm_bg")
    try:
        os.makedirs(cache, exist_ok=True)
    except Exception:
        return None
    return cache


def _bg_src_file():
    cache = _bg_cache_dir()
    if cache is None:
        return None, None
    src = os.path.join(cache, "background_src_%s.png" % _BG_SIG)
    if not os.path.exists(src):
        try:
            with open(src, "wb") as f:
                f.write(base64.b64decode(_BG_PNG_B64))
        except Exception:
            return None, None
    if not _BG_PURGED[0]:
        _BG_PURGED[0] = True
        for name in os.listdir(cache):
            if (name.startswith("background_") or name.startswith("canvas_")) \
                    and name.endswith(".png") and _BG_SIG not in name:
                try:
                    os.remove(os.path.join(cache, name))
                except Exception:
                    pass
    return cache, src


def _scaled_file(width, height):
    cache, src = _bg_src_file()
    if src is None:
        return None, None
    return src, os.path.join(cache, "background_%s_%dx%d.png" % (_BG_SIG, width, height))


def _background_photo(window, width, height):
    import tkinter
    key = (int(width), int(height))
    photos = getattr(window, "_mm_bg_photos", None)
    if photos is None:
        photos = window._mm_bg_photos = {}
    if key in photos:
        window._mm_bg_photo = photos[key]
        window._mm_bg_photo_key = key
        return photos[key]
    src, dst = _scaled_file(key[0], key[1])
    if src is None:
        return None
    if not os.path.exists(dst):
        if getattr(window, "_mm_bg_async_ok", False):
            # 缩放放到后台线程，拖动/最大化动画期间主线程不被阻塞
            if getattr(window, "_mm_bg_pending", None) != key:
                window._mm_bg_pending = key

                def work():
                    ok = _scale_png(src, dst, key[0], key[1])
                    window._mm_bg_ready = (key, ok)

                threading.Thread(target=work, daemon=True).start()
            return None
        if not _scale_png(src, dst, key[0], key[1]):
            return None
    try:
        photo = tkinter.PhotoImage(master=window, file=dst)
    except Exception:
        return None
    while len(photos) >= 4:
        photos.pop(next(iter(photos)), None)
    photos[key] = photo
    window._mm_bg_photo = photo
    window._mm_bg_photo_key = key
    return photo


def _canvas_photo(window, x, y, width, height, win_width, win_height):
    """从已缩放的整窗壁纸里裁出画布区域，保证与标题栏/状态栏完全对齐。"""
    import tkinter
    key = (int(x), int(y), int(width), int(height))
    full = ((int(win_width), int(win_height)), key)
    if getattr(window, "_mm_bg_canvas_key", None) == full:
        return window._mm_bg_canvas
    cache = _bg_cache_dir()
    if cache is None:
        return None
    src = os.path.join(cache, "background_%s_%dx%d.png"
                       % (_BG_SIG, int(win_width), int(win_height)))
    if not os.path.exists(src):
        return None
    dst = os.path.join(cache, "canvas_%s_%d_%d_%dx%d_%dx%d.png"
                       % ((_BG_SIG,) + key + (int(win_width), int(win_height))))
    if not os.path.exists(dst) and not _crop_png(src, dst, key[0], key[1], key[2], key[3]):
        return None
    try:
        photo = tkinter.PhotoImage(master=window, file=dst)
    except Exception:
        return None
    window._mm_bg_canvas = photo
    window._mm_bg_canvas_key = full
    return photo


def _sample_color(photo, x, y, width, height):
    """取控件范围若干点的平均色，让控件背景与壁纸贴合。"""
    total = [0, 0, 0]
    count = 0
    for fx in (0.25, 0.5, 0.75):
        px = int(x + width * fx)
        for fy in (0.3, 0.7):
            try:
                value = photo.get(px, int(y + height * fy))
            except Exception:
                continue
            parts = value if isinstance(value, (tuple, list)) else str(value).split()
            try:
                total[0] += int(parts[0])
                total[1] += int(parts[1])
                total[2] += int(parts[2])
            except Exception:
                continue
            count += 1
    if not count:
        return None
    return "#%02x%02x%02x" % (total[0] // count, total[1] // count, total[2] // count)


def _paint_widget(widget, color):
    cls = widget.winfo_class()
    try:
        widget.configure(bg=color)
    except Exception:
        pass
    if cls == "Button":
        try:
            widget.configure(activebackground=color)
        except Exception:
            pass
        try:
            if int(widget.cget("highlightthickness") or 0) > 0:
                widget.configure(highlightbackground=color, highlightcolor=color)
        except Exception:
            pass
    if not getattr(widget, "_mm_tint_bound", False):
        widget._mm_tint_bound = True

        def shade(color, delta):
            try:
                r = min(255, int(color[1:3], 16) + delta)
                g = min(255, int(color[3:5], 16) + delta)
                b = min(255, int(color[5:7], 16) + delta)
                return "#%02x%02x%02x" % (r, g, b)
            except Exception:
                return None

        def hover(_event=None, w=widget):
            color_ = getattr(w, "_mm_tint", None)
            hover_color = shade(color_, 14) if color_ else None
            if hover_color:
                try:
                    w.after(1, lambda: _paint_widget(w, hover_color))
                except Exception:
                    pass

        def restore(_event=None, w=widget):
            color_ = getattr(w, "_mm_tint", None)
            if not color_:
                return
            try:
                w.after(40, lambda: _paint_widget(w, color_))
            except Exception:
                pass

        for seq, handler in (("<Enter>", hover), ("<Leave>", restore)):
            try:
                widget.bind(seq, handler, add="+")
            except Exception:
                pass


def _tint_titlebar(window, photo):
    """标题栏各控件（图标、标题、版本号、检测更新、─ □ ✕）背景跟随壁纸。"""
    try:
        title = _find_title_label(window)
        if title is None:
            return
        bar = title.master
        rx, ry = window.winfo_rootx(), window.winfo_rooty()
        targets = [bar]

        def collect(widget):
            for child in widget.winfo_children():
                if getattr(child, "_mm_band", False):
                    continue
                if child.winfo_class() in ("Label", "Button", "Frame"):
                    targets.append(child)
                    if child.winfo_class() == "Frame":
                        collect(child)

        collect(bar)
        for widget in targets:
            try:
                w, h = widget.winfo_width(), widget.winfo_height()
                if w < 2 or h < 2:
                    continue
                color = _sample_color(photo, widget.winfo_rootx() - rx,
                                      widget.winfo_rooty() - ry, w, h)
                if color is None:
                    continue
                widget._mm_tint = color
                _paint_widget(widget, color)
            except Exception:
                continue
    except Exception:
        pass


def _install_background(window):
    """整窗壁纸：标题栏、工具栏、内容区、状态栏共用同一张按窗口尺寸缩放的图。"""
    try:
        import tkinter
        if getattr(window, "_mm_shell_on", False):
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
        window._mm_shell_on = True
        state = {"item": None, "photo": None, "size": (0, 0), "labels": [],
                 "root": None, "applied": None}

        def build():
            w, h = window.winfo_width(), window.winfo_height()
            if w < 400 or h < 300:
                return False
            photo = _background_photo(window, w, h)
            if photo is None:
                return False
            canvas_photo = _canvas_photo(window,
                                         canvas.winfo_rootx() - window.winfo_rootx(),
                                         canvas.winfo_rooty() - window.winfo_rooty(),
                                         canvas.winfo_width(), canvas.winfo_height(),
                                         w, h)
            if state["root"] is None:
                root_label = tkinter.Label(window, image=photo, bd=0, highlightthickness=0)
                root_label.place(x=0, y=0)
                root_label._mm_band = True
                state["root"] = root_label
            else:
                state["root"].configure(image=photo)
            if state["item"] is None:
                item = canvas.create_image(0, 0, anchor="nw",
                                           image=canvas_photo or photo)
                canvas.tag_lower(item)
                state["item"] = item
                window._mm_bg_item = item
            elif canvas_photo is not None:
                canvas.itemconfigure(state["item"], image=canvas_photo)
            # 条带背景标签复用，重排时只换图，避免反复销毁/创建造成闪烁
            frames = [c for c in window.winfo_children() if c.winfo_class() == "Frame"]
            spare = []
            for label in state["labels"]:
                try:
                    if label.winfo_exists():
                        spare.append(label)
                except Exception:
                    pass
            labels = []
            for frame in frames:
                label = None
                for old in spare:
                    if old.master is frame:
                        label = old
                        spare.remove(old)
                        break
                if label is None:
                    label = tkinter.Label(frame, image=photo, bd=0, highlightthickness=0)
                    label.place(x=0, y=0)
                    label._mm_band = True
                else:
                    label.configure(image=photo)
                label.lower()
                labels.append(label)
            for old in spare:
                try:
                    old.destroy()
                except Exception:
                    pass
            state["labels"] = labels
            state["photo"] = photo
            state["size"] = (w, h)
            state["applied"] = None
            # 首次同步缩放完成后，后续尺寸变化走后台线程
            window._mm_bg_async_ok = True
            window._mm_bg_photo = photo
            window._mm_bg_photo_key = (w, h)
            window._mm_bg_size = (w, h)
            window.after_idle(lambda: _tint_titlebar(window, photo))
            return True

        def sync():
            try:
                if state["photo"] is None:
                    return
                rx, ry = window.winfo_rootx(), window.winfo_rooty()
                cy = int(canvas.canvasy(0))
                moves = []
                for label in state["labels"]:
                    frame = label.master
                    if not frame.winfo_exists():
                        continue
                    moves.append((label, -(frame.winfo_rootx() - rx),
                                  -(frame.winfo_rooty() - ry)))
                signature = (cy, tuple((id(l), x, y) for l, x, y in moves))
                if state["applied"] == signature:
                    return
                state["applied"] = signature
                item = state["item"]
                if item is not None and canvas.winfo_exists():
                    canvas.coords(item, 0, cy)
                    canvas.tag_lower(item)
                for label, x, y in moves:
                    label.place(x=x, y=y)
                    label.lower()
                if state["root"] is not None:
                    state["root"].lower()
            except Exception:
                pass

        def fit():
            try:
                if not window.winfo_exists():
                    return
                w, h = window.winfo_width(), window.winfo_height()
                old = state["size"]
                if abs(w - old[0]) >= 16 or abs(h - old[1]) >= 16:
                    build()
                sync()
            except Exception:
                pass

        window._mm_bg_wake = fit

        def resized(event=None):
            if event is not None and event.widget is not window:
                return
            w, h = window.winfo_width(), window.winfo_height()
            old = state["size"]
            if abs(w - old[0]) < 16 and abs(h - old[1]) < 16:
                return
            try:
                if getattr(window, "_mm_bg_job", None):
                    window.after_cancel(window._mm_bg_job)
            except Exception:
                pass
            # 窗口动画期间不缩放图片，停稳后再重绘，避免卡顿
            window._mm_bg_job = window.after(280, fit)

        if not build():
            window._mm_shell_on = False
            window.after(250, lambda: _install_background(window))
            return
        sync()
        window.bind("<Configure>", resized, add="+")

        def keep():
            try:
                if not window.winfo_exists():
                    return
                ready = getattr(window, "_mm_bg_ready", None)
                if ready:
                    window._mm_bg_ready = None
                    key, ok = ready
                    if ok:
                        w, h = window.winfo_width(), window.winfo_height()
                        if abs(w - key[0]) < 16 and abs(h - key[1]) < 16:
                            build()
                sync()
                if state.get("tint_w") != window.winfo_width() and state["photo"] is not None:
                    state["tint_w"] = window.winfo_width()
                    _tint_titlebar(window, state["photo"])
                window.after(220, keep)
            except Exception:
                pass

        keep()
    except Exception:
        pass


def _install_version_label(window):
    """版本号放在标题栏右上角，与「检测更新」相邻。"""
    try:
        import tkinter
        if getattr(window, "_mm_version_btn", None) is not None:
            return
        title_label = _find_title_label(window)
        if title_label is None:
            return
        bar = title_label.master
        label = tkinter.Label(bar, text="v%s" % _APP_VERSION, bg=bar.cget("bg"),
                              fg="#0B5FA8", font=("Microsoft YaHei UI", 9),
                              bd=0, highlightthickness=0, padx=8)
        label.pack(side=tkinter.RIGHT, padx=(0, 4))
        window._mm_version_btn = label
    except Exception:
        pass


def _install_drag(window):
    """无边框窗口拖动：按住标题栏空白/标题区域移动窗口，最大化时不拖。"""
    try:
        import tkinter
        if getattr(window, "_mm_drag_on", False):
            return
        title_label = _find_title_label(window)
        if title_label is None:
            return
        window._mm_drag_on = True
        bar = title_label.master
        state = {"armed": False, "px": 0, "py": 0, "wx": 0, "wy": 0}

        def inside_bar(widget):
            while widget is not None and widget is not window:
                if widget is bar:
                    return True
                try:
                    widget = widget.master
                except Exception:
                    return False
            return False

        def blocked(widget):
            whitelist = (getattr(window, "_mm_update_btn", None),
                         getattr(window, "_mm_version_btn", None))
            while widget is not None and widget is not window:
                if widget in whitelist:
                    return True
                if widget.winfo_class() in ("Button", "Entry", "TCombobox", "TEntry",
                                            "Checkbutton", "TSpinbox", "Scrollbar"):
                    return True
                try:
                    widget = widget.master
                except Exception:
                    return False
            return False

        def maximized():
            try:
                if window.state() == "zoomed":
                    return True
            except Exception:
                pass
            return (window.winfo_width() >= window.winfo_screenwidth() - 2
                    and window.winfo_height() >= window.winfo_screenheight() - 80)

        def press(event):
            if getattr(event, "num", 1) != 1:
                return
            if not inside_bar(event.widget) or blocked(event.widget) or maximized():
                state["armed"] = False
                return
            state.update(armed=True, px=event.x_root, py=event.y_root,
                         wx=window.winfo_x(), wy=window.winfo_y())

        def motion(event):
            if not state["armed"]:
                return
            window.geometry("+%d+%d" % (state["wx"] + event.x_root - state["px"],
                                        state["wy"] + event.y_root - state["py"]))

        def release(_event=None):
            state["armed"] = False

        window.bind("<ButtonPress-1>", press, add="+")
        window.bind("<B1-Motion>", motion, add="+")
        window.bind("<ButtonRelease-1>", release, add="+")
    except Exception:
        pass


def _install_card_flow(window):
    """窗口变宽时按可用宽度重排卡片列数，并让内容区填满画布。"""
    try:
        import tkinter
        if getattr(window, "_mm_flow_on", False):
            return
        window._mm_flow_on = True
        state = {}

        def locate():
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
                return False
            inner = item = None
            for i in canvas.find_all():
                if canvas.type(i) != "window":
                    continue
                try:
                    widget = window.nametowidget(canvas.itemcget(i, "window"))
                except Exception:
                    continue
                inner, item = widget, i
                break
            if inner is None:
                return False
            found = [None, 0]

            def walk2(widget):
                kids = [k for k in widget.winfo_children() if k.grid_info()]
                if len(kids) > found[1]:
                    found[0] = widget
                    found[1] = len(kids)
                for k in widget.winfo_children():
                    walk2(k)

            walk2(inner)
            if found[0] is None:
                return False
            state.update(canvas=canvas, inner=inner, item=item, container=found[0])
            return True

        def cards_of(container):
            return [k for k in container.winfo_children() if k.grid_info()]

        def columns_of(cards):
            return max(int(k.grid_info()["column"]) for k in cards) + 1

        def ordered(cards):
            return sorted(cards, key=lambda k: (int(k.grid_info()["row"]),
                                                int(k.grid_info()["column"])))

        def apply():
            if not locate():
                return
            if not state.get("wired"):
                state["wired"] = True
                try:
                    # 主程序在画布 <Configure> 里会销毁重建全部卡片（约 0.8s），
                    # 尺寸变化改由本函数重排列数，避免最大化/拖动时卡顿。
                    state["canvas"].unbind("<Configure>")
                    state["canvas"].bind("<Configure>", resized, add="+")
                except Exception:
                    pass
            canvas, inner, item, container = (state["canvas"], state["inner"],
                                              state["item"], state["container"])
            width = canvas.winfo_width()
            if width < 400:
                return
            cards = cards_of(container)
            if len(cards) < 2:
                return
            # 原始 4 列布局下卡片宽 232、间距 16，重排时按此基准算列数
            cell = state.setdefault("cell", 248)
            cols = min(max(4, (width - 4) // max(cell, 1)), len(cards))

            def relayout(work):
                # 重排期间先藏起卡片，停稳后一次画出，避免逐帧重绘造成的画面撕裂
                try:
                    canvas.itemconfigure(item, state="hidden")
                except Exception:
                    pass
                try:
                    work()
                finally:
                    try:
                        canvas.itemconfigure(item, state="normal")
                    except Exception:
                        pass

            if cols <= 4:
                if state.get("expanded"):
                    def collapse():
                        canvas.itemconfigure(item, width=0)
                        for j in range(16):
                            container.grid_columnconfigure(j, weight=1 if j < 4 else 0)
                        for i, k in enumerate(ordered(cards)):
                            k.grid_configure(row=i // 4, column=i % 4)
                        inner.update_idletasks()
                        canvas.configure(scrollregion=(0, 0, max(inner.winfo_reqwidth(), 1),
                                                       max(inner.winfo_reqheight(), 1)))
                    relayout(collapse)
                    state["expanded"] = False
                return
            if state.get("expanded") and columns_of(cards) == cols:
                return

            def expand():
                canvas.itemconfigure(item, width=width)
                for j in range(16):
                    container.grid_columnconfigure(j, weight=1 if j < cols else 0)
                for i, k in enumerate(ordered(cards)):
                    k.grid_configure(row=i // cols, column=i % cols)
                inner.update_idletasks()
                canvas.configure(scrollregion=(0, 0, width, max(inner.winfo_reqheight(), 1)))
            relayout(expand)
            state["expanded"] = True

        def tick():
            try:
                if not window.winfo_exists():
                    return
                apply()
                window.after(600, tick)
            except Exception:
                pass

        def resized(_event=None):
            try:
                if getattr(window, "_mm_flow_job", None):
                    window.after_cancel(window._mm_flow_job)
            except Exception:
                pass
            window._mm_flow_job = window.after(260, apply)

        window.after(300, apply)
        window.after(700, tick)
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
    exe = manifest = patch = None
    for a in assets:
        name = str(a.get("name") or "")
        url = str(a.get("browser_download_url") or "")
        if not url.startswith("https://"):
            continue
        if name.lower().endswith(".exe"):
            exe = url
        elif name.lower().endswith(".json"):
            manifest = url
        elif name.lower().endswith(".patch"):
            patch = url
    return tag, str(data.get("name") or ""), str(data.get("body") or ""), exe, manifest, patch


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


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _sha(b):
    return hashlib.sha256(b).hexdigest()


def _archive(path):
    """读取 PyInstaller onefile 的 CArchive，返回文件头、归档区和条目。"""
    with open(path, "rb") as f:
        data = f.read()
    at = data.rfind(_MEI_MAGIC)
    if at < 0:
        return None
    pkg_len, tocpos, toclen, pyver = struct.unpack("!IIII", data[at + 8:at + 24])
    pylibname = data[at + 24:at + 88]
    base = len(data) - pkg_len
    if base <= 0 or base + tocpos + toclen > len(data):
        return None
    entries = []
    j = base + tocpos
    end = j + toclen
    while j < end:
        elen, off, dlen, ulen, cf, ty = struct.unpack("!IIIIBB", data[j:j + 18])
        if elen < 18 or j + elen > end:
            return None
        name = data[j + 18:j + elen].split(b"\0")[0].decode("utf-8", "replace")
        raw = data[base + off:base + off + dlen]
        if len(raw) != dlen:
            return None
        entries.append({"name": name, "raw": raw, "ty": ty, "cf": cf, "ulen": ulen})
        j += elen
    return {"data": data, "base": base, "entries": entries,
            "pyver": pyver, "pylibname": pylibname}


def _toc_entry(name, ty, off, dlen, ulen, cf):
    body = name.encode("utf-8") + b"\0"
    elen = (18 + len(body) + 15) // 16 * 16
    return (struct.pack("!IIIIBB", elen, off, dlen, ulen, cf, ty) + body
            + b"\0" * (elen - 18 - len(body)))


def _apply_patch(local_exe, manifest, patch_path, dest):
    """用归档条目级补丁拼出新 exe；失败返回 False 交给全量下载。"""
    try:
        with open(patch_path, "rb") as f:
            blob_all = f.read()
        if blob_all[:4] != _PATCH_MAGIC:
            return False
        head_len, data_len = struct.unpack("!II", blob_all[4:12])
        if len(blob_all) != 12 + head_len + data_len:
            return False
        header = json.loads(blob_all[12:12 + head_len].decode("utf-8"))
        blob = blob_all[12 + head_len:]
    except Exception:
        return False
    if str(header.get("base_sha256") or "") != _sha256(local_exe):
        return False
    old = _archive(local_exe)
    if old is None:
        return False
    if _sha(old["data"][:old["base"]]) != str(header.get("prefix_sha256") or ""):
        return False
    local = {e["name"]: e["raw"] for e in old["entries"]}
    body = bytearray()
    toc = bytearray()
    for e in header.get("entries") or []:
        want = str(e.get("sha256") or "")
        raw = local.get(str(e.get("name") or ""))
        if raw is not None and _sha(raw) != want:
            raw = None
        if raw is None:
            off, size = int(e.get("off", -1)), int(e.get("len", 0))
            if off < 0 or size < 0 or off + size > len(blob):
                return False
            raw = blob[off:off + size]
        if _sha(raw) != want:
            return False
        pos = len(body)
        body += raw
        toc += _toc_entry(str(e["name"]), int(e["ty"]), pos, len(raw),
                          int(e["ulen"]), int(e["cf"]))
    pkg_len = len(body) + len(toc) + 88
    out = (old["data"][:old["base"]] + bytes(body) + bytes(toc)
           + struct.pack("!8sIIII64s", _MEI_MAGIC, pkg_len, len(body), len(toc),
                         int(header.get("pyver") or old["pyver"]), old["pylibname"]))
    if _sha(out) != str(manifest.get("sha256") or header.get("sha256") or ""):
        return False
    with open(dest, "wb") as f:
        f.write(out)
    return True


def _update_batch(stage, target, pid, digest):
    """先校验临时副本，再原子改名覆盖；避免半截文件被当成新版本启动。"""
    bat = os.path.join(tempfile.gettempdir(), "mm_update_%d.bat" % int(time.time()))
    verify = ""
    if digest:
        verify = ('powershell -NoProfile -ExecutionPolicy Bypass -Command '
                  '"if ((Get-FileHash -LiteralPath \'{0}.new\' -Algorithm SHA256).Hash '
                  '-ne \'{1}\') {{ exit 1 }}" >nul 2>&1\r\n'
                  'if errorlevel 1 goto retry\r\n').format(target, digest)
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
copy /Y "{stage}" "{target}.new" >nul 2>&1
if errorlevel 1 goto retry
{verify}move /Y "{target}.new" "{target}" >nul 2>&1
if errorlevel 1 goto retry
goto run
:retry
set /a n+=1
if %n% geq 60 goto giveup
timeout /t 1 /nobreak >nul
goto copy
:run
start "" "{target}"
del "{stage}" >nul 2>&1
del "{target}.new" >nul 2>&1
del "%~f0" >nul 2>&1
exit /b
:giveup
del "{target}.new" >nul 2>&1
start "" "{target}"
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
    _update_batch(stage, target, os.getpid(), _sha256(new_exe))
    window.destroy()
    os._exit(0)


def _center(top, parent):
    parent.update_idletasks()
    top.update_idletasks()
    w, h = top.winfo_width(), top.winfo_height()
    x = parent.winfo_rootx() + (parent.winfo_width() - w) // 2
    y = parent.winfo_rooty() + (parent.winfo_height() - h) // 3
    top.geometry("+%d+%d" % (max(x, 0), max(y, 0)))


def _current_exe():
    return sys.executable if getattr(sys, "frozen", False) else None


def _run_update(window, version, url, manifest_url, patch_url, info):
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
            want = ""
            if isinstance(manifest, dict):
                want = str(manifest.get("sha256") or "").lower()
                pinfo = manifest.get("patch") or {}
                local_exe = _current_exe()
                if (local_exe and patch_url and isinstance(pinfo, dict)
                        and pinfo.get("sha256")
                        and str(manifest.get("base_sha256") or "").lower()):
                    pp = os.path.join(tmp_dir, "patch-v%s.bin" % version)
                    try:
                        ui(lambda: hint.config(text="正在下载增量补丁…"))
                        _download_full(patch_url, pp)
                        if _sha256(pp) == str(pinfo["sha256"]).lower():
                            ui(lambda: hint.config(text="正在拼装新版本…"))
                            ok = _apply_patch(local_exe, manifest, pp, dest)
                    except Exception:
                        ok = False
                    finally:
                        try:
                            os.remove(pp)
                        except Exception:
                            pass
            if not ok:
                ui(lambda: hint.config(text="正在下载完整更新包…"))
                _download_full(url, dest)
                progress(os.path.getsize(dest), os.path.getsize(dest))
                if want:
                    ui(lambda: hint.config(text="正在校验更新包…"))
                    if _sha256(dest) != want:
                        _download_full(url, dest)
                        if _sha256(dest) != want:
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


def _check_update(window, auto=False):
    import tkinter
    from tkinter import messagebox

    if auto:
        if getattr(window, "_mm_auto_checked", False):
            return
        window._mm_auto_checked = True
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
            tag, name, body, url, manifest_url, patch_url = _latest_release()
        except Exception as exc:
            def fail():
                done()
                if not auto:
                    messagebox.showerror("检测更新失败", "无法连接 Gitee 更新源。\n\n%s" % exc, parent=window)
            window.after(0, fail)
            return
        newest = _version_tuple(tag)
        current = _version_tuple(_APP_VERSION)
        if not tag or newest <= current:
            def up_to_date():
                done()
                if not auto:
                    messagebox.showinfo("检测更新", "当前已是最新版本 v%s。" % _APP_VERSION, parent=window)
            window.after(0, up_to_date)
            return
        if not url:
            def no_asset():
                done()
                if not auto:
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
                _run_update(window, tag.lstrip("vV"), url, manifest_url, patch_url, (tag, name, notes))
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

def _round_window(window):
    """Win10 没有 DWM 圆角，用窗口区域裁出圆角；最大化时保持直角。"""
    try:
        if getattr(window, "_mm_round_on", False):
            return
        window._mm_round_on = True
        user32 = ctypes.windll.user32
        gdi32 = ctypes.windll.gdi32
        gdi32.CreateRoundRectRgn.restype = ctypes.c_void_p
        gdi32.CreateRectRgn.restype = ctypes.c_void_p
        user32.SetWindowRgn.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_bool]
        state = {"hwnd": user32.GetParent(window.winfo_id()) or window.winfo_id(),
                 "size": (0, 0), "round": None}

        def apply(round_corners):
            try:
                if not window.winfo_exists():
                    return
                w, h = window.winfo_width(), window.winfo_height()
                if w < 100 or h < 100:
                    return
                hwnd = state["hwnd"]
                if not user32.IsWindow(hwnd):
                    state["hwnd"] = hwnd = user32.GetParent(window.winfo_id()) or window.winfo_id()
                if state["size"] == (w, h) and state["round"] == round_corners:
                    return
                if round_corners:
                    region = gdi32.CreateRoundRectRgn(0, 0, w + 1, h + 1, 28, 28)
                else:
                    region = gdi32.CreateRectRgn(0, 0, w + 1, h + 1)
                if user32.SetWindowRgn(hwnd, region, bool(round_corners)):
                    state["size"] = (w, h)
                    state["round"] = round_corners
            except Exception:
                pass

        def maximized(w, h):
            return (w >= user32.GetSystemMetrics(0) - 2
                    and h >= user32.GetSystemMetrics(1) - 80)

        def settle():
            w, h = window.winfo_width(), window.winfo_height()
            apply(not maximized(w, h))

        def resized(event=None):
            if event is not None and event.widget is not window:
                return
            w, h = window.winfo_width(), window.winfo_height()
            if state["size"] == (w, h):
                return
            # 动画期间先用整窗矩形，保证新增区域立刻重绘，停稳后再裁圆角
            apply(False)
            try:
                if getattr(window, "_mm_round_job", None):
                    window.after_cancel(window._mm_round_job)
            except Exception:
                pass
            window._mm_round_job = window.after(300, settle)

        w, h = window.winfo_width(), window.winfo_height()
        apply(not maximized(w, h))
        window.bind("<Configure>", resized, add="+")
    except Exception:
        pass


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
            _install_version_label(window)
            _install_update_button(window)
            _install_background(window)
            _install_card_flow(window)
            try:
                window.deiconify()
            except Exception:
                pass
            _round_window(window)
            _install_drag(window)

            def tint():
                photo = getattr(window, "_mm_bg_photo", None)
                if photo is not None:
                    _tint_titlebar(window, photo)

            window.after(120, tint)
            window.after(600, tint)
            window.after(2500, lambda: _check_update(window, True))

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
