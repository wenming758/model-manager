"""把运行时钩子注入现有 PyInstaller onefile exe，并应用卡通主题配色。

用法: python repack_taskbar_fix.py <原exe> <输出exe> [--version 1.1.2] [--no-theme]
"""
import argparse
import base64
import marshal
import os
import re
import struct
import types
import zlib

MAGIC = b'MEI\014\013\012\013\016'
HOOK_NAME = 'pyi_rth_taskbar_fix'
HERE = os.path.dirname(os.path.abspath(__file__))
HOOK_SOURCE = os.path.join(HERE, 'update_hook.py')
ASSETS = os.path.join(HERE, 'assets')

THEME = {
    '#0078D4': '#0B5FA8',
    '#60CDFF': '#57B4E6',
    '#005A9E': '#083F6B',
    '#1A86D9': '#1975BC',
    '#F0F4F8': '#CFE2F2',
    '#FAFBFC': '#E7F1FA',
    '#E8F0FE': '#C3DBF2',
    '#F5F7FA': '#DCE9F5',
    '#F8FAFC': '#D8E8F5',
    '#E2E8F0': '#AECBE3',
    '#CBD5E1': '#9CBCDA',
    '#F1F5F9': '#E3EEF8',
    '#94A3B8': '#7C97B4',
    '#64748B': '#566E8A',
    '#475569': '#3C4F66',
    '#1E293B': '#16233A',
    '#DBEAFE': '#C7DDF6',
    '#D1FAE5': '#C4EFD9',
    '#EDE9FE': '#DFD7FA',
    '#FFEDD5': '#FBE0C0',
    '#FCE7F3': '#F9D7E9',
}


def align16(n):
    return (n + 15) // 16 * 16


def parse_toc(data, base, tocpos, toclen):
    entries = []
    j = base + tocpos
    end = j + toclen
    while j < end:
        elen, off, dlen, ulen, cf, ty = struct.unpack('!IIIIBB', data[j:j + 18])
        name = data[j + 18:j + elen].split(b'\0')[0].decode('utf-8')
        raw = data[base + off:base + off + dlen]
        entries.append({
            'name': name, 'raw': raw, 'dlen': dlen, 'ulen': ulen,
            'cf': cf, 'ty': ty,
        })
        j += elen
    return entries


def toc_entry(name, ty, off, dlen, ulen, cf):
    body = name.encode('utf-8') + b'\0'
    elen = align16(18 + len(body))
    return struct.pack('!IIIIBB', elen, off, dlen, ulen, cf, ty) + body + b'\0' * (elen - 18 - len(body))


def main_script(entries):
    candidates = [e for e in entries
                  if e['ty'] == ord('s') and not e['name'].startswith(('pyi', 'pyiboot'))]
    if len(candidates) != 1:
        raise SystemExit('未找到唯一的主脚本')
    return candidates[0]


def load_code(entry):
    return marshal.loads(zlib.decompress(entry['raw']) if entry['cf'] else entry['raw'])


def save_code(entry, code):
    data = marshal.dumps(code)
    raw = zlib.compress(data, 9)
    entry.update(raw=raw, dlen=len(raw), ulen=len(data), cf=1)


def patch_version(entry, new_version):
    if not new_version:
        return
    code = load_code(entry)
    consts = list(code.co_consts)
    indexes = [i for i, c in enumerate(consts)
               if isinstance(c, str) and re.fullmatch(r'\d+\.\d+\.\d+', c)]
    if len(indexes) != 1:
        raise SystemExit('主脚本中没有唯一的版本号常量')
    old = consts[indexes[0]]
    consts[indexes[0]] = new_version
    save_code(entry, code.replace(co_consts=tuple(consts)))
    print(f'版本号 {old} -> {new_version}')


def apply_theme(code):
    consts = list(code.co_consts)
    changed = 0
    for i, c in enumerate(consts):
        if isinstance(c, str) and c in THEME:
            consts[i] = THEME[c]
            changed += 1
        elif isinstance(c, types.CodeType):
            consts[i], sub = apply_theme(c)
            changed += sub
    return code.replace(co_consts=tuple(consts)), changed


def build_hook(version):
    src = open(HOOK_SOURCE, encoding='utf-8').read()
    for token, name in (('__ICON_PNG_B64__', 'icon_128.png'),
                        ('__ICON_TITLE_B64__', 'icon_title.png'),
                        ('__BG_PNG_B64__', 'background.png')):
        with open(os.path.join(ASSETS, name), 'rb') as f:
            src = src.replace(token, base64.b64encode(f.read()).decode('ascii'))
    return src.replace('__APP_VERSION__', version)


def main(src, dst, version=None, theme=True):
    data = open(src, 'rb').read()
    cookie_at = data.rfind(MAGIC)
    if cookie_at < 0:
        raise SystemExit('未找到 PyInstaller 归档')
    pkg_len, tocpos, toclen, pyver = struct.unpack('!IIII', data[cookie_at + 8:cookie_at + 24])
    pylibname = data[cookie_at + 24:cookie_at + 88]
    base = len(data) - pkg_len
    entries = parse_toc(data, base, tocpos, toclen)

    if any(e['name'] == HOOK_NAME for e in entries):
        raise SystemExit('该 exe 已注入过钩子')

    entry = main_script(entries)
    patch_version(entry, version)
    if theme:
        code, changed = apply_theme(load_code(entry))
        save_code(entry, code)
        print(f'配色替换 {changed} 处')

    hook_pyc = marshal.dumps(compile(build_hook(version or '0.0.0'),
                                     HOOK_NAME + '.py', 'exec'))
    hook_raw = zlib.compress(hook_pyc, 9)
    hook = {'name': HOOK_NAME, 'raw': hook_raw, 'dlen': len(hook_raw),
            'ulen': len(hook_pyc), 'cf': 1, 'ty': ord('s')}

    # 放在 pyi_rth__tkinter 之后、主脚本之前，保证 tkinter 可用且先于应用执行
    order = [e['name'] for e in entries]
    pos = order.index('pyi_rth__tkinter') + 1 if 'pyi_rth__tkinter' in order else len(entries)
    entries.insert(pos, hook)

    body = bytearray()
    toc = bytearray()
    for e in entries:
        off = len(body)
        body += e['raw']
        toc += toc_entry(e['name'], e['ty'], off, e['dlen'], e['ulen'], e['cf'])

    new_pkg_len = len(body) + len(toc) + 88
    cookie = struct.pack('!8sIIII64s', MAGIC, new_pkg_len, len(body), len(toc),
                         pyver, pylibname)
    out = data[:base] + bytes(body) + bytes(toc) + cookie
    open(dst, 'wb').write(out)
    print(f'已生成 {dst} ({len(out)} bytes), 注入 {HOOK_NAME} 于第 {pos} 项')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('src')
    parser.add_argument('dst')
    parser.add_argument('--version')
    parser.add_argument('--no-theme', action='store_true')
    args = parser.parse_args()
    main(args.src, args.dst, args.version, not args.no_theme)
