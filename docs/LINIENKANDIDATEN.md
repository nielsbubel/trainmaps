# Linienkandidaten aus dem aktuellen Export

Die Kandidatenliste wurde automatisch aus `daten/frontend.json` erzeugt. Sie
ist eine Arbeitsliste für den Betreiber und wird nicht automatisch in den
öffentlichen Linienkatalog übernommen.

[Vollständige Kandidatenliste als JSON herunterladen](line-candidates.json).

## Ergebnis

| Klasse | Anzahl | Behandlung |
| --- | ---: | --- |
| Explizite S-Bahn-Bezeichnung wie `S1` | 141 | Stabile ID vorschlagen, reale Linie und Fahrweg prüfen. |
| Explizite regionale S-Bahn wie `RS1` | 19 | Stabile ID vorschlagen, System und Fahrweg prüfen. |
| Numerischer Wert oder Variante wie `1`, `5X` | 190 | Bedeutung und möglichen S-Alias manuell klären. |
| Andere Bahnbezeichnung wie `RB6`, `RE14`, `FEX` | 7 | Nicht automatisch als S-Bahn übernehmen. |
| Manuell zu klassifizieren, etwa `1/2` oder `12,` | 3 | Quelle korrigieren oder fachlich zuordnen. |
| Platzhalter `LEER` | 1 | Ablehnen oder durch eine echte Kennung ersetzen. |
| **Gesamt** | **361** | |

Für 160 explizite S- und RS-Bezeichnungen enthält der Bericht einen
ID-Vorschlag. Ein Vorschlag bestätigt weder die reale Linie noch ihren
basemap.de-Fahrweg.

## Erster Kandidat: München S1

Für das Quellpaar `München/S1` wurde vorgeschlagen:

```json
{
  "source_alias": {"netz": "München", "line": "S1"},
  "proposed_network_id": "de.muenchen",
  "proposed_line_id": "de.muenchen.s1",
  "possible_aliases": [
    {"netz": "München", "line": "1"}
  ],
  "first_month": "2021-09",
  "last_month": "2026-05"
}
```

`München/S1` besitzt 57 Ausfallmonate, 57 Pünktlichkeitsmonate und 24 Einträge
in der Stationsrangliste. `München/1` wird nicht übernommen: Beide Bezeichnungen
kommen mit unterschiedlichen Werten vor und müssen zunächst fachlich geklärt
werden.

Der erste Katalogeintrag verwendet deshalb ausschließlich den eindeutigen Alias
`München/S1`. Sein Fahrweg wurde aus basemap.de-Gleisen aufgebaut, gegen die
MVV-GTFS-Haltefolge geprüft und mit Revision 2 auf `verified` gesetzt.
Das verwendete [Katalogdokument kann als JSON heruntergeladen werden](../examples/line-reference-muenchen-s1.json).

## Bericht neu erzeugen

```powershell
.\.venv\Scripts\python.exe scripts\build_line_candidates.py `
  daten\frontend.json --output docs\line-candidates.json
```

Der Bericht enthält pro Paar:

- Klassifikation und vorgeschlagene Netzwerk-/Linien-ID;
- mögliche numerische oder unterschiedlich geschriebene Aliase;
- Zeilenzahlen je Datenblock;
- ersten und letzten vorhandenen Monat;
- konkrete Prüfschritte vor der Katalogaufnahme.

Die Quelldatei wird nicht verändert. Der SHA-256-Hash im Bericht stellt sicher,
dass die Kandidatenliste zum dokumentierten Export gehört.

## Freigabeprozess

1. Reale S-Bahnlinie bestätigen.
2. Vorgeschlagene `line_id` prüfen.
3. Nur bestätigte Quellaliase übernehmen.
4. basemap.de-Gleisabschnitte auswählen.
5. Technische Zuordnung mit `mapped` speichern.
6. Verlauf visuell prüfen und mit höherer Revision auf `verified` setzen.

Die Regeln und API-Aufrufe stehen unter [Linienreferenzen](LINIENREFERENZEN.md).
