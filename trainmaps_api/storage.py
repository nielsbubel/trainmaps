"""Atomic, durable development imports. One configured source per instance."""
import json
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path


class Conflict(Exception):
    pass


class StorageFull(Exception):
    pass


class ReferenceConflict(Exception):
    pass


class Store:
    def __init__(self, path: Path, max_bytes=512 * 1024 * 1024):
        self.path = path
        self.max_bytes = max_bytes
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self.connect()) as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("""CREATE TABLE IF NOT EXISTS imports (
                id TEXT PRIMARY KEY, request_key TEXT UNIQUE NOT NULL,
                revision INTEGER UNIQUE NOT NULL, sha256 TEXT NOT NULL,
                received_at TEXT NOT NULL, receipt TEXT NOT NULL, payload BLOB NOT NULL
            )""")
            db.execute("""CREATE TABLE IF NOT EXISTS line_references (
                line_id TEXT PRIMARY KEY, revision INTEGER NOT NULL,
                updated_at TEXT NOT NULL, payload TEXT NOT NULL
            )""")
            db.execute("""CREATE TABLE IF NOT EXISTS line_aliases (
                netz TEXT NOT NULL, line TEXT NOT NULL, line_id TEXT NOT NULL,
                PRIMARY KEY (netz, line),
                FOREIGN KEY (line_id) REFERENCES line_references(line_id)
            )""")

    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return db

    def save(self, raw, report, request_key, revision):
        db = self.connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT revision,sha256,receipt FROM imports WHERE request_key=?",
                             (request_key,)).fetchone()
            if old:
                if old["sha256"] != report["sha256"] or old["revision"] != revision:
                    raise Conflict("Idempotency-Key wurde mit anderem Inhalt oder anderer Revision verwendet.")
                return json.loads(old["receipt"]), False
            highest = db.execute("SELECT MAX(revision) FROM imports").fetchone()[0]
            if highest is not None and revision <= highest:
                raise Conflict("Die Revision muss groesser als die zuletzt gespeicherte Revision sein.")
            used = db.execute("SELECT COALESCE(SUM(LENGTH(payload)),0) FROM imports").fetchone()[0]
            if used + len(raw) > self.max_bytes:
                raise StorageFull("Speicherlimit fuer Entwicklungsimporte erreicht.")
            import_id = str(uuid.uuid4())
            receipt = dict(report)
            receipt.update({"status": "stored", "import_id": import_id,
                            "revision": revision,
                            "received_at": datetime.now(timezone.utc).isoformat()})
            db.execute("INSERT INTO imports VALUES(?,?,?,?,?,?,?)", (
                import_id, request_key, revision, report["sha256"], receipt["received_at"],
                json.dumps(receipt, ensure_ascii=False), raw))
            db.commit()
            return receipt, True
        finally:
            db.close()

    def get(self, import_id=None, include_payload=False):
        fields = "receipt,sha256" + (",payload" if include_payload else "")
        with closing(self.connect()) as db:
            if import_id:
                row = db.execute(f"SELECT {fields} FROM imports WHERE id=?", (import_id,)).fetchone()
            else:
                row = db.execute(f"SELECT {fields} FROM imports ORDER BY revision DESC LIMIT 1").fetchone()
        return dict(row) if row else None

    def put_line(self, record):
        """Versioned, idempotent upsert. Source aliases may belong to only one line."""
        incoming = dict(record)
        db = self.connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT revision,updated_at,payload FROM line_references WHERE line_id=?",
                             (incoming["line_id"],)).fetchone()
            if old:
                existing = json.loads(old["payload"])
                comparable = {k: v for k, v in existing.items() if k != "updated_at"}
                if incoming["revision"] == old["revision"] and incoming == comparable:
                    return existing, False
                if incoming["revision"] <= old["revision"]:
                    raise ReferenceConflict(
                        "Die Mapping-Revision muss groesser sein; identische Wiederholungen bleiben erlaubt.")
            for alias in incoming["source_aliases"]:
                owner = db.execute("SELECT line_id FROM line_aliases WHERE netz=? AND line=?",
                                   (alias["netz"], alias["line"])).fetchone()
                if owner and owner["line_id"] != incoming["line_id"]:
                    raise ReferenceConflict(
                        f"Quellalias {alias['netz']}/{alias['line']} gehoert bereits zu {owner['line_id']}.")
            now = datetime.now(timezone.utc).isoformat()
            stored = {**incoming, "updated_at": now}
            payload = json.dumps(stored, ensure_ascii=False, sort_keys=True,
                                 separators=(",", ":"))
            db.execute("""INSERT INTO line_references(line_id,revision,updated_at,payload)
                          VALUES(?,?,?,?)
                          ON CONFLICT(line_id) DO UPDATE SET
                          revision=excluded.revision,updated_at=excluded.updated_at,payload=excluded.payload""",
                       (incoming["line_id"], incoming["revision"], now, payload))
            db.execute("DELETE FROM line_aliases WHERE line_id=?", (incoming["line_id"],))
            db.executemany("INSERT INTO line_aliases(netz,line,line_id) VALUES(?,?,?)",
                           [(a["netz"], a["line"], incoming["line_id"])
                            for a in incoming["source_aliases"]])
            db.commit()
            return stored, True
        finally:
            db.close()

    def get_line(self, line_id):
        with closing(self.connect()) as db:
            row = db.execute("SELECT payload FROM line_references WHERE line_id=?", (line_id,)).fetchone()
        return json.loads(row["payload"]) if row else None

    def list_lines(self):
        with closing(self.connect()) as db:
            rows = db.execute("SELECT payload FROM line_references ORDER BY line_id").fetchall()
        return [json.loads(row["payload"]) for row in rows]

    def alias_map(self):
        with closing(self.connect()) as db:
            rows = db.execute("SELECT netz,line,line_id FROM line_aliases").fetchall()
        return {(row["netz"], row["line"]): row["line_id"] for row in rows}

    def lines_by_ids(self, line_ids):
        ids = sorted(set(line_ids))
        if not ids:
            return {}
        placeholders = ",".join("?" for _ in ids)
        with closing(self.connect()) as db:
            rows = db.execute(
                f"SELECT line_id,payload FROM line_references WHERE line_id IN ({placeholders})", ids
            ).fetchall()
        return {row["line_id"]: json.loads(row["payload"]) for row in rows}
