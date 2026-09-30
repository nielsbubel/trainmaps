"""Inspect a trainmaps frontend export without changing the input file.

This is a local data audit, not an HTTP API or a geographic line classifier.
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import hashlib
import json
import math
from pathlib import Path

THRESHOLDS = (2, 5, 10, 20, 40)
DIMENSIONS = {
    "cancellationsByMonth": ("month",),
    "cancellationsByNetworkMonth": ("month", "netz"),
    "cancellationsByNetworkLineMonth": ("month", "netz", "line"),
    "delaysByMonth": ("month",),
    "delaysByNetworkMonth": ("month", "netz"),
    "delaysByNetworkLineMonth": ("month", "netz", "line"),
    "mostCancelledStops": ("stop_id", "netz", "line"),
}


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON property: {key}")
        result[key] = value
    return result


def reject_constant(value):
    raise ValueError(f"Non-finite JSON constant: {value}")


def inspect(path: Path) -> dict:
    return inspect_bytes(path.read_bytes(), path.name)


def inspect_bytes(raw: bytes, filename: str = "frontend.json") -> dict:
    if len(raw) > 32 * 1024 * 1024:
        raise ValueError("Maximum decompressed size: 32 MiB")
    data = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_object,
                      parse_constant=reject_constant)
    if not isinstance(data, dict) or set(data) != set(DIMENSIONS):
        raise ValueError("Expected exactly the seven frontend export arrays")
    if any(not isinstance(rows, list) for rows in data.values()):
        raise ValueError("Every export collection must be an array")
    total = sum(len(rows) for rows in data.values())
    if total > 100_000:
        raise ValueError("Maximum total rows: 100000")
    errors = []
    inventory = {}
    all_pairs = set()
    keyed = {}
    for name, dims in DIMENSIONS.items():
        suffixes = ("cancelled",) if not name.startswith("delays") else tuple(
            f"on_time_{t}" for t in THRESHOLDS)
        expected = set(dims) | {"n_data_points"} | {
            prefix + suffix for prefix in ("n_", "p_") for suffix in suffixes}
        seen = {}
        months = set()
        for index, row in enumerate(data[name]):
            pointer = f"/{name}/{index}"
            if not isinstance(row, dict) or set(row) != expected:
                errors.append({"path": pointer, "code": "unexpected_fields"})
                continue
            if any(not isinstance(row[k], str) or not row[k].strip() for k in dims):
                errors.append({"path": pointer, "code": "invalid_dimension"})
                continue
            identity = tuple(row[k][:7] if k == "month" else row[k] for k in dims)
            if identity in seen:
                errors.append({"path": pointer, "code": "duplicate_row_key"})
            seen[identity] = row
            if "month" in row:
                try:
                    month = dt.datetime.fromisoformat(row["month"])
                    if (month.day != 1 or month.time() != dt.time(0)
                            or month.utcoffset() != dt.timedelta(0)):
                        raise ValueError("Expected UTC month-start label")
                    months.add(row["month"][:7])
                except ValueError:
                    errors.append({"path": pointer + "/month", "code": "invalid_month"})
            if "line" in row:
                all_pairs.add((row["netz"], row["line"]))
            n = row["n_data_points"]
            if type(n) is not int or not 0 <= n <= 9_007_199_254_740_991:
                errors.append({"path": pointer, "code": "invalid_denominator"})
                continue
            counts = [row["n_" + s] for s in suffixes]
            if any(type(c) is not int or not 0 <= c <= n for c in counts):
                errors.append({"path": pointer, "code": "invalid_count"})
                continue
            if counts != sorted(counts):
                errors.append({"path": pointer, "code": "nonmonotonic_counts"})
            for suffix in suffixes:
                count, ratio = row["n_" + suffix], row["p_" + suffix]
                valid = ratio is None if n == 0 else (
                    type(ratio) in (int, float) and math.isfinite(ratio)
                    and 0 <= ratio <= 1 and abs(ratio - count / n) <= 1e-6)
                if not valid:
                    errors.append({"path": pointer + "/p_" + suffix,
                                   "code": "inconsistent_ratio"})
        keyed[name] = seen
        inventory[name] = {"rows": len(data[name]), "dimensions": list(dims),
                           "months": sorted(months), "fields": sorted(expected)}

    rollups = []
    if not errors:
        for family in ("cancellations", "delays"):
            metrics = ["n_data_points"] + (["n_cancelled"] if family == "cancellations"
                       else [f"n_on_time_{t}" for t in THRESHOLDS])
            for parent, child in ((family + "ByMonth", family + "ByNetworkMonth"),
                                  (family + "ByNetworkMonth", family + "ByNetworkLineMonth")):
                dims = DIMENSIONS[parent]
                sums = collections.defaultdict(collections.Counter)
                for row in data[child]:
                    key = tuple(row[d][:7] if d == "month" else row[d] for d in dims)
                    for metric in metrics:
                        sums[key][metric] += row[metric]
                parent_rows = keyed[parent]
                mismatches = set(sums) ^ set(parent_rows)
                mismatches.update(k for k in set(sums) & set(parent_rows)
                                  if any(sums[k][m] != parent_rows[k][m] for m in metrics))
                rollups.append({"parent": parent, "child": child,
                                "mismatch_count": len(mismatches)})
                if mismatches:
                    errors.append({"path": "/" + child, "code": "rollup_mismatch"})

    cancellations = keyed["cancellationsByNetworkLineMonth"]
    delays = keyed["delaysByNetworkLineMonth"]
    population_mismatches = []
    if not errors:
        population_mismatches = [list(k) for k in cancellations.keys() & delays.keys()
                                if cancellations[k]["n_data_points"] - cancellations[k]["n_cancelled"]
                                != delays[k]["n_data_points"]]
    source_networks = sorted({n for n, _ in all_pairs})
    monthly_periods = sorted({m for item in inventory.values() for m in item["months"]})
    stops = {r.get("stop_id") for r in data["mostCancelledStops"] if isinstance(r, dict)}
    return {
        "file": filename, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
        "total_rows": total, "collections": inventory, "validation_errors": errors,
        "rollups": rollups, "months": monthly_periods,
        "networks": source_networks, "source_network_line_pairs": len(all_pairs),
        "line_inventory": {n: sorted(line for net, line in all_pairs if net == n)
                           for n in source_networks},
        "unique_stop_ids_in_ranking": len(stops),
        "cancellation_rows_without_delay": len(cancellations.keys() - delays.keys()),
        "delay_rows_without_cancellation": len(delays.keys() - cancellations.keys()),
        "unequal_non_cancelled_and_delay_denominators": len(population_mismatches),
        "denominator_mismatch_examples": sorted(population_mismatches)[:5],
        "notes": [
            "Source network/line pairs are not verified real S-Bahn routes.",
            "stop_id has no declared ID system, names, coordinates or ranking period.",
            "Cancellation and delay populations must remain separate.",
            "The latest monthly label does not prove a complete month.",
            "No source labels, counters, ratios or input bytes were changed.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if args.report and args.report.resolve() == args.input.resolve():
        parser.error("The report cannot overwrite the input")
    report = inspect(args.input)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in (
        "bytes", "total_rows", "source_network_line_pairs", "unique_stop_ids_in_ranking",
        "validation_errors", "cancellation_rows_without_delay",
        "unequal_non_cancelled_and_delay_denominators")}, ensure_ascii=True))
    return 1 if report["validation_errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
