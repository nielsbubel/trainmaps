from __future__ import annotations

import asyncio
import collections
import copy
import hashlib
import hmac
import itertools
import json
import os
import time
import uuid
import zlib
from pathlib import Path
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Path as ApiPath, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jsonschema import Draft202012Validator
from starlette.concurrency import run_in_threadpool

from scripts.inspect_frontend import inspect_bytes, reject_constant, unique_object
from .contract import EVA_ID_PATTERN, MAX_BYTES, export_schema
from .documentation import register_documentation
from .map_page import register_map
from .reference import LINE_ID_PATTERN, LineDefinition, LineList, LineRecord
from .storage import Conflict, ReferenceConflict, StorageFull, Store

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_V1 = export_schema()
SCHEMA_V2 = export_schema(require_line_ids=True)
SCHEMA_V3 = export_schema(require_line_ids=True, require_eva_stations=True)
VALIDATORS = {
    "frontend-1": Draft202012Validator(SCHEMA_V1),
    "frontend-2": Draft202012Validator(SCHEMA_V2),
    "frontend-3": Draft202012Validator(SCHEMA_V3),
}
VERSION = "0.10.0"
LINE_COLLECTIONS = (
    "cancellationsByNetworkLineMonth",
    "delaysByNetworkLineMonth",
    "mostCancelledStops",
)
security = HTTPBearer(auto_error=False)


def fail(status, code, message, errors=None):
    raise HTTPException(status_code=status, detail={"code": code, "message": message,
                                                    "errors": errors or []})


def _pointer(parts):
    return "/" + "/".join(str(part).replace("~", "~0").replace("/", "~1")
                            for part in parts)


def validate_raw(raw, *, contract_version="frontend-1", store=None):
    try:
        parsed = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_object,
                            parse_constant=reject_constant)
    except (ValueError, UnicodeDecodeError, RecursionError) as exc:
        fail(400, "invalid_json", f"Gueltiges UTF-8 JSON wird erwartet: {str(exc)[:200]}")
    validator = VALIDATORS[contract_version]
    try:
        errors = [{"path": _pointer(error.absolute_path), "code": "schema_error",
                   "message": error.message[:300]}
                  for error in itertools.islice(validator.iter_errors(parsed), 20)]
    except (RecursionError, TypeError, ValueError):
        fail(422, "schema_error", "JSON-Struktur ist ungueltig.")
    if errors:
        fail(422, "schema_error",
             f"Das JSON entspricht nicht dem {contract_version}-Vertrag.", errors)

    references = {}
    audit_raw = raw
    if contract_version in ("frontend-2", "frontend-3"):
        if store is None:
            raise RuntimeError("frontend-2/3 validation requires a reference store")
        occurrences = [
            (name, index, row)
            for name in LINE_COLLECTIONS
            for index, row in enumerate(parsed[name])
        ]
        line_ids = {row["line_id"] for _, _, row in occurrences}
        references = store.lines_by_ids(line_ids)
        aliases = store.alias_map()
        reference_errors = []
        for name, index, row in occurrences:
            line_id = row["line_id"]
            record = references.get(line_id)
            path = f"/{name}/{index}/line_id"
            if record is None:
                reference_errors.append({"path": path, "code": "unknown_line_id",
                                         "message": f"Unbekannte line_id: {line_id}"})
            elif not record["active"]:
                reference_errors.append({"path": path, "code": "inactive_line_id",
                                         "message": f"Inaktive line_id: {line_id}"})
            elif aliases.get((row["netz"], row["line"])) != line_id:
                reference_errors.append({
                    "path": path, "code": "line_alias_mismatch",
                    "message": (f"{row['netz']}/{row['line']} ist nicht als Quellalias "
                                f"von {line_id} registriert."),
                })
            if len(reference_errors) == 20:
                break
        if reference_errors:
            fail(422, "line_reference_error",
                 "Linien-IDs oder Quellalias-Zuordnungen sind ungueltig.", reference_errors)

        if contract_version == "frontend-3":
            names_by_stop = {}
            station_errors = []
            for index, row in enumerate(parsed["mostCancelledStops"]):
                existing = names_by_stop.setdefault(row["stop_id"], row["stop_name"])
                if existing != row["stop_name"]:
                    station_errors.append({
                        "path": f"/mostCancelledStops/{index}/stop_name",
                        "code": "station_name_mismatch",
                        "message": (f"EVA {row['stop_id']} wurde bereits mit dem Namen "
                                    f"{existing!r} geliefert."),
                    })
                if len(station_errors) == 20:
                    break
            if station_errors:
                fail(422, "station_reference_error",
                     "Eine EVA-Nummer muss innerhalb eines Exports genau einen Namen haben.",
                     station_errors)

        # The established inspector validates the numerical relationships. It expects
        # frontend-1 fields, so only the added line_id is removed from an audit copy.
        audit_data = copy.deepcopy(parsed)
        for name in LINE_COLLECTIONS:
            for row in audit_data[name]:
                row.pop("line_id")
        if contract_version == "frontend-3":
            for row in audit_data["mostCancelledStops"]:
                row.pop("stop_name")
        audit_raw = json.dumps(audit_data, ensure_ascii=False, allow_nan=False,
                               separators=(",", ":")).encode("utf-8")

    try:
        audit = inspect_bytes(audit_raw)
    except ValueError as exc:
        fail(422, "invalid_export", str(exc)[:300])
    if audit["validation_errors"]:
        fail(422, "inconsistent_data", "Zaehler, Quoten oder Aggregationen sind inkonsistent.",
             audit["validation_errors"][:20])
    if audit["total_rows"] == 0:
        fail(422, "empty_export", "Ein vollstaendig leerer Export wird nicht gespeichert.")

    used_references = {line_id: record["revision"]
                       for line_id, record in sorted(references.items())}
    map_ready = bool(used_references) and all(
        record["active"] and record["geometry"]["status"] == "verified"
        for record in references.values()
    )
    warnings = []
    if not map_ready:
        warnings.append({
            "code": "mapping_unverified",
            "message": ("Mindestens ein Fahrweg ist noch nicht freigegeben."
                        if used_references else
                        "Der Import enthaelt keine verifizierten trainmaps-Linienreferenzen."),
        })
    warnings.append({
        "code": "measurement_definition_pending",
        "message": "Schwellenvergleich, Zaehleinheit und Monatsabgrenzung sind noch zu klaeren.",
    })
    if audit["collections"]["mostCancelledStops"]["rows"]:
        warnings.append({
            "code": "ranking_period_unknown",
            "message": "Stationsrangliste hat keinen Zeitraum; sie bleibt getrennt vom Monatsfilter.",
        })
    if audit["unequal_non_cancelled_and_delay_denominators"]:
        warnings.append({
            "code": "different_denominators",
            "message": "Ausfall- und Puenktlichkeitsquoten haben unterschiedliche Grundgesamtheiten und werden nicht kombiniert.",
        })
    return {
        "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw),
        "contract_version": contract_version,
        "total_rows": audit["total_rows"],
        "collection_counts": {key: value["rows"] for key, value in audit["collections"].items()},
        "months": audit["months"], "networks": audit["networks"],
        "station_count": audit["unique_stop_ids_in_ranking"],
        "line_reference_revisions": used_references,
        "map_ready": map_ready, "warnings": warnings,
    }


def create_app(*, data_dir=None, write_token=None, read_token=None, mapping_token=None):
    folder = Path(data_dir or os.getenv("TRAINMAPS_DATA_DIR", str(ROOT / ".local")))
    write_token = write_token or os.getenv("TRAINMAPS_WRITE_TOKEN")
    read_token = read_token or os.getenv("TRAINMAPS_READ_TOKEN")
    mapping_token = mapping_token or os.getenv("TRAINMAPS_MAPPING_TOKEN")
    if not write_token or not read_token or not mapping_token:
        config = json.loads((folder / "access.local.json").read_text(encoding="utf-8"))
        write_token = write_token or config["write_token"]
        read_token = read_token or config["read_token"]
        mapping_token = mapping_token or config["mapping_token"]
    tokens = (write_token, read_token, mapping_token)
    if min(map(len, tokens)) < 32 or len(set(tokens)) != 3:
        raise ValueError("Three distinct tokens of at least 32 characters are required")

    store = Store(folder / "trainmaps.sqlite3")
    app = FastAPI(
        title="trainmaps Development API", version=VERSION,
        description=("[Vollständige Dokumentation](/dokumentation) · "
                     "[Schnellstart](/dokumentation/schnellstart) · "
                     "[API-Anleitung](/dokumentation/api)\n\n"
                     "Versioned data imports and a separately managed line-reference catalog. "
                     "Use frontend-3 for stable line IDs and canonical German EVA station IDs."),
        swagger_ui_parameters={"persistAuthorization": False},
    )
    origins = [value.strip() for value in os.getenv("TRAINMAPS_CORS_ORIGINS", "").split(",")
               if value.strip()]
    if "*" in origins:
        raise ValueError("Configure explicit frontend origins instead of '*'")
    if origins:
        app.add_middleware(
            CORSMiddleware, allow_origins=origins, allow_methods=["GET", "POST", "PUT"],
            allow_headers=["Authorization", "Content-Type", "Content-Encoding",
                           "Idempotency-Key", "X-Dataset-Revision"],
        )
    recent = {"write": collections.deque(), "read": collections.deque()}
    ingest_lock = asyncio.Lock()

    async def authorize(credentials, permission):
        supplied = credentials.credentials if credentials else ""
        encoded = supplied.encode("utf-8")
        writer = hmac.compare_digest(encoded, write_token.encode("utf-8"))
        reader = hmac.compare_digest(encoded, read_token.encode("utf-8"))
        mapper = hmac.compare_digest(encoded, mapping_token.encode("utf-8"))
        if not writer and not reader and not mapper:
            fail(401, "unauthorized", "Ein gueltiger Bearer-Token ist erforderlich.")
        allowed = {
            "write": writer,
            "read": writer or reader,
            "mapping": mapper,
            "reference_read": writer or reader or mapper,
        }[permission]
        if not allowed:
            fail(403, "forbidden", "Der verwendete Token hat fuer diesen Endpunkt keine Berechtigung.")
        bucket = recent["write" if permission in ("write", "mapping") else "read"]
        now = time.monotonic()
        while bucket and bucket[0] < now - 60:
            bucket.popleft()
        if len(bucket) >= (30 if permission in ("write", "mapping") else 120):
            fail(429, "rate_limit", "Anfragelimit erreicht; spaeter erneut versuchen.")
        bucket.append(now)

    async def can_write(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)]):
        await authorize(credentials, "write")

    async def can_read(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)]):
        await authorize(credentials, "read")

    async def can_manage_mapping(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)]):
        await authorize(credentials, "mapping")

    async def can_read_reference(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)]):
        await authorize(credentials, "reference_read")

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        headers = {"Cache-Control": "no-store"}
        if exc.status_code == 401:
            headers["WWW-Authenticate"] = "Bearer"
        if exc.status_code == 429:
            headers["Retry-After"] = "60"
        return JSONResponse(exc.detail, status_code=exc.status_code, headers=headers)

    @app.exception_handler(RequestValidationError)
    async def request_error(request, exc):
        errors = [{"path": _pointer(error["loc"]), "code": error["type"],
                   "message": error["msg"]} for error in exc.errors()[:20]]
        return JSONResponse({"code": "invalid_parameters",
                             "message": "Parameter fehlen oder sind ungueltig.",
                             "errors": errors}, status_code=422)

    @app.middleware("http")
    async def response_headers(request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        return response

    register_documentation(app, ROOT)
    register_map(app, store, version=VERSION)

    @app.get("/health", tags=["Status"])
    async def health():
        return {"status": "ok", "service": "trainmaps-development", "version": VERSION}

    @app.get("/api/v1/reference/lines", tags=["Linienreferenzen"],
             dependencies=[Depends(can_read_reference)], response_model=LineList)
    def list_line_references(
        netz: str | None = None,
        line: str | None = None,
        network_id: str | None = None,
        geometry_status: Literal["pending", "mapped", "verified"] | None = None,
        active: bool | None = None,
        offset: Annotated[int, Query(ge=0)] = 0,
        limit: Annotated[int, Query(ge=1, le=5000)] = 1000,
    ):
        """Catalog of stable line IDs. Data suppliers use these IDs in frontend-2/3."""
        values = [record for record in store.list_lines()
                  if ((netz is None and line is None) or any(
                      (netz is None or alias["netz"] == netz)
                      and (line is None or alias["line"] == line)
                      for alias in record["source_aliases"]))
                  and (network_id is None or record["network_id"] == network_id)
                  and (geometry_status is None
                       or record["geometry"]["status"] == geometry_status)
                  and (active is None or record["active"] is active)]
        page_values = values[offset:offset + limit]
        return {"total": len(values), "offset": offset,
                "next_offset": offset + limit if offset + limit < len(values) else None,
                "values": page_values}

    @app.get("/api/v1/reference/lines/{line_id}", tags=["Linienreferenzen"],
             dependencies=[Depends(can_read_reference)], response_model=LineRecord)
    def get_line_reference(line_id: Annotated[str, ApiPath(pattern=LINE_ID_PATTERN)]):
        record = store.get_line(line_id)
        if record is None:
            fail(404, "line_reference_not_found", "Linienreferenz nicht gefunden.")
        return record

    @app.put("/api/v1/reference/lines/{line_id}", tags=["Linienreferenzen"],
             dependencies=[Depends(can_manage_mapping)], response_model=LineRecord,
             responses={201: {"description": "Linienreferenz angelegt"},
                        409: {"description": "Revision oder Quellalias kollidiert"}})
    def put_line_reference(line_id: Annotated[str, ApiPath(pattern=LINE_ID_PATTERN)],
                           definition: LineDefinition, response: Response):
        """Create or revise a line mapping. Only the dedicated mapping token is accepted."""
        existing = store.get_line(line_id)
        try:
            stored, _ = store.put_line({"line_id": line_id, **definition.model_dump()})
        except ReferenceConflict as exc:
            fail(409, "line_reference_conflict", str(exc))
        response.status_code = 201 if existing is None else 200
        return stored

    async def ingest_export(request, idempotency_key, revision, validate_only,
                            contract_version):
        if request.headers.get("content-type", "").split(";")[0].lower() != "application/json":
            fail(415, "content_type", "Content-Type application/json ist erforderlich.")
        encoding = request.headers.get("content-encoding", "identity").lower()
        if encoding not in ("identity", "gzip"):
            fail(415, "content_encoding", "Unterstuetzt werden identity und gzip.")
        if ingest_lock.locked():
            fail(429, "import_busy", "Ein Import laeuft bereits.")
        async with ingest_lock:
            async def receive():
                chunks, size = [], 0
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > MAX_BYTES:
                        fail(413, "body_too_large", "Maximal 32 MiB pro Lieferung.")
                    chunks.append(chunk)
                return b"".join(chunks)

            try:
                raw = await asyncio.wait_for(receive(), timeout=60)
            except TimeoutError:
                fail(408, "upload_timeout", "Upload-Zeitlimit von 60 Sekunden erreicht.")
            if encoding == "gzip":
                try:
                    inflater = zlib.decompressobj(16 + zlib.MAX_WBITS)
                    raw = inflater.decompress(raw, MAX_BYTES + 1)
                    if len(raw) > MAX_BYTES or inflater.unconsumed_tail:
                        fail(413, "decompressed_too_large", "Entpacktes JSON uebersteigt 32 MiB.")
                    if not inflater.eof or inflater.unused_data:
                        fail(400, "invalid_gzip", "Ein vollstaendiger einzelner gzip-Datenstrom wird erwartet.")
                except zlib.error:
                    fail(400, "invalid_gzip", "Ungueltiger gzip-Datenstrom.")
            report = await run_in_threadpool(
                lambda: validate_raw(raw, contract_version=contract_version, store=store))
            if validate_only:
                return JSONResponse({**report, "status": "validated", "stored": False})
            try:
                receipt, created = await run_in_threadpool(
                    store.save, raw, report, str(idempotency_key), revision)
            except Conflict as exc:
                fail(409, "import_conflict", str(exc))
            except StorageFull as exc:
                fail(507, "storage_quota", str(exc))
            return JSONResponse(receipt, status_code=201 if created else 200)

    common_import_responses = {
        200: {"description": "Dry run or identical replay"},
        400: {"description": "Malformed JSON or gzip"},
        401: {"description": "Authentication required"},
        403: {"description": "Wrong token role"},
        409: {"description": "Idempotency or revision conflict"},
        413: {"description": "Body exceeds 32 MiB"},
        415: {"description": "Unsupported media type/encoding"},
        422: {"description": "Invalid data or line reference"},
        429: {"description": "Rate limit or another import in progress"},
        507: {"description": "Development storage quota reached"},
    }

    @app.post("/api/v1/imports/frontend", tags=["Import"], dependencies=[Depends(can_write)],
              status_code=201, deprecated=True,
              openapi_extra={"requestBody": {"required": True, "content": {
                  "application/json": {"schema": {"$ref": "#/components/schemas/FrontendExportV1"}}}}},
              responses=common_import_responses)
    async def ingest_v1(request: Request,
                        idempotency_key: Annotated[uuid.UUID, Header()],
                        x_dataset_revision: Annotated[int, Header(ge=1, le=2_147_483_647)],
                        validate_only: bool = False):
        """Legacy import without stable line IDs. It remains readable but never map-ready."""
        return await ingest_export(request, idempotency_key, x_dataset_revision,
                                   validate_only, "frontend-1")

    @app.post("/api/v2/imports/frontend", tags=["Import"], dependencies=[Depends(can_write)],
              status_code=201,
              openapi_extra={"requestBody": {"required": True, "content": {
                  "application/json": {"schema": {"$ref": "#/components/schemas/FrontendExportV2"}}}}},
              responses=common_import_responses)
    async def ingest_v2(request: Request,
                        idempotency_key: Annotated[uuid.UUID, Header()],
                        x_dataset_revision: Annotated[int, Header(ge=1, le=2_147_483_647)],
                        validate_only: bool = False):
        """Preferred import. Every source line must resolve to a catalog line_id."""
        return await ingest_export(request, idempotency_key, x_dataset_revision,
                                   validate_only, "frontend-2")

    @app.post("/api/v3/imports/frontend", tags=["Import"], dependencies=[Depends(can_write)],
              status_code=201,
              openapi_extra={"requestBody": {"required": True, "content": {
                  "application/json": {"schema": {"$ref": "#/components/schemas/FrontendExportV3"}}}}},
              responses=common_import_responses)
    async def ingest_v3(request: Request,
                        idempotency_key: Annotated[uuid.UUID, Header()],
                        x_dataset_revision: Annotated[int, Header(ge=1, le=2_147_483_647)],
                        validate_only: bool = False):
        """Preferred import with line IDs, German EVA station IDs and station names."""
        return await ingest_export(request, idempotency_key, x_dataset_revision,
                                   validate_only, "frontend-3")

    def lookup(import_id=None, payload=False):
        result = store.get(str(import_id) if import_id else None, include_payload=payload)
        if result is None:
            fail(404, "import_not_found", "Noch kein Import vorhanden oder Import-ID unbekannt.")
        return result

    @app.get("/api/v1/imports/{import_id}", tags=["Import"], dependencies=[Depends(can_read)])
    def receipt(import_id: uuid.UUID):
        return json.loads(lookup(import_id)["receipt"])

    @app.get("/api/v1/data/frontend", tags=["Daten"], dependencies=[Depends(can_read)])
    def frontend(import_id: uuid.UUID | None = None):
        """Retrieve exact original JSON bytes, latest revision or a pinned import ID."""
        result = lookup(import_id, True)
        return Response(content=result["payload"], media_type="application/json",
                        headers={"ETag": '"' + result["sha256"] + '"'})

    @app.get("/api/v1/data/monthly", tags=["Daten"], dependencies=[Depends(can_read)])
    def monthly(
        metric: Literal["punctuality", "cancellations"],
        month: Annotated[str, Query(pattern=r"^[0-9]{4}-(0[1-9]|1[0-2])$")],
        scope: Literal["all", "network", "line"] = "line",
        netz: str | None = None,
        line: str | None = None,
        line_id: Annotated[str | None, Query(pattern=LINE_ID_PATTERN)] = None,
        import_id: uuid.UUID | None = None,
        offset: Annotated[int, Query(ge=0)] = 0,
        limit: Annotated[int, Query(ge=1, le=5000)] = 1000,
    ):
        """Return monthly source rows and current line-reference status for line scope."""
        if (line and (not netz or scope != "line")) or (netz and scope == "all"):
            fail(422, "invalid_filter", "Linienfilter benoetigt scope=line und netz; Netzfilter benoetigt scope=network oder line.")
        if line_id and scope != "line":
            fail(422, "invalid_filter", "line_id kann nur mit scope=line verwendet werden.")
        result = lookup(import_id, True)
        receipt_data = json.loads(result["receipt"])
        data = json.loads(result["payload"])
        collection = ("delays" if metric == "punctuality" else "cancellations") + {
            "all": "ByMonth", "network": "ByNetworkMonth", "line": "ByNetworkLineMonth"}[scope]
        aliases = store.alias_map() if scope == "line" else {}
        candidates = []
        for source_row in data[collection]:
            if source_row["month"][:7] != month:
                continue
            if netz is not None and source_row.get("netz") != netz:
                continue
            if line is not None and source_row.get("line") != line:
                continue
            enriched = dict(source_row)
            if scope == "line":
                resolved_id = source_row.get("line_id") or aliases.get(
                    (source_row["netz"], source_row["line"]))
                reference = store.get_line(resolved_id) if resolved_id else None
                enriched["line_id"] = resolved_id
                enriched["geometry_status"] = (
                    reference["geometry"]["status"] if reference and reference["active"]
                    else "unmapped")
                if line_id is not None and resolved_id != line_id:
                    continue
            candidates.append(enriched)
        output = []
        for source_row in candidates[offset:offset + limit]:
            result_row = {**source_row, "month": month}
            for key in list(result_row):
                if key.startswith("p_"):
                    result_row[key] = (result_row["n_" + key[2:]] / result_row["n_data_points"]
                                       if result_row["n_data_points"] else None)
            output.append(result_row)
        map_ready = (scope == "line" and bool(output)
                     and all(row["geometry_status"] == "verified" for row in output))
        return {
            "import_id": receipt_data["import_id"], "revision": receipt_data["revision"],
            "contract_version": receipt_data.get("contract_version", "frontend-1"),
            "metric": metric, "scope": scope, "month": month, "total": len(candidates),
            "offset": offset,
            "next_offset": offset + limit if offset + limit < len(candidates) else None,
            "map_ready": map_ready, "values": output,
        }

    @app.get("/api/v1/data/stops/{stop_id}", tags=["Daten"],
             dependencies=[Depends(can_read)])
    def stop(
        stop_id: Annotated[str, ApiPath(pattern=EVA_ID_PATTERN)],
        line_id: Annotated[str | None, Query(pattern=LINE_ID_PATTERN)] = None,
        import_id: uuid.UUID | None = None,
    ):
        """Return all cancellation-ranking rows for one German DB EVA station."""
        stored = lookup(import_id, True)
        receipt_data = json.loads(stored["receipt"])
        data = json.loads(stored["payload"])
        aliases = store.alias_map()
        values = []
        for source_row in data["mostCancelledStops"]:
            if source_row["stop_id"] != stop_id:
                continue
            resolved_id = source_row.get("line_id") or aliases.get(
                (source_row["netz"], source_row["line"]))
            if line_id is not None and resolved_id != line_id:
                continue
            reference = store.get_line(resolved_id) if resolved_id else None
            value = dict(source_row)
            value["line_id"] = resolved_id
            value["geometry_status"] = (
                reference["geometry"]["status"] if reference and reference["active"]
                else "unmapped")
            value["p_cancelled"] = (
                value["n_cancelled"] / value["n_data_points"]
                if value["n_data_points"] else None)
            values.append(value)
        if not values:
            fail(404, "stop_not_found",
                 "Haltestelle oder angeforderte Linienzuordnung nicht gefunden.")
        values.sort(key=lambda row: (row.get("line_id") or "", row["netz"], row["line"]))
        names = sorted({row["stop_name"] for row in values if row.get("stop_name")})
        return {
            "import_id": receipt_data["import_id"],
            "revision": receipt_data["revision"],
            "contract_version": receipt_data.get("contract_version", "frontend-1"),
            "stop_id": stop_id,
            "station_id": f"de.eva.{stop_id}",
            "id_type": "eva",
            "stop_name": names[0] if len(names) == 1 else None,
            "ranking_period": None,
            "total": len(values),
            "values": values,
        }

    def openapi():
        if app.openapi_schema is None:
            spec = get_openapi(title=app.title, version=app.version,
                               description=app.description, routes=app.routes)
            schemas = spec.setdefault("components", {}).setdefault("schemas", {})
            schemas["FrontendExport"] = SCHEMA_V1  # Compatibility alias.
            schemas["FrontendExportV1"] = SCHEMA_V1
            schemas["FrontendExportV2"] = SCHEMA_V2
            schemas["FrontendExportV3"] = SCHEMA_V3
            app.openapi_schema = spec
        return app.openapi_schema

    app.openapi = openapi
    return app
