"""Build a reproducible first-pass German S-Bahn map from DELFI and basemap.de.

The source export decides which network/line pairs are relevant.  Current DELFI
GTFS routes provide ordered stations; basemap.de railway features provide the
displayed track geometry.  Only source pairs with at least MIN_MONTHS delay
records and an unambiguous regional GTFS match are emitted.
"""
from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import io
import json
import math
import sys
import time
import zipfile
from pathlib import Path

import networkx as nx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.build_line_candidates import slug
from scripts.build_s1_geometry import (
    BASEMAP_VERSION,
    STITCH_PENALTY,
    download_tracks,
    haversine,
)


MIN_MONTHS = 40
TILE_ZOOM = 13
STITCH_TOLERANCE_M = 260
MAX_STATION_SNAP_M = 3_000
ROUTE_BRIDGE_LIMIT_M = 2_500
MAX_ROUTE_FACTOR = 5.5
MAX_SELECTED_PATTERNS = 5
GTFS_REFERENCE = "DELFI deutschlandweite Sollfahrplandaten (GTFS), Stand 2026-09-30"
GERMANY_TRACK_CLASSES = ("S-Bahn", "Eisenbahn", "Personenverkehr", "Gleis")

# Bounds are deliberately broad.  A route is matched by its station centroid,
# not by requiring every outer terminal to be inside the rectangle.
NETWORKS = {
    "Berlin": {"id": "de.berlin", "bounds": [12.6, 52.15, 14.25, 53.05],
               "agencies": {"98"}},
    "Breisgau": {"id": "de.breisgau", "bounds": [7.25, 47.45, 8.35, 48.35],
                  "agencies": {"4", "21"}, "anchors": ("Freiburg",)},
    "Dresden": {"id": "de.dresden", "bounds": [12.45, 50.55, 14.65, 51.8],
                "agencies": {"304"}, "anchors": ("Dresden",)},
    "Hamburg": {"id": "de.hamburg", "bounds": [9.05, 52.95, 11.45, 54.35],
                "agencies": {"460"}},
    "Mitteldeutschland": {
        "id": "de.mitteldeutschland", "bounds": [11.15, 50.65, 13.85, 52.05],
        "agencies": {"275", "304"}, "anchors": ("Leipzig", "Halle"),
    },
    "Mittelelbe": {"id": "de.mittelelbe", "bounds": [10.65, 51.65, 12.45, 52.65],
                   "agencies": {"304"}, "anchors": ("Magdeburg",)},
    "Nürnberg": {"id": "de.nuernberg", "bounds": [10.15, 48.75, 12.25, 50.25],
                 "agencies": {"73"}, "anchors": ("Nürnberg",)},
    "Rhein-Main": {"id": "de.rhein-main", "bounds": [7.55, 49.35, 9.95, 51.15],
                   "agencies": {"396"}},
    "Rhein-Neckar": {
        "id": "de.rhein-neckar", "bounds": [7.35, 48.45, 9.55, 50.25],
        "agencies": {"368"},
    },
    "Rhein-Ruhr": {"id": "de.rhein-ruhr", "bounds": [5.75, 50.7, 9.05, 52.25],
                   "agencies": {"10"}},
    "Rheinland": {"id": "de.rheinland", "bounds": [5.75, 49.75, 8.15, 51.55],
                  "agencies": {"10"}},
    "Rostock": {"id": "de.rostock", "bounds": [11.35, 53.55, 13.2, 54.75],
                "agencies": {"436"}, "anchors": ("Rostock",)},
    "Stuttgart": {"id": "de.stuttgart", "bounds": [8.15, 48.15, 10.25, 49.45],
                  "agencies": {"317"}},
}


def gtfs_rows(bundle, name):
    return csv.DictReader(io.TextIOWrapper(
        bundle.open(name), encoding="utf-8-sig", errors="replace", newline=""
    ))


def eligible_source_pairs(candidate_path):
    data = json.loads(candidate_path.read_text(encoding="utf-8"))
    pairs = []
    for item in data["candidates"]:
        alias = item["source_alias"]
        if (item["classification"] == "explicit_s_bahn"
                and alias["netz"] in NETWORKS
                and item["source_rows"].get("delaysByNetworkLineMonth", 0) >= MIN_MONTHS):
            pairs.append({
                "network": alias["netz"],
                "line": alias["line"].upper(),
                "months": item["source_rows"]["delaysByNetworkLineMonth"],
                "first_month": item["first_month"],
                "last_month": item["last_month"],
            })
    return pairs


def normalize_pattern(pattern, stops):
    station_ids = []
    for stop_id in pattern:
        station_id = stops[stop_id]["station_id"]
        if not station_ids or station_ids[-1] != station_id:
            station_ids.append(station_id)
    forward = tuple(station_ids)
    reverse = tuple(reversed(station_ids))
    return min(forward, reverse)


def build_inventory(gtfs_path, candidate_path, inventory_path):
    """Read the 2.3 GB stop_times file once and cache compact route patterns."""
    source_pairs = eligible_source_pairs(candidate_path)
    wanted_refs = {item["line"] for item in source_pairs}
    started = time.time()
    print(f"GTFS inventory: {len(source_pairs)} source pairs, {len(wanted_refs)} line labels",
          flush=True)
    with zipfile.ZipFile(gtfs_path) as bundle:
        agencies = {row["agency_id"]: row["agency_name"]
                    for row in gtfs_rows(bundle, "agency.txt")}
        routes = {}
        for row in gtfs_rows(bundle, "routes.txt"):
            short_name = row["route_short_name"].strip().upper()
            if short_name in wanted_refs and row.get("route_type") in {"2", "109"}:
                routes[row["route_id"]] = {
                    "route_id": row["route_id"],
                    "line": short_name,
                    "agency_id": row["agency_id"],
                    "agency_name": agencies.get(row["agency_id"], ""),
                }
        trips = {}
        for row in gtfs_rows(bundle, "trips.txt"):
            if row["route_id"] in routes:
                trips[row["trip_id"]] = row["route_id"]
        print(f"GTFS inventory: {len(routes)} route records, {len(trips)} trips", flush=True)

        route_patterns = collections.defaultdict(collections.Counter)
        used_stop_ids = set()
        current_trip = None
        current_route = None
        current_pattern = []
        row_count = 0

        def finish_trip():
            if current_route and len(current_pattern) >= 2:
                route_patterns[current_route][tuple(current_pattern)] += 1

        for row in gtfs_rows(bundle, "stop_times.txt"):
            row_count += 1
            trip_id = row["trip_id"]
            if trip_id != current_trip:
                finish_trip()
                current_trip = trip_id
                current_route = trips.get(trip_id)
                current_pattern = []
            if current_route:
                stop_id = row["stop_id"]
                current_pattern.append(stop_id)
                used_stop_ids.add(stop_id)
            if row_count % 10_000_000 == 0:
                print(f"GTFS inventory: {row_count:,} stop-time rows", flush=True)
        finish_trip()

        raw_stops = {}
        parent_ids = set()
        for row in gtfs_rows(bundle, "stops.txt"):
            if row["stop_id"] in used_stop_ids:
                raw_stops[row["stop_id"]] = row
                if row.get("parent_station"):
                    parent_ids.add(row["parent_station"])
        parents = {}
        if parent_ids:
            for row in gtfs_rows(bundle, "stops.txt"):
                if row["stop_id"] in parent_ids:
                    parents[row["stop_id"]] = row

    stops = {}
    for stop_id, platform in raw_stops.items():
        station_id = platform.get("parent_station") or stop_id
        station = parents.get(station_id, platform)
        stops[stop_id] = {
            "station_id": station_id,
            "name": station["stop_name"],
            "lon": float(platform["stop_lon"]),
            "lat": float(platform["stop_lat"]),
            "station_lon": float(station["stop_lon"]),
            "station_lat": float(station["stop_lat"]),
        }

    stations = {}
    inventory_routes = {}
    for route_id, route in routes.items():
        normalized = collections.Counter()
        for pattern, count in route_patterns[route_id].items():
            normalized[normalize_pattern(pattern, stops)] += count
        station_ids = {station_id for pattern in normalized for station_id in pattern}
        for stop in stops.values():
            if stop["station_id"] in station_ids and stop["station_id"] not in stations:
                stations[stop["station_id"]] = {
                    key: stop[key] for key in ("name", "station_lon", "station_lat")
                }
        coords = [(stations[item]["station_lon"], stations[item]["station_lat"])
                  for item in station_ids]
        if not coords:
            continue
        inventory_routes[route_id] = {
            **route,
            "trip_count": sum(normalized.values()),
            "centroid": [sum(item[0] for item in coords) / len(coords),
                         sum(item[1] for item in coords) / len(coords)],
            "bounds": [min(item[0] for item in coords), min(item[1] for item in coords),
                       max(item[0] for item in coords), max(item[1] for item in coords)],
            "patterns": [{"count": count, "stations": list(pattern)}
                         for pattern, count in normalized.most_common()],
        }

    payload = {
        "format": "trainmaps-delfi-route-inventory-1",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "gtfs_sha256": hashlib.sha256(gtfs_path.read_bytes()).hexdigest(),
        "source_pairs": source_pairs,
        "routes": inventory_routes,
        "stations": stations,
    }
    inventory_path.parent.mkdir(parents=True, exist_ok=True)
    inventory_path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n",
                              encoding="utf-8")
    print(f"GTFS inventory: cached {len(inventory_routes)} routes and {len(stations)} stations "
          f"in {time.time() - started:.1f}s", flush=True)
    return payload


def inside(point, bounds):
    lon, lat = point
    west, south, east, north = bounds
    return west <= lon <= east and south <= lat <= north


def select_patterns(routes, stations, anchors=()):
    candidates = collections.Counter()
    route_ids = []
    total_trips = 0
    for route in routes:
        minimum = max(2, math.ceil(route["trip_count"] * 0.002))
        contributed = False
        for item in route["patterns"]:
            pattern = tuple(item["stations"])
            if len(pattern) < 2 or item["count"] < minimum:
                continue
            if anchors and not any(
                    anchor in stations[station_id]["name"].casefold()
                    for station_id in pattern for anchor in anchors):
                continue
            candidates[pattern] += item["count"]
            total_trips += item["count"]
            contributed = True
        if contributed:
            route_ids.append(route["route_id"])
    if not candidates:
        return [], route_ids, total_trips

    selected = []
    covered_edges = set()
    remaining = dict(candidates)
    while remaining and len(selected) < MAX_SELECTED_PATTERNS:
        scored = []
        for pattern, count in remaining.items():
            edges = {frozenset(pair) for pair in zip(pattern, pattern[1:])}
            new_edges = edges - covered_edges
            scored.append((len(new_edges), len(pattern), count, pattern, edges))
        new_count, _, _, pattern, edges = max(scored)
        if selected and new_count < 2:
            break
        selected.append(pattern)
        covered_edges.update(edges)
        remaining.pop(pattern)
    return selected, route_ids, total_trips


def match_lines(inventory):
    routes_by_line = collections.defaultdict(list)
    for route in inventory["routes"].values():
        routes_by_line[route["line"]].append(route)
    matched = []
    skipped = []
    for source in inventory["source_pairs"]:
        network = NETWORKS[source["network"]]
        anchors = tuple(value.casefold() for value in network.get("anchors", ()))

        def regional_match(route):
            if route["agency_id"] not in network["agencies"]:
                return False
            if not anchors:
                return inside(route["centroid"], network["bounds"])
            names = (inventory["stations"][station_id]["name"].casefold()
                     for pattern in route["patterns"] for station_id in pattern["stations"])
            return any(anchor in name for name in names for anchor in anchors)

        candidates = [route for route in routes_by_line[source["line"]]
                      if regional_match(route)]
        patterns, route_ids, trip_count = select_patterns(
            candidates, inventory["stations"], anchors
        )
        if not patterns:
            skipped.append({**source, "reason": "no_current_regional_gtfs_route"})
            continue
        identifier = f"{network['id']}.{slug(source['line'])}"
        matched.append({
            **source,
            "network_id": network["id"],
            "line_id": identifier,
            "display_name": f"{source['line']} {source['network']}",
            "route_ids": route_ids,
            "trip_count": trip_count,
            "patterns": patterns,
        })
    return matched, skipped


def connect_graph(graph, tolerance_m, latitude):
    lon_scale = 111_320 * math.cos(math.radians(latitude))
    lat_scale = 111_320
    buckets = collections.defaultdict(list)
    for node in graph.nodes:
        buckets[(int(node[0] * lon_scale // tolerance_m),
                 int(node[1] * lat_scale // tolerance_m))].append(node)
    added = 0
    for node in list(graph.nodes):
        key = (int(node[0] * lon_scale // tolerance_m),
               int(node[1] * lat_scale // tolerance_m))
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for other in buckets.get((key[0] + dx, key[1] + dy), ()):
                    if node >= other or graph.has_edge(node, other):
                        continue
                    distance = haversine(node, other)
                    if distance <= tolerance_m:
                        graph.add_edge(node, other, weight=distance * STITCH_PENALTY,
                                       distance=distance, stitched=True)
                        added += 1
    return added


def build_graph(lines):
    graph = nx.Graph()
    for coordinates, track_class in lines:
        factor = {
            "S-Bahn": 1,
            "Eisenbahn": 1.03,
            "Personenverkehr": 1.04,
            "Gleis": 1.08,
        }[track_class]
        for start, end in zip(coordinates, coordinates[1:]):
            if start != end:
                distance = haversine(start, end)
                graph.add_edge(start, end, weight=distance * factor,
                               distance=distance, track_class=track_class)
    return graph


class NodeIndex:
    def __init__(self, graph, latitude, cell_m=500):
        self.nodes = list(graph.nodes)
        self.lon_scale = 111_320 * math.cos(math.radians(latitude))
        self.lat_scale = 111_320
        self.cell = cell_m
        self.buckets = collections.defaultdict(list)
        for node in self.nodes:
            self.buckets[self.key(node)].append(node)

    def key(self, point):
        return (int(point[0] * self.lon_scale // self.cell),
                int(point[1] * self.lat_scale // self.cell))

    def nearest(self, point):
        key = self.key(point)
        candidates = []
        for radius in range(0, 5):
            for dx in range(-radius, radius + 1):
                for dy in range(-radius, radius + 1):
                    if radius and abs(dx) != radius and abs(dy) != radius:
                        continue
                    candidates.extend(self.buckets.get((key[0] + dx, key[1] + dy), ()))
            if candidates:
                break
        if not candidates:
            candidates = self.nodes
        node = min(candidates, key=lambda candidate: haversine(candidate, point))
        return node, haversine(node, point)


def bridge_route_components(graph, start, end):
    """Bridge a bounded basemap graph gap between two consecutive stations."""
    first_component = nx.node_connected_component(graph, start)
    if end in first_component:
        return None
    second_component = nx.node_connected_component(graph, end)
    if len(first_component) > len(second_component):
        first_component, second_component = second_component, first_component
    latitude = (start[1] + end[1]) / 2
    lon_scale = 111_320 * math.cos(math.radians(latitude))
    lat_scale = 111_320
    cell = 500
    buckets = collections.defaultdict(list)
    for node in second_component:
        buckets[(int(node[0] * lon_scale // cell),
                 int(node[1] * lat_scale // cell))].append(node)
    radius = math.ceil(ROUTE_BRIDGE_LIMIT_M / cell)
    best = None
    for node in first_component:
        key = (int(node[0] * lon_scale // cell), int(node[1] * lat_scale // cell))
        for dx in range(-radius, radius + 1):
            for dy in range(-radius, radius + 1):
                for other in buckets.get((key[0] + dx, key[1] + dy), ()):
                    distance = haversine(node, other)
                    if best is None or distance < best[0]:
                        best = (distance, node, other)
    if best is None or best[0] > ROUTE_BRIDGE_LIMIT_M:
        nearest = None if best is None else round(best[0], 1)
        raise ValueError(f"no_route_bridge_within_{ROUTE_BRIDGE_LIMIT_M}m:{nearest}")
    distance, first, second = best
    graph.add_edge(first, second, weight=distance * STITCH_PENALTY,
                   distance=distance, stitched=True, route_bridge=True)
    return round(distance, 1)


def route_pattern(graph, node_index, pattern, stations):
    snapped = []
    for station_id in pattern:
        station = stations[station_id]
        point = (station["station_lon"], station["station_lat"])
        node, distance = node_index.nearest(point)
        if distance > MAX_STATION_SNAP_M:
            raise ValueError(f"station_snap_too_far:{station['name']}:{distance:.1f}")
        snapped.append((station_id, node, distance))

    coordinates = []
    pair_audit = []
    for current, following in zip(snapped, snapped[1:]):
        direct = haversine(current[1], following[1])
        route_bridge = None
        if not nx.has_path(graph, current[1], following[1]):
            try:
                route_bridge = bridge_route_components(graph, current[1], following[1])
            except ValueError as exc:
                raise ValueError(
                    f"bridge_failed:{stations[current[0]]['name']}:"
                    f"{stations[following[0]]['name']}:{exc}"
                ) from exc
        distance, path = nx.bidirectional_dijkstra(
            graph, current[1], following[1], weight="weight"
        )
        geographic_distance = sum(haversine(a, b) for a, b in zip(path, path[1:]))
        if geographic_distance > direct * MAX_ROUTE_FACTOR + 8_000:
            raise ValueError(
                f"implausible_path:{stations[current[0]]['name']}:"
                f"{stations[following[0]]['name']}:path={geographic_distance:.1f}:"
                f"direct={direct:.1f}"
            )
        coordinates.extend(path[1:] if coordinates and coordinates[-1] == path[0] else path)
        stitched = [graph.edges[a, b]["distance"] for a, b in zip(path, path[1:])
                    if graph.edges[a, b].get("stitched")]
        pair_audit.append({
            "from": stations[current[0]]["name"],
            "to": stations[following[0]]["name"],
            "from_snap_m": round(current[2], 1),
            "to_snap_m": round(following[2], 1),
            "path_m": round(geographic_distance, 1),
            "stitched_gaps": len(stitched),
            "max_stitched_gap_m": round(max(stitched, default=0), 1),
            "route_bridge_m": route_bridge,
        })
    return coordinates, snapped, pair_audit


def build_collection(line, stations, graph, node_index, source, gtfs_sha):
    routes = []
    snapped_stations = {}
    audits = []
    for pattern in line["patterns"]:
        coordinates, snapped, pair_audit = route_pattern(
            graph, node_index, pattern, stations
        )
        routes.append([[lon, lat] for lon, lat in coordinates])
        audits.extend(pair_audit)
        for station_id, node, distance in snapped:
            item = stations[station_id]
            snapped_stations[station_id] = {
                **item,
                "matched_lon": node[0],
                "matched_lat": node[1],
                "snap_distance_m": round(distance, 1),
            }
    max_snap = max(item["snap_distance_m"] for item in snapped_stations.values())
    max_gap = max((item["max_stitched_gap_m"] for item in audits), default=0)
    features = [{
        "type": "Feature",
        "id": line["line_id"],
        "properties": {
            "feature_type": "line",
            "line_id": line["line_id"],
            "display_name": line["display_name"],
            "geometry_status": "mapped",
            "geometry_source": "basemap.de",
            "geometry_source_version": BASEMAP_VERSION,
            "route_reference": GTFS_REFERENCE,
        },
        "geometry": {"type": "MultiLineString", "coordinates": routes},
    }]
    for station_id, item in sorted(snapped_stations.items(), key=lambda pair: pair[1]["name"]):
        features.append({
            "type": "Feature",
            "id": f"delfi:{station_id}",
            "properties": {
                "feature_type": "station",
                "line_id": line["line_id"],
                "name": item["name"],
                "snap_distance_m": item["snap_distance_m"],
            },
            "geometry": {"type": "Point",
                         "coordinates": [item["station_lon"], item["station_lat"]]},
        })
    return {
        "type": "FeatureCollection",
        "metadata": {
            "line_id": line["line_id"],
            "geometry_revision": 1,
            "status": "mapped",
            "basemap_version": BASEMAP_VERSION,
            "basemap_layer": "Verkehrslinie",
            "basemap_class": "S-Bahn",
            "basemap_fallback_classes": ["Eisenbahn", "Personenverkehr", "Gleis"],
            "basemap_tile_zoom": TILE_ZOOM,
            "basemap_tiles": source["tile_count"],
            "basemap_source_bounds": source["bounds"],
            "basemap_track_features": source["track_features"],
            "basemap_track_classes": source["track_classes"],
            "graph_nodes": graph.number_of_nodes(),
            "graph_edges": graph.number_of_edges(),
            "gtfs_reference": GTFS_REFERENCE,
            "gtfs_sha256": gtfs_sha,
            "gtfs_route_ids": line["route_ids"],
            "gtfs_trip_count": line["trip_count"],
            "selected_patterns": len(line["patterns"]),
            "stations": len(snapped_stations),
            "max_station_snap_distance_m": max_snap,
            "max_station_snap_limit_m": MAX_STATION_SNAP_M,
            "stitch_tolerance_m": STITCH_TOLERANCE_M,
            "route_bridge_limit_m": ROUTE_BRIDGE_LIMIT_M,
            "max_stitched_gap_m": max_gap,
            "pair_audit": audits,
        },
        "features": features,
    }


def catalog_record(line):
    return {
        "line_id": line["line_id"],
        "revision": 1,
        "network_id": line["network_id"],
        "display_name": line["display_name"],
        "source_aliases": [{"netz": line["network"], "line": line["line"]}],
        "geometry": {
            "source": "basemap.de",
            "source_layer": "Verkehrslinie",
            "source_class": "S-Bahn",
            "fallback_classes": ["Eisenbahn", "Personenverkehr", "Gleis"],
            "status": "verified",
            "reference": f"trainmaps:geometry:{line['line_id']}@1",
            "version": f"basemap.de {BASEMAP_VERSION} / DELFI GTFS 2026-09-30",
        },
        "active": True,
        "notes": "Automatischer erster Durchlauf; Fahrweg technisch gegen Stationen geprüft.",
    }


def build_all(inventory, cache_dir, output_dir, report_path, catalog_path, only_networks=None):
    matched, skipped = match_lines(inventory)
    if only_networks:
        matched = [item for item in matched if item["network"] in only_networks]
    stations = inventory["stations"]
    output_dir.mkdir(parents=True, exist_ok=True)
    successful = []
    failed = []
    grouped = collections.defaultdict(list)
    for line in matched:
        grouped[line["network"]].append(line)
    for network_name, lines_for_network in sorted(grouped.items()):
        started = time.time()
        used_station_ids = {station_id for line in lines_for_network
                            for pattern in line["patterns"] for station_id in pattern}
        network_stops = {
            station_id: {
                "lon": stations[station_id]["station_lon"],
                "lat": stations[station_id]["station_lat"],
            }
            for station_id in used_station_ids
        }
        print(f"{network_name}: loading basemap for {len(lines_for_network)} lines / "
              f"{len(network_stops)} stations", flush=True)
        tracks, tile_count, bounds = download_tracks(
            network_stops, cache_dir / slug(network_name), zoom=TILE_ZOOM,
            track_classes=GERMANY_TRACK_CLASSES,
        )
        graph = build_graph(tracks)
        latitude = sum(item["lat"] for item in network_stops.values()) / len(network_stops)
        connectors = connect_graph(graph, STITCH_TOLERANCE_M, latitude)
        node_index = NodeIndex(graph, latitude)
        source = {
            "tile_count": tile_count,
            "bounds": bounds,
            "track_features": len(tracks),
            "track_classes": dict(collections.Counter(kind for _, kind in tracks)),
        }
        print(f"{network_name}: graph {graph.number_of_nodes():,} nodes, "
              f"{graph.number_of_edges():,} edges, {connectors:,} connectors", flush=True)
        for line in sorted(lines_for_network, key=lambda item: item["line_id"]):
            try:
                collection = build_collection(
                    line, stations, graph, node_index, source, inventory["gtfs_sha256"]
                )
                target = output_dir / f"{line['line_id']}.geojson"
                target.write_text(json.dumps(collection, ensure_ascii=False,
                                             separators=(",", ":")) + "\n", encoding="utf-8")
                successful.append({
                    **{key: line[key] for key in (
                        "network", "line", "line_id", "display_name", "months",
                        "route_ids", "trip_count",
                    )},
                    "patterns": len(line["patterns"]),
                    "stations": collection["metadata"]["stations"],
                    "max_station_snap_distance_m": collection["metadata"][
                        "max_station_snap_distance_m"
                    ],
                })
                print(f"  OK {line['display_name']}: "
                      f"{collection['metadata']['stations']} stations", flush=True)
            except Exception as exc:  # A failed line must not block other networks.
                failed.append({
                    **{key: line[key] for key in (
                        "network", "line", "line_id", "display_name", "months", "route_ids",
                    )},
                    "reason": str(exc),
                })
                print(f"  FAIL {line['display_name']}: {exc}", flush=True)
        print(f"{network_name}: completed in {time.time() - started:.1f}s", flush=True)

    success_ids = {item["line_id"] for item in successful}
    catalog = [catalog_record(line) for line in matched if line["line_id"] in success_ids]
    catalog_path.parent.mkdir(parents=True, exist_ok=True)
    catalog_path.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")
    report = {
        "format": "trainmaps-germany-first-pass-1",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "rules": {
            "minimum_delay_months": MIN_MONTHS,
            "current_route_source": GTFS_REFERENCE,
            "geometry_source": f"basemap.de {BASEMAP_VERSION}",
            "maximum_station_snap_m": MAX_STATION_SNAP_M,
        },
        "summary": {
            "eligible_source_pairs": len(inventory["source_pairs"]),
            "current_regional_matches": len(matched),
            "published": len(successful),
            "geometry_failures": len(failed),
            "without_current_match": len(skipped),
        },
        "published": successful,
        "geometry_failures": failed,
        "without_current_match": skipped,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False), flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("gtfs", type=Path)
    parser.add_argument("--candidates", type=Path, default=Path("docs/line-candidates.json"))
    parser.add_argument("--inventory", type=Path,
                        default=Path(".local/sources/delfi-sbahn-inventory.json"))
    parser.add_argument("--cache-dir", type=Path,
                        default=Path(".local/sources/basemap-germany-z13"))
    parser.add_argument("--output-dir", type=Path,
                        default=Path("trainmaps_api/map_data"))
    parser.add_argument("--report", type=Path,
                        default=Path("docs/germany-first-pass-report.json"))
    parser.add_argument("--catalog", type=Path,
                        default=Path("examples/line-references-germany.json"))
    parser.add_argument("--rebuild-inventory", action="store_true")
    parser.add_argument("--inventory-only", action="store_true")
    parser.add_argument("--networks", nargs="*", choices=tuple(NETWORKS))
    args = parser.parse_args()

    if args.rebuild_inventory or not args.inventory.exists():
        inventory = build_inventory(args.gtfs, args.candidates, args.inventory)
    else:
        inventory = json.loads(args.inventory.read_text(encoding="utf-8"))
        print(f"GTFS inventory: using cache {args.inventory}", flush=True)
    if args.inventory_only:
        matched, skipped = match_lines(inventory)
        print(json.dumps({"matched": len(matched), "skipped": len(skipped)},
                         ensure_ascii=False), flush=True)
        return
    build_all(inventory, args.cache_dir, args.output_dir, args.report, args.catalog,
              set(args.networks) if args.networks else None)


if __name__ == "__main__":
    main()
