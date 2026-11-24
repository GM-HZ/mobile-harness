"""Read the DSH files from the staged chunk manifest or a legacy archive."""
from contextlib import ExitStack, contextmanager
import json
import os
from pathlib import Path
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[2]
STAGED = ROOT / ".build/stage/harmonyos/entry/src/main/resources/rawfile"
MANIFEST = "dsh-chunks.json"


def locate_layer(explicit=None):
    selected = explicit or os.environ.get("MH_DSH_LAYER")
    if selected:
        path = Path(selected)
        if path.is_dir():
            path = path / MANIFEST
        return path if path.is_file() else None
    for path in (STAGED / MANIFEST, STAGED / "dsh-layer.zip"):
        if path.is_file():
            return path
    return None


@contextmanager
def open_layer(layer):
    archives = [layer]
    if layer.name == MANIFEST:
        chunks = json.loads(layer.read_text())["chunks"]
        if not chunks:
            raise ValueError(f"No DSH chunks in {layer}")
        archives = [layer.with_name(chunk["file"]) for chunk in chunks]
        optional = layer.with_name("dsh-layer-optional.zip")
        if optional.is_file():
            archives.append(optional)
    with ExitStack() as stack:
        members = {}
        for path in archives:
            archive = stack.enter_context(ZipFile(path))
            for name in archive.namelist():
                members[name] = archive
        yield members
