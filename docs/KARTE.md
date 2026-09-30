# Webkarte

Die erste trainmaps-Karte ist unter **[https://34.7.91.18/karte](https://34.7.91.18/karte)**
erreichbar. Sie zeigt S1 bis S8 sowie S20 in München mit jeweils 57 Monatswerten
von September 2021 bis Mai 2026. Die Kartenansicht und die vier dafür vorgesehenen
Leseendpunkte sind öffentlich; ein API-Token wird dafür nicht im Browser gespeichert.

## Bedienung

Beim Start ist kein Datenfenster geöffnet. Jede verfügbare S-Bahn wird anhand
ihrer über alle Monate gemittelten, geschätzten Verspätung eingefärbt. Die
Farbskala reicht vom tatsächlich niedrigsten bis zum tatsächlich höchsten Wert
aller verfügbaren S-Bahnlinien. Ein Klick auf die Linie oder eine ihrer Stationen
wählt die S-Bahn aus und öffnet das Kontextfenster.

Ein direkter Kartenlink kann die interne Linien-ID als Parameter angeben, zum
Beispiel `/karte?line=de.muenchen.s8`. Die Karte öffnet dann sofort die gewählte
Linie und ihre Zeitreihe.

Das Liniendiagramm zeigt sofort alle verfügbaren Monatswerte. Zwei direkt
sichtbare Schaltflächen wechseln zwischen:

- geschätzter Verspätung in Minuten;
- Ausfallanteil in Prozent.

Monat und Kennzahl werden nicht über Dropdown-Menüs ausgewählt. Für jeden
Diagrammpunkt zeigt ein Tooltip den Monat und den Wert. Das Fenster nennt außerdem
Mittelwert, niedrigsten, höchsten und neuesten Monatswert. Diese vier Angaben sind
Schaltflächen. Ein Klick färbt alle S-Bahnlinien nach dem jeweils eigenen Wert
dieser Art ein. Beim Wechsel zu „Ausfälle“ wird wieder der mittlere Ausfallanteil
verwendet; anschließend können auch dort Minimum, Maximum und letzter Monat als
Vergleich ausgewählt werden.

Grün kennzeichnet den kleinsten und Rot den größten vorhandenen Vergleichswert;
dazwischen wird die Farbe kontinuierlich berechnet. Die Legende zeigt die jeweils
tatsächliche Spannweite. Gibt es nur eine verfügbare Linie oder sind alle Werte
gleich, existiert keine Vergleichsspannweite und die Linien erscheinen neutral
grau.

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
| `GET /api/v1/map/config` | Verfügbare, verifizierte Linien, Zeiträume, Vergleichswerte und Ebenen. |
| `GET /api/v1/map/lines.geojson?line_id=de.muenchen.s1` | Freigegebener Fahrweg und Stationen als GeoJSON. |
| `GET /api/v1/map/series?line_id=de.muenchen.s1` | Alle Monats- und Vergleichswerte sowie die dokumentierte Verspätungsschätzung. |
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
    "minimum_estimated_delay_minutes": 1.997,
    "maximum_estimated_delay_minutes": 5.349,
    "latest_estimated_delay_minutes": 4.545,
    "mean_cancellation_percentage": 3.49,
    "minimum_cancellation_percentage": 0.661,
    "maximum_cancellation_percentage": 17.707,
    "latest_cancellation_percentage": 3.164,
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
arithmetische Mittel aller vorhandenen Monatswerte. Die Kartenfarbe wird relativ
zur aktuellen Spannweite aller verfügbaren S-Bahnlinien berechnet: Der kleinste
Wert ist grün, der größte rot. Feste Minutengrenzen werden dafür nicht verwendet.
Diese Werte sind Schätzwerte; Ausfälle sind ausgeschlossen und werden getrennt
dargestellt. Für Ausfälle verwendet die Karte dieselbe relative Berechnung mit
den Ausfallquoten in Prozent.

## Fahrwege der Münchner S-Bahnlinien

Die MVV-GTFS-Datei 06/2026 dient als offizielle Referenz für Linien,
Haltereihenfolgen und Stationskoordinaten. Die sichtbaren Fahrwege stammen aus
dem basemap.de-Vektorlayer `Verkehrslinie`. Enthalten sind:

| Linie | abgebildeter Laufweg | Stationen |
| --- | --- | ---: |
| S1 | Freising/Flughafen München–Leuchtenbergring | 23 |
| S2 | Petershausen/Altomünster–Erding | 39 |
| S3 | Mammendorf–Holzkirchen | 31 |
| S4 | Geltendorf–Zorneding | 29 |
| S5 | Weßling–Kreuzstraße | 34 |
| S6 | Tutzing–Ebersberg | 35 |
| S7 | Wolfratshausen–München Hbf | 16 |
| S8 | Herrsching–Flughafen München | 32 |
| S20 | Geltendorf–Höllriegelskreuth | 18 |

Der reproduzierbare Builder `scripts/build_munich_geometries.py` lädt die
benötigten Kacheln auf Zoomstufe 14 und verwendet zuerst die Klasse `S-Bahn`.
Wo dieselben Gleise allgemeiner klassifiziert sind, werden `Eisenbahn` und
`Gleis` als dokumentierte Rückfallklassen berücksichtigt. Er wählt je Linie den
vollständigen regulären GTFS-Laufweg; seltene Kurz- und Baustellenführungen
werden nicht als zusätzliche Linienäste übernommen.

Technische Segmentlücken bis 250 Meter werden im Gleisgraph verbunden. Zwischen
Feldkirchen und Heimstetten schließt der Builder eine zusätzlich protokollierte
449,3-Meter-Lücke in der Basemap-Geometrie der S2. Jede GeoJSON-Datei enthält
Quellversionen, GTFS-SHA-256, Kachelzahl, Klassen, Stationsabstände und sämtliche
verwendeten Segmentverbindungen im Metadatenblock.

Der größte Abstand eines verwendeten GTFS-Bahnsteigpunkts zum Basemap-Gleis
beträgt bei der S8 am Flughafen 551,1 Meter. Die Stationsmarkierungen verwenden
weiterhin die offiziellen GTFS-Stationskoordinaten; dieser bekannte Unterschied
wird dokumentiert und nicht durch erfundene Gleisgeometrie ersetzt. Der aktuelle
MVV-Umfang S1 bis S8 und S20 ist auch in den offiziellen
[Fahrplanmedien 2026](https://www.mvv-muenchen.de/netz-plaene-medien/fahrplanmedien/download/s-bahn/)
aufgeführt.

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
Pixeln in Microsoft Edge geprüft. Dabei wurden alle neun Linien und jeweils 57
Diagrammpunkte, die Auswahl per Kartenlink und Kartenklick, der Wechsel zwischen
Verspätung und Ausfällen, alle vier Vergleichsarten sowie die Ebenensteuerung
kontrolliert. Die API-, Stil- und Geometrietests sind Bestandteil der
automatisierten Testsuite.
