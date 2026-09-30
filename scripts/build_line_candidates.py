"""Build a review list from raw source network/line pairs.

This tool never writes to the live line catalog. Proposed IDs are suggestions;
source aliases and basemap.de geometries still require operator review.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import re
import unicodedata
from pathlib import Path

try:
    from scripts.inspect_frontend import DIMENSIONS, reject_constant, unique_object
except ModuleNotFoundError:  # Direct execution: python scripts/build_line_candidates.py
    from inspect_frontend import DIMENSIONS, reject_constant, unique_object

LINE_COLLECTIONS = tuple(name for name, dims in DIMENSIONS.items() if "line" in dims)
NETWORK_CORRECTIONS = {
    "Karlruhe": ("karlsruhe", "Karlsruhe", "Quellname vermutlich falsch geschrieben"),
}


def slug(value: str) -> str:
    value = (value.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")
             .replace("Ä", "Ae").replace("Ö", "Oe").replace("Ü", "Ue")
             .replace("ß", "ss"))
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def classify(label: str) -> str:
    if label.upper() == "LEER":
        return "placeholder"
    if re.fullmatch(r"S\d+[A-Za-z]?", label, re.IGNORECASE):
        return "explicit_s_bahn"
    if re.fullmatch(r"RS\d+[A-Za-z]?", label, re.IGNORECASE):
        return "explicit_regional_s_bahn"
    if re.fullmatch(r"(?:RB|RE)\d+[A-Za-z]?|FEX", label, re.IGNORECASE):
        return "other_rail_label"
    if re.fullmatch(r"\d+[A-Za-z]?", label):
        return "numeric_or_variant"
    return "needs_manual_classification"


def network_fields(source_network: str):
    correction = NETWORK_CORRECTIONS.get(source_network)
    if correction:
        network_slug, display_name, note = correction
        return "de." + network_slug, display_name, note
    return "de." + slug(source_network), source_network, None


def possible_alias_key(label: str):
    match = re.fullmatch(r"S(\d+[A-Za-z]?)", label, re.IGNORECASE)
    if match:
        return match.group(1).upper()
    if re.fullmatch(r"\d+[A-Za-z]?", label):
        return label.upper()
    return None


def build_report(raw: bytes) -> dict:
    data = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_object,
                      parse_constant=reject_constant)
    if not isinstance(data, dict) or set(data) != set(DIMENSIONS):
        raise ValueError("Expected exactly the seven frontend export arrays")

    inventory = collections.defaultdict(lambda: {
        "collections": collections.Counter(), "months": set(),
    })
    for collection in LINE_COLLECTIONS:
        for row in data[collection]:
            key = (row["netz"], row["line"])
            inventory[key]["collections"][collection] += 1
            if "month" in row:
                inventory[key]["months"].add(row["month"][:7])

    labels_by_network = collections.defaultdict(set)
    normalized_by_network = collections.defaultdict(lambda: collections.defaultdict(set))
    for network, label in inventory:
        labels_by_network[network].add(label)
        normalized_by_network[network][label.upper()].add(label)

    candidates = []
    for network, label in sorted(inventory):
        details = inventory[(network, label)]
        category = classify(label)
        network_id, network_display, network_note = network_fields(network)
        proposed_line_id = None
        if category in ("explicit_s_bahn", "explicit_regional_s_bahn"):
            proposed_line_id = f"{network_id}.{slug(label)}"

        reviews = ["confirm_real_service", "select_basemap_geometry"]
        if category not in ("explicit_s_bahn", "explicit_regional_s_bahn"):
            reviews.insert(0, "classify_source_label")
        if category == "placeholder":
            reviews.insert(0, "reject_or_replace_placeholder")
        if network_note:
            reviews.append("confirm_network_name_correction")

        aliases = []
        alias_key = possible_alias_key(label)
        if alias_key:
            for other in sorted(labels_by_network[network]):
                if other != label and possible_alias_key(other) == alias_key:
                    aliases.append({"netz": network, "line": other})
        spelling_variants = sorted(normalized_by_network[network][label.upper()] - {label})
        if aliases:
            reviews.append("resolve_possible_aliases")
        if spelling_variants:
            reviews.append("resolve_case_variants")

        months = sorted(details["months"])
        candidates.append({
            "source_alias": {"netz": network, "line": label},
            "classification": category,
            "proposed_network_id": network_id,
            "proposed_line_id": proposed_line_id,
            "proposed_display_name": (f"{label.upper()} {network_display}"
                                      if proposed_line_id else None),
            "possible_aliases": aliases,
            "case_variants": spelling_variants,
            "source_rows": dict(sorted(details["collections"].items())),
            "first_month": months[0] if months else None,
            "last_month": months[-1] if months else None,
            "review": reviews,
            "notes": [network_note] if network_note else [],
        })

    classifications = collections.Counter(item["classification"] for item in candidates)
    return {
        "format": "trainmaps-line-candidates-1",
        "source": "daten/frontend.json",
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "summary": {
            "networks": len(labels_by_network),
            "source_pairs": len(candidates),
            "with_proposed_line_id": sum(item["proposed_line_id"] is not None
                                         for item in candidates),
            "classifications": dict(sorted(classifications.items())),
        },
        "rules": [
            "Proposed IDs are review suggestions and are never imported automatically.",
            "Numeric and S-prefixed labels remain separate until their meaning is confirmed.",
            "Every accepted line still needs a selected and verified basemap.de geometry.",
        ],
        "candidates": candidates,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = build_report(args.input.read_bytes())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=True))


if __name__ == "__main__":
    main()
