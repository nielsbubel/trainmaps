"""Public documentation, with an explicit list of publishable files."""
from __future__ import annotations

import io
import json
import posixpath
import re
import unicodedata
import zipfile
from dataclasses import dataclass
from html import escape
from pathlib import Path
from urllib.parse import unquote, urlsplit, urlunsplit

from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from markdown_it import MarkdownIt


@dataclass(frozen=True)
class Document:
    slug: str
    file: str
    title: str
    description: str


DOCUMENTS = (
    Document("schnellstart", "docs/SCHNELLSTART.md", "Schnellstart", "Verbindung prüfen und die erste JSON-Lieferung testen."),
    Document("karte", "docs/KARTE.md", "Webkarte", "96 deutsche S-Bahnlinien ansehen, Ebenen wählen und öffentliche Kartenendpunkte verwenden."),
    Document("api", "docs/API.md", "API & Datenlieferung", "Datenformat, Authentifizierung, Endpunkte und Fehlercodes."),
    Document("linienreferenzen", "docs/LINIENREFERENZEN.md", "Linienreferenzen", "Stabile Linien-IDs mit basemap.de-Fahrwegen verknüpfen."),
    Document("linienkandidaten", "docs/LINIENKANDIDATEN.md", "Linienkandidaten", "Rohwerte prüfen und schrittweise in den Katalog übernehmen."),
    Document("https", "docs/HTTPS.md", "HTTPS & Betrieb", "Zertifikat, Firewall, Protokolle und Neustart des Servers."),
    Document("kartenplanung", "docs/MONATSDATEN_UND_API.md", "Karte & Architektur", "Kartenebenen, Linienzuordnung und geplante Erweiterungen."),
    Document("datenpruefung", "docs/DATENPRUEFUNG.md", "Datenprüfung", "Umfang, Qualität und fachliche Grenzen des gelieferten Exports."),
    Document("projekt", "README.md", "Projektübersicht", "Aktueller Stand und Einstieg in das Projekt trainmaps."),
)
ATTACHMENTS = {
    "frontend-minimal.json": "examples/frontend-minimal.json",
    "frontend-v2-minimal.json": "examples/frontend-v2-minimal.json",
    "frontend-v3-minimal.json": "examples/frontend-v3-minimal.json",
    "line-reference.json": "examples/line-reference.json",
    "line-reference-muenchen-s1.json": "examples/line-reference-muenchen-s1.json",
    "line-references-muenchen.json": "examples/line-references-muenchen.json",
    "line-references-germany.json": "examples/line-references-germany.json",
    "germany-first-pass-report.json": "docs/germany-first-pass-report.json",
    "line-candidates.json": "docs/line-candidates.json",
    "frontend-inspection.json": "docs/frontend-inspection.json",
    "monthly-line.json": "examples/monthly-line.json",
}
DOC_BY_SLUG = {doc.slug: doc for doc in DOCUMENTS}
URL_BY_FILE = {doc.file: f"/dokumentation/{doc.slug}" for doc in DOCUMENTS}
URL_BY_FILE.update({path: f"/dokumentation/dateien/{name}" for name, path in ATTACHMENTS.items()})
URL_BY_FILE["api/openapi.json"] = "/openapi.json"

CSP = "default-src 'none'; style-src 'self'; script-src 'self'; img-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"


def slugify(text):
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-") or "abschnitt"


def rewrite_link(href, source):
    url = urlsplit(href)
    if url.scheme or url.netloc or not url.path or url.path.startswith("/"):
        return href
    path = posixpath.normpath(posixpath.join(posixpath.dirname(source), unquote(url.path)))
    target = URL_BY_FILE.get(path)
    return urlunsplit(("", "", target, url.query, url.fragment)) if target else href


def render_markdown(text, source):
    renderer = MarkdownIt("commonmark", {"html": False}).enable("table")
    tokens = renderer.parse(text)
    headings, seen = [], {}
    for index, token in enumerate(tokens):
        if token.type == "heading_open":
            inline = tokens[index + 1]
            title = "".join(child.content for child in inline.children or [] if child.type in ("text", "code_inline"))
            base = slugify(title)
            count = seen.get(base, 0)
            seen[base] = count + 1
            anchor = base if not count else f"{base}-{count}"
            token.attrSet("id", anchor)
            if token.tag != "h1":
                headings.append((anchor, title))
        # Use CSS classes instead of inline alignment styles for the strict CSP.
        alignment = token.attrGet("style")
        if alignment and alignment.startswith("text-align:"):
            token.attrs.pop("style", None)
            token.attrSet("class", "align-" + alignment.split(":", 1)[1])
        for child in token.children or []:
            if child.type == "link_open":
                child.attrSet("href", rewrite_link(child.attrGet("href") or "", source))
    return renderer.renderer.render(tokens, renderer.options, {}), headings


def page(title, content, *, selected="", headings=(), version="0.10.0"):
    links = ['<a href="/dokumentation"' + (' aria-current="page"' if not selected else '') + '>Übersicht</a>']
    for doc in DOCUMENTS:
        current = ' aria-current="page"' if doc.slug == selected else ''
        links.append(f'<a href="/dokumentation/{doc.slug}"{current}>{escape(doc.title)}</a>')
    toc = ''.join(f'<li><a href="#{escape(anchor)}">{escape(label)}</a></li>' for anchor, label in headings)
    contents = f'<aside class="toc" aria-label="Auf dieser Seite"><p class="eyebrow">Auf dieser Seite</p><ul>{toc}</ul></aside>' if toc else ''
    html = f'''<!doctype html>
<html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="Dokumentation der trainmaps-API: Datenlieferung, HTTPS, Kartenplanung und Datenprüfung.">
<title>{escape(title)} · trainmaps</title><link rel="icon" href="/dokumentation/assets/icon.svg" type="image/svg+xml">
<link rel="stylesheet" href="/dokumentation/assets/docs.css">
<script src="/dokumentation/assets/docs.js" defer></script></head>
<body><a class="skip-link" href="#inhalt">Zum Inhalt</a>
<header class="topbar"><a class="brand" href="/dokumentation"><span class="brand-icon" aria-hidden="true">t</span>trainmaps<span class="brand-label">Dokumentation</span></a>
<nav aria-label="Schnittstelle"><a href="/karte">Karte öffnen ↗</a><a href="/docs">API ausprobieren ↗</a><a href="/health">Status</a></nav></header>
<div class="layout"><aside class="sidebar"><details open><summary>Dokumentation</summary><nav aria-label="Dokumentation">{''.join(links)}</nav></details>
<div class="sidebar-resources"><span class="eyebrow">Für Entwickler</span><a href="/openapi.json">OpenAPI herunterladen</a><a href="/dokumentation/download.zip">Gesamte Doku als ZIP</a></div>
<p class="version">Entwicklungs-API · v{escape(version)}<br>96 Linien · 14 Verkehrsgebiete.</p></aside>
<main id="inhalt" class="{'reading' if selected else 'overview'}">{content}</main>{contents}</div>
<footer>trainmaps · Monatsdaten zur S-Bahn-Pünktlichkeit<span>Dokumentation frei zugänglich. Datenzugriff mit Token.</span></footer>
<div id="copy-status" class="sr-only" role="status" aria-live="polite"></div></body></html>'''
    return HTMLResponse(html, headers={"Content-Security-Policy": CSP, "Referrer-Policy": "no-referrer"})


def register_documentation(app, root: Path):
    router = APIRouter(include_in_schema=False)

    @router.get("/", response_class=HTMLResponse)
    @router.get("/dokumentation", response_class=HTMLResponse)
    def overview():
        cards = ''.join(f'<a class="doc-card" href="/dokumentation/{doc.slug}"><span class="card-number">{index:02d}</span><h2>{escape(doc.title)}</h2><p>{escape(doc.description)}</p><span class="card-link">Lesen <span aria-hidden="true">→</span></span></a>' for index, doc in enumerate(DOCUMENTS, 1))
        content = f'''<p class="eyebrow">Entwicklerportal</p><h1>Alle Informationen.<br>Ein Einstieg.</h1>
<p class="lead">JSON-Daten an trainmaps liefern, die Schnittstelle testen und den Betrieb verstehen. Hier findest du die vollständige Projektdokumentation.</p>
<div class="actions"><a class="button primary" href="/karte">Webkarte öffnen →</a><a class="button" href="/dokumentation/schnellstart">Mit dem Schnellstart beginnen</a><a class="button" href="/docs">Interaktive API</a></div>
<section class="endpoint-strip" aria-label="API-Adresse"><div><span class="eyebrow">Öffentliche Basisadresse</span><code>https://34.7.91.18</code></div><a href="/health">Verbindung testen ↗</a></section>
<div class="doc-grid">{cards}</div>
<section class="downloads"><h2>Vertrag, Beispiele und Prüfbericht</h2>
<p>Die Dokumente werden aus den Projektdateien angezeigt. Das ZIP enthält alle Anleitungen, den API-Vertrag und die folgenden Begleitdateien.</p>
<ul><li><a href="/openapi.json">OpenAPI 3.1 – aktueller Schnittstellenvertrag</a></li>
<li><a href="/dokumentation/dateien/frontend-v3-minimal.json">JSON-Testbeispiel für frontend-3</a> – mit Linien-ID und EVA-Haltestelle</li>
<li><a href="/dokumentation/dateien/frontend-v2-minimal.json">Altes JSON-Testbeispiel für frontend-2</a> – weiterhin kompatibel</li>
<li><a href="/dokumentation/dateien/line-reference.json">Beispiel einer Linienreferenz</a> – für die getrennte Mapping-Verwaltung</li>
<li><a href="/dokumentation/dateien/line-reference-muenchen-s1.json">Erste verifizierte Linienreferenz</a> – München/S1 mit basemap.de-Fahrweg</li>
<li><a href="/dokumentation/dateien/line-candidates.json">Kandidatenliste aus dem aktuellen Export</a> – 361 Quellpaare mit Prüfhinweisen</li>
<li><a href="/dokumentation/dateien/frontend-minimal.json">Altes frontend-1-Testbeispiel</a> – weiterhin im Prüfmodus nutzbar</li>
<li><a href="/dokumentation/dateien/frontend-inspection.json">Vollständiger Datenprüfbericht als JSON</a></li>
<li><a href="/dokumentation/dateien/monthly-line.json">Früherer Formatentwurf</a> – archiviert, kein gültiger Import-Body</li></ul>
<a class="button" href="/dokumentation/download.zip">Gesamte Dokumentation herunterladen ↓</a></section>'''
        return page("Dokumentation", content, version=app.version)

    @router.get("/dokumentation/download.zip")
    def archive():
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
            for file in [*(doc.file for doc in DOCUMENTS), *ATTACHMENTS.values()]:
                bundle.writestr(file, (root / file).read_bytes())
            bundle.writestr("api/openapi.json", json.dumps(app.openapi(), indent=2, ensure_ascii=False))
        return Response(buffer.getvalue(), media_type="application/zip", headers={
            "Content-Disposition": 'attachment; filename="trainmaps-dokumentation.zip"'})

    @router.get("/dokumentation/dateien/{filename}")
    def attachment(filename: str):
        path = ATTACHMENTS.get(filename)
        if path is None:
            raise HTTPException(404, "Dokumentationsdatei nicht gefunden.")
        return Response((root / path).read_bytes(), media_type="application/json", headers={
            "Content-Disposition": f'attachment; filename="{filename}"'})

    @router.get("/dokumentation/quellen/{slug}.md")
    def source(slug: str):
        doc = DOC_BY_SLUG.get(slug)
        if doc is None:
            raise HTTPException(404, "Dokument nicht gefunden.")
        return Response((root / doc.file).read_bytes(), media_type="text/markdown; charset=utf-8", headers={
            "Content-Disposition": f'attachment; filename="{Path(doc.file).name}"'})

    @router.get("/dokumentation/{slug}", response_class=HTMLResponse)
    def document(slug: str):
        doc = DOC_BY_SLUG.get(slug)
        if doc is None:
            raise HTTPException(404, "Dokument nicht gefunden.")
        rendered, headings = render_markdown((root / doc.file).read_text(encoding="utf-8-sig"), doc.file)
        toolbar = f'<div class="document-tools"><a href="/dokumentation">← Dokumentation</a><a href="/dokumentation/quellen/{doc.slug}.md">Markdown herunterladen ↓</a><button type="button" id="print-page">Drucken</button></div>'
        return page(doc.title, toolbar + '<article class="prose">' + rendered + '</article>', selected=slug, headings=headings, version=app.version)

    # Only this asset directory is public; never mount the repository or .local/.
    app.mount("/dokumentation/assets", StaticFiles(directory=Path(__file__).parent / "doc_assets"), name="documentation-assets")
    app.include_router(router)
