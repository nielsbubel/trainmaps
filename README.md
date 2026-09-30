# trainmaps

Deutschlandweite S-Bahn-Pünktlichkeitskarte mit basemap.de: Kartenplanung und
lauffähige Entwicklungs-API für die Datenlieferung.

Die Karte startet deutschlandweit mit einer farbigen Bubble je Verkehrsgebiet.
Beim Hineinzoomen erscheinen die einzelnen S-Bahnlinien. Über „Kartenebenen“
lassen sich Inhalte einzeln schalten; Grenzen, Autobahnen und übrige Straßen
sind standardmäßig ausgeschaltet.

Für die erste Kartenversion stehen Linienstatistiken im Mittelpunkt. Der Export
`daten/frontend.json` enthält 33.108 Zeilen mit Monatswerten und einer separaten
Stations-Ausfallrangliste; Stationsnamen, Koordinaten und deren Zeitraum fehlen.

Stand 0.9.0: Import, Prüfmodus, Tokenzugriff, dauerhafte Entwicklungs-Snapshots,
Leseendpunkte, Linienkatalog und die erste responsive Webkarte sind implementiert
und getestet. 96 S-Bahnlinien aus 14 Netzen werden auf basemap.de-Gleisen mit
ihren vorhandenen Monatswerten dargestellt. Ein Verkehrsgebiet oder eine Linie
wird direkt in der Karte ausgewählt; erst danach erscheint die vollständige
Monatszeitreihe als Liniendiagramm. Beim Einstieg vergleichen die Bubble-Farben
die Verspätung des letzten Monats aller 14 Verkehrsgebiete. Mittelwert, Minimum,
Maximum und letzter Monatswert lassen sich anschließend für Verkehrsgebiete und
Linien vergleichen. Beim Wechsel zu Ausfällen beginnt der Vergleich mit dem
mittleren Ausfallanteil.
Die neun Münchner Fahrwege lassen sich mit `scripts/build_munich_geometries.py`
aus MVV-GTFS und basemap.de reproduzieren. Der bundesweite erste Durchlauf wird
mit `scripts/build_germany_geometries.py` aus den deutschlandweiten
DELFI-Sollfahrplandaten und basemap.de reproduziert.
Der Entwicklungsserver ist über **https://34.7.91.18** erreichbar; lokal läuft
die API auf http://127.0.0.1:8787. Caddy übernimmt HTTPS mit einem automatisch
erneuerten Let's-Encrypt-Zertifikat für die IP-Adresse. Der Rechner und beide
Prozesse müssen laufen; nach einem Neustart sind sie erneut zu starten.

- [Vollständige Dokumentation im Browser](https://34.7.91.18/dokumentation)
- [Webkarte mit 96 deutschen S-Bahnlinien](https://34.7.91.18/karte)
- [Bedienung und öffentliche Kartenendpunkte](docs/KARTE.md)
- [Schnellstart für Datenlieferanten](docs/SCHNELLSTART.md)
- [Architektur, benötigte Daten und API-Vertrag](docs/MONATSDATEN_UND_API.md)
- [API-Anleitung für Datenlieferanten und Entwickler](docs/API.md)
- [Stabile Linien-IDs und basemap.de-Fahrwege](docs/LINIENREFERENZEN.md)
- [HTTPS, Zertifikat und Serverbetrieb](docs/HTTPS.md)
- [Prüfbericht zur vollständigen Datei](docs/DATENPRUEFUNG.md)
- [OpenAPI 3.1](api/openapi.json)
- [Interaktive API-Dokumentation](https://34.7.91.18/docs)

Die bevorzugte API `POST /api/v2/imports/frontend` ergänzt den vollständigen
Export auf Linienebene um stabile `line_id`-Werte aus dem Linienkatalog. Der
bisherige Originalexport ohne IDs bleibt über `POST /api/v1/imports/frontend`
nutzbar. Zugriffstoken stehen ausschließlich in der ignorierten Datei
`.local/access.local.json`. Die vollständige Ausgangsdatei wurde bereits als
Entwicklungsrevision 1 importiert und bytegenau zurückgelesen.

Der produktive Linienkatalog enthält 96 verifizierte Linien aus 14 Netzen:
87 Fahrwege aus dem bundesweiten ersten Durchlauf sowie die neun Münchner Linien.
`map_ready` wird für v2-Daten erst mit ausschließlich verifizierten
Fahrwegzuordnungen `true`. Ausfälle sind aus den Pünktlichkeitswerten ausgeschlossen
und als eigene Datenserie vorhanden. Der bisherige
`examples/monthly-line.json` ist nur der frühere Planungsentwurf und kein Body
für den jetzt implementierten Importendpunkt.
