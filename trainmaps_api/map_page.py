"""Public, read-only map page and its deliberately narrow data endpoints."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .reference import LINE_ID_PATTERN


THRESHOLDS = (2, 5, 10, 20, 40)
MAP_ASSETS = Path(__file__).resolve().parent / "map_assets"


def _error(status, code, message):
    raise HTTPException(status_code=status, detail={
        "code": code, "message": message, "errors": [],
    })


def _geometry_path(line_id):
    return Path(__file__).resolve().parent / "map_data" / f"{line_id}.geojson"


def _ready_line(store, line_id):
    record = store.get_line(line_id)
    if (record is None or not record["active"]
            or record["geometry"]["status"] != "verified"
            or not _geometry_path(line_id).is_file()):
        _error(404, "map_line_not_found",
               "Die Linie ist nicht vorhanden oder ihr Fahrweg ist noch nicht freigegeben.")
    return record


def _latest_payload(store):
    snapshot = store.get(include_payload=True)
    if snapshot is None:
        _error(503, "map_data_unavailable", "Es wurden noch keine Kartendaten importiert.")
    try:
        return snapshot, json.loads(snapshot["payload"])
    except (UnicodeDecodeError, json.JSONDecodeError):
        _error(503, "map_data_invalid", "Der aktuelle Datenstand kann nicht gelesen werden.")


def _matching_rows(data, collection, record):
    aliases = {(item["netz"], item["line"]) for item in record["source_aliases"]}
    return [row for row in data.get(collection, [])
            if row.get("line_id") == record["line_id"]
            or (row.get("netz"), row.get("line")) in aliases]


def register_map(app: FastAPI, store, *, version: str):
    app.mount("/karte/assets", StaticFiles(directory=MAP_ASSETS), name="map-assets")

    @app.get("/karte", include_in_schema=False)
    @app.get("/karte/", include_in_schema=False)
    def map_page():
        response = FileResponse(MAP_ASSETS / "index.html", media_type="text/html")
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'; "
            "script-src 'self'; style-src 'self'; worker-src 'self' blob:; "
            "connect-src 'self' https://sgx.geodatenzentrum.de; "
            "img-src 'self' data: blob: https://sgx.geodatenzentrum.de; "
            "font-src 'self' https://sgx.geodatenzentrum.de"
        )
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @app.get("/api/v1/map/config", tags=["Karte"])
    def map_config():
        snapshot, data = _latest_payload(store)
        available = []
        for record in store.list_lines():
            line_id = record["line_id"]
            if (not record["active"] or record["geometry"]["status"] != "verified"
                    or not _geometry_path(line_id).is_file()):
                continue
            delay_rows = _matching_rows(data, "delaysByNetworkLineMonth", record)
            cancel_rows = _matching_rows(data, "cancellationsByNetworkLineMonth", record)
            months = sorted({row["month"][:7] for row in delay_rows + cancel_rows})
            if months:
                available.append({
                    "line_id": line_id,
                    "display_name": record["display_name"],
                    "network_id": record["network_id"],
                    "months": months,
                    "geometry_version": record["geometry"]["version"],
                    "mapping_revision": record["revision"],
                })
        receipt = json.loads(snapshot["receipt"])
        default_line = available[0] if available else None
        return {
            "application_version": version,
            "data_revision": receipt["revision"],
            "data_imported_at": receipt["received_at"],
            "default_line_id": default_line["line_id"] if default_line else None,
            "default_month": default_line["months"][-1] if default_line else None,
            "lines": available,
            "metrics": [
                {"id": "punctuality", "label": "Verspätung"},
                {"id": "cancellations", "label": "Ausfälle"},
            ],
            "thresholds_minutes": list(THRESHOLDS),
            "default_threshold_minutes": 5,
            "layers": [
                {"id": "selected", "label": "Ausgewählte S-Bahn", "default": True},
                {"id": "stations", "label": "Stationen", "default": True},
                {"id": "sbahn", "label": "Weiteres S-Bahn-Netz", "default": True},
                {"id": "places", "label": "Ortsnamen", "default": True},
                {"id": "water", "label": "Gewässer", "default": True},
                {"id": "rail", "label": "Übrige Bahnstrecken", "default": False},
                {"id": "boundaries", "label": "Grenzen", "default": False},
                {"id": "roads", "label": "Straßen und Autobahnen", "default": False},
            ],
            "attribution": {
                "basemap": "© 2026 basemap.de / BKG · Datenquellen: © GeoBasis-DE",
                "route_reference": "MVV Gesamt-Soll-Fahrplandaten (GTFS), 06/2026 · CC BY 4.0",
            },
        }

    @app.get("/api/v1/map/lines.geojson", tags=["Karte"])
    def map_geometry(
        line_id: Annotated[str, Query(pattern=LINE_ID_PATTERN)],
    ):
        _ready_line(store, line_id)
        return FileResponse(_geometry_path(line_id), media_type="application/geo+json",
                            headers={"X-Geometry-Status": "verified"})

    @app.get("/api/v1/map/monthly", tags=["Karte"])
    def map_monthly(
        line_id: Annotated[str, Query(pattern=LINE_ID_PATTERN)],
        month: Annotated[str, Query(pattern=r"^[0-9]{4}-(0[1-9]|1[0-2])$")],
        metric: Literal["punctuality", "cancellations"] = "punctuality",
        threshold_minutes: Annotated[int, Query()] = 5,
    ):
        if threshold_minutes not in THRESHOLDS:
            _error(422, "invalid_threshold", "Erlaubt sind 2, 5, 10, 20 oder 40 Minuten.")
        record = _ready_line(store, line_id)
        snapshot, data = _latest_payload(store)
        collection = ("delaysByNetworkLineMonth" if metric == "punctuality"
                      else "cancellationsByNetworkLineMonth")
        rows = [row for row in _matching_rows(data, collection, record)
                if row["month"][:7] == month]
        if not rows:
            _error(404, "map_value_not_found",
                   "Für diese Linie, Kennzahl und diesen Monat liegt kein Wert vor.")
        if len(rows) != 1:
            _error(503, "map_value_ambiguous",
                   "Der aktuelle Datenstand enthält mehr als einen passenden Linienwert.")
        row = rows[0]
        denominator = row["n_data_points"]
        if metric == "punctuality":
            on_time = row[f"n_on_time_{threshold_minutes}"]
            numerator = denominator - on_time
            ratio = numerator / denominator if denominator else None
            label = f"Nicht innerhalb von {threshold_minutes} Min."
            definition = (
                "Anteil der berücksichtigten Messpunkte, die nicht innerhalb der gewählten "
                "Verspätungsschwelle lagen. Ausfälle zählen in dieser Kennzahl nicht mit."
            )
        else:
            numerator = row["n_cancelled"]
            ratio = numerator / denominator if denominator else None
            label = "Ausgefallen"
            definition = "Anteil der im Quelldatensatz als ausgefallen gezählten Datenpunkte."
        receipt = json.loads(snapshot["receipt"])
        return JSONResponse({
            "line_id": line_id,
            "display_name": record["display_name"],
            "month": month,
            "metric": metric,
            "threshold_minutes": threshold_minutes if metric == "punctuality" else None,
            "label": label,
            "definition": definition,
            "ratio": ratio,
            "percentage": ratio * 100 if ratio is not None else None,
            "numerator": numerator,
            "n_data_points": denominator,
            "data_revision": receipt["revision"],
            "source_alias": {"netz": row["netz"], "line": row["line"]},
        })
