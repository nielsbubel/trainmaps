# HTTPS auf dem trainmaps-Rechner

Stand: 30. September 2026. Öffentliche Basisadresse: **https://34.7.91.18**.
Die API läuft auf diesem Windows-Rechner unter `127.0.0.1:8787`. Caddy nimmt
Anfragen auf Port 80/443 entgegen und leitet HTTPS-Anfragen an die API weiter.
API-Daten und private Zertifikatsschlüssel liegen lokal unter `.local/` und
werden nicht eingecheckt. Cloudflare ist nicht beteiligt.

## Endpunkte von außen testen

| Zweck | Aufruf | Zugang |
| --- | --- | --- |
| Erreichbarkeit und TLS | `GET https://34.7.91.18/health` | Ohne Token |
| Nur HTTP-Erreichbarkeit | `GET http://34.7.91.18/health` | Ohne Token |
| Interaktive Dokumentation | `GET https://34.7.91.18/docs` | Ohne Token |
| API-Vertrag | `GET https://34.7.91.18/openapi.json` | Ohne Token |
| Linienkatalog lesen | `GET https://34.7.91.18/api/v1/reference/lines` | Lese- oder Schreibtoken |
| JSON mit Linien-IDs prüfen | `POST https://34.7.91.18/api/v2/imports/frontend?validate_only=true` | Schreibtoken |
| JSON mit Linien-IDs speichern | `POST https://34.7.91.18/api/v2/imports/frontend` | Schreibtoken |
| Alten Export ohne IDs prüfen | `POST https://34.7.91.18/api/v1/imports/frontend?validate_only=true` | Schreibtoken |
| Monatsdaten lesen | `GET https://34.7.91.18/api/v1/data/monthly?metric=punctuality&month=2021-09&netz=Berlin&line=1` | Lesetoken oder Schreibtoken |

```powershell
curl.exe --fail-with-body https://34.7.91.18/health
```

Erwartet: HTTP 200 und
`{"status":"ok","service":"trainmaps-development","version":"0.4.0"}`.
Die Zertifikatsprüfung bleibt eingeschaltet; `--insecure` ist nicht nötig.
Weitere HTTP-Pfade werden auf HTTPS umgeleitet. Tokens und JSON-Lieferungen
immer direkt an die HTTPS-Adresse senden, nicht erst an die HTTP-Weiterleitung.
Benötigte Header, Datenformat und Beispiele stehen in [API.md](API.md).

Geprüft am 30. September 2026 über die öffentliche HTTPS-Adresse: Status,
Swagger und OpenAPI jeweils HTTP 200; Datenzugriffe ohne Token HTTP 401;
Schreibversuch mit Lesetoken HTTP 403. Der vollständige Export wurde mit
identischer SHA-256-Prüfsumme zurückgelesen. Der Import-Prüflauf validierte
33.108 Zeilen, ohne eine neue Revision zu speichern. Prüfbeleg:
`.local/https-checks.json` (enthält keine Tokens).

## Zertifikat und Erneuerung

Installiert ist Caddy **2.11.4**, heruntergeladen aus dem offiziellen
[Caddy-Release](https://github.com/caddyserver/caddy/releases/tag/v2.11.4).
Die SHA-256-Prüfsumme des Windows-amd64-ZIP wurde überprüft:
`1708333f79e274c7697285afe6d592ab39314e0b131e9ec6bea08ad27df62ebf`.
Programm: `.local/tools/caddy-2.11.4/caddy.exe`.

Let's Encrypt unterstützt IP-Zertifikate mit dem Profil `shortlived` und einer
Gültigkeit von 160 Stunden. Das erste echte Zertifikat wurde für `34.7.91.18`
ausgestellt (Aussteller Let's Encrypt YE2; gültig bis 7. Oktober 2026,
00:24:47 UTC). Diese Angabe ist eine Momentaufnahme, kein festes Ablaufdatum
für den Dienst: Caddy verwaltet die nachfolgenden Erneuerungen automatisch.
Quelle: [Let's Encrypt: IP-Zertifikate](https://letsencrypt.org/2026/01/15/6day-and-ip-general-availability).

Die Konfiguration in `deploy/Caddyfile` wählt ausdrücklich Let's Encrypt aus
und verwendet HTTP-01 zur Kontrolle der IP-Adresse. TCP-Port 80 muss deshalb
auch künftig erreichbar bleiben. Port 443 dient den verschlüsselten Anfragen.
`default_sni 34.7.91.18` stellt das richtige Zertifikat auch für Clients bereit,
die bei einem IP-Aufruf keinen TLS-Servernamen senden.
Quellen: [Caddy TLS](https://caddyserver.com/docs/caddyfile/directives/tls),
[Caddy default_sni](https://caddyserver.com/docs/caddyfile/options#default_sni).

Private Schlüssel und Kontodaten bleiben in `.local/caddy-production/`.
Testzertifikate liegen getrennt in `.local/caddy-staging/` und sind nicht
öffentlich vertrauenswürdig. Die Testumgebung wurde vor der echten Ausstellung
erfolgreich verwendet; aktuell wird das Produktionszertifikat ausgeliefert.

## Neustart und Protokolle

Es ist **kein Windows-Dienst und kein Autostart** eingerichtet. Nach einem
Rechnerneustart zuerst die API in einem Terminal starten:

```powershell
Set-Location 'C:\Users\nb005\Documents\Herbstcamp\trainmaps'
.\.venv\Scripts\python.exe -m uvicorn trainmaps_api.app:create_app --factory `
  --host 127.0.0.1 --port 8787 --workers 1 --no-access-log
```

Dann in einem zweiten Terminal Caddy im Hintergrund starten:

```powershell
Set-Location 'C:\Users\nb005\Documents\Herbstcamp\trainmaps'
.\scripts\start_https.ps1
curl.exe --fail-with-body https://34.7.91.18/health
```

Caddy erneuert Zertifikate, solange er läuft; bei ausgeschaltetem Rechner oder
gestopptem Prozess gibt es weder Erreichbarkeit noch Erneuerung. Vor einem
Dauerbetrieb ist ein Dienst/Autostart für beide Prozesse einzurichten.

- Proxy stoppen: `scripts/stop_https.ps1`. Die API und gespeicherte Daten bleiben erhalten.
- Nach einer Konfigurationsänderung: stoppen, dann `scripts/start_https.ps1`.
- Zertifikats- und Fehlerprotokoll: `.local/https.stderr.log`.
- Prozesskennung: `.local/https-process.json`; das Stoppskript prüft Pfad und Startzeit.
- Nur HTTP-Status ohne Zertifikatsversuche: `scripts/start_https.ps1 -HealthOnly`.
- Separater Zertifikatstest: `scripts/start_https.ps1 -Staging`; anschließend stoppen und normal starten.

Bei einem erneuten Start werden die aktuellen Prozessprotokolle ersetzt;
benötigte Diagnoseprotokolle vorher sichern. Ein erfolgreicher Prozessstart
allein beweist noch keine erfolgreiche Zertifikatsausstellung.

## Firewall und öffentliche IP

In Windows wurde die Regel `trainmaps-caddy-http-https` eingerichtet. Sie gibt
nur TCP 80/443 für das konkrete Caddy-Programm frei. Das Skript
`scripts/enable_https_firewall.ps1` dient zum erstmaligen Anlegen und verlangt
Administratorrechte. Port 8787 bleibt nur an localhost gebunden.

Die zusätzliche Cloud-Firewall wurde vom Nutzer freigegeben. Die erfolgreiche
Let's-Encrypt-Validierung bestätigt den Zugriff von extern auf Port 80; HTTPS
wurde anschließend über die öffentliche IP mit vollständiger Zertifikatsprüfung
getestet. Der genaue Umfang der Cloud-Regel konnte mangels gültiger
Verwaltungsanmeldung nicht ausgelesen werden.

Die Reservierung von `34.7.91.18` als statische IP wurde nicht geprüft. Ändert
sich die IP, müssen beide Caddy-Konfigurationen, `default_sni` und die
veröffentlichten Endpunkte angepasst und ein neues Zertifikat ausgestellt werden.
