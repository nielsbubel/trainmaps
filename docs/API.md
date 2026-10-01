# trainmaps: Datenlieferung und Entwicklungs-API

Version 0.10.0. Öffentliche Basisadresse: **https://34.7.91.18**. Lokal läuft
die Anwendung unter **http://127.0.0.1:8787**. Die interaktive Beschreibung
steht unter **https://34.7.91.18/docs**, der maschinenlesbare Vertrag unter
`/openapi.json` bzw. [api/openapi.json](../api/openapi.json).

Die API verwaltet zwei getrennte Bereiche:

1. vollständige, versionierte Statistikimporte;
2. einen versionierten Katalog stabiler `line_id`-Werte und ihrer Zuordnung zu
   S-Bahn-Fahrwegen aus basemap.de.

## Zugriffsrollen

Die lokalen Schlüssel liegen in `.local/access.local.json` und werden nie über
die Dokumentation veröffentlicht.

| Schlüssel | Rechte |
| --- | --- |
| `write_token` | Import prüfen und speichern, Daten und Linienkatalog lesen. |
| `read_token` | Daten und Linienkatalog lesen. |
| `mapping_token` | Linienreferenzen lesen, anlegen und mit höherer Revision ändern. |

Der Mapping-Schlüssel wird nur vom Betreiber verwendet. Ein Datenlieferant kann
die veröffentlichten Linien-IDs mit seinem Schreibschlüssel lesen, aber keine
Zuordnung verändern. Alle geschützten Anfragen senden
`Authorization: Bearer <TOKEN>` über HTTPS.

## Endpunkte

| Methode | Pfad | Rolle | Funktion |
| --- | --- | --- | --- |
| GET | `/health` | frei | Dienst und Version prüfen. |
| GET | `/docs`, `/openapi.json` | frei | Schnittstelle ansehen bzw. herunterladen. |
| GET | `/dokumentation` | frei | Vollständige Projektdokumentation. |
| GET | `/karte` | frei | Responsive Webkarte öffnen. |
| GET | `/api/v1/map/config` | frei | Freigegebene Verkehrsgebiete und Linien, Vergleichswerte, Kartengrenzen und Ebenen. |
| GET | `/api/v1/map/networks` | frei | Zusammenfassung aller Verkehrsgebiete für die deutschlandweite Startansicht. |
| GET | `/api/v1/map/network-series` | frei | Gewichtete Monatszeitreihe eines Verkehrsgebiets lesen. |
| GET | `/api/v1/map/lines.geojson` | frei | Verifizierten Fahrweg und Stationen einer Linie lesen. |
| GET | `/api/v1/map/series` | frei | Vollständige Monatszeitreihe und Vergleichswerte einer verifizierten Linie lesen. |
| GET | `/api/v1/map/monthly` | frei | Einen darstellbaren Monatswert einer verifizierten Linie lesen. |
| GET | `/api/v1/reference/lines` | read, write oder mapping | Linienkatalog filtern und seitenweise lesen. |
| GET | `/api/v1/reference/lines/{line_id}` | read, write oder mapping | Eine Linienreferenz lesen. |
| PUT | `/api/v1/reference/lines/{line_id}` | mapping | Linienreferenz anlegen oder revidieren. |
| POST | `/api/v3/imports/frontend` | write | Bevorzugter Import mit Linien-IDs, EVA-Nummern und Stationsnamen. |
| POST | `/api/v3/imports/frontend?validate_only=true` | write | v3 prüfen, ohne zu speichern. |
| POST | `/api/v2/imports/frontend` | write | Bestehender Import mit stabilen Linien-IDs. |
| POST | `/api/v1/imports/frontend` | write | Alter Import ohne Linien-IDs; weiterhin unterstützt. |
| GET | `/api/v1/imports/{import_id}` | read oder write | Importbeleg abrufen. |
| GET | `/api/v1/data/frontend` | read oder write | Exakte Bytes eines gespeicherten Imports abrufen. |
| GET | `/api/v1/data/monthly` | read oder write | Monatswerte filtern und Mappingstatus anzeigen. |
| GET | `/api/v1/data/stops/{stop_id}` | read oder write | Ausfallwerte einer Haltestelle anhand ihrer EVA-Nummer lesen. |

Die öffentlichen Kartenendpunkte sind absichtlich enger als die geschützten
Datenendpunkte. Sie geben nur aktive Linien im Status `verified`, deren Geometrie
und genau angeforderte Monatswerte aus. Details und vollständige Beispielaufrufe:
[Webkarte](KARTE.md).

Aktuell veröffentlicht die Karte 96 Linien aus 14 Netzen. Die neun Münchner IDs
stehen in [line-references-muenchen.json](../examples/line-references-muenchen.json),
die 87 Linien des bundesweiten ersten Durchlaufs in
[line-references-germany.json](../examples/line-references-germany.json). Der
[Prüfbericht](germany-first-pass-report.json) nennt die Auswahlregeln und die
elf historischen oder aktuell nicht zugeordneten Quellkennungen.

`GET /api/v1/map/network-series?network_id=de.muenchen` liefert die Zeitreihe
für ein ganzes Verkehrsgebiet. Die API summiert je Monat zuerst die Rohzähler
aller veröffentlichten Linien. Verspätung und Ausfallquote sind damit nach
`n_data_points` gewichtet. `GET /api/v1/map/series?line_id=de.muenchen.s1`
liefert die entsprechende Auswertung für eine einzelne Linie. Beide liefern alle
Monate in chronologischer Reihenfolge, geschätzte
Verspätungsminuten, Ausfallquoten sowie Mittelwert, Minimum, Maximum und letzten
Monatswert beider Kennzahlen.
Die Antwort enthält die verwendeten Klassenmittelpunkte, damit die aus den
kumulierten Schwellen abgeleitete Verspätungsschätzung nachvollziehbar bleibt.

## Linienkatalog

`line_id` ist eine stabile, von trainmaps vergebene ID wie `de.berlin.s1`.
Sie ist unabhängig von Anzeigenamen und von technischen Feature-IDs einzelner
basemap.de-Ausgaben. Zulässig sind Kleinbuchstaben, Ziffern sowie Punkte,
Unterstriche und Bindestriche als Trenner.

Ein Katalogeintrag enthält:

```json
{
  "revision": 3,
  "network_id": "de.berlin",
  "display_name": "S1 Berlin",
  "source_aliases": [
    {"netz": "Berlin", "line": "1"},
    {"netz": "Berlin", "line": "S1"}
  ],
  "geometry": {
    "source": "basemap.de",
    "source_layer": "Verkehrslinie",
    "source_class": "S-Bahn",
    "fallback_classes": ["Eisenbahn", "Gleis"],
    "status": "verified",
    "reference": "trainmaps:geometry:de.berlin.s1",
    "version": "2026-09"
  },
  "active": true,
  "notes": null
}
```

`source_aliases` ordnet die gelieferten Werte aus `netz` und `line` genau einer
`line_id` zu. Ein Alias kann nicht mehreren Linien gehören. `geometry.status`
durchläuft `pending`, `mapped` und `verified`. Für `mapped` und `verified` sind
`reference` und `version` Pflicht. Die Referenz bezeichnet die vom Betreiber
ausgewählte, versionierte Fahrweg-Geometrie auf Basis des basemap.de-Layers
`Verkehrslinie` mit Klasse `S-Bahn`.

Ein `PUT` legt Revision 1 mit HTTP 201 an. Eine identische Wiederholung derselben
Revision liefert HTTP 200. Inhaltliche Änderungen benötigen eine höhere
Revision; sonst folgt HTTP 409. Löschen ist absichtlich nicht vorgesehen.
Stillgelegte Zuordnungen werden mit einer neuen Revision und `active: false`
markiert, damit alte Belege nachvollziehbar bleiben.

Beispiel für den Betreiber:

```powershell
$base = 'https://34.7.91.18'
$access = Get-Content -Raw '.local/access.local.json' | ConvertFrom-Json
$headers = @{ Authorization = "Bearer $($access.mapping_token)" }
Invoke-RestMethod -Method Put -Headers $headers -ContentType 'application/json' `
  -Uri "$base/api/v1/reference/lines/de.test.s1" `
  -InFile 'examples/line-reference.json'
```

Der mitgelieferte Eintrag ist synthetisch und bleibt im Status `pending`. Echte
IDs werden erst nach Prüfung der Quelle angelegt.

Der Katalog unterstützt `netz`, `line`, `network_id`, `geometry_status`,
`active`, `offset` und `limit` als Filter. Mit `netz` und `line` löst ein
Lieferant ein exaktes Quellpaar auf. `limit` liegt zwischen 1 und 5.000.

## Importformat frontend-3

Der bevorzugte Body besteht unmittelbar aus den sieben Arrays des vorhandenen
Exports. `frontend-3` verlangt in jeder Zeile mit `line` zusätzlich
`line_id`. Das betrifft:

- `cancellationsByNetworkLineMonth`;
- `delaysByNetworkLineMonth`;
- `mostCancelledStops`.

Beispiel einer Zeile:

```json
{
  "month": "2021-09-01T00:00:00.000000+0000",
  "netz": "Berlin",
  "line": "1",
  "line_id": "de.berlin.s1",
  "n_data_points": 10303,
  "p_on_time_2": 0.9506939726293313,
  "p_on_time_5": 0.9886440842473067,
  "p_on_time_10": 0.9966999902940891,
  "p_on_time_20": 0.9998058817820052,
  "p_on_time_40": 1.0,
  "n_on_time_2": 9795,
  "n_on_time_5": 10186,
  "n_on_time_10": 10269,
  "n_on_time_20": 10301,
  "n_on_time_40": 10303
}
```

Der Server prüft, dass jede ID existiert, aktiv ist und genau zum mitgelieferten
Paar `netz`/`line` gehört. Er speichert die verwendeten Katalogrevisionen im
Importbeleg. Unbekannte, inaktive oder falsch zugeordnete IDs liefern HTTP 422
mit `code: "line_reference_error"`.

Für jede Zeile in `mostCancelledStops` gelten zusätzlich:

| Feld | Regel |
| --- | --- |
| `stop_id` | Pflichtfeld: siebenstellige deutsche DB-EVA-Nummer, beginnend mit `80`. |
| `stop_name` | Pflichtfeld: lesbarer Stationsname, 1 bis 200 Zeichen. |
| `line_id` | Pflichtfeld: aktive Trainmaps-Linie, passend zu `netz` und `line`. |

Eine EVA-Nummer darf innerhalb einer Lieferung nur einen Stationsnamen haben.
Die API verwendet dafür das von der Deutschen Bahn als `evaNumber` bezeichnete
Stationsmerkmal ([DB RIS::Stations](https://developer-docs.deutschebahn.com/doku/apis/ris-stations-10686906)).
Die abgeleitete kanonische ID `de.eva.<stop_id>` wird nicht angeliefert, sondern
von der API beim Lesen als `station_id` ausgegeben. Quellspezifische Kennungen
wie `delfi:*` oder `mvv:*` gehören nicht in den Statistikimport.

Beispiel aus der bereitgestellten Haltestellendatei:

```json
{
  "stop_id": "8004128",
  "stop_name": "München Donnersbergerbrücke",
  "netz": "München",
  "line": "S1",
  "line_id": "de.muenchen.s1",
  "n_data_points": 51338,
  "p_cancelled": 0.02491331956835093,
  "n_cancelled": 1279
}
```

Der vollständige Beispielkörper steht in
[frontend-v3-minimal.json](../examples/frontend-v3-minimal.json). Er verwendet
die vorhandene Linienreferenz
[line-reference-muenchen-s1.json](../examples/line-reference-muenchen-s1.json).

## Weiterhin unterstützter Vertrag frontend-2

`POST /api/v2/imports/frontend` bleibt unverändert verfügbar. Er verlangt
`line_id`, behandelt `stop_id` aber weiterhin als nicht näher bezeichneten
Quellwert und kennt kein `stop_name`. Neue Lieferungen mit Haltestellendaten
sollen deshalb v3 verwenden.

## Alter Vertrag frontend-1

`POST /api/v1/imports/frontend` akzeptiert den bisherigen Originalexport ohne
`line_id`. Der Endpunkt ist im OpenAPI-Vertrag als veraltet markiert, bleibt aber
für bestehende Dateien verfügbar. Gelingt später eine eindeutige Aliaszuordnung,
ergänzt der Monatsendpunkt die aktuelle `line_id` beim Lesen. Der gespeicherte
Originalexport wird dabei nicht verändert.

## Validierung und Grenzen

Alle sieben Eigenschaften müssen vorhanden sein; fehlende Daten werden als
leere Arrays geliefert. Ein vollständig leerer Export wird abgewiesen.
Pro Lieferung gelten 32 MiB entpackt und 100.000 Zeilen. `Content-Encoding: gzip`
wird unterstützt.

Geprüft werden unter anderem Pflichtfelder, UTC-Monatslabels, Typen,
nichtnegative Zähler, monotone Schwellen, doppelte Zeilenschlüssel, Quoten und
Summen Linie → Netz → Gesamt. Quoten müssen bis zu einer absoluten Abweichung
von 0,000001 zu den Zählern passen. Bei Nenner 0 sind die Zähler 0 und Quoten
`null`. Doppelte JSON-Eigenschaften, NaN und zusätzliche Felder sind verboten.

## Header, Revisionen und Wiederholungen

```http
POST /api/v3/imports/frontend HTTP/1.1
Authorization: Bearer <WRITE_TOKEN>
Content-Type: application/json
Idempotency-Key: <UUID>
X-Dataset-Revision: 2
```

v1, v2 und v3 verwenden gemeinsam dieselbe steigende Revisionsfolge. Jede neue
Lieferung erhält eine neue UUID und eine höhere positive Revision. Eine
Wiederholung nach einem Timeout verwendet dieselbe UUID, Revision und dieselben
entpackten Bytes. Der erste gespeicherte Import antwortet mit 201, eine
identische Wiederholung mit 200. Konflikte liefern 409.

`validate_only=true` prüft den Inhalt, reserviert aber weder UUID noch Revision
und schreibt nichts. Die Speicherung erfolgt atomar in SQLite; ein Fehler lässt
den bisherigen Datenstand unverändert.

PowerShell-Beispiel:

```powershell
$base = 'https://34.7.91.18'
$access = Get-Content -Raw '.local/access.local.json' | ConvertFrom-Json
$headers = @{
  Authorization = "Bearer $($access.write_token)"
  'Idempotency-Key' = [guid]::NewGuid().ToString()
  'X-Dataset-Revision' = '2'
}
Invoke-RestMethod -Method Post `
  -Uri "$base/api/v3/imports/frontend?validate_only=true" `
  -Headers $headers -ContentType 'application/json' `
  -InFile 'examples/frontend-v3-minimal.json'
```

## Antworten und Kartenfreigabe

Ein Importbeleg enthält `contract_version`, `import_id`, `revision`,
`station_count`,
`line_reference_revisions`, Prüfsummen, Zeilenzahlen, Monate, Netze,
`map_ready` und Warnungen. Bei einem Dry Run lauten die zusätzlichen Felder
`status: "validated"` und `stored: false`.

Für v2 und v3 ist `map_ready` genau dann `true`, wenn mindestens eine Linienreferenz
verwendet wurde und alle verwendeten Geometrien aktiv und `verified` sind. Für
v1 bleibt der Importbeleg `false`, weil im gelieferten Snapshot keine stabilen
IDs stehen. Der Monatsendpunkt bewertet den aktuellen Katalogzustand und kann
deshalb auch eine alte v1-Zeile nach späterer, eindeutiger Zuordnung als
darstellbar melden.

## Daten lesen

`GET /api/v1/data/frontend?import_id=<UUID>` liefert die exakten Originalbytes;
ohne ID den neuesten Snapshot. Der SHA-256 steht im `ETag`.

`GET /api/v1/data/monthly` hat folgende Parameter:

| Parameter | Bedeutung |
| --- | --- |
| `metric` | Pflicht: `punctuality` oder `cancellations`. |
| `month` | Pflicht: `YYYY-MM`. |
| `scope` | `line` (Standard), `network` oder `all`. |
| `netz`, `line` | Optionale exakte Quellwerte; `line` benötigt `netz`. |
| `line_id` | Optionale stabile ID; nur für `scope=line`. |
| `import_id` | Optionaler fester Snapshot. |
| `offset`, `limit` | Seitennavigation; maximal 5.000 Werte. |

Zeilen mit `scope=line` enthalten zusätzlich `line_id` oder `null` und
`geometry_status` mit `pending`, `mapped`, `verified` oder `unmapped`.
Stationsranglisten sind nicht Teil dieses Monatsendpunkts, weil im gelieferten
Export ihr Zeitraum fehlt.

`GET /api/v1/data/stops/8004128` liest alle Zeilen einer Haltestelle aus dem
neuesten Snapshot. Optional begrenzen `line_id` und `import_id` die Abfrage.
Die Antwort enthält unter anderem:

```json
{
  "stop_id": "8004128",
  "station_id": "de.eva.8004128",
  "id_type": "eva",
  "stop_name": "München Donnersbergerbrücke",
  "ranking_period": null,
  "total": 1,
  "values": [
    {
      "line_id": "de.muenchen.s1",
      "geometry_status": "verified",
      "n_data_points": 51338,
      "n_cancelled": 1279,
      "p_cancelled": 0.02491331956835093
    }
  ]
}
```

`ranking_period` bleibt `null`, bis die Quelle einen verbindlichen Zeitraum für
die Rangliste liefert. Eine unbekannte EVA-Nummer antwortet mit HTTP 404 und
`code: "stop_not_found"`.

## Fehler und Betriebsgrenzen

Fehlerantworten enthalten `code`, `message` und höchstens 20 Einträge in
`errors`. Wichtige Statuscodes:

| Status | Bedeutung |
| --- | --- |
| 400 | Ungültiges UTF-8-JSON, doppelte Eigenschaft oder ungültiges gzip. |
| 401 / 403 | Token fehlt, ist falsch oder hat nicht die erforderliche Rolle. |
| 404 | Import oder Linienreferenz unbekannt. |
| 408 | Upload dauerte länger als 60 Sekunden. |
| 409 | Importrevision, Idempotenz, Mappingrevision oder Quellalias kollidiert. |
| 413 / 415 | Inhalt zu groß oder Medientyp/Encoding nicht unterstützt. |
| 422 | Struktur, Zahlen, Parameter oder Linienreferenzen ungültig. |
| 429 | Ratenlimit oder bereits laufender Import. |
| 507 | Entwicklungsquota für gespeicherte Rohdaten erreicht. |

Es gelten 30 Schreib-, Prüf- oder Mappinganfragen und 120 Leseanfragen pro
Minute sowie höchstens ein laufender Import. Die Limits gelten pro Prozess.

## Lokal starten

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe scripts/init_dev.py
.\.venv\Scripts\python.exe -m uvicorn trainmaps_api.app:create_app --factory `
  --host 127.0.0.1 --port 8787 --workers 1 --no-access-log
```

macOS/Linux verwendet `.venv/bin/python`. Alternativ können
`TRAINMAPS_WRITE_TOKEN`, `TRAINMAPS_READ_TOKEN` und `TRAINMAPS_MAPPING_TOKEN`
aus einer Geheimnisverwaltung kommen. Alle drei müssen verschieden und
mindestens 32 Zeichen lang sein. `TRAINMAPS_DATA_DIR` setzt das Datenverzeichnis.

Die HTTPS- und Caddy-Konfiguration beschreibt [HTTPS & Betrieb](HTTPS.md).
