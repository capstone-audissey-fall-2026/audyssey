"""Run by the smoke stage of tools.Dockerfile: the heavy imports work, and the stub
tool server starts, lists its four tools and rejects a wrong token."""

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

import audyssey
import torch

TOKEN = "ci-smoke-token"
URL = "http://127.0.0.1:8700"
TOOLS = ["separation", "filtering", "grounding", "generation"]


def call(path, token=None, data=None):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        with urllib.request.urlopen(
            urllib.request.Request(URL + path, data=data, headers=headers), timeout=5
        ) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


print("torch", torch.__version__, "audyssey", audyssey.__file__)
server = subprocess.Popen(
    ["audyssey", "tool-server", *[a for t in TOOLS for a in ("--tool", t)]]
    + ["--impl", "stub", "--host", "0.0.0.0", "--port", "8700"],
    env={**os.environ, "AUDYSSEY_TOOL_TOKEN": TOKEN},
)
try:
    for _ in range(60):
        if server.poll() is not None:
            sys.exit("tool server exited")
        try:
            health = call("/health")
            break
        except OSError:
            time.sleep(1)
    else:
        sys.exit("tool server did not come up")
    assert health[0] == 200 and json.loads(health[1])["tools"] == TOOLS, health
    # An empty POST: a wrong token stops at the middleware, the right one reaches validation.
    assert call("/separate", "wrong", b"")[0] == 401
    assert call("/separate", TOKEN, b"")[0] == 422
    print("tool server ok")
finally:
    server.terminate()
