"""Create the deliberately small trainmaps background style from basemap.de."""
from __future__ import annotations

import argparse
import json
import urllib.request
from pathlib import Path


STYLE_URL = "https://sgx.geodatenzentrum.de/gdz_basemapde_vektor/styles/bm_web_gry.json"


def category(layer):
    layer_id = layer["id"]
    source_layer = layer.get("source-layer", "")
    if layer["type"] == "background" or layer_id in {
        "SiedlungF_Siedlung", "SiedlungF_Siedlung_Industrie",
        "SiedlungF_Industrie_und_Gewerbe",
    }:
        return "base"
    if source_layer.startswith("Gewaesser") or "Gewaesser" in layer_id or "Gewasser" in layer_id:
        return "water"
    if (source_layer == "Name_Punkt" and layer_id.startswith((
        "Name_Ortsteil", "Name_Landgemeinde", "Name_Stadtgemeinde",
        "Name_Landeshauptstadt", "Name_Bundesland",
    ))) or layer_id.startswith("SiedlungP_Stadt") or layer_id == "SiedlungP_Landeshauptstadt":
        return "places"
    if "S_Bahn" in layer_id or layer_id in {
        "Name_Bahnhof", "Symbol_VerkehrP_Bahnhof", "Symbol_VerkehrF_Bahnhof",
    }:
        return "sbahn"
    if source_layer.startswith("Grenze") or layer_id.startswith("Grenzen_"):
        return "boundaries"
    if "Bahnstrecke" in layer_id or layer_id == "Verkehrsflaeche_Bahnverkehr_Schiffsverkehr":
        return "rail"
    road_terms = (
        "Autobahn", "Bundesstr", "Landesstr", "Staatsstr", "Kreisstr",
        "Gemeindestr", "Sonstige_Str", "Strasse", "Fussgaengerzone", "Mittellinie",
    )
    if any(term in layer_id for term in road_terms):
        return "roads"
    return None


def build_style(source):
    style = json.loads(source)
    selected = []
    counts = {}
    for original in style["layers"]:
        group = category(original)
        if group is None:
            continue
        layer = dict(original)
        layer["metadata"] = {**layer.get("metadata", {}), "trainmaps:category": group}
        if group in {"roads", "rail", "boundaries"}:
            layer["layout"] = {**layer.get("layout", {}), "visibility": "none"}
        selected.append(layer)
        counts[group] = counts.get(group, 0) + 1
    style["name"] = "trainmaps – basemap.de grau, reduziert"
    style["layers"] = selected
    style["metadata"] = {
        **style.get("metadata", {}),
        "trainmaps:source-style": STYLE_URL,
        "trainmaps:categories": counts,
    }
    return style


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source = (args.source.read_text(encoding="utf-8") if args.source
              else urllib.request.urlopen(STYLE_URL, timeout=60).read().decode("utf-8"))
    style = build_style(source)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(style, ensure_ascii=False, separators=(",", ":")) + "\n",
                           encoding="utf-8")
    print(json.dumps(style["metadata"]["trainmaps:categories"], sort_keys=True))


if __name__ == "__main__":
    main()
