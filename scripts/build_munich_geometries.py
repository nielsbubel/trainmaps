"""Build all current Munich S-Bahn geometries from basemap.de and MVV GTFS."""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import math
import sys
import zipfile
from pathlib import Path

import networkx as nx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.build_s1_geometry import (
    BASEMAP_VERSION,
    STITCH_PENALTY,
    build_graph,
    connect_nearby_nodes,
    download_tracks,
    haversine,
    nearest_node,
    rows,
)


STITCH_TOLERANCE_M = 250
ROUTE_BRIDGE_LIMIT_M = 1_000
MAX_STATION_SNAP_M = 600


ROUTE_BRANCHES = {
    "S1": (("Freising", "Leuchtenbergring"),
           ("Flughafen München", "Leuchtenbergring")),
    "S2": (("Petershausen", "Erding"),
           ("Altomünster", "Erding")),
    "S3": (("Mammendorf", "Holzkirchen"),),
    "S4": (("Geltendorf", "Zorneding"),),
    "S5": (("Weßling", "Kreuzstraße"),),
    "S6": (("Tutzing", "Ebersberg"),),
    "S7": (("Wolfratshausen", "München Hbf"),),
    "S8": (("Herrsching", "Flughafen München"),),
    "S20": (("Geltendorf", "Höllriegelskreuth"),),
}


def line_id(route_name):
    return f"de.muenchen.{route_name.lower()}"


def load_gtfs_reference(gtfs_path, route_names):
    route_names = set(route_names)
    with zipfile.ZipFile(gtfs_path) as bundle:
        route_lookup = {
            row["route_id"]: row["route_short_name"].strip().upper()
            for row in rows(bundle, "routes.txt")
            if row["route_short_name"].strip().upper() in route_names
            and row.get("route_type") == "0"
        }
        trips = {
            row["trip_id"]: route_lookup[row["route_id"]]
            for row in rows(bundle, "trips.txt")
            if row["route_id"] in route_lookup
        }
        sequences = collections.defaultdict(list)
        used_stop_ids = set()
        for row in rows(bundle, "stop_times.txt"):
            route_name = trips.get(row["trip_id"])
            if route_name:
                sequences[row["trip_id"]].append(
                    (int(row["stop_sequence"]), row["stop_id"])
                )
                used_stop_ids.add(row["stop_id"])
        all_stops = {row["stop_id"]: row for row in rows(bundle, "stops.txt")}

    stops = {}
    for stop_id in used_stop_ids:
        platform = all_stops[stop_id]
        station_id = platform.get("parent_station") or stop_id
        station = all_stops.get(station_id, platform)
        stops[stop_id] = {
            "stop_id": stop_id,
            "station_id": station_id,
            "name": station["stop_name"],
            "lon": float(platform["stop_lon"]),
            "lat": float(platform["stop_lat"]),
            "station_lon": float(station["stop_lon"]),
            "station_lat": float(station["stop_lat"]),
        }

    result = {}
    for route_name in route_names:
        patterns = collections.Counter(
            tuple(stop_id for _, stop_id in sorted(sequences[trip_id]))
            for trip_id, trip_route in trips.items()
            if trip_route == route_name
        )
        selected = []
        for first_term, second_term in ROUTE_BRANCHES[route_name]:
            matches = []
            for pattern, count in patterns.items():
                names = [stops[stop_id]["name"] for stop_id in pattern]
                endpoints = (names[0], names[-1])
                if ((first_term in endpoints[0] and second_term in endpoints[1])
                        or (second_term in endpoints[0] and first_term in endpoints[1])):
                    matches.append((len(pattern), count, pattern))
            if not matches:
                raise ValueError(
                    f"No {route_name} pattern found between {first_term} and {second_term}"
                )
            pattern = max(matches, key=lambda item: (item[0], item[1]))[2]
            if stops[pattern[0]]["name"].find(first_term) < 0:
                pattern = tuple(reversed(pattern))
            selected.append(pattern)
        result[route_name] = {
            "patterns": selected,
            "trip_count": sum(patterns.values()),
            "pattern_count": len(patterns),
        }
    return result, stops


def bridge_route_components(graph, start, end):
    """Bridge one audited source gap between consecutive GTFS stations."""
    start_component = nx.node_connected_component(graph, start)
    if end in start_component:
        return None
    end_component = nx.node_connected_component(graph, end)
    west, east = sorted((start[0], end[0]))
    south, north = sorted((start[1], end[1]))
    margin = 0.025
    first = [node for node in start_component
             if west - margin <= node[0] <= east + margin
             and south - margin <= node[1] <= north + margin]
    second = [node for node in end_component
              if west - margin <= node[0] <= east + margin
              and south - margin <= node[1] <= north + margin]
    if not first or not second:
        first, second = list(start_component), list(end_component)
    if len(first) > len(second):
        first, second = second, first

    latitude = (start[1] + end[1]) / 2
    lon_scale = 111_320 * math.cos(math.radians(latitude))
    lat_scale = 111_320
    cell = 250
    buckets = collections.defaultdict(list)
    for node in second:
        buckets[(int(node[0] * lon_scale // cell),
                 int(node[1] * lat_scale // cell))].append(node)
    radius = math.ceil(ROUTE_BRIDGE_LIMIT_M / cell)
    best = None
    for node in first:
        key = (int(node[0] * lon_scale // cell), int(node[1] * lat_scale // cell))
        for dx in range(-radius, radius + 1):
            for dy in range(-radius, radius + 1):
                for other in buckets.get((key[0] + dx, key[1] + dy), ()):
                    distance = haversine(node, other)
                    if best is None or distance < best[0]:
                        best = (distance, node, other)
    if best is None or best[0] > ROUTE_BRIDGE_LIMIT_M:
        distance = None if best is None else round(best[0], 1)
        raise ValueError(f"No route bridge within {ROUTE_BRIDGE_LIMIT_M} m; nearest={distance}")
    distance, first_node, second_node = best
    graph.add_edge(first_node, second_node, weight=distance * STITCH_PENALTY,
                   distance=distance, stitched=True, route_bridge=True)
    return round(distance, 1)


def route_pattern(graph, pattern, stops):
    snapped = []
    for stop_id in pattern:
        stop = stops[stop_id]
        node, distance = nearest_node(graph, (stop["lon"], stop["lat"]))
        snapped.append((stop_id, node, distance))

    route = []
    pairs = []
    for current, following in zip(snapped, snapped[1:]):
        route_bridge = None
        if not nx.has_path(graph, current[1], following[1]):
            try:
                route_bridge = bridge_route_components(graph, current[1], following[1])
            except ValueError as exc:
                raise ValueError(
                    f"No basemap path from {stops[current[0]]['name']} "
                    f"to {stops[following[0]]['name']}: {exc}"
                ) from exc
        try:
            path = nx.shortest_path(graph, current[1], following[1], weight="weight")
        except nx.NetworkXNoPath as exc:
            raise ValueError(
                f"No basemap path from {stops[current[0]]['name']} "
                f"to {stops[following[0]]['name']}"
            ) from exc
        route.extend(path[1:] if route and route[-1] == path[0] else path)
        stitched = [graph.edges[a, b]["distance"] for a, b in zip(path, path[1:])
                    if graph.edges[a, b].get("stitched")]
        pairs.append({
            "from": stops[current[0]]["name"],
            "to": stops[following[0]]["name"],
            "from_snap_m": round(current[2], 1),
            "to_snap_m": round(following[2], 1),
            "path_m": round(sum(haversine(a, b) for a, b in zip(path, path[1:])), 1),
            "stitched_gaps": len(stitched),
            "stitched_distance_m": round(sum(stitched), 1),
            "max_stitched_gap_m": round(max(stitched, default=0), 1),
            "route_bridge_m": route_bridge,
        })
    return route, snapped, pairs


def build_collection(route_name, reference, stops, graph, source, gtfs_bytes):
    routes = []
    snapped_stops = {}
    pair_audit = []
    for pattern in reference["patterns"]:
        route, snapped, pairs = route_pattern(graph, pattern, stops)
        routes.append([[lon, lat] for lon, lat in route])
        pair_audit.extend(pairs)
        for stop_id, node, distance in snapped:
            item = stops[stop_id]
            station_id = item["station_id"]
            candidate = {
                **item,
                "matched_lon": node[0],
                "matched_lat": node[1],
                "snap_distance_m": round(distance, 1),
            }
            if (station_id not in snapped_stops
                    or candidate["snap_distance_m"]
                    < snapped_stops[station_id]["snap_distance_m"]):
                snapped_stops[station_id] = candidate

    max_snap = max(stop["snap_distance_m"] for stop in snapped_stops.values())
    if max_snap > MAX_STATION_SNAP_M:
        raise ValueError(f"{route_name}: station too far from basemap graph: {max_snap} m")
    max_stitched_gap = max(pair["max_stitched_gap_m"] for pair in pair_audit)
    if max_stitched_gap > ROUTE_BRIDGE_LIMIT_M:
        raise ValueError(f"{route_name}: stitched gap exceeds limit: {max_stitched_gap} m")

    identifier = line_id(route_name)
    display_name = f"{route_name} München"
    features = [{
        "type": "Feature",
        "id": identifier,
        "properties": {
            "feature_type": "line",
            "line_id": identifier,
            "display_name": display_name,
            "geometry_status": "mapped",
            "geometry_source": "basemap.de",
            "geometry_source_version": BASEMAP_VERSION,
            "route_reference": "MVV GTFS 06/2026",
        },
        "geometry": {"type": "MultiLineString", "coordinates": routes},
    }]
    for stop in sorted(snapped_stops.values(), key=lambda item: item["name"]):
        features.append({
            "type": "Feature",
            "id": "mvv:" + stop["station_id"],
            "properties": {
                "feature_type": "station",
                "line_id": identifier,
                "name": stop["name"],
                "snap_distance_m": stop["snap_distance_m"],
            },
            "geometry": {
                "type": "Point",
                "coordinates": [stop["station_lon"], stop["station_lat"]],
            },
        })

    used_stitches = sum(pair["stitched_gaps"] for pair in pair_audit)
    stitched_distance = sum(pair["stitched_distance_m"] for pair in pair_audit)
    return {
        "type": "FeatureCollection",
        "metadata": {
            "line_id": identifier,
            "geometry_revision": 1,
            "status": "mapped",
            "basemap_version": BASEMAP_VERSION,
            "basemap_layer": "Verkehrslinie",
            "basemap_class": "S-Bahn",
            "basemap_fallback_classes": ["Eisenbahn", "Gleis"],
            "basemap_tile_zoom": source["zoom"],
            "basemap_tiles": source["tile_count"],
            "basemap_source_bounds": source["bounds"],
            "basemap_track_features": source["track_features"],
            "basemap_track_classes": source["track_classes"],
            "graph_nodes": graph.number_of_nodes(),
            "graph_edges": graph.number_of_edges(),
            "graph_components": source["graph_components"],
            "largest_graph_component_nodes": source["largest_component"],
            "gtfs_reference": "MVV Gesamt-Soll-Fahrplandaten (GTFS-Feed, 06/2026)",
            "gtfs_sha256": hashlib.sha256(gtfs_bytes).hexdigest(),
            "gtfs_trip_count": reference["trip_count"],
            "gtfs_pattern_count": reference["pattern_count"],
            "selected_patterns": len(reference["patterns"]),
            "stations": len(snapped_stops),
            "max_station_snap_distance_m": max_snap,
            "max_station_snap_limit_m": MAX_STATION_SNAP_M,
            "stitch_tolerance_m": STITCH_TOLERANCE_M,
            "route_bridge_limit_m": ROUTE_BRIDGE_LIMIT_M,
            "used_stitched_gaps": used_stitches,
            "stitched_distance_m": round(stitched_distance, 1),
            "max_stitched_gap_m": max_stitched_gap,
            "pair_audit": pair_audit,
        },
        "features": features,
    }


def build_geometries(gtfs_path, cache_dir, route_names):
    references, stops = load_gtfs_reference(gtfs_path, route_names)
    used_stop_ids = {stop_id for reference in references.values()
                     for pattern in reference["patterns"] for stop_id in pattern}
    used_stops = {stop_id: stops[stop_id] for stop_id in used_stop_ids}
    lines, tile_count, bounds = download_tracks(used_stops, cache_dir)
    graph = build_graph(lines)
    connect_nearby_nodes(graph, STITCH_TOLERANCE_M)
    components = sorted(nx.connected_components(graph), key=len, reverse=True)
    source = {
        "zoom": 14,
        "tile_count": tile_count,
        "bounds": bounds,
        "track_features": len(lines),
        "track_classes": dict(collections.Counter(kind for _, kind in lines)),
        "graph_components": len(components),
        "largest_component": len(components[0]) if components else 0,
    }
    gtfs_bytes = gtfs_path.read_bytes()
    return {
        route_name: build_collection(
            route_name, references[route_name], stops, graph, source, gtfs_bytes
        )
        for route_name in route_names
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("gtfs", type=Path)
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--lines", nargs="+", choices=tuple(ROUTE_BRANCHES),
                        default=tuple(ROUTE_BRANCHES))
    args = parser.parse_args()
    collections_by_line = build_geometries(args.gtfs, args.cache_dir, args.lines)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    report = {}
    for route_name, collection in collections_by_line.items():
        path = args.output_dir / f"{line_id(route_name)}.geojson"
        path.write_text(json.dumps(collection, ensure_ascii=False,
                                   separators=(",", ":")) + "\n", encoding="utf-8")
        metadata = collection["metadata"]
        report[route_name] = {
            "path": str(path),
            "stations": metadata["stations"],
            "max_station_snap_distance_m": metadata["max_station_snap_distance_m"],
            "used_stitched_gaps": metadata["used_stitched_gaps"],
            "max_stitched_gap_m": metadata["max_stitched_gap_m"],
        }
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
