import json
import os
from pathlib import Path
import sys

assert os.getcwd().endswith("/workspace-native")
assert sys.argv[1] == "literal '$(); \" argument"
assert os.environ.get("MH_FIXTURE") == "space 'quote'\nnext"
assert "DEEPSEEK_API_KEY" not in os.environ

for line in sys.stdin:
    request = json.loads(line)
    if "id" not in request:
        continue
    method = request["method"]
    if method == "initialize":
        result = {
            "protocolVersion": request["params"]["protocolVersion"],
            "serverInfo": {"name": "python-stdio-fixture", "version": "1"},
            "capabilities": {"tools": {}},
        }
    elif method == "tools/list":
        result = {"tools": [{
            "name": "stdio_fixture_echo", "description": "Returns a fixed marker",
            "inputSchema": {"type": "object", "properties": {}},
        }]}
        if os.environ.get("MH_LIVE") == "1":
            Path(sys.argv[0] + ".ready").write_text("ok")
    elif method == "tools/call":
        result = {"content": [{"type": "text", "text": "MH_MCP_STDIO_OK"}]}
    else:
        result = None
    response = {"jsonrpc": "2.0", "id": request["id"]}
    response.update({"result": result} if result is not None else {"error": {"code": -32601, "message": "Method not found"}})
    print(json.dumps(response), flush=True)
