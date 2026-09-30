import json
import uuid
from pathlib import Path

from fastapi.testclient import TestClient

from trainmaps_api.app import create_app


WRITE = "map-writer-" + "w" * 32
READ = "map-reader-" + "r" * 32
MAPPING = "map-mapper-" + "m" * 32
LINE_ID = "de.muenchen.s1"
ROOT = Path(__file__).resolve().parents[1]


def auth(token):
    return {"Authorization": "Bearer " + token}


def payload():
    month = "2026-05-01T00:00:00.000000+0000"
    delay = {"month": month, "n_data_points": 100}
    for threshold, count in ((2, 80), (5, 90), (10, 95), (20, 99), (40, 100)):
        delay[f"n_on_time_{threshold}"] = count
        delay[f"p_on_time_{threshold}"] = count / 100
    cancel = {"month": month, "n_data_points": 250, "n_cancelled": 10,
              "p_cancelled": .04}
    alias = {"netz": "München", "line": "1"}
    return {
        "cancellationsByMonth": [cancel],
        "cancellationsByNetworkMonth": [{**cancel, "netz": "München"}],
        "cancellationsByNetworkLineMonth": [{**cancel, **alias}],
        "delaysByMonth": [delay],
        "delaysByNetworkMonth": [{**delay, "netz": "München"}],
        "delaysByNetworkLineMonth": [{**delay, **alias}],
        "mostCancelledStops": [],
    }


def seeded_client(tmp_path, *, status="verified"):
    app = create_app(data_dir=tmp_path, write_token=WRITE, read_token=READ,
                     mapping_token=MAPPING)
    client = TestClient(app)
    definition = {
        "revision": 2,
        "network_id": "de.muenchen",
        "display_name": "S1 München",
        "source_aliases": [{"netz": "München", "line": "1"}],
        "geometry": {
            "source": "basemap.de", "source_layer": "Verkehrslinie",
            "source_class": "S-Bahn", "fallback_classes": ["Eisenbahn", "Gleis"],
            "status": status,
            "reference": "trainmaps:geometry:de.muenchen.s1@1",
            "version": "basemap.de 2026-08-18 / MVV GTFS 06/2026",
        },
        "active": True,
        "notes": "Test",
    }
    assert client.put(f"/api/v1/reference/lines/{LINE_ID}", json=definition,
                      headers=auth(MAPPING)).status_code == 201
    headers = {**auth(WRITE), "Idempotency-Key": str(uuid.uuid4()),
               "X-Dataset-Revision": "1"}
    assert client.post("/api/v1/imports/frontend", json=payload(), headers=headers).status_code == 201
    return client


def test_map_page_is_public_and_uses_restrictive_csp(tmp_path):
    with seeded_client(tmp_path) as client:
        page = client.get("/karte")
        assert page.status_code == 200
        assert "trainmaps · S-Bahn-Pünktlichkeit" in page.text
        assert "default-src 'none'" in page.headers["content-security-policy"]
        assert client.get("/karte/assets/map.js").status_code == 200
        assert client.get("/karte/assets/basemap-style.json").status_code == 200


def test_public_map_config_geometry_and_monthly_values(tmp_path):
    with seeded_client(tmp_path) as client:
        config = client.get("/api/v1/map/config")
        assert config.status_code == 200
        body = config.json()
        assert body["default_line_id"] == LINE_ID
        assert body["default_month"] == "2026-05"
        assert body["lines"][0]["geometry_version"].startswith("basemap.de")
        assert next(layer for layer in body["layers"] if layer["id"] == "roads")["default"] is False

        geometry = client.get("/api/v1/map/lines.geojson", params={"line_id": LINE_ID})
        assert geometry.status_code == 200
        assert geometry.headers["content-type"].startswith("application/geo+json")
        assert geometry.json()["features"][0]["properties"]["line_id"] == LINE_ID

        delay = client.get("/api/v1/map/monthly", params={
            "line_id": LINE_ID, "month": "2026-05", "metric": "punctuality",
            "threshold_minutes": 5,
        })
        assert delay.status_code == 200
        assert delay.json()["ratio"] == .1
        assert delay.json()["numerator"] == 10
        assert "Ausfälle zählen" in delay.json()["definition"]

        cancelled = client.get("/api/v1/map/monthly", params={
            "line_id": LINE_ID, "month": "2026-05", "metric": "cancellations",
        })
        assert cancelled.json()["ratio"] == .04
        assert cancelled.json()["threshold_minutes"] is None


def test_map_hides_unverified_geometry(tmp_path):
    with seeded_client(tmp_path, status="mapped") as client:
        assert client.get("/api/v1/map/config").json()["lines"] == []
        hidden = client.get("/api/v1/map/lines.geojson", params={"line_id": LINE_ID})
        assert hidden.status_code == 404


def test_committed_geometry_and_style_have_auditable_sources():
    geometry = json.loads((ROOT / "trainmaps_api/map_data/de.muenchen.s1.geojson")
                          .read_text(encoding="utf-8"))
    metadata = geometry["metadata"]
    assert metadata["line_id"] == LINE_ID
    assert metadata["basemap_layer"] == "Verkehrslinie"
    assert metadata["basemap_fallback_classes"] == ["Eisenbahn", "Gleis"]
    assert metadata["max_stitched_gap_m"] <= metadata["stitch_tolerance_m"]
    assert metadata["stations"] == 23
    assert all(feature["properties"]["name"].find("Gleis") == -1
               for feature in geometry["features"]
               if feature["properties"]["feature_type"] == "station")

    style = json.loads((ROOT / "trainmaps_api/map_assets/basemap-style.json")
                       .read_text(encoding="utf-8"))
    categories = style["metadata"]["trainmaps:categories"]
    assert set(categories) == {"base", "water", "places", "sbahn", "rail", "roads", "boundaries"}
    hidden = {"roads", "rail", "boundaries"}
    assert all(layer.get("layout", {}).get("visibility") == "none"
               for layer in style["layers"]
               if layer["metadata"]["trainmaps:category"] in hidden)
