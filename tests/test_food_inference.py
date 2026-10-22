import json

import pytest

from scripts.food_benchmark import infer
from scripts.food_benchmark.infer import FIELDS, parse_response, payload


def test_image_request_contains_no_answer_labels(tmp_path, monkeypatch):
    monkeypatch.setattr(infer, "ROOT", tmp_path)
    image = tmp_path / "data/food-estimation/pilot/images/P01.jpg"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"test-image")
    row = {"image": "data/food-estimation/pilot/images/P01.jpg",
           "split": "development_pilot", "prompt": "Estimate food", "mass_g": 99999}
    request = payload(row, "test-model")
    assert "99999" not in json.dumps(request)
    assert request["store"] is False
    assert request["input"][0]["content"][1]["image_url"].startswith("data:image/jpeg;base64,")


def test_rejects_holdout_or_outside_image():
    for image, split in [("README.md", "development_pilot"),
                         ("data/food-estimation/pilot/images/P01.jpg", "locked_test")]:
        with pytest.raises(ValueError):
            payload({"image": image, "split": split}, "test")


def test_refusal_or_incomplete_is_not_an_estimate():
    with pytest.raises(ValueError):
        parse_response({"status": "incomplete"})


def test_invalid_numeric_response_is_rejected():
    estimate = dict.fromkeys(FIELDS, 1)
    estimate.update(mass_g=float("nan"), food_description="food")
    with pytest.raises(ValueError):
        parse_response({"status": "completed", "output": [{"content": [
            {"type": "output_text", "text": json.dumps(estimate)}]}]})
