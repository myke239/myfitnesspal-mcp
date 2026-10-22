"""Deterministic data-pipeline tests; no downloads, models, or account access."""

import io
import json
import tarfile
import zipfile
from pathlib import Path

import pytest

pytest.importorskip("PIL")
pytest.importorskip("truststore")

from scripts.food_benchmark.acquire import extract_archive, stratified
from scripts.food_benchmark.evaluate import score


def test_weight_metrics_and_interval_coverage():
    predictions = [
        {"sample_id": "a", "mass_g": 120, "lower_g": 90, "upper_g": 130},
        {"sample_id": "b", "mass_g": 180, "lower_g": 190, "upper_g": 220},
    ]
    # Invalid intervals cannot be silently graded.
    with pytest.raises(ValueError):
        score(
            predictions,
            [{"sample_id": "a", "mass_g": 100}, {"sample_id": "b", "mass_g": 200}],
        )
    predictions[1]["lower_g"] = 150
    result, _ = score(
        predictions,
        [{"sample_id": "a", "mass_g": 100}, {"sample_id": "b", "mass_g": 200}],
    )
    assert result["mass_mae_g"] == 20
    assert result["mass_bias_g"] == 0
    assert result["subjective_interval_coverage"] == 1
    assert result["mass_wape_percent"] == pytest.approx(40 / 300 * 100)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), True, -1])
def test_invalid_predictions_rejected(value):
    with pytest.raises(ValueError):
        score(
            [{"sample_id": "a", "mass_g": value, "lower_g": 0, "upper_g": 100}],
            [{"sample_id": "a", "mass_g": 100}],
        )


def test_missing_predictions_are_visible():
    result, _ = score(
        [{"sample_id": "a", "mass_g": 100, "lower_g": 50, "upper_g": 150}],
        [{"sample_id": "a", "mass_g": 100}, {"sample_id": "b", "mass_g": 100}],
    )
    assert result["prediction_completion_fraction"] == 0.5


def test_duplicate_ids_rejected():
    row = {"sample_id": "a", "mass_g": 100, "lower_g": 50, "upper_g": 150}
    with pytest.raises(ValueError):
        score([row, row], [{"sample_id": "a", "mass_g": 100}])


def test_zip_cannot_escape_destination(tmp_path):
    path = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("../escape.txt", "unsafe")
    with pytest.raises(ValueError):
        extract_archive(path, tmp_path / "out")
    assert not (tmp_path / "escape.txt").exists()


def test_tar_link_shortcuts_are_omitted(tmp_path):
    path = tmp_path / "source.tar.gz"
    with tarfile.open(path, "w:gz") as archive:
        item = tarfile.TarInfo("real.txt")
        item.size = 2
        archive.addfile(item, io.BytesIO(b"ok"))
        link = tarfile.TarInfo("shortcut")
        link.type = tarfile.SYMTYPE
        link.linkname = "../../outside"
        archive.addfile(link)
    extract_archive(path, tmp_path / "out")
    assert (tmp_path / "out/real.txt").read_text() == "ok"
    assert not (tmp_path / "out/shortcut").exists()


def test_stratified_selection_reproducible_and_unique():
    rows = [
        {"dish_id": str(i), "mass_g": i * 20, "ingredients": [{}], "cafe": "a"}
        for i in range(100)
    ]
    first = stratified(rows, 30)
    assert first == stratified(rows, 30)
    assert len({r["dish_id"] for r in first}) == 30


def test_local_manifest_has_no_group_overlap():
    root = Path(__file__).resolve().parents[1]
    path = root / "data/food-estimation/manifest.jsonl"
    if not path.exists():
        pytest.skip("Benchmark data is intentionally not distributed")
    groups = {}
    for line in path.read_text().splitlines():
        row = json.loads(line)
        group = (row["dataset"], row["dish_id"])
        if group in groups:
            assert groups[group] == row["split"]
        groups[group] = row["split"]
    assert any(v == "development" for v in groups.values())
    assert any(v == "locked_test" for v in groups.values())


def test_optional_nutrition_scores_keep_missing_coverage_explicit():
    predictions = [
        {
            "sample_id": "a",
            "mass_g": 100,
            "lower_g": 50,
            "upper_g": 150,
            "kcal": 220,
            "protein_g": 12,
        }
    ]
    truth = [
        {"sample_id": "a", "mass_g": 100, "kcal": 200, "protein_g": 10, "fat_g": 5}
    ]
    result, _ = score(predictions, truth)
    assert result["nutrition_metrics"]["kcal"]["mae"] == 20
    assert result["nutrition_metrics"]["protein_g"]["bias"] == 2
    assert result["nutrition_metrics"]["fat_g"]["scored"] == 0
