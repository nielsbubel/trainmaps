# Webkarte

Die erste trainmaps-Karte ist unter **[https://34.7.91.18/karte](https://34.7.91.18/karte)**
erreichbar. Sie zeigt die Münchner S1 und 57 Monatswerte von September 2021 bis
Mai 2026. Die Kartenansicht und die drei dafür vorgesehenen Leseendpunkte sind
öffentlich; ein API-Token wird dafür nicht im Browser gespeichert.

## Bedienung

Der Monat, die Kennzahl und bei Verspätungen eine Schwelle von 2, 5, 10, 20
oder 40 Minuten können gewählt werden. Die Linie wird nach dem Anteil der
Messpunkte eingefärbt, die **nicht innerhalb** der gewählten Schwelle lagen.
Ausfälle sind dabei ausgeschlossen und stehen als eigene Kennzahl zur Wahl.

Der Wert gilt für die ganze Linie. Der gelieferte Datensatz enthält keine
monatlichen Stationswerte. Ein Klick auf eine Station weist deshalb ausdrücklich
darauf hin, dass dort noch kein eigener Wert vorliegt.

Standardmäßig sind nur folgende Ebenen sichtbar:

- ausgewählte S-Bahn und ihre Stationen;
- übriges S-Bahn-Netz als dezenter Kontext;
- Ortsnamen und Gewässer.

Übrige Bahnstrecken, Grenzen sowie Straßen und Autobahnen können unter
„Kartenebenen“ zugeschaltet werden. Sie starten ausgeschaltet.

## Öffentliche Kartenendpunkte

| Methode und Pfad | Zweck |
| --- | --- |
| `GET /api/v1/map/config` | Verfügbare, verifizierte Linien, Monate, Kennzahlen, Schwellen und Ebenen. |
| `GET /api/v1/map/lines.geojson?line_id=de.muenchen.s1` | Freigegebener Fahrweg und Stationen als GeoJSON. |
| `GET /api/v1/map/monthly?line_id=de.muenchen.s1&month=2026-05&metric=punctuality&threshold_minutes=5` | Genau ein darstellbarer Monatswert. |

Nur aktive Linien mit Geometriestatus `verified` werden ausgeliefert. Die
allgemeinen Daten- und Katalogendpunkte bleiben mit Bearer-Token geschützt.

Beispielantwort des Monatsendpunkts:

```json
{
  "line_id": "de.muenchen.s1",
  "display_name": "S1 München",
  "month": "2026-05",
  "metric": "punctuality",
  "threshold_minutes": 5,
  "label": "Nicht innerhalb von 5 Min.",
  "ratio": 0.252,
  "percentage": 25.2,
  "numerator": 8161,
  "n_data_points": 32418,
  "data_revision": 1,
  "source_alias": {"netz": "München", "line": "S1"}
}
```

Die Zahlen im Beispiel sind gerundet dargestellt. Die API liefert den
berechneten Gleitkommawert ohne diese redaktionelle Rundung.

## Fahrweg der Münchner S1

Die MVV-GTFS-Datei 06/2026 enthält für die S1 keine `shape_id`. Sie dient daher
als offizielle Referenz für Linie, Haltereihenfolge und Stationskoordinaten. Der
sichtbare Fahrweg stammt aus dem basemap.de-Vektorlayer `Verkehrslinie`.

Der reproduzierbare Builder `scripts/build_s1_geometry.py` lädt die benötigten
Kacheln auf Zoomstufe 14 und verwendet zuerst die Klasse `S-Bahn`. Wo dieselben
Gleise allgemeiner klassifiziert sind, werden `Eisenbahn` und `Gleis` als
dokumentierte Rückfallklassen berücksichtigt. Kurze technische Segmentlücken
werden bis höchstens 100 Meter verbunden und je Stationspaar protokolliert.

Das Ergebnis enthält:

- zwei Linienäste Freising–Leuchtenbergring und Flughafen–Leuchtenbergring;
- 23 zusammengeführte Stationen anstelle einzelner Bahnsteighalte;
- Quellversionen, GTFS-SHA-256, Kachelzahl, Klassen, Snap-Distanzen und alle
  verwendeten Segmentverbindungen im GeoJSON-Metadatenblock;
- eine größte tatsächlich verwendete Segmentlücke von 59,8 Metern.

Der maximale Abstand eines GTFS-Bahnsteigpunkts zum Basemap-Gleis beträgt am
Flughafen 512,4 Meter. Die Stationsmarkierung verwendet weiterhin die offizielle
GTFS-Stationskoordinate; dieser bekannte Unterschied wird nicht verschwiegen
oder durch eine erfundene Gleisgeometrie ersetzt.

## Technische Umsetzung

Die Oberfläche verwendet das lokal ausgelieferte MapLibre GL JS 6.11.2. Der
reduzierte graue Stil wird mit `scripts/build_basemap_style.py` aus dem offiziellen
basemap.de-Stil erzeugt. Kartenbibliothek, JavaScript und CSS liegen auf dem
trainmaps-Server; Vektorkacheln, Schriften und Symbole werden direkt von
`sgx.geodatenzentrum.de` geladen.

Die Seite besitzt eine restriktive Content Security Policy. Die drei öffentlichen
Endpunkte liefern nur Daten, die die Karte benötigt. Rohimporte, Importbelege und
der vollständige Linienkatalog werden dadurch nicht öffentlich.

## Prüfung

Die Desktopansicht wurde mit 1440 × 1000 Pixeln, die Mobilansicht mit 390 × 844
Pixeln in Microsoft Edge geprüft. Dabei wurden Kartenaufbau, Monatswert,
Kennzahlwechsel, ausgeblendete Verspätungsschwelle bei Ausfällen und das
Zuschalten der Straßenebene kontrolliert. Die API-, Stil- und Geometrietests sind
Bestandteil der automatisierten Testsuite.
