"""把任务栏修复钩子注入现有 PyInstaller onefile exe，不改动界面与其它资源。

用法: python repack_taskbar_fix.py <原exe> <输出exe>
"""
import marshal
import os
import struct
import sys
import zlib

MAGIC = b'MEI\014\013\012\013\016'
HOOK_NAME = 'pyi_rth_taskbar_fix'
HOOK_SOURCE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'taskbar_fix_hook.py')


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


def main(src, dst):
    data = open(src, 'rb').read()
    cookie_at = data.rfind(MAGIC)
    if cookie_at < 0:
        raise SystemExit('未找到 PyInstaller 归档')
    pkg_len, tocpos, toclen, pyver = struct.unpack('!IIII', data[cookie_at + 8:cookie_at + 24])
    pylibname = data[cookie_at + 24:cookie_at + 88]
    base = len(data) - pkg_len
    entries = parse_toc(data, base, tocpos, toclen)

    if any(e['name'] == HOOK_NAME for e in entries):
        raise SystemExit('该 exe 已注入过修复钩子')

    hook_pyc = marshal.dumps(compile(open(HOOK_SOURCE, encoding='utf-8').read(),
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
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    main(sys.argv[1], sys.argv[2])
