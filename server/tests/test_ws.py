"""Тест WebSocket-канала /ws (как ходит UI)."""

import json
import os
import sys
from pathlib import Path

import pytest

SERVER_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVER_DIR))

os.environ.setdefault(
    "MT_WORKER", json.dumps([sys.executable, str(Path(__file__).parent / "fake_worker.py")])
)

from fastapi.testclient import TestClient

import gateway


@pytest.fixture()
def client():
    with TestClient(gateway.app) as c:
        yield c


def test_ws_translate_flow(client):
    with client.websocket_connect("/ws") as ws:
        ws.send_json(
            {"type": "translate", "text": "Hello", "src": "auto", "tgt": "Russian", "seq": 1}
        )
        events = []
        while True:
            ev = ws.receive_json()
            events.append(ev)
            if ev["type"] in ("done", "error"):
                break
    kinds = [e["type"] for e in events]
    assert "detect" in kinds
    assert "token" in kinds
    done = next(e for e in events if e["type"] == "done")
    assert done["translation"].startswith("[Russian]")
    assert done["seq"] == 1
    assert all(e.get("seq") == 1 for e in events if "seq" in e)


def test_ws_unknown_type(client):
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "что-то"})
        ev = ws.receive_json()
    assert ev["type"] == "error"


def test_ws_bad_language(client):
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "translate", "text": "hi", "src": "auto", "tgt": "Klingon", "seq": 2})
        ev = ws.receive_json()
    assert ev["type"] == "error"
    assert ev["seq"] == 2
