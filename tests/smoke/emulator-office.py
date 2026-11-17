"""Exercise the real Office skill, converter, image attachments, and formula engine on a Phone emulator."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import re
import runpy
import tempfile
import time
import uuid
import xml.etree.ElementTree as ET
import zipfile

toolkit = runpy.run_path(str(Path(__file__).with_name("emulator-toolkit.py")))
support = toolkit["support"]
ptc = toolkit["approval"]["ptc"]
ROOT = Path(__file__).resolve().parents[2]


def fixtures(directory, marker):
    types = 'http://schemas.openxmlformats.org/package/2006/content-types'
    rels = 'http://schemas.openxmlformats.org/package/2006/relationships'
    relation = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
    word = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
    sheet = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
    with zipfile.ZipFile(directory / "input.docx", "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", f'<Types xmlns="{types}"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        archive.writestr("_rels/.rels", f'<Relationships xmlns="{rels}"><Relationship Id="rId1" Type="{relation}officeDocument" Target="word/document.xml"/></Relationships>')
        archive.writestr("word/document.xml", f'<w:document xmlns:w="{word}"><w:body><w:p><w:r><w:t>{marker}</w:t></w:r></w:p><w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"/></w:sectPr></w:body></w:document>')
    with zipfile.ZipFile(directory / "input.xlsx", "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", f'<Types xmlns="{types}"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>')
        archive.writestr("_rels/.rels", f'<Relationships xmlns="{rels}"><Relationship Id="rId1" Type="{relation}officeDocument" Target="xl/workbook.xml"/></Relationships>')
        archive.writestr("xl/workbook.xml", f'<workbook xmlns="{sheet}" xmlns:r="{relation[:-1]}"><sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets><calcPr fullCalcOnLoad="1"/></workbook>')
        archive.writestr("xl/_rels/workbook.xml.rels", f'<Relationships xmlns="{rels}"><Relationship Id="rId1" Type="{relation}worksheet" Target="worksheets/sheet1.xml"/></Relationships>')
        archive.writestr("xl/worksheets/sheet1.xml", f'<worksheet xmlns="{sheet}"><sheetData><row r="1"><c r="A1"><v>1</v></c><c r="B1"><v>41</v></c><c r="C1"><f>A1+B1</f><v>0</v></c></row></sheetData></worksheet>')
    (directory / "invalid.docx").write_bytes(b"This is not an Office ZIP archive.")


def trace(emulator):
    rows = emulator.app("grep office- alpine/tmp/dsh-native-timeline.log || true")
    return [json.loads(row) for row in rows.splitlines()]


def invoke(emulator, sid, name, args, expect_error=False, preamble=""):
    start = time.monotonic()
    calls, results = toolkit["prompt"](emulator, sid,
        preamble + f"This is a local regression fixture. Call {name} exactly once with precisely {json.dumps(args)}. "
        "Report the tool result and stop. Do not use another tool, copy or modify files, retry, or substitute another engine.", timeout=225)
    assert len(calls) == len(results) == 1 and calls[0]["name"] == name, calls
    assert json.loads(calls[0]["arguments"]) == args, calls
    assert bool(results[0]["isError"]) == expect_error, toolkit["texts"](results)
    return results[0], round((time.monotonic() - start) * 1000)


def file_result(emulator, result, destination):
    text = toolkit["texts"]([result])
    match = re.search(r": (/[^\n]+)\nCopy this temporary file", text)
    assert match, text
    actual = match[1]
    relative = ptc["app_path"](actual)
    content = base64.b64decode(emulator.app(f"base64 {relative}"), validate=False)
    destination.write_bytes(content)
    return {"path": actual, "bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()}


def run(emulator, output, artifacts, require_native=False):
    artifacts.mkdir(parents=True, exist_ok=True)
    name = "mh-office-" + uuid.uuid4().hex[:12]
    marker = "HARMONY_OFFICE_" + uuid.uuid4().hex.upper()
    app = "alpine/workspace-native/" + name
    workspace = support["WORKSPACE"] + "/" + name
    remotes = []
    sid = None
    evidence = {"fixture": name, "marker": marker}
    try:
        evidence["readyMs"] = emulator.ready("normal")
        emulator.app(f"mkdir -p {app}")
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary)
            fixtures(source, marker)
            presentation = ROOT / "vendor/repos/dsh/scripts/fixtures/office-render/color-blocks.pptx"
            files = [(source / filename, filename) for filename in ("input.docx", "input.xlsx", "invalid.docx")]
            files.append((presentation, "input.pptx"))
            evidence["fixtureSha256"] = {filename: hashlib.sha256(local.read_bytes()).hexdigest() for local, filename in files}
            for local, filename in files:
                remote = "/data/local/tmp/" + name + "-" + filename
                remotes.append(remote)
                assert "FileTransfer finish" in emulator.hdc("file", "send", str(local), remote)
                emulator.app(f"cp {remote} {app}/{filename}")
        with support["model_key"](emulator) as configured:
            assert configured, "MH_TEST_DEEPSEEK_API_KEY is required"
            sid = support["session"](emulator, True)
            result, elapsed = invoke(emulator, sid, "skill", {"name": "office"})
            assert "office" in toolkit["texts"]([result])
            evidence["officeSkillLoaded"] = True
            result, elapsed = invoke(emulator, sid, "office_convert", {"input": workspace + "/input.docx", "format": "pdf"})
            pdf = artifacts / "document.pdf"
            record = file_result(emulator, result, pdf)
            assert pdf.read_bytes().startswith(b"%PDF-") and "1 page" in toolkit["texts"]([result])
            evidence["documentPdf"] = {**record, "pageCount": 1, "promptElapsedMs": elapsed}
            print("document PDF passed", elapsed, flush=True)

            previous = sum(row["event"] == "office-operation-running" for row in trace(emulator))
            result, elapsed = invoke(emulator, sid, "office_convert", {"input": workspace + "/input.docx", "format": "pdf"})
            cached = file_result(emulator, result, artifacts / "cached.pdf")
            assert cached["sha256"] == record["sha256"]
            assert sum(row["event"] == "office-operation-running" for row in trace(emulator)) == previous
            evidence["repeatUsedHostCache"] = True

            result, elapsed = invoke(emulator, sid, "office_render", {"input": workspace + "/input.docx", "pages": [1], "dpi": 72})
            images = [block["attachment"] for block in result["content"] if block["type"] == "image"]
            assert len(images) == 1 and images[0]["width"] > 0 and images[0]["height"] > 0
            attachment = emulator.rpc("session/attachment", {"request": {"sessionId": sid, "attachment": images[0]}})
            png = base64.b64decode(attachment["data"], validate=True)
            image = artifacts / ("document." + images[0]["mediaType"].split("/")[1])
            image.write_bytes(png)
            assert len(png) == images[0]["bytes"] and len(png) > 100
            evidence["documentImage"] = {"attachment": images[0], "sha256": hashlib.sha256(png).hexdigest(),
                                         "promptElapsedMs": elapsed, "localArtifact": str(image)}
            print("document render passed", elapsed, flush=True)

            result, elapsed = invoke(emulator, sid, "office_recalculate", {"input": workspace + "/input.xlsx", "format": "xlsx"})
            workbook = artifacts / "recalculated.xlsx"
            record = file_result(emulator, result, workbook)
            with zipfile.ZipFile(workbook) as archive:
                sheet = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
                ns = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
                cell = sheet.find('.//s:c[@r="C1"]', ns)
                assert cell is not None and cell.find("s:f", ns) is not None
                assert cell.find("s:v", ns).text in {"42", "42.0"}, ET.tostring(cell).decode()
            evidence["workbookRecalculated"] = {**record, "cell": "C1", "formulaRetained": True,
                                                "beforeCachedValue": 0, "afterCachedValue": 42, "promptElapsedMs": elapsed}
            print("workbook recalc passed", elapsed, flush=True)

            result, elapsed = invoke(emulator, sid, "office_convert", {"input": workspace + "/input.pptx", "format": "pdf"})
            slides = artifacts / "slides.pdf"
            record = file_result(emulator, result, slides)
            assert slides.read_bytes().startswith(b"%PDF-")
            evidence["presentationPdf"] = {**record, "promptElapsedMs": elapsed}
            print("presentation PDF passed", elapsed, flush=True)

            result, elapsed = invoke(emulator, sid, "office_convert", {"input": workspace + "/invalid.docx", "format": "pdf"}, True)
            text = toolkit["texts"]([result])
            assert "cannot convert" in text and "unavailable" not in text.lower(), text
            evidence["invalidDocumentRejected"] = text
        evidence["temporaryModelCredentialRemoved"] = True
        evidence["trace"] = trace(emulator)
        if require_native:
            assert any(row["event"] == "office-worker-started" and row.get("runtime") == "native" for row in evidence["trace"])
    finally:
        try:
            if sid is not None:
                emulator.rpc("session/cancel", {"request": {"sessionId": sid}})
            emulator.app(f"rm -rf {app}")
            for remote in remotes:
                emulator.hdc("shell", "rm", "-f", remote)
            evidence["sourceFixturesRemoved"] = True
        finally:
            output.write_text(json.dumps(evidence, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target")
    parser.add_argument("output", type=Path)
    parser.add_argument("--port", type=int, default=19643)
    parser.add_argument("--artifacts", type=Path, default=Path(".build/office-artifacts"))
    parser.add_argument("--require-native", action="store_true")
    options = parser.parse_args()
    emulator = support["Emulator"](options.target, options.port)
    forward = (f"tcp:{options.port}", "tcp:19592")
    assert "Forwardport result:OK" in emulator.hdc("fport", *forward)
    try:
        run(emulator, options.output, options.artifacts, options.require_native)
    finally:
        emulator.hdc("fport", "rm", *forward)
