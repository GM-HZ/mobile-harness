set -eu
cd "$1"
cat > requirements.txt <<'REQ'
numpy==2.2.6 --hash=sha256:37c0ca431f82cd5fa716eca9506aefcabc247fb27ba69c5062a6d3ade8cf8f49
orjson==3.11.4 --hash=sha256:149d95d5e018bdd822e3f38c103b1a7c91f88d38a88aada5c4e9b3a73a244241
REQ
python3 -m venv --copies .venv
.venv/bin/python -m pip --isolated install \
  --disable-pip-version-check --no-cache-dir --timeout 20 --retries 1 \
  --index-url https://pypi.org/simple --only-binary :all: --no-deps --require-hashes \
  --report install.json -r requirements.txt
OPENBLAS_NUM_THREADS=1 .venv/bin/python - <<'PY'
from importlib.metadata import version
import json
from pathlib import Path
import platform
import sys
from urllib.parse import urlsplit

import numpy as np
import numpy._core._multiarray_umath as ndarray_native
import numpy.linalg._umath_linalg as linalg_native
import orjson
import orjson.orjson as json_native

assert sys.prefix != sys.base_prefix and sys.version_info[:2] == (3, 12)
assert platform.machine() == 'aarch64'
assert all(Path(module.__file__).is_relative_to(Path(sys.prefix)) and module.__file__.endswith('.so')
           for module in (ndarray_native, linalg_native, json_native))
libraries = sorted(item.name for item in Path(np.__file__).resolve().parent.parent.joinpath('numpy.libs').glob('*.so*'))
assert any('openblas' in name for name in libraries), libraries
solution = np.linalg.solve(np.array([[3.0, 1.0], [1.0, 2.0]]), np.array([9.0, 8.0])).tolist()
assert solution == [2.0, 3.0]
document = {'solution': solution, 'label': '鸿蒙'}
encoded = orjson.dumps(document, option=orjson.OPT_SORT_KEYS)
assert encoded == b'{"label":"' + '鸿蒙'.encode() + b'","solution":[2.0,3.0]}'
assert orjson.loads(encoded) == document

install = json.loads(Path('install.json').read_text())['install']
wheels = {}
for archive in install:
    name = archive['metadata']['name']
    download = archive['download_info']
    address = urlsplit(download['url'])
    assert address.scheme == 'https' and address.hostname == 'files.pythonhosted.org'
    wheels[name] = {'filename': Path(address.path).name, 'sha256': download['archive_info']['hashes']['sha256'],
                    'version': version(name)}
result = json.dumps(dict(
    wheels=wheels, artifacts=[Path(module.__file__).name for module in (ndarray_native, linalg_native, json_native)],
    libraries=libraries, isolated=True, arch=platform.machine(), solution=solution, nativeJson=encoded.decode(),
), ensure_ascii=False)
Path('probe-result.tmp').write_text(result, encoding='utf8')
Path('probe-result.tmp').replace('probe-result.json')
print('HARMONY_NATIVE_PYTHON:' + result)
PY
