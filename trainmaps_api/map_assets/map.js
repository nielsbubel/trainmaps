import {Map, NavigationControl, Popup, LngLatBounds, setWorkerUrl} from './vendor/maplibre-gl.mjs';

setWorkerUrl('/karte/assets/vendor/maplibre-gl-worker.mjs');

const $ = (id) => document.getElementById(id);
const state = {config: null, line: null, geometry: null, value: null, map: null};
const colors = {good: '#238657', ok: '#8bac42', warn: '#e2a62e', bad: '#d65945', empty: '#87918c'};

function colorFor(ratio) {
  if (ratio == null) return colors.empty;
  if (ratio <= .02) return colors.good;
  if (ratio <= .05) return colors.ok;
  if (ratio <= .10) return colors.warn;
  return colors.bad;
}

function showError(error) {
  const box = $('error-box');
  box.textContent = error?.message || 'Die Karte konnte nicht geladen werden.';
  box.hidden = false;
  $('loading').classList.add('ready');
}

async function getJson(url) {
  const response = await fetch(url, {headers: {'Accept': 'application/json'}});
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.message || `HTTP ${response.status}`);
  return body;
}

function monthLabel(value) {
  const [year, month] = value.split('-').map(Number);
  return new Intl.DateTimeFormat('de-DE', {month: 'long', year: 'numeric'}).format(new Date(year, month - 1, 1));
}

function populateControls() {
  const line = state.line;
  $('line-badge').textContent = line.display_name.split(' ')[0];
  $('line-title').textContent = line.display_name.replace(/^\S+\s*/, '') || line.display_name;
  $('month-select').replaceChildren(...line.months.map(month => new Option(monthLabel(month), month)));
  $('month-select').value = new URLSearchParams(location.search).get('month') || state.config.default_month;
  $('metric-select').replaceChildren(...state.config.metrics.map(item => new Option(item.label, item.id)));
  $('metric-select').value = new URLSearchParams(location.search).get('metric') || 'punctuality';
  $('threshold-select').replaceChildren(...state.config.thresholds_minutes.map(value => new Option(`${value} Minuten`, value)));
  $('threshold-select').value = new URLSearchParams(location.search).get('threshold') || state.config.default_threshold_minutes;
  $('revision-label').textContent = `Datenrevision ${state.config.data_revision}`;
  $('source-note').textContent = `Fahrweg: ${state.config.attribution.basemap}. Haltefolge: ${state.config.attribution.route_reference}.`;
  const list = $('layer-list');
  list.replaceChildren(...state.config.layers.map(layer => {
    const label = document.createElement('label');
    const input = document.createElement('input');
    input.type = 'checkbox'; input.checked = layer.default; input.dataset.layer = layer.id;
    input.addEventListener('change', () => setLayerVisibility(layer.id, input.checked));
    label.append(input, document.createTextNode(layer.label));
    return label;
  }));
}

function setLayerVisibility(category, visible) {
  if (!state.map?.isStyleLoaded()) return;
  const custom = {
    selected: ['selected-line-shadow', 'selected-line'],
    stations: ['selected-stations-halo', 'selected-stations', 'selected-station-labels'],
  };
  const ids = custom[category] || state.map.getStyle().layers
    .filter(layer => layer.metadata?.['trainmaps:category'] === category)
    .map(layer => layer.id);
  ids.forEach(id => { if (state.map.getLayer(id)) state.map.setLayoutProperty(id, 'visibility', visible ? 'visible' : 'none'); });
}

function geometryBounds(collection) {
  const bounds = new LngLatBounds();
  function visit(value) {
    if (typeof value?.[0] === 'number') bounds.extend(value);
    else if (Array.isArray(value)) value.forEach(visit);
  }
  collection.features.forEach(feature => visit(feature.geometry.coordinates));
  return bounds;
}

function addSelectedLine() {
  state.map.addSource('selected-line-source', {type: 'geojson', data: state.geometry});
  const lineFilter = ['==', ['get', 'feature_type'], 'line'];
  const stationFilter = ['==', ['get', 'feature_type'], 'station'];
  state.map.addLayer({id: 'selected-line-shadow', type: 'line', source: 'selected-line-source', filter: lineFilter,
    paint: {'line-color': '#fff', 'line-width': ['interpolate', ['linear'], ['zoom'], 7, 6, 13, 10], 'line-opacity': .94}});
  state.map.addLayer({id: 'selected-line', type: 'line', source: 'selected-line-source', filter: lineFilter,
    paint: {'line-color': colors.empty, 'line-width': ['interpolate', ['linear'], ['zoom'], 7, 3, 13, 6], 'line-opacity': .98}});
  state.map.addLayer({id: 'selected-stations-halo', type: 'circle', source: 'selected-line-source', filter: stationFilter,
    paint: {'circle-radius': ['interpolate', ['linear'], ['zoom'], 8, 3, 13, 6], 'circle-color': '#fff', 'circle-stroke-width': 1, 'circle-stroke-color': 'rgba(21,37,31,.16)'}});
  state.map.addLayer({id: 'selected-stations', type: 'circle', source: 'selected-line-source', filter: stationFilter, minzoom: 8.5,
    paint: {'circle-radius': ['interpolate', ['linear'], ['zoom'], 9, 2, 13, 3.5], 'circle-color': '#173f31'}});
  state.map.addLayer({id: 'selected-station-labels', type: 'symbol', source: 'selected-line-source', filter: stationFilter, minzoom: 11,
    layout: {'text-field': ['get', 'name'], 'text-font': ['Roboto Condensed Regular'], 'text-size': 11, 'text-offset': [0, 1.15], 'text-anchor': 'top', 'text-optional': true},
    paint: {'text-color': '#20342c', 'text-halo-color': '#fff', 'text-halo-width': 1.5}});
  state.map.on('mouseenter', 'selected-line', () => { state.map.getCanvas().style.cursor = 'pointer'; });
  state.map.on('mouseleave', 'selected-line', () => { state.map.getCanvas().style.cursor = ''; });
  state.map.on('click', 'selected-line', event => {
    const value = state.value;
    if (!value) return;
    const node = document.createElement('div');
    const strong = document.createElement('strong'); strong.textContent = value.display_name;
    const small = document.createElement('small'); small.textContent = `${value.label}: ${value.percentage.toLocaleString('de-DE', {maximumFractionDigits: 1})} % · ${monthLabel(value.month)}`;
    node.append(strong, small);
    new Popup({closeButton: false}).setLngLat(event.lngLat).setDOMContent(node).addTo(state.map);
  });
  state.map.on('click', 'selected-stations', event => {
    const name = event.features?.[0]?.properties?.name;
    if (!name) return;
    const node = document.createElement('div');
    const strong = document.createElement('strong'); strong.textContent = name;
    const small = document.createElement('small'); small.textContent = 'Noch kein eigener Stationswert vorhanden';
    node.append(strong, small);
    new Popup({closeButton: false}).setLngLat(event.lngLat).setDOMContent(node).addTo(state.map);
  });
}

async function updateValue() {
  const metric = $('metric-select').value;
  const month = $('month-select').value;
  const threshold = $('threshold-select').value;
  $('threshold-field').hidden = metric !== 'punctuality';
  const query = new URLSearchParams({line_id: state.line.line_id, month, metric, threshold_minutes: threshold});
  const value = await getJson(`/api/v1/map/monthly?${query}`);
  state.value = value;
  const color = colorFor(value.ratio);
  if (state.map?.getLayer('selected-line')) state.map.setPaintProperty('selected-line', 'line-color', color);
  $('value-swatch').style.background = color;
  $('value-label').textContent = value.label;
  $('value-number').textContent = value.percentage == null ? 'Keine Daten' : `${value.percentage.toLocaleString('de-DE', {minimumFractionDigits: 1, maximumFractionDigits: 1})} %`;
  $('value-count').textContent = `${value.numerator.toLocaleString('de-DE')} von ${value.n_data_points.toLocaleString('de-DE')} Datenpunkten`;
  $('value-definition').textContent = value.definition;
  const params = new URLSearchParams({month, metric});
  if (metric === 'punctuality') params.set('threshold', threshold);
  history.replaceState(null, '', `${location.pathname}?${params}`);
}

async function start() {
  state.config = await getJson('/api/v1/map/config');
  if (!state.config.default_line_id) throw new Error('Noch keine freigegebene Linie mit Monatsdaten verfügbar.');
  state.line = state.config.lines.find(line => line.line_id === state.config.default_line_id);
  populateControls();
  const [style, geometry] = await Promise.all([
    getJson('/karte/assets/basemap-style.json'),
    getJson(`/api/v1/map/lines.geojson?line_id=${encodeURIComponent(state.line.line_id)}`),
  ]);
  state.geometry = geometry;
  state.map = new Map({container: 'map', style, center: [11.58, 48.18], zoom: 9.3, attributionControl: true});
  state.map.addControl(new NavigationControl({showCompass: false}), 'top-right');
  state.map.once('load', async () => {
    addSelectedLine();
    state.map.fitBounds(geometryBounds(state.geometry), {padding: {top: 105, right: 90, bottom: 70, left: 410}, maxZoom: 11, duration: 0});
    await updateValue();
    $('loading').classList.add('ready');
  });
  state.map.on('error', event => { if (event.error) console.warn('Kartenressource:', event.error.message); });
  ['month-select', 'metric-select', 'threshold-select'].forEach(id => $(id).addEventListener('change', () => updateValue().catch(showError)));
  $('panel-toggle').addEventListener('click', () => {
    const collapsed = $('control-panel').classList.toggle('collapsed');
    $('panel-toggle').setAttribute('aria-expanded', String(!collapsed));
  });
}

start().catch(showError);
