"""Schema for the supplied export; raw request JSON stays unchanged."""
from scripts.inspect_frontend import DIMENSIONS, THRESHOLDS

MAX_BYTES = 32 * 1024 * 1024
MAX_ROWS = 100_000
MONTH_PATTERN = r"^[0-9]{4}-(0[1-9]|1[0-2])-01T00:00:00(?:\.[0-9]{1,6})?(?:Z|\+00:?00)$"


def export_schema(*, require_line_ids=False):
    properties = {}
    for name, dims in DIMENSIONS.items():
        counts = ["cancelled"] if not name.startswith("delays") else [
            f"on_time_{t}" for t in THRESHOLDS]
        fields = {d: {"type": "string", "minLength": 1, "maxLength": 200}
                  for d in dims}
        if require_line_ids and "line" in dims:
            fields["line_id"] = {
                "type": "string", "pattern": r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$",
                "minLength": 1, "maxLength": 120,
                "description": "Stable trainmaps line identifier from the reference catalog.",
            }
        if "month" in fields:
            fields["month"] = {"type": "string", "pattern": MONTH_PATTERN,
                               "description": "Original UTC month label; +0000 is supported."}
        integer = {"type": "integer", "minimum": 0, "maximum": 9_007_199_254_740_991}
        fields["n_data_points"] = integer
        for suffix in counts:
            fields["n_" + suffix] = integer
            fields["p_" + suffix] = {"type": ["number", "null"], "minimum": 0, "maximum": 1}
        row = {"type": "object", "additionalProperties": False,
               "required": list(fields), "properties": fields}
        properties[name] = {"type": "array", "maxItems": MAX_ROWS, "items": row}
    return {"type": "object", "additionalProperties": False,
            "required": list(properties), "properties": properties,
            "description": ("Complete frontend export. At most 100000 total rows and 32 MiB "
                            "decompressed. Counts, ratios, duplicates and aggregate sums are "
                            "additionally checked by the server."
                            + (" Every row with a source line requires a registered line_id."
                               if require_line_ids else ""))}
