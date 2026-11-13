"""Verify image uploads in an installed AppGallery Release build on a Phone emulator."""
import argparse
import binascii
import importlib
import json
import re
import struct
from urllib.parse import urlencode
from urllib.request import Request
import uuid
import zlib

recovery = importlib.import_module("emulator-recovery")


def png_chunk(kind, data):
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", binascii.crc32(kind + data))


def fixture_png(width=3, height=2, transparent=False):
    pixel = bytes([255, 10, 20, 127] if transparent else [255, 10, 20])
    header = struct.pack(">IIBBBBB", width, height, 8, 6 if transparent else 2, 0, 0, 0)
    rows = (b"\x00" + pixel * width) * height
    return (
        bytes.fromhex("89504e470d0a1a0a")
        + png_chunk(b"IHDR", header)
        + png_chunk(b"IDAT", zlib.compress(rows))
        + png_chunk(b"IEND", b"")
    )


def test(emulator, port):
    if emulator.hdc("shell", "param get const.product.model") != "emulator":
        raise SystemExit("Expected a Phone emulator")
    forward = (f"tcp:{port}", "tcp:19592")
    if "Forwardport result:OK" not in emulator.hdc("fport", *forward):
        raise RuntimeError("Could not forward the local Host port")
    folder = f"appgallery-image-smoke-{uuid.uuid4().hex[:10]}"
    folder_created = False
    try:
        emulator.ready("normal")
        workspace_path = recovery.WORKSPACE + "/" + folder
        emulator.app("mkdir -p alpine/workspace-native/" + folder)
        folder_created = True
        workspace = emulator.rpc("workspace/create", {"request": {"path": workspace_path}})["workspace"]
        try:
            session = emulator.rpc("session/create", {"request": {
                "workspaceId": workspace["workspaceId"],
            }})["sessionId"]
            params = urlencode({"sessionId": session, "name": "fixture.png", "mediaType": "image/png"})
            headers = {"Content-Type": "application/octet-stream", "Cookie": emulator.cookie(),
                       "Host": recovery.HOST_HEADER}
            url = emulator.url + "/api/session/uploadFileBinary?" + params

            def upload(data):
                with emulator.opener.open(Request(url, data, headers), timeout=35) as response:
                    return json.load(response)

            def check_image(data, media_type, expected_dimensions=None):
                result = upload(data)
                if not result["ok"]:
                    raise RuntimeError(f"Valid PNG was rejected: {result['error']}")
                receipt = result["value"]
                image = receipt["image"]
                if not receipt["receiptId"] or image["mediaType"] != media_type:
                    raise RuntimeError(f"Invalid image upload receipt: {receipt}")
                dimensions = image["width"], image["height"]
                if expected_dimensions and dimensions != expected_dimensions:
                    raise RuntimeError(f"Unexpected image dimensions: {dimensions}")
                return image

            check_image(fixture_png(), "image/png", (3, 2))
            print("Valid PNG stored with correct dimensions.", flush=True)
            for transparent, output in ((False, "image/jpeg"), (True, "image/webp")):
                image = check_image(fixture_png(9000, 10, transparent=transparent), output)
                if not (8000 <= image["width"] <= 8192 and image["height"] == 9):
                    raise RuntimeError(f"Wide image was not proportionally downscaled: {image}")
                if image["originalDimensions"] != {"width": 9000, "height": 10}:
                    raise RuntimeError(f"Original dimensions were lost: {image}")
                print(f"Wide PNG downscaled and stored as {output}.", flush=True)

            for malformed in (b"not a PNG", fixture_png()[:-12]):
                result = upload(malformed)
                if result["ok"] or result["error"]["details"].get("reason") != "INVALID_IMAGE":
                    raise RuntimeError(f"Unexpected malformed PNG upload response: {result}")
            print("Malformed and truncated PNGs rejected.")
        finally:
            emulator.rpc("workspace/delete", {"request": {"workspaceId": workspace["workspaceId"]}})
    finally:
        try:
            if folder_created:
                emulator.app("rmdir alpine/workspace-native/" + folder)
        finally:
            emulator.hdc("fport", "rm", *forward)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", help="loopback Phone emulator HDC target")
    parser.add_argument("--bundle", default="org.mobileharness.dshmh")
    parser.add_argument("--port", type=int, default=19637)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)+", args.bundle):
        parser.error("invalid application bundle name")
    recovery.BUNDLE = args.bundle
    test(recovery.Emulator(args.target, args.port), args.port)
