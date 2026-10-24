"""Тесты gateway с фейковым воркером (модель не грузится)."""

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


def parse_sse(text: str):
    events = []
    name = ""
    for line in text.splitlines():
        if line.startswith("event:"):
            name = line[len("event:") :].strip()
        elif line.startswith("data:"):
            events.append((name, json.loads(line[len("data:") :].strip())))
    return events


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["languages"] >= 200


def test_detect_russian(client):
    r = client.post("/detect", json={"text": "Привет, как у тебя дела сегодня?"})
    assert r.status_code == 200
    assert r.json()["language"] == "Russian"


def test_detect_english(client):
    r = client.post("/detect", json={"text": "Hello, how are you doing today my friend?"})
    assert r.json()["language"] == "English"


def test_translate_sse_stream(client):
    with client.stream(
        "POST", "/translate", json={"text": "Hello", "src": "auto", "tgt": "Russian"}
    ) as r:
        assert r.status_code == 200
        events = parse_sse(r.read().decode())
    kinds = [e for e, _ in events]
    assert "detect" in kinds
    assert "token" in kinds
    done = next(d for e, d in events if e == "done")
    assert done["translation"].startswith("[Russian]")
    assert done["src"] == "English"  # определился авто-детектом


def test_translate_unknown_target(client):
    r = client.post("/translate", json={"text": "hi", "tgt": "Klingon"})
    assert r.status_code == 422


def test_translate_same_lang(client):
    r = client.post("/translate", json={"text": "hi", "src": "English", "tgt": "English"})
    assert r.status_code == 400
