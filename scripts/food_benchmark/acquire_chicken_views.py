"""Additional weighed, mostly-chicken Nutrition5k side views, grouped by dish."""

import concurrent.futures
import csv
import json
import subprocess

import imageio_ffmpeg
import truststore

from scripts.food_benchmark.acquire import (
    DATA,
    ROOT,
    digest,
    download,
    list_gcs,
    save_json,
)
from scripts.food_benchmark.prepare import write_jsonl


def main():
    truststore.inject_into_ssl()
    folder = DATA / "raw/nutrition5k"
    train = set((folder / "dish_ids/splits/rgb_train_ids.txt").read_text().split())
    test = set((folder / "dish_ids/splits/rgb_test_ids.txt").read_text().split())
    rows = []
    for path in sorted((folder / "metadata").glob("dish_metadata*.csv")):
        for row in csv.reader(path.open()):
            while row and row[-1] == "":
                row.pop()
            ing = [(row[i+1], float(row[i+2])) for i in range(6, len(row), 7)]
            mass = float(row[2])
            chicken = sum(m for n, m in ing if n in {"chicken", "chicken breast", "grilled chicken", "chicken thighs"})
            if chicken > 0 and chicken >= mass * .9 and (row[0] in train or row[0] in test):
                rows.append({"dish_id": row[0], "mass_g": chicken,
                             "split": "development" if row[0] in train else "locked_test"})
    def acquire(row):
        objects = list_gcs("imagery/side_angles/" + row["dish_id"] + "/")
        obj = next((o for o in objects if o["name"].endswith("camera_A.h264")), None)
        if not obj:
            return None
        folder = DATA / "raw/nutrition5k/chicken-side" / row["dish_id"]
        video = folder / "camera_A.h264"
        download("https://storage.googleapis.com/nutrition5k_dataset/" + obj["name"], video)
        import base64
        if base64.b64encode(bytes.fromhex(digest(video, "md5"))).decode() != obj["md5Hash"]:
            raise ValueError("Video publisher hash mismatch")
        image = folder / "frame.png"
        subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-loglevel", "error", "-y", "-i", str(video),
                        "-vf", "select=eq(n\\,15)", "-frames:v", "1", str(image)],
                       check=True, capture_output=True, timeout=60)
        return {"sample_id": row["dish_id"] + "-side", "group_id": row["dish_id"],
                "image": str(image.relative_to(ROOT)), "mass_g": row["mass_g"],
                "category": "chicken", "split": row["split"], "source": "Nutrition5k-side",
                "mass_basis": "weighed chicken ingredient grams; at least 90% dish mass",
                "image_sha256": digest(image), "video_md5": obj["md5Hash"]}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        result = []
        for row in pool.map(acquire, rows):
            if row:
                result.append(row)
                print("Acquired", row["sample_id"], flush=True)
    write_jsonl(DATA / "basics/nutrition5k-side-labels.jsonl", result)
    save_json(DATA / "basics/chicken-side-acquisition.json", {"images": len(result),
        "development": sum(r["split"] == "development" for r in result),
        "locked_test": sum(r["split"] == "locked_test" for r in result),
        "license": "CC-BY-4.0", "source": "https://github.com/google-research-datasets/Nutrition5k",
        "note": "One fixed frame per dish, no random frame split. Same dishes as overhead keep original split."})
    print(json.dumps({"acquired": len(result)}))


if __name__ == "__main__":
    main()
