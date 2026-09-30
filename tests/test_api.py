import copy
import gzip
import json
import uuid

import pytest
from fastapi.testclient import TestClient

from trainmaps_api.app import create_app

WRITE = "development-writer-" + "w" * 32
READ = "development-reader-" + "r" * 32
MAPPING = "development-mapper-" + "m" * 32


@pytest.fixture
def payload():
    period = "2021-09-01T00:00:00.000000+0000"
    delay = {"month": period, "n_data_points": 100}
    for threshold, count in [(2, 80), (5, 90), (10, 95), (20, 99), (40, 100)]:
        delay[f"n_on_time_{threshold}"] = count
        delay[f"p_on_time_{threshold}"] = count / 100
    cancel = {"month": period, "n_data_points": 250, "n_cancelled": 10, "p_cancelled": .04}
    return {
        "cancellationsByMonth": [cancel],
        "cancellationsByNetworkMonth": [{**cancel, "netz": "Testnetz"}],
        "cancellationsByNetworkLineMonth": [{**cancel, "netz": "Testnetz", "line": "S1"}],
        "delaysByMonth": [delay],
        "delaysByNetworkMonth": [{**delay, "netz": "Testnetz"}],
        "delaysByNetworkLineMonth": [{**delay, "netz": "Testnetz", "line": "S1"}],
        "mostCancelledStops": [],
    }


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(data_dir=tmp_path, write_token=WRITE, read_token=READ,
                               mapping_token=MAPPING)) as c:
        yield c


def headers(key=None, revision=1, token=WRITE):
    return {"Authorization": "Bearer " + token, "Content-Type": "application/json",
            "Idempotency-Key": key or str(uuid.uuid4()), "X-Dataset-Revision": str(revision)}


def test_auth_and_read_token_cannot_write(client, payload):
    assert client.get("/health").status_code == 200
    assert client.get("/api/v1/data/frontend").status_code == 401
    assert client.post("/api/v1/imports/frontend", json=payload).status_code == 401
    assert client.post("/api/v1/imports/frontend", json=payload, headers=headers(token=READ)).status_code == 403


def test_dry_run_does_not_reserve_key_or_revision(client, payload):
    h = headers()
    r = client.post("/api/v1/imports/frontend?validate_only=true", json=payload, headers=h)
    assert r.status_code == 200 and r.json()["stored"] is False
    assert client.get("/api/v1/data/frontend", headers=headers(token=READ)).status_code == 404
    assert client.post("/api/v1/imports/frontend", json=payload, headers=h).status_code == 201


def test_exact_roundtrip_replay_conflicts_and_gzip(client, payload):
    raw = json.dumps(payload, indent=2).encode()
    h = headers()
    first = client.post("/api/v1/imports/frontend", content=raw, headers=h)
    assert first.status_code == 201
    replay = client.post("/api/v1/imports/frontend", content=gzip.compress(raw),
                         headers={**h, "Content-Encoding": "gzip"})
    assert replay.status_code == 200 and replay.json() == first.json()
    assert client.get("/api/v1/data/frontend", headers=headers(token=READ)).content == raw
    assert client.post("/api/v1/imports/frontend", content=raw + b" ", headers=h).status_code == 409
    assert client.post("/api/v1/imports/frontend", content=raw, headers=headers()).status_code == 409


def test_persistence_and_old_snapshot_remains_readable(tmp_path, payload):
    app = create_app(data_dir=tmp_path, write_token=WRITE, read_token=READ,
                     mapping_token=MAPPING)
    with TestClient(app) as c:
        first = c.post("/api/v1/imports/frontend", json=payload, headers=headers()).json()
    with TestClient(create_app(data_dir=tmp_path, write_token=WRITE, read_token=READ,
                               mapping_token=MAPPING)) as c:
        assert c.get("/api/v1/imports/" + first["import_id"], headers=headers()).status_code == 200
        second = c.post("/api/v1/imports/frontend", json=payload, headers=headers(revision=2))
        assert second.status_code == 201
        old = c.get("/api/v1/data/monthly", params={"metric": "punctuality", "month": "2021-09", "import_id": first["import_id"]}, headers=headers(token=READ))
        assert old.json()["revision"] == 1


@pytest.mark.parametrize("problem", ["ratio", "negative", "nonmonotonic", "duplicate", "rollup", "nan", "extra", "month", "empty"])
def test_invalid_delivery_leaves_previous_import_untouched(client, payload, problem):
    first = client.post("/api/v1/imports/frontend", json=payload, headers=headers()).json()
    changed = copy.deepcopy(payload)
    row = changed["delaysByNetworkLineMonth"][0]
    if problem == "ratio": row["p_on_time_5"] = .2
    elif problem == "negative": row["n_data_points"] = -1
    elif problem == "nonmonotonic": row["n_on_time_2"], row["p_on_time_2"] = 98, .98
    elif problem == "duplicate": changed["delaysByNetworkLineMonth"].append(copy.deepcopy(row))
    elif problem == "rollup": changed["delaysByNetworkMonth"][0]["n_on_time_5"], changed["delaysByNetworkMonth"][0]["p_on_time_5"] = 91, .91
    elif problem == "nan": row["p_on_time_5"] = float("nan")
    elif problem == "extra": changed["unexpected"] = []
    elif problem == "month": row["month"] = "2021-09-02T00:00:00Z"
    elif problem == "empty": changed = {k: [] for k in changed}
    r = client.post("/api/v1/imports/frontend", content=json.dumps(changed).encode(), headers=headers(revision=2))
    assert r.status_code in (400, 422)
    current = client.get("/api/v1/data/monthly?metric=punctuality&month=2021-09", headers=headers()).json()
    assert current["import_id"] == first["import_id"]


def test_duplicate_properties_and_bad_gzip(client, payload):
    raw = json.dumps(payload)
    raw = '{"mostCancelledStops": [],' + raw[1:]
    assert client.post("/api/v1/imports/frontend", content=raw, headers=headers()).status_code == 400
    assert client.post("/api/v1/imports/frontend", content=b"broken", headers={**headers(), "Content-Encoding": "gzip"}).status_code == 400


def test_gzip_bomb_is_bounded(client):
    raw = gzip.compress(b" " * (32 * 1024 * 1024 + 1))
    assert client.post("/api/v1/imports/frontend", content=raw, headers={**headers(), "Content-Encoding": "gzip"}).status_code == 413


def test_read_filters_and_missing_values_are_not_zero(client, payload):
    client.post("/api/v1/imports/frontend", json=payload, headers=headers())
    r = client.get("/api/v1/data/monthly?metric=punctuality&month=2021-09&netz=Testnetz&line=S1", headers=headers(token=READ)).json()
    assert r["values"][0]["p_on_time_5"] == .9
    assert r["values"][0]["month"] == "2021-09"
    assert r["map_ready"] is False
    assert client.get("/api/v1/data/monthly?metric=punctuality&month=2020-01", headers=headers()).json()["values"] == []
    assert client.get("/api/v1/data/monthly?metric=punctuality&month=2021-09&line=S1", headers=headers()).status_code == 422


def test_openapi_exposes_actual_body_and_bearer_auth(client):
    spec = client.get("/openapi.json").json()
    endpoint = spec["paths"]["/api/v1/imports/frontend"]["post"]
    assert endpoint["security"]
    assert endpoint["requestBody"]["content"]["application/json"]["schema"]["$ref"].endswith("FrontendExportV1")
    assert len(spec["components"]["schemas"]["FrontendExport"]["properties"]) == 7
    endpoint_v2 = spec["paths"]["/api/v2/imports/frontend"]["post"]
    assert endpoint_v2["requestBody"]["content"]["application/json"]["schema"]["$ref"].endswith("FrontendExportV2")
    assert "line_id" in spec["components"]["schemas"]["FrontendExportV2"]["properties"]["delaysByNetworkLineMonth"]["items"]["required"]
