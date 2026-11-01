"""生成增量更新清单与归档条目级补丁。

用法: python make_update_manifest.py <新exe> <版本号> <输出.json> <输出.patch> --base <旧exe>

补丁只包含相对旧版本变化的归档条目，客户端用本地 exe 的其余条目拼装，
校验整包 SHA-256 后才覆盖安装。缺少 --base 时只生成全量清单。
"""
import hashlib
import json
import os
import struct
import sys

import repack_taskbar_fix as rp

PATCH_MAGIC = b'MMP1'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def read_archive(path):
    with open(path, 'rb') as f:
        data = f.read()
    at = data.rfind(rp.MAGIC)
    if at < 0:
        raise SystemExit(f'不是 PyInstaller onefile：{path}')
    pkg_len, tocpos, toclen, pyver = struct.unpack('!IIII', data[at + 8:at + 24])
    pylibname = data[at + 24:at + 88]
    base = len(data) - pkg_len
    entries = rp.parse_toc(data, base, tocpos, toclen)
    return data, base, entries, pyver, pylibname


def build_patch(new_exe, version, base_exe, out_patch):
    ndata, nbase, nentries, pyver, _ = read_archive(new_exe)
    bdata, _, bentries, _, _ = read_archive(base_exe)
    local = {e['name']: e['raw'] for e in bentries}
    entries = []
    blob = bytearray()
    changed = 0
    for e in nentries:
        digest = sha(e['raw'])
        old = local.get(e['name'])
        if old is not None and sha(old) == digest:
            off, size = -1, 0
        else:
            off, size = len(blob), len(e['raw'])
            blob += e['raw']
            changed += 1
        entries.append({
            'name': e['name'], 'ty': e['ty'], 'cf': e['cf'], 'ulen': e['ulen'],
            'sha256': digest, 'off': off, 'len': size,
        })
    header = {
        'version': version,
        'size': len(ndata),
        'sha256': sha(ndata),
        'base_sha256': sha(bdata),
        'prefix_sha256': sha(ndata[:nbase]),
        'pyver': pyver,
        'entries': entries,
    }
    hj = json.dumps(header, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    packed = PATCH_MAGIC + struct.pack('!II', len(hj), len(blob)) + hj + bytes(blob)
    with open(out_patch, 'wb') as f:
        f.write(packed)
    print(f'{os.path.basename(out_patch)}  {len(packed)} bytes  {changed}/{len(entries)} 个条目变化')
    return {
        'name': os.path.basename(out_patch), 'sha256': sha(packed), 'size': len(packed),
    }


def main(new_exe, version, out_json, out_patch=None, base_exe=None):
    with open(new_exe, 'rb') as f:
        data = f.read()
    manifest = {
        'version': version,
        'size': len(data),
        'sha256': sha(data),
    }
    if base_exe and out_patch:
        with open(base_exe, 'rb') as f:
            manifest['base_sha256'] = sha(f.read())
        manifest['patch'] = build_patch(new_exe, version, base_exe, out_patch)
    with open(out_json, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, ensure_ascii=False, separators=(',', ':'))
    print(f'{os.path.basename(out_json)}  {len(data)} bytes  {manifest["sha256"][:16]}…')


if __name__ == '__main__':
    args = sys.argv[1:]
    if len(args) < 3:
        raise SystemExit(__doc__)
    base = None
    if '--base' in args:
        i = args.index('--base')
        base = args[i + 1]
        del args[i:i + 2]
    new_exe, version, out_json = args[:3]
    out_patch = args[3] if len(args) > 3 else None
    main(new_exe, version, out_json, out_patch, base)
