import copy
import json
import uuid

import pytest
from fastapi.testclient import TestClient

from trainmaps_api.app import create_app

WRITE = "development-writer-" + "w" * 32
READ = "development-reader-" + "r" * 32
MAPPING = "development-mapper-" + "m" * 32
LINE_ID = "de.test.s1"


def auth(token):
    return {"Authorization": "Bearer " + token}


def import_headers(revision=1):
    return {**auth(WRITE), "Content-Type": "application/json",
            "Idempotency-Key": str(uuid.uuid4()),
            "X-Dataset-Revision": str(revision)}


def reference(revision=1, status="pending", aliases=None, active=True):
    geometry = {"source": "basemap.de", "source_layer": "Verkehrslinie",
                "source_class": "S-Bahn", "status": status,
                "reference": None, "version": None}
    if status != "pending":
        geometry.update({"reference": "trainmaps:geometry:test-s1",
                         "version": "2026-09"})
    return {"revision": revision, "network_id": "de.test",
            "display_name": "S1 Testnetz",
            "source_aliases": aliases or [{"netz": "Testnetz", "line": "S1"}],
            "geometry": geometry, "active": active, "notes": None}


def export(line_ids=True):
    period = "2021-09-01T00:00:00.000000+0000"
    delay = {"month": period, "n_data_points": 100}
    for threshold, count in [(2, 80), (5, 90), (10, 95), (20, 99), (40, 100)]:
        delay[f"n_on_time_{threshold}"] = count
        delay[f"p_on_time_{threshold}"] = count / 100
    cancel = {"month": period, "n_data_points": 250,
              "n_cancelled": 10, "p_cancelled": .04}
    line_fields = {"netz": "Testnetz", "line": "S1"}
    if line_ids:
        line_fields["line_id"] = LINE_ID
    return {
        "cancellationsByMonth": [cancel],
        "cancellationsByNetworkMonth": [{**cancel, "netz": "Testnetz"}],
        "cancellationsByNetworkLineMonth": [{**cancel, **line_fields}],
        "delaysByMonth": [delay],
        "delaysByNetworkMonth": [{**delay, "netz": "Testnetz"}],
        "delaysByNetworkLineMonth": [{**delay, **line_fields}],
        "mostCancelledStops": [],
    }


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(data_dir=tmp_path, write_token=WRITE, read_token=READ,
                               mapping_token=MAPPING)) as instance:
        yield instance


def test_catalog_auth_versioning_filters_and_alias_ownership(client):
    url = "/api/v1/reference/lines/" + LINE_ID
    assert client.get("/api/v1/reference/lines").status_code == 401
    assert client.put(url, json=reference(), headers=auth(WRITE)).status_code == 403

    created = client.put(url, json=reference(), headers=auth(MAPPING))
    assert created.status_code == 201
    assert created.json()["line_id"] == LINE_ID
    assert client.put(url, json=reference(), headers=auth(MAPPING)).status_code == 200

    changed_same_revision = reference()
    changed_same_revision["display_name"] = "Changed"
    assert client.put(url, json=changed_same_revision, headers=auth(MAPPING)).status_code == 409

    revised = reference(revision=2)
    revised["display_name"] = "S1 revised"
    assert client.put(url, json=revised, headers=auth(MAPPING)).status_code == 200

    collision = client.put("/api/v1/reference/lines/de.other.s1", json={
        **reference(), "network_id": "de.other", "display_name": "Other S1",
    }, headers=auth(MAPPING))
    assert collision.status_code == 409
    for token in (READ, WRITE, MAPPING):
        listing = client.get("/api/v1/reference/lines?netz=Testnetz&geometry_status=pending",
                             headers=auth(token))
        assert listing.status_code == 200 and listing.json()["total"] == 1
    exact = client.get("/api/v1/reference/lines?netz=Testnetz&line=S1",
                       headers=auth(READ))
    assert exact.json()["values"][0]["line_id"] == LINE_ID
    assert client.get("/api/v1/reference/lines?netz=Testnetz&line=S2",
                      headers=auth(READ)).json()["total"] == 0


def test_v2_requires_known_matching_active_line_ids(client):
    no_id = client.post("/api/v2/imports/frontend?validate_only=true",
                        json=export(line_ids=False), headers=import_headers())
    assert no_id.status_code == 422 and no_id.json()["code"] == "schema_error"

    unknown = client.post("/api/v2/imports/frontend?validate_only=true",
                          json=export(), headers=import_headers())
    assert unknown.status_code == 422 and unknown.json()["code"] == "line_reference_error"
    assert unknown.json()["errors"][0]["code"] == "unknown_line_id"

    client.put("/api/v1/reference/lines/" + LINE_ID, json=reference(), headers=auth(MAPPING))
    mismatch = export()
    mismatch["delaysByNetworkLineMonth"][0]["line"] = "S2"
    invalid = client.post("/api/v2/imports/frontend?validate_only=true",
                          json=mismatch, headers=import_headers())
    assert invalid.status_code == 422
    assert any(error["code"] == "line_alias_mismatch" for error in invalid.json()["errors"])

    client.put("/api/v1/reference/lines/" + LINE_ID,
               json=reference(revision=2, active=False), headers=auth(MAPPING))
    inactive = client.post("/api/v2/imports/frontend?validate_only=true",
                           json=export(), headers=import_headers())
    assert inactive.status_code == 422
    assert inactive.json()["errors"][0]["code"] == "inactive_line_id"


def test_v2_roundtrip_mapping_state_and_monthly_line_filter(client):
    url = "/api/v1/reference/lines/" + LINE_ID
    client.put(url, json=reference(), headers=auth(MAPPING))
    raw = json.dumps(export(), ensure_ascii=False, indent=2).encode()
    saved = client.post("/api/v2/imports/frontend", content=raw, headers=import_headers())
    assert saved.status_code == 201
    receipt = saved.json()
    assert receipt["contract_version"] == "frontend-2"
    assert receipt["line_reference_revisions"] == {LINE_ID: 1}
    assert receipt["map_ready"] is False
    assert client.get("/api/v1/data/frontend", headers=auth(READ)).content == raw

    monthly = client.get("/api/v1/data/monthly", params={
        "metric": "punctuality", "month": "2021-09", "line_id": LINE_ID,
    }, headers=auth(READ))
    assert monthly.status_code == 200
    assert monthly.json()["values"][0]["line_id"] == LINE_ID
    assert monthly.json()["values"][0]["geometry_status"] == "pending"
    assert monthly.json()["map_ready"] is False

    client.put(url, json=reference(revision=2, status="verified"), headers=auth(MAPPING))
    validated = client.post("/api/v2/imports/frontend?validate_only=true",
                            json=export(), headers=import_headers(revision=2))
    assert validated.status_code == 200
    assert validated.json()["map_ready"] is True
    monthly = client.get("/api/v1/data/monthly", params={
        "metric": "punctuality", "month": "2021-09", "line_id": LINE_ID,
    }, headers=auth(READ)).json()
    assert monthly["map_ready"] is True
    assert monthly["values"][0]["geometry_status"] == "verified"


def test_v1_rows_are_enriched_from_current_catalog(client):
    client.put("/api/v1/reference/lines/" + LINE_ID,
               json=reference(status="verified"), headers=auth(MAPPING))
    response = client.post("/api/v1/imports/frontend", json=export(line_ids=False),
                           headers=import_headers())
    assert response.status_code == 201
    monthly = client.get("/api/v1/data/monthly", params={
        "metric": "cancellations", "month": "2021-09", "line_id": LINE_ID,
    }, headers=auth(READ)).json()
    assert monthly["values"][0]["line_id"] == LINE_ID
    assert monthly["map_ready"] is True
