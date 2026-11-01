"""生成增量更新清单（分块 SHA-1 + 整包 SHA-256）。

用法: python make_update_manifest.py <exe> <版本号> <输出.json>
"""
import hashlib
import json
import os
import sys

CHUNK = 512 * 1024


def main(exe, version, out):
    size = os.path.getsize(exe)
    sha = hashlib.sha256()
    chunks = []
    with open(exe, 'rb') as f:
        for block in iter(lambda: f.read(CHUNK), b''):
            sha.update(block)
            chunks.append(hashlib.sha1(block).hexdigest())
    data = {
        'version': version,
        'size': size,
        'chunk': CHUNK,
        'sha256': sha.hexdigest(),
        'chunks': chunks,
    }
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, separators=(',', ':'))
    print(f'{os.path.basename(out)}  {size} bytes  {len(chunks)} blocks  {sha.hexdigest()[:16]}…')


if __name__ == '__main__':
    if len(sys.argv) != 4:
        raise SystemExit(__doc__)
    main(sys.argv[1], sys.argv[2], sys.argv[3])
