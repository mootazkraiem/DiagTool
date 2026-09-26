"""Model selection through the real FastAPI route functions (Step 12: P1-5, P1-6, P1-7, P0-3).

The server module is imported as the app runs it and its route functions are
called directly (fastapi's TestClient needs httpx, which is not a project
dependency). Only side channels are replaced: the SQLite store (so no test data
reaches the user's database) and the LLM explainer (no network).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
os.environ["GOOGLE_API_KEY"] = ""

import numpy as np
import pytest

import asyncio
import io

from fastapi import HTTPException
from starlette.datastructures import UploadFile


class _NullStore:
    def __getattr__(self, name):
        return lambda *a, **k: "test-session" if name == "new_session" else None


class _Response:
    def __init__(self, status_code: int, body: dict):
        self.status_code, self._body = status_code, body

    def json(self) -> dict:
        return self._body

    @property
    def text(self) -> str:
        return str(self._body)


class _Routes:
    """The four routes under test, answering like HTTP: a status code and a JSON body."""

    def __init__(self, server):
        self.s = server

    def _call(self, fn, *a, **k):
        try:
            out = fn(*a, **k)
            if asyncio.iscoroutine(out):
                out = asyncio.run(out)
            return _Response(200, out.model_dump() if hasattr(out, "model_dump") else out)
        except HTTPException as exc:
            return _Response(exc.status_code, {"detail": exc.detail})

    def models(self):
        return self._call(self.s.api_models)

    def analyze(self, model_id: str, body: bytes):
        return self._call(self.s.analyze, files=[UploadFile(file=io.BytesIO(body), filename="t.csv")], model_id=model_id)

    def connect(self, **req):
        return self._call(self.s.api_live_hardware_connect, self.s.HardwareConnectRequest(**req))

    def status(self):
        return self._call(self.s.api_live_hardware_status)

    def disconnect(self):
        return self._call(self.s.api_live_hardware_disconnect)


@pytest.fixture(scope="module")
def client():
    import backend.api.server as server
    mp = pytest.MonkeyPatch()
    mp.setattr(server, "_store", _NullStore())
    mp.setattr(server, "llm_explain_alert",
               lambda alert: {"summary": "test", "detail": "", "recommendation": "", "kb_match_label": "",
                              "mode": "rule_based"})
    yield _Routes(server)
    mp.undo()


def _csv(ids: list[int], frames_each: int = 30) -> bytes:
    rng = np.random.default_rng(0)
    lines, t = ["timestamp,can_id,b0,b1,b2,b3,b4,b5,b6,b7"], 0.0
    for i in range(frames_each):
        for cid in ids:
            lines.append(",".join([f"{t:.6f}", str(cid), *[str(v) for v in [i % 256, *rng.integers(0, 4, 7)]]]))
            t += 0.01
    return ("\n".join(lines) + "\n").encode()


def _analyze(client, model_id: str, body: bytes):
    return client.analyze(model_id, body)


def test_models_listing_exposes_status(client) -> None:
    models = {m["id"]: m for m in client.models().json()["models"]}
    expect = {
        "kia_ev6": ("clean_holdout_evaluated", "clean_2", "clean_2"),
        "jaguar_ipace": ("clean_holdout_evaluated", "clean_2", "clean_2"),
        "mg_zs_ev": ("clean_held_back", "refused", "refused"),
        "tesla": ("clean_unvalidated_no_holdout", "refused", "legacy"),
        "skoda_enyaq": ("unavailable_no_clean_model", "refused", "refused"),
        "bmw_i3": ("legacy", "refused", "legacy"),
        "general": ("general", "general", "general"),
        "renault_zoe": ("general", "general", "general"),
    }
    for mid, (status, offline, live) in expect.items():
        assert (models[mid]["status"], models[mid]["offline"], models[mid]["live"]) == (status, offline, live), mid
    assert models["kia_ev6"]["model_version"] == "clean-2-002"


def test_analyze_promoted_family_reports_scored_and_unresolved(client) -> None:
    import json
    m = json.loads(Path("assets/models/nissan_leaf_2019/manifest.json").read_text(encoding="utf-8"))
    known, sparse = int(sorted(m["id_models"])[0], 16), int(sorted(m["sparse_ids"])[0], 16)
    r = _analyze(client, "nissan_leaf_2019", _csv([known, sparse, 0x7FE]))
    assert r.status_code == 200, r.text
    s = r.json()["summary"]
    assert s["model_id"] == s["requested_model_id"] == "nissan_leaf_2019"
    assert s["model_status"] == "clean_holdout_evaluated"
    assert s["rows_parsed"] == s["scored_count"] + s["unresolved_count"] == 90
    assert s["scored_count"] == s["anomaly_count"] + s["normal_count"] == 20        # known ID after warm-up
    assert s["unresolved_reasons"] == {"warmup": 30, "sparse_id": 20, "unseen_id": 20}


@pytest.mark.parametrize("model_id, status", [("mg_zs_ev", "clean_held_back"), ("skoda_enyaq", "unavailable_no_clean_model"),
                                              ("tesla", "clean_unvalidated_no_holdout"), ("bmw_i3", "legacy")])
def test_analyze_refuses_non_clean_models_with_reason(client, model_id, status) -> None:
    r = _analyze(client, model_id, _csv([0x100]))
    assert r.status_code == 409
    assert model_id in r.json()["detail"] and status in r.json()["detail"]


def test_analyze_unknown_model_is_an_error_not_general(client) -> None:
    r = _analyze(client, "no_such_vehicle", _csv([0x100]))
    assert r.status_code == 400 and "unknown model id 'no_such_vehicle'" in r.json()["detail"]


def test_analyze_alias_resolves_to_general_and_says_so(client) -> None:
    r = _analyze(client, "renault_zoe", _csv([0x100, 0x200]))
    assert r.status_code == 200, r.text
    s = r.json()["summary"]
    assert (s["model_id"], s["requested_model_id"], s["model_status"]) == ("general", "renault_zoe", "general")
    assert s["unresolved_count"] == 0 and s["scored_count"] == s["rows_parsed"]


def test_hardware_connect_refuses_held_back_model(client) -> None:
    r = client.connect(interface="virtual", channel="step12api", vehicle_id="mg_zs_ev")
    assert r.status_code == 409 and "clean_held_back" in r.json()["detail"]


def test_hardware_connect_uses_clean_2_for_promoted_vehicle(client) -> None:
    pytest.importorskip("can")
    r = client.connect(interface="virtual", channel="step12api", vehicle_id="road_ambient")
    assert r.status_code == 200, r.text
    try:
        st = client.status().json()
        assert st["model_status"]["status"] == "clean_holdout_evaluated"
        assert st["model_status"]["id"] == "road_ambient"
    finally:
        client.disconnect()
