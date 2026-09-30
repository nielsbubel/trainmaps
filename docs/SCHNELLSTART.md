# Schnellstart: Daten an trainmaps liefern

Die öffentliche Basisadresse lautet **https://34.7.91.18**. Die bevorzugte
Schnittstelle ist `frontend-2` mit stabilen Linien-IDs. Bestehende Exporte ohne
IDs können weiterhin über v1 geprüft und geliefert werden.

## 1. Verbindung prüfen

```sh
curl --fail-with-body https://34.7.91.18/health
```

Unter Windows `curl.exe` verwenden. Erwartet wird HTTP 200:

```json
{"status":"ok","service":"trainmaps-development","version":"0.9.0"}
```

Die [interaktive API](https://34.7.91.18/docs), der
[OpenAPI-Vertrag](../api/openapi.json) und das Dokumentationsportal sind ohne
Token erreichbar.

## 2. Zugriff einrichten

Der Betreiber gibt dem Datenlieferanten einen **Schreibtoken**. Er erlaubt
Prüfläufe, Importe sowie das Lesen der Daten und des Linienkatalogs. Der interne
Mapping-Schlüssel wird nicht an Datenlieferanten verteilt.

```http
Authorization: Bearer <DEIN_WRITE_TOKEN>
```

Token nur über HTTPS und aus einer lokalen Umgebungsvariable oder
Geheimnisverwaltung verwenden.

## 3. Verfügbare Linien-IDs lesen

Vor einem v2-Export den aktuellen Katalog abrufen:

```powershell
$base = 'https://34.7.91.18'
$headers = @{ Authorization = "Bearer $env:TRAINMAPS_WRITE_TOKEN" }
$catalog = Invoke-RestMethod -Headers $headers `
  -Uri "$base/api/v1/reference/lines?active=true&limit=5000"
$catalog.values | Select-Object line_id, display_name, source_aliases, geometry
```

Ein einzelnes Quellpaar lässt sich beispielsweise mit
`?netz=Berlin&line=1` nachschlagen.

Der Lieferant setzt für jedes gelieferte Paar `netz`/`line` die dort
veröffentlichte `line_id`. Fehlt eine Zuordnung, wird sie zuerst vom Betreiber
geprüft und im Katalog angelegt. Es werden keine IDs aus Namen geraten.

## 4. v2-Prüflauf

Der Download [frontend-v2-minimal.json](../examples/frontend-v2-minimal.json)
zeigt das Format. Das synthetische Beispiel verwendet `de.test.s1` und
funktioniert nur auf einer Instanz, auf der der zugehörige
[Beispiel-Katalogeintrag](../examples/line-reference.json) angelegt wurde.

Für eine reale Prüfung den vollständigen Export mit den IDs aus Schritt 3
verwenden:

```powershell
if (-not $env:TRAINMAPS_WRITE_TOKEN) {
  throw 'Zuerst TRAINMAPS_WRITE_TOKEN lokal setzen.'
}
$base = 'https://34.7.91.18'
$headers = @{
  Authorization = "Bearer $env:TRAINMAPS_WRITE_TOKEN"
  'Idempotency-Key' = [guid]::NewGuid().ToString()
  'X-Dataset-Revision' = '2'
}
Invoke-RestMethod -Method Post `
  -Uri "$base/api/v2/imports/frontend?validate_only=true" `
  -Headers $headers -ContentType 'application/json' `
  -InFile 'frontend-v2.json'
```

Erfolg bedeutet HTTP 200, `status: "validated"` und `stored: false`. Der
Prüflauf reserviert weder UUID noch Revision.

## 5. Vorhandenen Export zunächst über v1 prüfen

Die Datei `daten/frontend.json` hat noch keine `line_id`. Sie kann unverändert
über den alten Endpunkt geprüft werden:

```powershell
Invoke-RestMethod -Method Post `
  -Uri "$base/api/v1/imports/frontend?validate_only=true" `
  -Headers $headers -ContentType 'application/json' `
  -InFile 'daten/frontend.json'
```

v1 bleibt kompatibel, ist im OpenAPI-Vertrag aber als veraltet markiert. Ein
v1-Importbeleg hat `map_ready: false`, weil die stabilen IDs nicht Bestandteil
des gelieferten Snapshots sind.

## 6. Echte Lieferung speichern

Nach erfolgreicher Prüfung denselben Body mit neuer, noch nicht verwendeter UUID
und einer höheren globalen Revision ohne `validate_only` senden:

```powershell
Invoke-RestMethod -Method Post `
  -Uri "$base/api/v2/imports/frontend" `
  -Headers $headers -ContentType 'application/json' `
  -InFile 'frontend-v2.json'
```

Ein neuer Import liefert HTTP 201. Bei einem Netzfehler dieselbe UUID, Revision
und dieselben Bytes erneut senden; die Wiederholung liefert HTTP 200. v1 und v2
teilen eine Revisionsfolge.

Jeder Import ist ein vollständiger Snapshot. Das kleine Beispiel deshalb nur im
Prüfmodus verwenden.

## 7. Monatswerte lesen

```sh
curl --fail-with-body \
  'https://34.7.91.18/api/v1/data/monthly?metric=punctuality&month=2021-09&line_id=de.berlin.s1' \
  --header "Authorization: Bearer $TRAINMAPS_READ_TOKEN"
```

Linienzeilen enthalten `line_id` und `geometry_status`. `map_ready: true`
bedeutet, dass alle Werte der Antwort eine aktuell verifizierte Fahrwegzuordnung
haben. Der vollständige Originalexport ist unter `/api/v1/data/frontend`
abrufbar.

## Fehler beheben

| Antwort | Nächster Schritt |
| --- | --- |
| 401 | Bearer-Token prüfen. |
| 403 | Für Importe den Schreibtoken verwenden. |
| 409 | Importrevision und UUID prüfen; Mappingänderungen brauchen eine höhere Revision. |
| 413 | JSON ist komprimiert oder entpackt größer als 32 MiB. |
| 422 `line_reference_error` | `line_id`, Aktivstatus und das exakte Paar `netz`/`line` mit dem Katalog abgleichen. |
| 422 sonst | Felder, Zähler, Quoten und Aggregationen anhand von `errors` korrigieren. |
| 429 | `Retry-After` beachten und später wiederholen. |

Alle Felder und Grenzen stehen im [API-Handbuch](API.md). Die Verwaltung der
Zuordnungen beschreibt [Linienreferenzen](LINIENREFERENZEN.md).
