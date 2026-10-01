# Linienreferenzen und basemap.de-Fahrwege

trainmaps verwendet die vorhandenen S-Bahn-Gleise aus basemap.de. Die
Statistikquelle muss deshalb keine eigene Liniengeometrie liefern. Sie muss aber
eine stabile `line_id` mitsenden, damit ein Wert eindeutig der vom Betreiber
geprüften S-Bahnlinie zugeordnet werden kann.

## Warum eine eigene Linien-ID nötig ist

Der Vektor-Layer `Verkehrslinie` von basemap.de kennzeichnet S-Bahn-Geometrien
über `klasse: "S-Bahn"`. Das veröffentlichte Datenmodell bietet dort keine
dokumentierte, deutschlandweit stabile Kennung einer konkreten S-Bahnlinie wie
„Berlin S1“. Außerdem teilen sich mehrere Linien häufig denselben Gleisabschnitt.
Eine Liniennummer allein ist ebenfalls nicht eindeutig: `S1` kommt in mehreren
Netzen vor und die Quelle kann dieselbe Linie als `1` oder `S1` bezeichnen.

Darum trennt trainmaps drei Dinge:

| Feld | Zweck |
| --- | --- |
| `line_id` | Stabile trainmaps-Kennung, zum Beispiel `de.berlin.s1`. |
| `source_aliases` | Zulässige Paare aus den gelieferten Feldern `netz` und `line`. |
| `geometry` | Versionierte Referenz auf den geprüften Fahrweg aus basemap.de. |

Grundlage sind die offiziellen Beschreibungen des
[basemap.de Web Vektor](https://basemap.de/produkte-und-dienste/web-vektor/)
und dessen
[Datenmodell](https://basemap.de/data/produkte/web_vektor/meta/bm_web_vektor_datenmodell.html).

## Ablauf einer Zuordnung

1. Der Betreiber sammelt ein Paar aus `netz` und `line`, zum Beispiel
   `Berlin`/`1`.
2. Er prüft, welche reale S-Bahnlinie gemeint ist, und vergibt oder wählt die
   stabile ID `de.berlin.s1`.
3. Er wählt die zugehörigen Geometrien aus dem basemap.de-Layer
   `Verkehrslinie` mit der Klasse `S-Bahn` aus.
4. Er speichert die Auswahl als versionierte Geometriereferenz zunächst mit
   `status: "mapped"`.
5. Nach Sichtprüfung des vollständigen Verlaufs wird eine höhere
   Mappingrevision mit `status: "verified"` veröffentlicht.
6. Der Datenlieferant liest den Katalog und verwendet die ID in allen Zeilen
   dieses Quellalias.

Beim Wechsel auf eine neue basemap.de-Ausgabe bleibt `line_id` stabil. Nur die
Mappingrevision, `geometry.version` und gegebenenfalls die Geometriereferenz
werden aktualisiert. Alte Importbelege nennen weiterhin die bei der Annahme
verwendete Mappingrevision.

## API-Vertrag

Der Katalog wird über folgende Endpunkte verwaltet:

```text
GET /api/v1/reference/lines
GET /api/v1/reference/lines/{line_id}
PUT /api/v1/reference/lines/{line_id}
```

Lesen dürfen Read-, Write- und Mapping-Token. Änderungen akzeptiert nur der
Mapping-Token. Das verhindert, dass ein Datenlieferant Statistikwerte durch
eine veränderte Fahrwegzuordnung auf eine andere Linie verschiebt.

Ein minimaler, noch nicht zugeordneter Datensatz:

```json
{
  "revision": 1,
  "network_id": "de.berlin",
  "display_name": "S1 Berlin",
  "source_aliases": [
    {"netz": "Berlin", "line": "1"}
  ],
  "geometry": {
    "source": "basemap.de",
    "source_layer": "Verkehrslinie",
    "source_class": "S-Bahn",
    "status": "pending",
    "reference": null,
    "version": null
  },
  "active": true,
  "notes": null
}
```

Die ID steht im URL-Pfad und nicht nochmals im Body:

```http
PUT /api/v1/reference/lines/de.berlin.s1
Authorization: Bearer <MAPPING_TOKEN>
Content-Type: application/json
```

## Status und Kartenverwendung

| Status | Bedeutung | Darstellung |
| --- | --- | --- |
| `pending` | Linie erkannt, Fahrweg noch nicht hinterlegt. | Keine statistische Einfärbung. |
| `mapped` | Fahrweg technisch verknüpft, Sichtprüfung offen. | Nur in interner Vorschau. |
| `verified` | Verlauf geprüft und freigegeben. | Monatswert darf auf der Karte erscheinen. |
| `active: false` | Zuordnung stillgelegt. | Neue v2-Importe werden abgewiesen. |

`map_ready` in einem v2-/v3-Prüf- oder Importbeleg wird nur dann `true`, wenn
mindestens eine Linien-ID verwendet wird und jede verwendete Geometrie aktiv und
`verified` ist. Der Monatsendpunkt verwendet den aktuellen Katalogzustand und
liefert pro Zeile `geometry_status`.

Der produktive Katalog enthält 96 Linien aus 14 Netzen. Der Münchner Teil umfasst
`de.muenchen.s1` bis `de.muenchen.s8` sowie `de.muenchen.s20`. Die Quellaliase lauten entsprechend
`München/S1` bis `München/S8` und `München/S20`; alle neun Fahrwege sind nach
der Desktop- und Mobilprüfung `verified`. Die Definitionen stehen gesammelt in
[`examples/line-references-muenchen.json`](../examples/line-references-muenchen.json).
Die numerischen Quellwerte `München/1` bis `München/9` bleiben wegen abweichender
Statistikwerte getrennt. `München/S9` besitzt nur einen historischen Monatswert
und keine aktuelle Linie im verwendeten MVV-GTFS 06/2026. Aufbau und Prüfdaten
der Fahrwege stehen unter [Webkarte](KARTE.md).

Der bundesweite erste Durchlauf ergänzt 87 Linien. Er berücksichtigt nur
Quellkennungen mit mindestens 40 Verspätungsmonaten und einer aktuellen,
regional passenden DELFI-GTFS-Route. Die Definitionen stehen in
[`examples/line-references-germany.json`](../examples/line-references-germany.json),
die Ergebnisse und elf nicht zugeordnete historische Kennungen im
[`Prüfbericht`](germany-first-pass-report.json). Die Fahrwege verwenden die
basemap.de-Klassen `S-Bahn`, `Eisenbahn`, `Personenverkehr` und `Gleis`.

## Regeln für Änderungen

- Jede inhaltliche Änderung erhöht `revision`.
- Ein identisches Dokument derselben Revision darf wiederholt werden.
- Ein Paar `netz`/`line` gehört immer höchstens einer `line_id`.
- Ein Alias wird erst aus der alten Linie entfernt und danach mit höherer
  Revision der neuen Linie zugeordnet.
- Einträge werden stillgelegt, nicht gelöscht.
- `reference` und `version` sind ab Status `mapped` Pflicht.
- Freitext in `notes` ersetzt keine geprüfte Geometriereferenz.

## Was die Statistikquelle liefern muss

Für jede Zeile auf Linienebene werden weiterhin `netz` und `line` benötigt,
zusätzlich die veröffentlichte `line_id`. Dadurch kann der Server sowohl die
stabile Zuordnung als auch den ursprünglichen Quellwert prüfen. Stationszeilen
in `mostCancelledStops` brauchen dieselbe ID.

Eigene Koordinaten oder Fahrweg-Geometrien muss der Statistiklieferant nicht
mitsenden. Für eine spätere Stationsdarstellung werden jedoch Stationsname,
ein dokumentiertes Stations-ID-System und Koordinaten benötigt; diese Angaben
sind im aktuellen Export noch nicht enthalten.
