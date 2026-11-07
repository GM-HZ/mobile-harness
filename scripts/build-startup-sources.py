from pathlib import Path
from zipfile import ZipFile
import gzip
import json
import re
import struct

raw = Path(__file__).resolve().parents[1] / 'entry/src/main/resources/rawfile'
entries = {}
sources = bytearray()
with ZipFile(raw / 'dsh-layer.zip') as layer:
    types = {}
    for entry in layer.infolist():
        if entry.filename.endswith('/package.json'):
            manifest = json.loads(layer.read(entry))
            types[entry.filename.rsplit('/', 1)[0]] = manifest.get('type')
    for info in layer.infolist():
        if not re.fullmatch(r'dsh/node_modules/[-@a-zA-Z0-9_./]+\.(?:m?js)', info.filename):
            continue
        if info.file_size == 0 or info.file_size > 256 * 1024:
            continue
        if info.filename.endswith('.js'):
            directory = info.filename.rsplit('/', 1)[0]
            while '/' in directory and directory not in types:
                directory = directory.rsplit('/', 1)[0]
            if types.get(directory) != 'module':
                continue
        source = layer.read(info)
        entries['file:///' + info.filename] = [len(sources), len(source)]
        sources.extend(source)
header = json.dumps(entries, separators=(',', ':')).encode('ascii')
with (raw / 'dsh-startup-sources.gz').open('wb') as output:
    with gzip.GzipFile(fileobj=output, mode='wb', compresslevel=5, mtime=0) as zipped:
        zipped.write(struct.pack('<I', len(header)))
        zipped.write(header)
        zipped.write(sources)
print(f'{len(entries)} startup source entries, {len(sources):,} uncompressed bytes')
