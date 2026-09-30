# trainmaps

Deutschlandweite S-Bahn-Pünktlichkeitskarte mit basemap.de: Kartenplanung und
lauffähige Entwicklungs-API für die Datenlieferung.

Die Karte startet mit hervorgehobenen S-Bahnlinien, Linienkennungen, dezenten
Ortsnamen und Gewässern. Über „Kartenebenen“ lassen sich Inhalte einzeln schalten;
Grenzen, Autobahnen und übrige Straßen sind standardmäßig ausgeschaltet.

Für die erste Kartenversion stehen Linienstatistiken im Mittelpunkt. Der Export
`daten/frontend.json` enthält 33.108 Zeilen mit Monatswerten und einer separaten
Stations-Ausfallrangliste; Stationsnamen, Koordinaten und deren Zeitraum fehlen.

Stand 0.7.0: Import, Prüfmodus, Tokenzugriff, dauerhafte Entwicklungs-Snapshots,
Leseendpunkte, Linienkatalog und die erste responsive Webkarte sind implementiert
und getestet. S1 bis S8 sowie S20 werden auf basemap.de-Gleisen mit jeweils 57
Monatswerten dargestellt. Eine Linie wird direkt in der Karte ausgewählt; erst
danach erscheint ihre vollständige Monatszeitreihe als Liniendiagramm. Die
Linienfarben vergleichen wahlweise Mittelwert, Minimum, Maximum oder letzten
Monatswert über alle verfügbaren S-Bahnlinien und passen sich beim Wechsel
zwischen Verspätung und Ausfällen an.
Die neun versionierten Fahrwege lassen sich mit
`scripts/build_munich_geometries.py` aus MVV-GTFS und basemap.de reproduzieren.
Der Entwicklungsserver ist über **https://34.7.91.18** erreichbar; lokal läuft
die API auf http://127.0.0.1:8787. Caddy übernimmt HTTPS mit einem automatisch
erneuerten Let's-Encrypt-Zertifikat für die IP-Adresse. Der Rechner und beide
Prozesse müssen laufen; nach einem Neustart sind sie erneut zu starten.

- [Vollständige Dokumentation im Browser](https://34.7.91.18/dokumentation)
- [Webkarte mit allen Münchner S-Bahnlinien](https://34.7.91.18/karte)
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

Der produktive Linienkatalog enthält die neun verifizierten Münchner Linien
`de.muenchen.s1` bis `de.muenchen.s8` sowie `de.muenchen.s20`.
`map_ready` wird für v2-Daten erst mit ausschließlich verifizierten
Fahrwegzuordnungen `true`. Ausfälle sind aus den Pünktlichkeitswerten ausgeschlossen
und als eigene Datenserie vorhanden. Der bisherige
`examples/monthly-line.json` ist nur der frühere Planungsentwurf und kein Body
für den jetzt implementierten Importendpunkt.
