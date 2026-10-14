"""Corruption checks for the agent-authored provisional screenshot subset.

These tests exercise source bytes and externally visible fixture constraints.
No retrieval/ranking implementation is imported or executed.
"""

import copy
import importlib.util
import json
import shutil
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "original_fixture_author", ROOT / "scripts/make_fixtures.py"
)
assert SPEC is not None and SPEC.loader is not None
FX = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FX)


@pytest.fixture(scope="module")
def dev():
    return json.loads((ROOT / "gold/dev.PROVISIONAL.json").read_bytes())


def test_grid_preimage_has_owner_exact_header_and_rgba_order():
    # what_bug_this_catches: old mode/width/row-order names or BGRA/channel swaps.
    image = Image.new("RGBA", (1, 2))
    image.putdata([(1, 2, 3, 4), (5, 6, 7, 8)])
    expected = (
        b'{"algorithm":"rgba8-source-grid-v1","channel_order":"RGBA","height_px":2,'
        b'"mode":"RGBA8","row_order":"top-to-bottom","width_px":1}\n'
        b"\x01\x02\x03\x04\x05\x06\x07\x08"
    )
    assert FX.grid_preimage(image) == expected


def test_canon_bytes_are_utf8_sorted_without_normalization():
    # what_bug_this_catches: ASCII escaping, Unicode normalization or pretty JSON.
    assert FX.canon({"z": "e\u0301", "a": "é"}) == '{"a":"é","z":"é"}'.encode()
    with pytest.raises(ValueError):
        FX.canon({"not_finite": float("nan")})


def test_actual_corpus_portable_audit_without_fonts_or_exact_patch(tmp_path, monkeypatch):
    # what_bug_this_catches: mandatory CI audit silently relying on Windows fonts/rerender.
    missing = tmp_path / "fonts-that-are-not-installed.ttf"
    assert not missing.exists()
    monkeypatch.setattr(FX, "FONT_INPUTS", {"arial": (str(missing), "0" * 64)})

    def forbidden(*args, **kwargs):
        raise AssertionError("Portable audit must not build, execute producer code or load fonts")

    for name in ("fonts", "runtime_inputs", "build_split", "load_historical_producer"):
        monkeypatch.setattr(FX, name, forbidden)
    monkeypatch.setattr(FX.ImageFont, "truetype", forbidden)
    monkeypatch.setattr(FX.platform, "python_version", lambda: "3.12.99")
    report = FX.check_all()
    assert report["totals"] == {"images": 60, "queries": 264, "groups": 54}
    assert report["duplicate_audit"]["cross_split_pairs_checked"] == 900
    assert len(report["duplicate_audit"]["intentional_confuser_pair_distances"]) == 6
    assert report["rerender"]["status"] == "not_run"
    assert report["current_auditor"]["python"] == "3.12.99"
    assert report["current_auditor"]["generated_originals_claimed"] is False
    assert all(s["font_metrics_recomputed"] is False for s in report["splits"])


def test_requested_rerender_reports_simulated_missing_fonts_and_nonzero_exit(
    tmp_path, monkeypatch, capsys
):
    # what_bug_this_catches: optional rerender reporting a pass after a fallback/skip.
    load_trusted = FX.load_historical_producer
    missing = tmp_path / "explicitly-missing-producer-font.ttf"

    def producer_with_simulated_absent_fonts():
        producer = load_trusted()
        producer.FONT_INPUTS = {"arial": (str(missing), "0" * 64)}
        return producer

    monkeypatch.setattr(FX, "load_historical_producer", producer_with_simulated_absent_fonts)
    assert FX.main(["--check", "--rerender"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "PASS_FROZEN_BYTE_AUDIT_RERENDER_UNAVAILABLE"
    assert report["totals"] == {"images": 60, "queries": 264, "groups": 54}
    assert report["rerender"]["requested"] is True
    assert report["rerender"]["performed"] is False
    assert report["rerender"]["status"] == "unavailable"
    assert missing.name in report["rerender"]["reason"]


@pytest.mark.parametrize("entrypoint", ["portable", "loader", "rerender"])
def test_historical_source_hash_failure_rejects_before_execution(tmp_path, monkeypatch, entrypoint):
    # what_bug_this_catches: arbitrary/tampered archived source being accepted or executed.
    original = FX.historical_producer_bytes()
    archive = tmp_path / FX.HISTORICAL_PRODUCER_RELATIVE_PATH
    archive.parent.mkdir(parents=True)
    archive.write_bytes(original + b'\nraise AssertionError("UNTRUSTED SOURCE EXECUTED")\n')
    monkeypatch.setattr(FX, "ROOT", tmp_path)
    with pytest.raises(ValueError, match="Historical producer archive hash mismatch"):
        if entrypoint == "loader":
            FX.load_historical_producer()
        else:
            FX.check_all(rerender=entrypoint == "rerender")


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_targets",
        "asset_as_item_id",
        "unknown_target",
        "bbox_overflow",
        "float_bbox",
        "duplicate_target",
        "negative_context_missing",
        "positive_context_leak",
        "unknown_private_field",
        "malformed_id",
        "duplicate_group_member",
        "wrong_scenario_asset",
        "blank_fake_exact",
        "missing_substitution",
        "boolean_dimension",
        "bad_raw_hash",
        "wrong_seed",
        "wrong_counts",
    ],
)
def test_strict_private_records_reject_plausible_corruptions(dev, mutation):
    # what_bug_this_catches: relabeling, unlabeled negatives, bad boxes/IDs and type coercion.
    m = copy.deepcopy(dev)
    if mutation == "missing_targets":
        del m["labels"][0]["targets"]
    elif mutation == "asset_as_item_id":
        m["labels"][0]["item_id"] = m["gallery"]["assets"][0]["asset_id"]
    elif mutation == "unknown_target":
        m["labels"][0]["targets"][0]["asset_id"] = "f" * 32
    elif mutation == "bbox_overflow":
        m["labels"][0]["targets"][0]["spatial_target"]["bbox_source_px"][2] = 99999
    elif mutation == "float_bbox":
        m["labels"][0]["targets"][0]["spatial_target"]["bbox_source_px"][0] = 1.2
    elif mutation == "duplicate_target":
        m["labels"][0]["targets"].append(copy.deepcopy(m["labels"][0]["targets"][0]))
    elif mutation == "negative_context_missing":
        m["labels"][-1]["negative_context_group_id"] = None
    elif mutation == "positive_context_leak":
        m["labels"][0]["negative_context_group_id"] = m["groups"][0]["group_id"]
    elif mutation == "unknown_private_field":
        m["labels"][0]["confidence"] = 1
    elif mutation == "malformed_id":
        m["gallery"]["source_id"] = "scene-readable-title"
    elif mutation == "duplicate_group_member":
        m["groups"][0]["asset_ids"][0] = m["groups"][1]["asset_ids"][0]
    elif mutation == "wrong_scenario_asset":
        m["scenarios"][0]["asset_id"] = m["scenarios"][1]["asset_id"]
    elif mutation == "blank_fake_exact":
        m["queries"][9 * 4]["query_type"] = "exact"
    elif mutation == "missing_substitution":
        m["queries"][10 * 4]["substitution"] = None
    elif mutation == "boolean_dimension":
        m["gallery"]["assets"][0]["width_px"] = True
    elif mutation == "bad_raw_hash":
        m["gallery"]["assets"][0]["encoded_sha256"] = "bad"
    elif mutation == "wrong_seed":
        m["seed"] = 731702
    elif mutation == "wrong_counts":
        m["counts"]["positive_queries"] = 119
    with pytest.raises(ValueError):
        FX.validate_manifest(m)


@pytest.mark.parametrize(
    "location,key",
    [
        ("root", "targets"),
        ("gallery", "groups"),
        ("asset", "stratum"),
        ("query", "negative_context_group_id"),
        ("query", "query_type"),
        ("query", "label_id"),
    ],
)
def test_public_projection_rejects_hidden_label_context_at_every_level(dev, location, key):
    # what_bug_this_catches: scorer-private labels/traps/groups reaching retrieval input.
    public = FX.public_projection(dev)
    node = {
        "root": public,
        "gallery": public["gallery"],
        "asset": public["gallery"]["assets"][0],
        "query": public["queries"][0],
    }[location]
    node[key] = "private-context"
    with pytest.raises(ValueError):
        FX.validate_public(public)


def test_blank_has_explicit_null_and_negatives_are_explicit_empty(dev):
    # what_bug_this_catches: absent targets being confused with labeled no-match queries.
    query_ids = {FX.opaque("query", "dev", [9, j]) for j in range(4)}
    assert all(
        label["targets"][0]["spatial_target"] is None
        for label in dev["labels"]
        if label["item_id"] in query_ids
    )
    negatives = [label for label in dev["labels"] if label["targets"] == []]
    assert len(negatives) == 12
    assert all(label["negative_context_group_id"] for label in negatives)
    assert sum(len(label["targets"]) == 2 for label in dev["labels"]) == 12


def test_first_generation_refuses_before_build_or_fonts(dev, capsys, monkeypatch, tmp_path):
    # what_bug_this_catches: a second generate command silently resealing changed originals.
    def forbidden(*args, **kwargs):
        raise AssertionError("Existing artifact refusal must precede runtime/font/build work")

    monkeypatch.setattr(FX, "FONT_INPUTS", {"arial": (str(tmp_path / "absent.ttf"), "0" * 64)})
    for name in ("fonts", "runtime_inputs", "build_split"):
        monkeypatch.setattr(FX, name, forbidden)
    before = {
        a["asset_id"]: FX.digest((ROOT / f"fixtures/dev/images/{a['asset_id']}.png").read_bytes())
        for a in dev["gallery"]["assets"]
    }
    assert FX.main(["--split", "dev", "--seed", "731701"]) == 1
    assert "First-generation-only refusal" in capsys.readouterr().err
    after = {
        a["asset_id"]: FX.digest((ROOT / f"fixtures/dev/images/{a['asset_id']}.png").read_bytes())
        for a in dev["gallery"]["assets"]
    }
    assert before == after


def test_encoded_png_corruption_is_rejected_without_changing_originals(tmp_path, monkeypatch, dev):
    # what_bug_this_catches: metadata-only checks accepting a modified actual PNG.
    shutil.copytree(ROOT / "fixtures/dev", tmp_path / "fixtures/dev")
    shutil.copytree(ROOT / "gold", tmp_path / "gold")
    asset = dev["gallery"]["assets"][0]
    path = tmp_path / f"fixtures/dev/images/{asset['asset_id']}.png"
    path.write_bytes(path.read_bytes() + b"changed")
    monkeypatch.setattr(FX, "ROOT", tmp_path)
    with pytest.raises(ValueError, match="encoded hash/bytes mismatch"):
        FX.audit_files("dev", dev)


def test_box_target_linkage_corruption_is_rejected(tmp_path, monkeypatch, dev):
    # what_bug_this_catches: a bounded but shifted gold box accepted without matching draw metrics.
    shutil.copytree(ROOT / "fixtures/dev", tmp_path / "fixtures/dev")
    shutil.copytree(ROOT / "gold", tmp_path / "gold")
    m = copy.deepcopy(dev)
    m["labels"][0]["targets"][0]["spatial_target"]["bbox_source_px"][0] += 1
    monkeypatch.setattr(FX, "ROOT", tmp_path)
    with pytest.raises(ValueError, match="differs from actual authored element"):
        FX.audit_files("dev", m)


def test_no_final_owner_seal_created():
    # what_bug_this_catches: the provisional author crossing the parent-only freeze boundary.
    files = FX.planned_output_paths("heldout")
    assert len(files) == 96
    assert "gold/manifest.json" not in files
    assert "fixtures/heldout/FROZEN" not in files
