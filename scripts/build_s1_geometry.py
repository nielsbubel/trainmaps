"""Build the Munich S1 geometry from basemap.de tracks using MVV GTFS stops."""
from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import io
import json
import math
import urllib.request
import zipfile
from pathlib import Path

import mapbox_vector_tile
import networkx as nx

LINE_ID = "de.muenchen.s1"
ROUTE_NAME = "S1"
BASEMAP_VERSION = "2026-08-18"
BASEMAP_TILE_URL = (
    "https://sgx.geodatenzentrum.de/gdz_basemapde_vektor/tiles/v2/"
    "bm_web_de_3857/{z}/{x}/{y}.pbf"
)
TILE_ZOOM = 14
EXTENT = 4096
TRACK_CLASSES = ("S-Bahn", "Eisenbahn", "Gleis")
STITCH_TOLERANCE_M = 100
STITCH_PENALTY = 8


def rows(bundle, name):
    return csv.DictReader(io.TextIOWrapper(
        bundle.open(name), encoding="utf-8-sig", newline=""))


def haversine(a, b):
    lon1, lat1 = map(math.radians, a)
    lon2, lat2 = map(math.radians, b)
    dlon, dlat = lon2 - lon1, lat2 - lat1
    value = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * 6_371_000 * math.asin(math.sqrt(value))


def tile_number(lon, lat, zoom):
    size = 2 ** zoom
    x = int((lon + 180) / 360 * size)
    y = int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * size)
    return x, y


def tile_transform(tile_x, tile_y, zoom):
    size = 2 ** zoom

    def transform(x, y):
        global_x = tile_x + x / EXTENT
        global_y = tile_y + (EXTENT - y) / EXTENT
        lon = global_x / size * 360 - 180
        lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * global_y / size))))
        return round(lon, 7), round(lat, 7)

    return transform


def load_gtfs_reference(gtfs_path):
    with zipfile.ZipFile(gtfs_path) as bundle:
        route_ids = {row["route_id"] for row in rows(bundle, "routes.txt")
                     if row["route_short_name"].strip().upper() == ROUTE_NAME}
        trips = {row["trip_id"]: row for row in rows(bundle, "trips.txt")
                 if row["route_id"] in route_ids}
        sequences = collections.defaultdict(list)
        used_stops = set()
        for row in rows(bundle, "stop_times.txt"):
            if row["trip_id"] in trips:
                sequences[row["trip_id"]].append((int(row["stop_sequence"]), row["stop_id"]))
                used_stops.add(row["stop_id"])
        all_stops = {row["stop_id"]: row for row in rows(bundle, "stops.txt")}
        stops = {stop_id: all_stops[stop_id] for stop_id in used_stops}

    patterns = collections.Counter(
        tuple(stop_id for _, stop_id in sorted(items)) for items in sequences.values())

    def station_names(pattern):
        return [stops[stop_id]["stop_name"] for stop_id in pattern]

    def best_pattern(first_term):
        matches = [(count, pattern) for pattern, count in patterns.items()
                   if any(first_term in name for name in station_names(pattern))
                   and any("Leuchtenbergring" in name for name in station_names(pattern))
                   and len(pattern) >= 20]
        if not matches:
            raise ValueError(f"No representative S1 pattern found for {first_term}")
        return max(matches, key=lambda item: item[0])[1]

    selected = [best_pattern("Freising"), best_pattern("Flughafen München")]
    # Normalize both patterns to run from their outer terminal towards Leuchtenbergring.
    normalized = []
    for pattern in selected:
        names = station_names(pattern)
        if "Leuchtenbergring" in names[0]:
            pattern = tuple(reversed(pattern))
        normalized.append(pattern)

    selected_ids = {stop_id for pattern in normalized for stop_id in pattern}
    reference_stops = {}
    for stop_id in selected_ids:
        platform = stops[stop_id]
        station_id = platform.get("parent_station") or stop_id
        station = all_stops.get(station_id, platform)
        reference_stops[stop_id] = {
            "stop_id": stop_id,
            "station_id": station_id,
            "name": station["stop_name"],
            "lon": float(platform["stop_lon"]),
            "lat": float(platform["stop_lat"]),
            "station_lon": float(station["stop_lon"]),
            "station_lat": float(station["stop_lat"]),
        }
    return normalized, reference_stops, len(trips), len(patterns)


def download_tracks(stops, cache_dir, zoom=TILE_ZOOM):
    margin = 0.025
    lons = [stop["lon"] for stop in stops.values()]
    lats = [stop["lat"] for stop in stops.values()]
    west, east = min(lons) - margin, max(lons) + margin
    south, north = min(lats) - margin, max(lats) + margin
    min_x, min_y = tile_number(west, north, zoom)
    max_x, max_y = tile_number(east, south, zoom)
    cache_dir.mkdir(parents=True, exist_ok=True)

    lines_by_geometry = {}
    tile_count = 0
    for tile_x in range(min_x, max_x + 1):
        for tile_y in range(min_y, max_y + 1):
            path = cache_dir / f"{zoom}-{tile_x}-{tile_y}.pbf"
            if not path.exists():
                url = BASEMAP_TILE_URL.format(z=zoom, x=tile_x, y=tile_y)
                with urllib.request.urlopen(url, timeout=30) as response:
                    path.write_bytes(response.read())
            tile_count += 1
            decoded = mapbox_vector_tile.decode(
                path.read_bytes(),
                per_layer_options={"Verkehrslinie": {
                    "transformer": tile_transform(tile_x, tile_y, zoom),
                }},
            )
            layer = decoded.get("Verkehrslinie", {"features": []})
            for feature in layer["features"]:
                track_class = feature["properties"].get("klasse")
                if track_class not in TRACK_CLASSES:
                    continue
                geometry = feature["geometry"]
                collections_to_add = ([geometry["coordinates"]]
                                      if geometry["type"] == "LineString"
                                      else geometry["coordinates"])
                for coordinates in collections_to_add:
                    line = tuple((round(float(lon), 7), round(float(lat), 7))
                                 for lon, lat in coordinates)
                    if len(line) < 2:
                        continue
                    canonical = min(line, tuple(reversed(line)))
                    # Prefer the more specific S-Bahn classification when the
                    # same clipped geometry occurs twice.
                    if (canonical not in lines_by_geometry
                            or track_class == "S-Bahn"):
                        lines_by_geometry[canonical] = (line, track_class)
    return list(lines_by_geometry.values()), tile_count, [west, south, east, north]


def build_graph(lines):
    graph = nx.Graph()
    for line, track_class in lines:
        for start, end in zip(line, line[1:]):
            if start != end:
                distance = haversine(start, end)
                factor = {"S-Bahn": 1, "Eisenbahn": 1.03, "Gleis": 1.08}[track_class]
                graph.add_edge(start, end, weight=distance * factor,
                               distance=distance, track_class=track_class)
    # Vector-tile clipping, switches and platform tracks leave short gaps in the
    # otherwise continuous railway graph. The connector penalty makes an actual
    # basemap.de track preferable whenever one exists.
    connect_nearby_nodes(graph, STITCH_TOLERANCE_M)
    return graph


def connect_nearby_nodes(graph, tolerance_m):
    latitude = 48.25
    lon_scale = 111_320 * math.cos(math.radians(latitude))
    lat_scale = 111_320
    cell = tolerance_m
    buckets = collections.defaultdict(list)
    nodes = list(graph.nodes)
    for node in nodes:
        key = (int(node[0] * lon_scale // cell), int(node[1] * lat_scale // cell))
        buckets[key].append(node)
    for node in nodes:
        key = (int(node[0] * lon_scale // cell), int(node[1] * lat_scale // cell))
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for other in buckets.get((key[0] + dx, key[1] + dy), ()):
                    if node >= other or graph.has_edge(node, other):
                        continue
                    distance = haversine(node, other)
                    if distance <= tolerance_m:
                        graph.add_edge(
                            node, other, weight=distance * STITCH_PENALTY,
                            distance=distance, stitched=True,
                        )


def nearest_node(graph, point):
    node = min(graph.nodes, key=lambda candidate: haversine(candidate, point))
    return node, haversine(node, point)


def route_pattern(graph, pattern, stops):
    snapped = []
    for stop_id in pattern:
        stop = stops[stop_id]
        node, distance = nearest_node(graph, (stop["lon"], stop["lat"]))
        snapped.append((stop_id, node, distance))

    route = []
    pairs = []
    for current, following in zip(snapped, snapped[1:]):
        try:
            path = nx.shortest_path(graph, current[1], following[1], weight="weight")
        except nx.NetworkXNoPath as exc:
            raise ValueError(
                f"No basemap S-Bahn path from {stops[current[0]]['name']} "
                f"to {stops[following[0]]['name']}"
            ) from exc
        if route and route[-1] == path[0]:
            route.extend(path[1:])
        else:
            route.extend(path)
        stitched = [graph.edges[a, b]["distance"] for a, b in zip(path, path[1:])
                    if graph.edges[a, b].get("stitched")]
        pairs.append({
            "from": stops[current[0]]["name"], "to": stops[following[0]]["name"],
            "from_snap_m": round(current[2], 1), "to_snap_m": round(following[2], 1),
            "path_m": round(sum(haversine(a, b) for a, b in zip(path, path[1:])), 1),
            "stitched_gaps": len(stitched),
            "stitched_distance_m": round(sum(stitched), 1),
            "max_stitched_gap_m": round(max(stitched, default=0), 1),
        })
    return route, snapped, pairs


def build_geometry(gtfs_path, cache_dir):
    patterns, stops, trip_count, pattern_count = load_gtfs_reference(gtfs_path)
    lines, tile_count, source_bounds = download_tracks(stops, cache_dir)
    graph = build_graph(lines)
    components = sorted(nx.connected_components(graph), key=len, reverse=True)

    routes = []
    snapped_stops = {}
    pair_audit = []
    for pattern in patterns:
        route, snapped, pairs = route_pattern(graph, pattern, stops)
        routes.append([[lon, lat] for lon, lat in route])
        pair_audit.extend(pairs)
        for stop_id, node, distance in snapped:
            item = stops[stop_id]
            station_id = item["station_id"]
            candidate = {
                **item, "matched_lon": node[0], "matched_lat": node[1],
                "snap_distance_m": round(distance, 1),
            }
            if (station_id not in snapped_stops
                    or candidate["snap_distance_m"] < snapped_stops[station_id]["snap_distance_m"]):
                snapped_stops[station_id] = candidate

    max_snap = max(stop["snap_distance_m"] for stop in snapped_stops.values())
    if max_snap > 550:
        raise ValueError(f"Station too far from basemap.de S-Bahn graph: {max_snap} m")
    used_stitches = sum(pair["stitched_gaps"] for pair in pair_audit)
    stitched_distance = sum(pair["stitched_distance_m"] for pair in pair_audit)
    max_stitched_gap = max(pair["max_stitched_gap_m"] for pair in pair_audit)
    features = [{
        "type": "Feature", "id": LINE_ID,
        "properties": {
            "feature_type": "line", "line_id": LINE_ID,
            "display_name": "S1 München", "geometry_status": "mapped",
            "geometry_source": "basemap.de", "geometry_source_version": BASEMAP_VERSION,
            "route_reference": "MVV GTFS 06/2026",
        },
        "geometry": {"type": "MultiLineString", "coordinates": routes},
    }]
    for stop in sorted(snapped_stops.values(), key=lambda item: item["name"]):
        features.append({
            "type": "Feature", "id": "mvv:" + stop["station_id"],
            "properties": {
                "feature_type": "station", "line_id": LINE_ID,
                "name": stop["name"], "snap_distance_m": stop["snap_distance_m"],
            },
            "geometry": {"type": "Point",
                         "coordinates": [stop["station_lon"], stop["station_lat"]]},
        })
    raw = gtfs_path.read_bytes()
    return {
        "type": "FeatureCollection",
        "metadata": {
            "line_id": LINE_ID, "geometry_revision": 1,
            "status": "mapped", "basemap_version": BASEMAP_VERSION,
            "basemap_layer": "Verkehrslinie", "basemap_class": "S-Bahn",
            "basemap_fallback_classes": ["Eisenbahn", "Gleis"],
            "basemap_tile_zoom": TILE_ZOOM, "basemap_tiles": tile_count,
            "basemap_source_bounds": source_bounds,
            "basemap_track_features": len(lines),
            "basemap_track_classes": dict(collections.Counter(kind for _, kind in lines)),
            "graph_nodes": graph.number_of_nodes(),
            "graph_edges": graph.number_of_edges(), "graph_components": len(components),
            "largest_graph_component_nodes": len(components[0]) if components else 0,
            "gtfs_reference": "MVV Gesamt-Soll-Fahrplandaten (GTFS-Feed, 06/2026)",
            "gtfs_sha256": hashlib.sha256(raw).hexdigest(),
            "gtfs_trip_count": trip_count, "gtfs_pattern_count": pattern_count,
            "selected_patterns": len(patterns), "stations": len(snapped_stops),
            "max_station_snap_distance_m": max_snap,
            "stitch_tolerance_m": STITCH_TOLERANCE_M,
            "used_stitched_gaps": used_stitches,
            "stitched_distance_m": round(stitched_distance, 1),
            "max_stitched_gap_m": max_stitched_gap,
            "pair_audit": pair_audit,
        },
        "features": features,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("gtfs", type=Path)
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    collection = build_geometry(args.gtfs, args.cache_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(collection, ensure_ascii=False,
                                      separators=(",", ":")) + "\n", encoding="utf-8")
    metadata = collection["metadata"]
    print(json.dumps({key: metadata[key] for key in (
        "basemap_tiles", "basemap_track_features", "graph_nodes", "graph_edges",
        "graph_components", "stations", "max_station_snap_distance_m")}, ensure_ascii=True))


if __name__ == "__main__":
    main()
