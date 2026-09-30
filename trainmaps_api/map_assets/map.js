import {Map as MapLibreMap, NavigationControl, LngLatBounds, setWorkerUrl} from './vendor/maplibre-gl.mjs';

setWorkerUrl('/karte/assets/vendor/maplibre-gl-worker.mjs');

const $ = (id) => document.getElementById(id);
const state = {
  config: null,
  map: null,
  entries: new globalThis.Map(),
  series: new globalThis.Map(),
  selected: null,
  metric: 'delay',
  basis: 'mean',
};
const SVG_NS = 'http://www.w3.org/2000/svg';
const comparisonStops = [
  [0, '#197a4b'], [.5, '#d8b72c'], [.72, '#eb8a2f'], [1, '#b7262f'],
];

function hexToRgb(hex) {
  return [1, 3, 5].map(offset => Number.parseInt(hex.slice(offset, offset + 2), 16));
}

function rgbToHex(rgb) {
  return `#${rgb.map(value => Math.round(value).toString(16).padStart(2, '0')).join('')}`;
}

function paletteColor(position) {
  const value = Math.max(0, Math.min(1, position));
  for (let index = 1; index < comparisonStops.length; index += 1) {
    const [rightValue, rightColor] = comparisonStops[index];
    const [leftValue, leftColor] = comparisonStops[index - 1];
    if (value <= rightValue) {
      const ratio = (value - leftValue) / (rightValue - leftValue);
      const left = hexToRgb(leftColor); const right = hexToRgb(rightColor);
      return rgbToHex(left.map((channel, channelIndex) => channel + (right[channelIndex] - channel) * ratio));
    }
  }
  return comparisonStops.at(-1)[1];
}

function comparisonField(metric = state.metric, basis = state.basis) {
  const suffix = metric === 'delay' ? 'estimated_delay_minutes' : 'cancellation_percentage';
  return `${basis}_${suffix}`;
}

function comparisonContext() {
  const field = comparisonField();
  const items = [...state.entries.values()].map(entry => ({entry, value: entry.line[field]}))
    .filter(item => item.value != null && Number.isFinite(item.value));
  const values = items.map(item => item.value);
  const minimum = values.length ? Math.min(...values) : null;
  const maximum = values.length ? Math.max(...values) : null;
  return {field, items, minimum, maximum, neutral: items.length < 2 || minimum === maximum};
}

function comparisonColor(value, context = comparisonContext()) {
  if (value == null || !Number.isFinite(value) || context.neutral) return '#718078';
  return paletteColor((value - context.minimum) / (context.maximum - context.minimum));
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

function monthLabel(value, short = false) {
  const [year, month] = value.split('-').map(Number);
  return new Intl.DateTimeFormat('de-DE', short
    ? {month: 'short', year: 'numeric'}
    : {month: 'long', year: 'numeric'}).format(new Date(year, month - 1, 1));
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

function allBounds() {
  const bounds = new LngLatBounds();
  state.entries.forEach(entry => {
    const item = geometryBounds(entry.geometry);
    bounds.extend(item.getSouthWest()); bounds.extend(item.getNorthEast());
  });
  return bounds;
}

function layerId(prefix, index) {
  return `trainmaps-${prefix}-${index}`;
}

function addLine(entry, index) {
  const source = layerId('source', index);
  const shadow = layerId('shadow', index);
  const route = layerId('route', index);
  const lineLabels = layerId('line-labels', index);
  const hit = layerId('hit', index);
  const stationHalo = layerId('station-halo', index);
  const stations = layerId('stations', index);
  const stationLabels = layerId('station-labels', index);
  const lineFilter = ['==', ['get', 'feature_type'], 'line'];
  const stationFilter = ['==', ['get', 'feature_type'], 'station'];
  const color = '#718078';

  state.map.addSource(source, {type: 'geojson', data: entry.geometry});
  state.map.addLayer({id: shadow, type: 'line', source, filter: lineFilter,
    paint: {'line-color': '#fff', 'line-width': ['interpolate', ['linear'], ['zoom'], 7, 6, 13, 10], 'line-opacity': .92}});
  state.map.addLayer({id: route, type: 'line', source, filter: lineFilter,
    paint: {'line-color': color, 'line-width': ['interpolate', ['linear'], ['zoom'], 7, 3.5, 13, 6], 'line-opacity': .96}});
  state.map.addLayer({id: lineLabels, type: 'symbol', source, filter: lineFilter, minzoom: 7,
    layout: {'symbol-placement': 'line', 'symbol-spacing': 280, 'text-field': entry.line.display_name.split(' ')[0],
      'text-font': ['Roboto Condensed Regular'], 'text-size': 12, 'text-keep-upright': true},
    paint: {'text-color': '#173f31', 'text-halo-color': '#fff', 'text-halo-width': 2.5}});
  state.map.addLayer({id: hit, type: 'line', source, filter: lineFilter,
    paint: {'line-color': '#000', 'line-width': 22, 'line-opacity': 0}});
  state.map.addLayer({id: stationHalo, type: 'circle', source, filter: stationFilter,
    paint: {'circle-radius': ['interpolate', ['linear'], ['zoom'], 8, 3, 13, 6], 'circle-color': '#fff', 'circle-stroke-width': 1, 'circle-stroke-color': 'rgba(21,37,31,.16)'}});
  state.map.addLayer({id: stations, type: 'circle', source, filter: stationFilter, minzoom: 8.5,
    paint: {'circle-radius': ['interpolate', ['linear'], ['zoom'], 9, 2, 13, 3.5], 'circle-color': '#173f31'}});
  state.map.addLayer({id: stationLabels, type: 'symbol', source, filter: stationFilter, minzoom: 11,
    layout: {'text-field': ['get', 'name'], 'text-font': ['Roboto Condensed Regular'], 'text-size': 11, 'text-offset': [0, 1.15], 'text-anchor': 'top', 'text-optional': true},
    paint: {'text-color': '#20342c', 'text-halo-color': '#fff', 'text-halo-width': 1.5}});

  entry.ids = {source, shadow, route, lineLabels, hit, stationHalo, stations, stationLabels};
  [hit, stations].forEach(id => {
    state.map.on('mouseenter', id, () => { state.map.getCanvas().style.cursor = 'pointer'; });
    state.map.on('mouseleave', id, () => { state.map.getCanvas().style.cursor = ''; });
    state.map.on('click', id, event => {
      event.originalEvent?.stopPropagation?.();
      selectLine(entry).catch(showError);
    });
  });
}

function populateLayerControls() {
  $('revision-label').textContent = `Datenrevision ${state.config.data_revision}`;
  $('source-note').textContent = `Fahrweg: ${state.config.attribution.basemap}. Haltefolge: ${state.config.attribution.route_reference}.`;
  $('layer-list').replaceChildren(...state.config.layers.map(layer => {
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
  const ids = [];
  if (category === 'lines' || category === 'stations') {
    state.entries.forEach(entry => ids.push(...(category === 'lines'
      ? [entry.ids.shadow, entry.ids.route, entry.ids.lineLabels, entry.ids.hit]
      : [entry.ids.stationHalo, entry.ids.stations, entry.ids.stationLabels])));
  } else {
    ids.push(...state.map.getStyle().layers
      .filter(layer => layer.metadata?.['trainmaps:category'] === category)
      .map(layer => layer.id));
  }
  ids.forEach(id => { if (state.map.getLayer(id)) state.map.setLayoutProperty(id, 'visibility', visible ? 'visible' : 'none'); });
}

function setSelectionStyles() {
  state.entries.forEach(entry => {
    const selected = state.selected?.line.line_id === entry.line.line_id;
    state.map.setPaintProperty(entry.ids.route, 'line-width', ['interpolate', ['linear'], ['zoom'], 7, selected ? 5 : 3.5, 13, selected ? 8 : 6]);
    state.map.setPaintProperty(entry.ids.route, 'line-opacity', state.selected && !selected ? .48 : .96);
    state.map.setPaintProperty(entry.ids.lineLabels, 'text-opacity', state.selected && !selected ? .42 : 1);
    state.map.setPaintProperty(entry.ids.shadow, 'line-opacity', state.selected && !selected ? .45 : .92);
  });
}

function comparisonTitle() {
  const metric = state.metric === 'delay' ? 'Verspätung' : 'Ausfallquote';
  return {
    mean: `Mittlere ${metric}`,
    minimum: `Niedrigste ${metric}`,
    maximum: `Höchste ${metric}`,
    latest: `Letzter Monatswert · ${metric}`,
  }[state.basis];
}

function updateLineColors() {
  const context = comparisonContext();
  state.entries.forEach(entry => {
    const value = entry.line[context.field];
    const color = comparisonColor(value, context);
    entry.currentColor = color;
    if (state.map.getLayer(entry.ids.route)) state.map.setPaintProperty(entry.ids.route, 'line-color', color);
  });
  if (state.selected) $('line-badge').style.background = state.selected.currentColor;
  $('legend-title').textContent = comparisonTitle();
  $('legend-note').textContent = context.items.length < 2
    ? 'Nur eine S-Bahnlinie verfügbar'
    : context.neutral
      ? `${context.items.length} S-Bahnlinien · gleiche Werte`
      : `Spannweite aller ${context.items.length} S-Bahnlinien`;
  $('legend-gradient').style.background = context.neutral
    ? '#718078'
    : 'linear-gradient(90deg, #197a4b 0%, #d8b72c 50%, #eb8a2f 72%, #b7262f 100%)';
  $('legend-min').textContent = formatValue(context.minimum, state.metric);
  $('legend-max').textContent = context.neutral
    ? 'keine Spannweite'
    : formatValue(context.maximum, state.metric);
}

async function selectLine(entry) {
  state.selected = entry;
  setSelectionStyles();
  $('selection-hint').hidden = true;
  $('context-panel').hidden = false;
  $('context-panel').classList.remove('collapsed');
  $('panel-toggle').hidden = false;
  $('panel-toggle').setAttribute('aria-expanded', 'true');
  const shortName = entry.line.display_name.split(' ')[0];
  $('line-badge').hidden = false;
  $('line-badge').textContent = shortName;
  $('line-badge').style.background = entry.currentColor || '#718078';
  $('line-title').textContent = entry.line.display_name;
  $('line-subtitle').textContent = 'Zeitreihe geöffnet';
  $('panel-title').textContent = entry.line.display_name;
  $('summary-value').textContent = '…';
  $('series-chart').replaceChildren();

  let series = state.series.get(entry.line.line_id);
  if (!series) {
    series = await getJson(`/api/v1/map/series?line_id=${encodeURIComponent(entry.line.line_id)}`);
    state.series.set(entry.line.line_id, series);
  }
  const first = series.values[0].month; const last = series.values.at(-1).month;
  $('period-label').textContent = `${monthLabel(first)} bis ${monthLabel(last)} · ${series.values.length} Monate`;
  renderSeries(series);
  const mobile = window.matchMedia('(max-width: 700px)').matches;
  state.map.fitBounds(geometryBounds(entry.geometry), {
    padding: mobile ? {top: 90, right: 35, bottom: 500, left: 35} : {top: 105, right: 80, bottom: 70, left: 525},
    maxZoom: 11,
    duration: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : 500,
  });
  history.replaceState(null, '', `${location.pathname}?line=${encodeURIComponent(entry.line.line_id)}`);
}

function closePanel() {
  state.selected = null;
  setSelectionStyles();
  $('context-panel').hidden = true;
  $('selection-hint').hidden = false;
  $('panel-toggle').hidden = true;
  $('panel-toggle').setAttribute('aria-expanded', 'false');
  $('line-badge').hidden = true;
  $('line-title').textContent = 'Linie auswählen';
  $('line-subtitle').textContent = 'S-Bahn direkt in der Karte anklicken';
  state.map.fitBounds(allBounds(), {padding: {top: 100, right: 80, bottom: 70, left: 80}, maxZoom: 11, duration: 350});
  history.replaceState(null, '', location.pathname);
}

function svgElement(name, attributes = {}, text = null) {
  const element = document.createElementNS(SVG_NS, name);
  Object.entries(attributes).forEach(([key, value]) => element.setAttribute(key, String(value)));
  if (text != null) element.textContent = text;
  return element;
}

function formatValue(value, metric) {
  if (value == null) return 'Keine Daten';
  return `${value.toLocaleString('de-DE', {minimumFractionDigits: 1, maximumFractionDigits: 1})} ${metric === 'delay' ? 'Min.' : '%'}`;
}

function renderSeries(series) {
  const metric = state.metric;
  const field = metric === 'delay' ? 'estimated_delay_minutes' : 'cancellation_percentage';
  const values = series.values.map(item => item[field]);
  const present = values.filter(value => value != null);
  const mean = metric === 'delay'
    ? series.summary.mean_estimated_delay_minutes
    : series.summary.mean_cancellation_percentage;
  const context = comparisonContext();
  const activeValue = state.selected?.line[context.field];
  const chartColor = comparisonColor(activeValue, context);
  const label = metric === 'delay' ? 'Geschätztes Monatsmittel' : 'Ausfallanteil';
  const yMax = metric === 'delay'
    ? Math.max(2, Math.ceil(Math.max(...present) / 2) * 2)
    : Math.max(5, Math.ceil(Math.max(...present) / 5) * 5);

  document.querySelectorAll('.metric-tabs button').forEach(button => {
    const selected = button.dataset.metric === metric;
    button.setAttribute('aria-selected', String(selected));
  });
  document.querySelectorAll('.comparison-card').forEach(button => {
    button.setAttribute('aria-pressed', String(button.dataset.basis === state.basis));
  });
  $('summary-swatch').style.background = chartColor;
  $('summary-label').textContent = metric === 'delay'
    ? `Mittelwert aus ${series.summary.delay_months} Monatswerten`
    : `Mittelwert aus ${series.summary.cancellation_months} Monatswerten`;
  $('summary-value').textContent = formatValue(mean, metric);
  $('minimum-value').textContent = formatValue(Math.min(...present), metric);
  $('maximum-value').textContent = formatValue(Math.max(...present), metric);
  $('latest-value').textContent = formatValue(values.filter(value => value != null).at(-1), metric);
  $('value-definition').textContent = metric === 'delay'
    ? `${series.delay_estimation.description} Ausfälle zählen nicht mit.`
    : 'Monatlicher Anteil der im Quelldatensatz als ausgefallen gezählten Datenpunkte. Die Ausfallquote besitzt eine eigene Grundgesamtheit.';

  const svg = $('series-chart');
  const title = svgElement('title', {id: 'chart-title'}, `${label} von ${series.display_name}`);
  const description = svgElement('desc', {id: 'chart-description'}, `Liniendiagramm mit ${present.length} Monatswerten.`);
  const width = 720; const height = 300;
  const margin = {left: 54, right: 18, top: 20, bottom: 40};
  const chartWidth = width - margin.left - margin.right;
  const chartHeight = height - margin.top - margin.bottom;
  const x = index => margin.left + (index / Math.max(1, values.length - 1)) * chartWidth;
  const y = value => margin.top + chartHeight - (value / yMax) * chartHeight;
  const nodes = [title, description];

  [0, .5, 1].forEach(step => {
    const value = yMax * step; const yPosition = y(value);
    nodes.push(svgElement('line', {x1: margin.left, x2: width - margin.right, y1: yPosition, y2: yPosition, class: 'chart-grid'}));
    nodes.push(svgElement('text', {x: margin.left - 9, y: yPosition + 4, class: 'chart-y-label', 'text-anchor': 'end'}, `${value.toLocaleString('de-DE', {maximumFractionDigits: 1})}${metric === 'cancellations' ? '%' : ''}`));
  });

  const labelIndexes = new Set([0, values.length - 1]);
  series.values.forEach((item, index) => { if (item.month.endsWith('-01')) labelIndexes.add(index); });
  [...labelIndexes].sort((a, b) => a - b).forEach(index => {
    const item = series.values[index];
    nodes.push(svgElement('text', {x: x(index), y: height - 13, class: 'chart-x-label', 'text-anchor': index === 0 ? 'start' : index === values.length - 1 ? 'end' : 'middle'}, item.month.slice(0, 4)));
  });

  let path = ''; let area = '';
  values.forEach((value, index) => {
    if (value == null) return;
    const command = path ? 'L' : 'M';
    path += `${command}${x(index).toFixed(1)},${y(value).toFixed(1)} `;
  });
  const firstIndex = values.findIndex(value => value != null);
  const lastIndex = values.findLastIndex(value => value != null);
  if (path && firstIndex >= 0) area = `${path}L${x(lastIndex)},${y(0)} L${x(firstIndex)},${y(0)} Z`;
  nodes.push(svgElement('path', {d: area, class: 'chart-area', fill: chartColor}));
  nodes.push(svgElement('path', {d: path, class: 'chart-line', stroke: chartColor}));

  values.forEach((value, index) => {
    if (value == null) return;
    const item = series.values[index];
    const point = svgElement('circle', {cx: x(index), cy: y(value), r: 3.5, class: 'chart-point', fill: chartColor, tabindex: 0,
      'aria-label': `${monthLabel(item.month)}: ${formatValue(value, metric)}`});
    point.append(svgElement('title', {}, `${monthLabel(item.month)} · ${formatValue(value, metric)}`));
    const show = event => showChartTooltip(event, item.month, value, metric);
    point.addEventListener('pointerenter', show); point.addEventListener('pointermove', show);
    point.addEventListener('focus', show);
    point.addEventListener('pointerleave', hideChartTooltip); point.addEventListener('blur', hideChartTooltip);
    nodes.push(point);
  });
  svg.replaceChildren(...nodes);
}

function showChartTooltip(event, month, value, metric) {
  const tooltip = $('chart-tooltip'); const card = tooltip.parentElement.getBoundingClientRect();
  const source = event.currentTarget.getBoundingClientRect();
  tooltip.textContent = `${monthLabel(month, true)} · ${formatValue(value, metric)}`;
  tooltip.style.left = `${Math.min(card.width - 135, Math.max(8, source.left - card.left - 52))}px`;
  tooltip.style.top = `${Math.max(6, source.top - card.top - 42)}px`;
  tooltip.hidden = false;
}

function hideChartTooltip() { $('chart-tooltip').hidden = true; }

async function start() {
  state.config = await getJson('/api/v1/map/config');
  if (!state.config.lines.length) throw new Error('Noch keine freigegebene Linie mit Monatsdaten verfügbar.');
  populateLayerControls();
  const [style, geometries] = await Promise.all([
    getJson('/karte/assets/basemap-style.json'),
    Promise.all(state.config.lines.map(line => getJson(`/api/v1/map/lines.geojson?line_id=${encodeURIComponent(line.line_id)}`))),
  ]);
  state.config.lines.forEach((line, index) => state.entries.set(line.line_id, {line, geometry: geometries[index], ids: null}));
  state.map = new MapLibreMap({container: 'map', style, center: [11.58, 48.18], zoom: 9.3, attributionControl: true});
  state.map.addControl(new NavigationControl({showCompass: false}), 'top-right');
  state.map.once('load', () => {
    [...state.entries.values()].forEach(addLine);
    updateLineColors();
    state.map.fitBounds(allBounds(), {padding: {top: 100, right: 80, bottom: 70, left: 80}, maxZoom: 11, duration: 0});
    $('loading').classList.add('ready');
    const requestedLine = new URLSearchParams(location.search).get('line');
    if (requestedLine && state.entries.has(requestedLine)) {
      selectLine(state.entries.get(requestedLine)).catch(showError);
    }
  });
  state.map.on('error', event => { if (event.error) console.warn('Kartenressource:', event.error.message); });
  document.querySelectorAll('.metric-tabs button').forEach(button => button.addEventListener('click', () => {
    state.metric = button.dataset.metric;
    state.basis = 'mean';
    updateLineColors();
    const series = state.selected && state.series.get(state.selected.line.line_id);
    if (series) renderSeries(series);
  }));
  document.querySelectorAll('.comparison-card').forEach(button => button.addEventListener('click', () => {
    state.basis = button.dataset.basis;
    updateLineColors();
    const series = state.selected && state.series.get(state.selected.line.line_id);
    if (series) renderSeries(series);
  }));
  $('panel-close').addEventListener('click', closePanel);
  $('panel-toggle').addEventListener('click', () => {
    const panel = $('context-panel'); const collapsed = panel.classList.toggle('collapsed');
    $('panel-toggle').setAttribute('aria-expanded', String(!collapsed));
  });
}

start().catch(showError);
