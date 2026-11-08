import os
from pathlib import Path
import hashlib
project=Path(__file__).resolve().parents[3]
root=Path(os.environ.get('HARMONY_STAGE', project / '.build/stage/harmonyos'))
raw=root/'entry/src/main/resources/rawfile'
files=[p for p in (root/'entry/libs').rglob('*') if p.is_file()]
files.extend(p for p in raw.iterdir() if p.suffix in ('.zip','.gz','.node') or p.name in ('alpine-busybox','alpine-ld-musl'))
with (project/'docs/build-inputs.sha256').open('w') as out:
 for file in sorted(files):
  h=hashlib.sha256()
  with file.open('rb') as src:
   for block in iter(lambda:src.read(1024*1024),b''): h.update(block)
  out.write(f'{h.hexdigest()}  {file.relative_to(root).as_posix()}\n')
