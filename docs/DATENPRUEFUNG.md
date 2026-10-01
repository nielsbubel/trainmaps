# Pruefung von daten/frontend.json

Der Export wurde vollstaendig eingelesen; die Originaldatei wurde nicht veraendert.
Der maschinenlesbare Bericht mit SHA-256, allen Netz-/Linienkennungen und
Pruefergebnissen steht in [frontend-inspection.json](frontend-inspection.json).

Umfang: **7.821.514 Bytes, 33.108 Zeilen, 57 Monatslabels von September 2021
bis Mai 2026, 18 Netzbezeichnungen und 361 unterschiedliche Netz-/Linienpaare**.
Die 361 Paare sind Quellkennungen, keine bestaetigte Anzahl realer S-Bahnlinien.

| Datenblock | Zeilen | Bedeutung |
| --- | ---: | --- |
| cancellationsByMonth | 57 | Ausfaelle je Monat insgesamt |
| cancellationsByNetworkMonth | 1.016 | Ausfaelle je Netz und Monat |
| cancellationsByNetworkLineMonth | 13.874 | Ausfaelle je Linie, Netz und Monat |
| delaysByMonth | 57 | Puenktlichkeitsquoten je Monat insgesamt |
| delaysByNetworkMonth | 1.016 | Puenktlichkeit je Netz und Monat |
| delaysByNetworkLineMonth | 13.832 | Puenktlichkeit je Linie, Netz und Monat |
| mostCancelledStops | 3.256 | Stations-/Linien-Ausfallwerte ohne angegebenen Zeitraum |

Alle Zaehler, Quoten und Schwellenreihenfolgen sind rechnerisch konsistent.
Die Summen Linie → Netz und Netz → Gesamt stimmen fuer beide Kennzahlenfamilien
ueberein. Es wurden keine doppelten Zeilenschluessel gefunden.

## Zuordnung und fachliche Grenzen

- Die Quelle enthaelt `Karlruhe`, `12,`, `LEER`, lange numerische Kennungen sowie
  gleichzeitig `1` und `S1`. Diese Namen werden unveraendert archiviert. Ein
  implementierte Alias-/Linienregister muss nun mit geprüften S-Bahnlinien
  befüllt werden und Auffälligkeiten klären; pauschales Voranstellen von „S“
  ist ungeeignet.
- Auch Bezeichnungen wie `RB6`, `RE14` und `FEX` sind enthalten. Ihr Auftreten
  belegt, dass die gelieferte Klassifikation vor der Kartendarstellung geprueft
  werden muss. Der Bericht behauptet nicht, dass jede Kombination geografisch
  oder verkehrlich korrekt ist.
- 42 Linien-Monatszeilen haben Ausfalldaten ohne passende Puenktlichkeitszeile.
  Dort bleibt Puenktlichkeit „keine Daten“; es wird keine Nullverspaetung erfunden.
- Bei 13.817 gemeinsamen Linien-Monatsschluesseln entspricht der Nenner der
  Puenktlichkeit **nicht** `Ausfall-Nenner minus Ausfaelle`. Beide Serien duerfen
  daher nicht zu einer Gesamtzuverlaessigkeitsquote zusammengerechnet werden.
  Beispiel Berlin / 1 / 2021-09: 25.088 Ausfall-Messpunkte, 4.494 ausgefallen,
  aber 10.303 Puenktlichkeits-Messpunkte.
- Ausfaelle sind laut Nutzer aus den Puenktlichkeitswerten ausgeschlossen.
  Der neue Export liefert sie zusaetzlich als eigenstaendige Kennzahl.
- Die Stationsrangliste enthaelt 1.501 verschiedene `stop_id`. Die ergänzende
  Datei `daten/most_cancelled_stops.csv` weist sie als siebenstellige deutsche
  EVA-Nummern aus und liefert Stationsnamen. Zeitraum, Koordinaten und
  Vollstaendigkeitsangabe fehlen weiterhin. Die Rangliste wird separat erhalten,
  nicht einem Monat zugeordnet und nicht automatisch als vollstaendiger
  Stationsbestand betrachtet.
- Das letzte Monatslabel 2026-05 beweist keinen vollstaendigen Monat. Stand der
  Datenerzeugung, Erfassungsende und Monat-Vollstaendigkeit fehlen im Export.
- Schwellenvergleich (`<` oder `<=`), Zaehleinheit, Ankunft/Abfahrt und fachliche
  Zeitzone bleiben offen. Der Export selbst enthält keine Fahrweggeometrien;
  trainmaps referenziert dafür geprüfte S-Bahn-Gleise aus basemap.de.

## Erneut pruefen

```sh
python scripts/inspect_frontend.py daten/frontend.json --report docs/frontend-inspection.json
```

Das Werkzeug benoetigt nur die Python-Standardbibliothek. Numerische Konsistenz
ist keine Bestaetigung der Netz-/Linienzuordnung oder geografischen Vollstaendigkeit.
