"""用多尺寸 .ico 替换 Windows exe 的图标资源（RT_ICON / RT_GROUP_ICON）。

PyInstaller onefile 的 exe 末尾还有一段归档，UpdateResource 会截掉它；
脚本会在更新后把这段 overlay 原样接回去。

用法: python apply_exe_icon.py <exe> <ico>
"""
import ctypes
import os
import struct
import sys
from ctypes import wintypes

RT_ICON = 3
RT_GROUP_ICON = 14
MEI_MAGIC = b'MEI\014\013\012\013\016'

k32 = ctypes.WinDLL('kernel32', use_last_error=True)
k32.BeginUpdateResourceW.argtypes = [wintypes.LPCWSTR, wintypes.BOOL]
k32.BeginUpdateResourceW.restype = wintypes.HANDLE
k32.UpdateResourceW.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.LPVOID,
                                wintypes.WORD, wintypes.LPVOID, wintypes.DWORD]
k32.UpdateResourceW.restype = wintypes.BOOL
k32.EndUpdateResourceW.argtypes = [wintypes.HANDLE, wintypes.BOOL]
k32.EndUpdateResourceW.restype = wintypes.BOOL


def parse_ico(path):
    data = open(path, 'rb').read()
    reserved, typ, count = struct.unpack('<HHH', data[:6])
    if reserved != 0 or typ != 1:
        raise SystemExit('不是有效的 .ico 文件')
    images = []
    for i in range(count):
        w, h, colors, _, planes, bitcount, size, offset = struct.unpack(
            '<BBBBHHII', data[6 + 16 * i:22 + 16 * i])
        images.append({
            'width': w, 'height': h, 'colors': colors, 'planes': planes,
            'bitcount': bitcount, 'data': data[offset:offset + size],
        })
    return images


def build_group(images):
    out = struct.pack('<HHH', 0, 1, len(images))
    for i, im in enumerate(images, 1):
        out += struct.pack('<BBBBHHIH', im['width'], im['height'], im['colors'], 0,
                           im['planes'], im['bitcount'], len(im['data']), i)
    return out


def existing_resources(exe):
    result = {RT_ICON: [], RT_GROUP_ICON: []}
    try:
        import pefile
    except ImportError:
        return {RT_ICON: [(i, [0]) for i in range(1, 17)], RT_GROUP_ICON: [(1, [0])]}

    pe = pefile.PE(exe, fast_load=True)
    try:
        pe.parse_data_directories(
            directories=[pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_RESOURCE']])
        root = getattr(pe, 'DIRECTORY_ENTRY_RESOURCE', None)
        if not root:
            return result
        for entry in root.entries:
            if entry.id not in (RT_ICON, RT_GROUP_ICON):
                continue
            for name in entry.directory.entries:
                langs = [l.id for l in name.directory.entries]
                result[entry.id].append((name.id, langs))
        return result
    finally:
        pe.close()


def split_overlay(path):
    data = open(path, 'rb').read()
    at = data.rfind(MEI_MAGIC)
    if at < 0:
        raise SystemExit('未在 exe 中找到 PyInstaller 归档')
    pkg_len = struct.unpack('!I', data[at + 8:at + 12])[0]
    base = len(data) - pkg_len
    if base <= 0:
        raise SystemExit('PyInstaller 归档长度异常')
    return base, data[base:]


def main(exe, ico):
    exe = os.path.abspath(exe)
    images = parse_ico(ico)
    old = existing_resources(exe)
    _, overlay = split_overlay(exe)

    h = k32.BeginUpdateResourceW(exe, False)
    if not h:
        raise SystemExit(f'BeginUpdateResource 失败: {ctypes.get_last_error()}')
    try:
        for typ, items in old.items():
            for name, langs in items:
                for lang in langs:
                    k32.UpdateResourceW(h, typ, name, lang, None, 0)
        for i, im in enumerate(images, 1):
            data = im['data']
            buf = ctypes.create_string_buffer(data, len(data))
            if not k32.UpdateResourceW(h, RT_ICON, i, 0, buf, len(data)):
                raise OSError(f'写入 RT_ICON {i} 失败: {ctypes.get_last_error()}')
        grp = build_group(images)
        buf = ctypes.create_string_buffer(grp, len(grp))
        if not k32.UpdateResourceW(h, RT_GROUP_ICON, 1, 0, buf, len(grp)):
            raise OSError(f'写入图标组失败: {ctypes.get_last_error()}')
    except Exception:
        k32.EndUpdateResourceW(h, True)
        raise
    if not k32.EndUpdateResourceW(h, False):
        raise OSError(f'EndUpdateResource 失败: {ctypes.get_last_error()}')

    with open(exe, 'ab') as f:
        f.write(overlay)

    print(f'已替换 {os.path.basename(exe)} 的图标：{len(images)} 个尺寸，归档 {len(overlay)} 字节已接回')


if __name__ == '__main__':
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    main(sys.argv[1], sys.argv[2])
