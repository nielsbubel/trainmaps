# Webkarte

Die erste trainmaps-Karte ist unter **[https://34.7.91.18/karte](https://34.7.91.18/karte)**
erreichbar. Sie zeigt die Münchner S1 und 57 Monatswerte von September 2021 bis
Mai 2026. Die Kartenansicht und die drei dafür vorgesehenen Leseendpunkte sind
öffentlich; ein API-Token wird dafür nicht im Browser gespeichert.

## Bedienung

Beim Start ist kein Datenfenster geöffnet. Jede verfügbare S-Bahn wird anhand
ihrer über alle Monate gemittelten, geschätzten Verspätung eingefärbt. Ein Klick
auf die farbige Linie oder eine ihrer Stationen wählt die S-Bahn aus und öffnet
das Kontextfenster.

Das Liniendiagramm zeigt sofort alle verfügbaren Monatswerte. Zwei direkt
sichtbare Schaltflächen wechseln zwischen:

- geschätzter Verspätung in Minuten;
- Ausfallanteil in Prozent.

Monat und Kennzahl werden nicht über Dropdown-Menüs ausgewählt. Für jeden
Diagrammpunkt zeigt ein Tooltip den Monat und den Wert. Das Fenster nennt außerdem
Mittelwert, niedrigsten, höchsten und neuesten Monatswert.

Die Werte gelten jeweils für die ganze Linie. Der gelieferte Datensatz enthält
keine monatlichen Stationswerte.

Standardmäßig sind nur folgende Ebenen sichtbar:

- ausgewählte S-Bahn und ihre Stationen;
- übriges S-Bahn-Netz als dezenter Kontext;
- Ortsnamen und Gewässer.

Übrige Bahnstrecken, Grenzen sowie Straßen und Autobahnen können unter
„Kartenebenen“ zugeschaltet werden. Sie starten ausgeschaltet.

## Öffentliche Kartenendpunkte

| Methode und Pfad | Zweck |
| --- | --- |
| `GET /api/v1/map/config` | Verfügbare, verifizierte Linien, Zeiträume, anfängliche Mittelwerte und Ebenen. |
| `GET /api/v1/map/lines.geojson?line_id=de.muenchen.s1` | Freigegebener Fahrweg und Stationen als GeoJSON. |
| `GET /api/v1/map/series?line_id=de.muenchen.s1` | Alle Monatswerte, Mittelwerte und die dokumentierte Verspätungsschätzung. |
| `GET /api/v1/map/monthly?line_id=de.muenchen.s1&month=2026-05&metric=punctuality&threshold_minutes=5` | Genau ein darstellbarer Monatswert. |

Nur aktive Linien mit Geometriestatus `verified` werden ausgeliefert. Die
allgemeinen Daten- und Katalogendpunkte bleiben mit Bearer-Token geschützt.

Gekürzte Beispielantwort des Zeitreihenendpunkts:

```json
{
  "line_id": "de.muenchen.s1",
  "display_name": "S1 München",
  "summary": {
    "mean_estimated_delay_minutes": 3.833,
    "mean_cancellation_percentage": 3.49,
    "delay_months": 57,
    "cancellation_months": 57
  },
  "delay_estimation": {
    "kind": "bucket_midpoint_estimate",
    "cumulative_thresholds_minutes": [2, 5, 10, 20, 40],
    "bucket_midpoints_minutes": [1, 3.5, 7.5, 15, 30, 50],
    "over_40_assumption_minutes": 50,
    "cancellations_excluded": true
  },
  "values": [
    {
      "month": "2021-09",
      "estimated_delay_minutes": 3.167,
      "cancellation_percentage": 13.155
    }
  ]
}
```

Die Zahlen im Beispiel sind redaktionell gekürzt und gerundet. Die API liefert
alle 57 Monate sowie die berechneten Gleitkommawerte.

## Berechnung der Verspätungsminuten

Der Quelldatensatz enthält keine exakte durchschnittliche Verspätung. Vorhanden
sind kumulierte Zähler für 2, 5, 10, 20 und 40 Minuten. trainmaps bildet daraus
sechs Klassen und verwendet deren repräsentative Mittelpunkte:

| Klasse | Rechenwert |
| --- | ---: |
| bis 2 Minuten | 1 Minute |
| über 2 bis 5 Minuten | 3,5 Minuten |
| über 5 bis 10 Minuten | 7,5 Minuten |
| über 10 bis 20 Minuten | 15 Minuten |
| über 20 bis 40 Minuten | 30 Minuten |
| über 40 Minuten | 50 Minuten |

Der Monatswert ist der mit den jeweiligen Zählern gewichtete Mittelwert dieser
Rechenwerte. Der anfängliche Farbwert einer Linie ist anschließend das einfache
arithmetische Mittel aller vorhandenen Monatswerte. Die Skala verläuft von Grün
unter zwei Minuten über Gelb und Orange bis Rot über 40 Minuten. Diese Werte sind
Schätzwerte; Ausfälle sind ausgeschlossen und werden getrennt dargestellt.

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

Die Seite besitzt eine restriktive Content Security Policy. Die vier öffentlichen
Endpunkte liefern nur Daten, die die Karte benötigt. Rohimporte, Importbelege und
der vollständige Linienkatalog werden dadurch nicht öffentlich.

## Prüfung

Die Desktopansicht wurde mit 1440 × 1000 Pixeln, die Mobilansicht mit 390 × 844
Pixeln in Microsoft Edge geprüft. Dabei wurden der geschlossene Anfangszustand,
die Auswahl per Kartenklick, 57 Diagrammpunkte, der Wechsel zwischen Verspätung
und Ausfällen sowie die Ebenensteuerung kontrolliert. Die API-, Stil- und
Geometrietests sind Bestandteil der automatisierten Testsuite.
