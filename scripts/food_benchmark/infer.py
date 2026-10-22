"""Run a bounded, image-only development benchmark using OpenAI Responses."""

import argparse
import base64
import hashlib
import json
import math
import subprocess
from pathlib import Path

import requests
import truststore

from .evaluate import load_jsonl, score

ROOT = Path(__file__).resolve().parents[2]
FIELDS = ("mass_g", "lower_g", "upper_g", "kcal", "protein_g", "fat_g", "carbohydrate_g")


def read_key():
    """Decrypt PowerShell SecureString in a child process; never print the result."""
    command = """
    $ErrorActionPreference = 'Stop'
    $encrypted = Get-Content -Raw -LiteralPath 'work/food-estimation/openai-key.dpapi'
    $secure = ConvertTo-SecureString $encrypted.Trim()
    $credential = [System.Management.Automation.PSCredential]::new('api', $secure)
    [Console]::Write($credential.GetNetworkCredential().Password)
    """
    result = subprocess.run(
        ["pwsh.exe", "-NoProfile", "-NonInteractive", "-Command", command],
        cwd=ROOT, capture_output=True, text=True, timeout=20,
    )
    if result.returncode or not result.stdout.strip():
        raise RuntimeError("Cannot decrypt the saved API key for this Windows account")
    return result.stdout.strip()


def payload(row, model):
    image = (ROOT / row["image"]).resolve()
    allowed = (ROOT / "data/food-estimation/pilot/images").resolve()
    if not image.is_relative_to(allowed) or row["split"] != "development_pilot":
        raise ValueError("This runner accepts only blinded development pilot images")
    schema = {
        "type": "object", "additionalProperties": False,
        "properties": {name: {"type": "number", "minimum": 0} for name in FIELDS},
        "required": [*FIELDS, "food_description"],
    }
    schema["properties"]["food_description"] = {"type": "string"}
    return {
        "model": model, "store": False, "max_output_tokens": 1000,
        "input": [{"role": "user", "content": [
            {"type": "input_text", "text": row["prompt"] +
             " Also estimate total calories (kcal), protein_g, fat_g, carbohydrate_g."
             " Treat nutrition as uncertain; describe visible foods and preparation."},
            {"type": "input_image", "detail": "high", "image_url":
             "data:image/jpeg;base64," + base64.b64encode(image.read_bytes()).decode()},
        ]}],
        "text": {"format": {"type": "json_schema", "name": "food_estimate",
                            "strict": True, "schema": schema}},
    }


def parse_response(body):
    if body.get("status") != "completed":
        raise ValueError("Response did not complete; no estimate recorded")
    texts = [part["text"] for item in body.get("output", [])
             for part in item.get("content", []) if part.get("type") == "output_text"]
    estimate = json.loads("".join(texts))
    if any(not isinstance(estimate.get(name), (int, float))
           or isinstance(estimate[name], bool)
           or not math.isfinite(estimate[name]) or estimate[name] < 0 for name in FIELDS):
        raise ValueError("Invalid numeric estimate")
    # Reuse finite-number and interval validation without opening any answer labels.
    score([{"sample_id": "validation", **estimate}],
          [{"sample_id": "validation", "mass_g": 1}])
    return estimate


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.limit <= 30:
        parser.error("limit must be between 1 and 30")
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / "work"):
        parser.error("output must be inside project work/")
    output.mkdir(parents=True, exist_ok=False)
    rows = load_jsonl(ROOT / "data/food-estimation/pilot/prompts.jsonl")[:args.limit]
    truststore.inject_into_ssl()
    session = requests.Session()
    session.headers["Authorization"] = "Bearer " + read_key()
    protocol = {"model": args.model, "limit": args.limit, "split": "development_pilot",
                "labels_sent": False, "max_output_tokens_per_request": 1000,
                "automatic_retries": 0,
                "inputs": [{"sample_id": row["sample_id"],
                            "request_sha256": hashlib.sha256(json.dumps(
                                payload(row, args.model), sort_keys=True).encode()).hexdigest()}
                           for row in rows]}
    (output / "protocol.json").write_text(json.dumps(protocol, indent=2))
    predictions = output / "predictions.jsonl"
    for row in rows:
        try:
            response = session.post("https://api.openai.com/v1/responses",
                                    json=payload(row, args.model), timeout=(15, 120),
                                    allow_redirects=False)
        except requests.RequestException:
            raise SystemExit("API connection failed; stopped without retrying") from None
        if response.status_code != 200:
            try:
                error = response.json().get("error", {})
                code = error.get("code")
                if code not in ("insufficient_quota", "invalid_api_key", "model_not_found",
                                "rate_limit_exceeded"):
                    code = "request_rejected"
            except ValueError:
                code = "request_rejected"
            raise SystemExit(f"API stopped: HTTP {response.status_code}, {code}")
        body = response.json()
        with (output / "usage.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"sample_id": row["sample_id"], "model": body["model"],
                                     "usage": body.get("usage", {})}) + "\n")
        estimate = parse_response(body)
        with predictions.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"sample_id": row["sample_id"], **estimate}) + "\n")
        print(f"Completed {row['sample_id']}", flush=True)
    (output / "predictions-commit.json").write_text(json.dumps({
        "sha256": hashlib.sha256(predictions.read_bytes()).hexdigest(),
        "labels_read_during_inference": False,
    }, indent=2))


if __name__ == "__main__":
    main()
