import json
from pathlib import Path

from scripts.build_line_candidates import build_report

ROOT = Path(__file__).resolve().parents[1]


def test_committed_candidate_report_matches_current_export():
    report = build_report((ROOT / "daten/frontend.json").read_bytes())
    committed = json.loads((ROOT / "docs/line-candidates.json").read_text(encoding="utf-8"))
    assert report == committed
    assert report["summary"] == {
        "networks": 18,
        "source_pairs": 361,
        "with_proposed_line_id": 160,
        "classifications": {
            "explicit_regional_s_bahn": 19,
            "explicit_s_bahn": 141,
            "needs_manual_classification": 3,
            "numeric_or_variant": 190,
            "other_rail_label": 7,
            "placeholder": 1,
        },
    }


def test_munich_s1_is_suggested_but_numeric_alias_stays_unconfirmed():
    report = build_report((ROOT / "daten/frontend.json").read_bytes())
    by_alias = {(item["source_alias"]["netz"], item["source_alias"]["line"]): item
                for item in report["candidates"]}
    s1 = by_alias[("München", "S1")]
    numeric = by_alias[("München", "1")]
    assert s1["proposed_line_id"] == "de.muenchen.s1"
    assert s1["possible_aliases"] == [{"netz": "München", "line": "1"}]
    assert "resolve_possible_aliases" in s1["review"]
    assert numeric["proposed_line_id"] is None
    assert numeric["classification"] == "numeric_or_variant"


def test_suggestions_never_claim_verified_geometry():
    report = build_report((ROOT / "daten/frontend.json").read_bytes())
    assert all("select_basemap_geometry" in item["review"]
               for item in report["candidates"])
    assert all("geometry" not in item for item in report["candidates"])
