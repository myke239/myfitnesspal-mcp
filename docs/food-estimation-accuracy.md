# Basic-food weight accuracy investigation

October 15, 2026. The requested **20% per-portion chicken weight error bound has not been achieved**. Candidate model, prompting, measured-example grounding and fitted correction factors were tested rather than assumed to improve accuracy. None qualified for general deployment. Version 0.5.0 keeps the existing photo-only model and adds explicit food scope, reference/view inputs and an accuracy-status response. It does not claim newly trained model weights or improved photo-only accuracy.

## Additional data

| Source | Acquisition and use | Important limits |
| --- | --- | --- |
| [NCI ASA24](https://epi.grants.cancer.gov/asa24/resources/portionsize.html) | Downloaded the 670,269,206-byte publisher archive: 17,135 PNG files locally, plus inventory/mapping workbooks. Downloaded 2022 image metadata. Selected 56 explicitly ounce-labelled images: 8 baked sliced chicken breast, 24 salmon, 24 steak. | NCI says images are freely available for use. Preserve source attribution. Labels are publisher portion labels converted using 28.349523125 grams/avoirdupois ounce; they are not new independent scale measurements. Cups and “one piece” are not silently converted to grams. The 8 chicken portions are one food/preparation series, not eight independent cooking sessions. |
| [Nutrition5k](https://github.com/google-research-datasets/Nutrition5k) additional subset | Acquired 31 side-angle chicken videos and extracted one fixed frame per dish. All video publisher MD5s checked. 25 development dishes and 6 publisher-test dishes; same-dish views keep the same split. Also prepared 40 mostly-single-food overhead cases for chicken, fish, steak/beef and salad. | CC-BY-4.0. Chicken component is at least 90% of dish mass; targets are weighed ingredient grams, not an assumed standard portion. Overhead and side-view cases can be the same dish and must not be counted twice as independent examples. Camera/plate/cafeteria domain differs from home phone photos. |
| [NutritionVerse-Synth](https://saeejithnair.github.io/nvsynth/) | Additional candidate found: 84,984 rendered images from 7,082 scenes, with depth, instance masks and per-food nutrition/mass. [Generation code](https://github.com/saeejithnair/nvsynth). | Not acquired or used in these experiments. Generation-code MIT licensing does not by itself establish rights to all underlying 3D assets. Synthetic viewpoints are not independent real weighed meals. |
| [MetaFood3D](https://arxiv.org/abs/2409.01966) | Additional 3D direction: 743 scanned objects across 131 categories with mass/nutrition. | Not acquired in this phase; previously inspected access process requires a dataset request. No request was sent to other people. |

Archive receipts: `data/food-estimation/provenance/asa24.json`. Targeted labels, image hashes and fixed partitions: `data/food-estimation/basics/`. Original benchmark labels, manifest and lock were not rewritten. Licensed/restricted research data remain excluded from package builds. The earlier SNAPMe evaluation-only and SimpleFood45 unclear-terms restrictions remain in effect.

## Experiments

Error means `abs(predicted_g - target_g) / target_g * 100`. Report the proportion of cases at or below 20%, not just a median. API requests contain images and food identity/scope, never the query's weight label. A benchmark food identity is supplied, so these tests do not grade identification accuracy.

1. Current GPT-4.1-mini snapshot versus GPT-5.4 snapshot on 27 mostly-single-food development plates. A model swap alone did not materially improve the four chicken cases. Fish/steak each have just one development example, insufficient for a category accuracy claim.
2. A basic-food prompt with GPT-5.4 separated pieces, footprint/thickness/taper and salad density assumptions. On 25 chicken side-view development cases it reached median error 20%, but failed separate cases.
3. Four measured chicken reference photos selected at fixed mass quantiles from the 25 development dishes were supplied as in-context training examples. Their dish IDs were excluded from development scoring. This is measured-example conditioning, not a fine-tuned model. On the other 21 development dishes, median error improved from 30.4% for the current baseline to 13.9%; cases within 20% improved from 7/21 to 14/21. The improvement did not generalize.
4. An affine correction fitted on the 25 development estimates underwent leave-one-out evaluation and source-separated scoring. It failed; no correction factor was installed.

| Chicken method | Separate Nutrition5k side dishes (n=6): median error; within 20% | ASA24 sliced breast portions (n=8): median error; within 20% |
| --- | --- | --- |
| Current photo-only baseline | 29.3%; 2/6 | Not run for this baseline |
| Stronger model + basic-food prompt | 34.1%; 1/6 | 63.0%; 0/8 |
| Stronger model + four measured reference examples | 47.4%; 2/6 | 66.1%; 0/8 |

The six publisher-test dishes were used for multiple exploratory candidate comparisons; do not treat a future selection on these results as a fresh confirmatory test. ASA24 photos are small standardized images and the chicken series has limited independence. Public pretraining contamination is unknown. These are useful failure signals, not comprehensive estimates of home-photo accuracy. No phone-photo 20% claim is supported. No calibration was derived from the user's earlier 104 g or 114 g chicken photos; their bytes were not retained by the connector.

Saved predictions, token usage and reports are in `work/food-estimation/` under `basics-*`, `chicken-side-*`, `chicken-reference-*`, `chicken-v2-asa-heldout/` and `chicken-calibration-experiment.json`. Prediction hashes were committed before scoring in the benchmark runner. Reference records list only development dish IDs and measured weights; test weights are excluded from reference inputs.

## Connector changes

- `food_focus="chicken"` estimates only chicken on a mixed plate. It also defines what a supplied `measured_weight_g` refers to.
- `plate_diameter_cm` accepts an actual measured outer rim diameter. The agent must not invent a standard plate size.
- `additional_images` (attachment file params) or `additional_image_urls` accept up to two other views of the **same portion**. Side views supply thickness evidence; they are not summed as extra servings.
- `accuracy_target` distinguishes measured weight from an unproven estimate, with `guaranteed=false`. A model-generated narrow range does not certify a 20% error bound.
- Photo-only default model/prompt remains the prior version. Stronger-model and basic-prompt candidates are research experiments, not promoted improvements. No research reference photos or fitted factors are loaded by production inference. Reference-input support itself remains unqualified for a 20% bound.

If a 20% limit is mandatory now, obtain a scale weight and log a matched database food using those measured grams. A visible ruler or measured plate plus overhead/side images is the next practical data-collection route, but must still be tested against independent weighed home meals. A single photograph without physical scale or thickness information cannot uniquely determine grams.

## Reproduce

Install benchmark extras and run from the project root. Each run must use a new output directory.

```powershell
.\.venv\Scripts\python.exe -m scripts.food_benchmark.basics prepare
.\.venv\Scripts\python.exe -m scripts.food_benchmark.acquire_chicken_views
.\.venv\Scripts\python.exe -m scripts.food_benchmark.basics run --source nutrition5k-side --protocol legacy --model gpt-4.1-mini-2025-04-14 --output work/food-estimation/repeat-baseline
.\.venv\Scripts\python.exe -m scripts.food_benchmark.basics run --source nutrition5k-side --protocol basic-v2 --model gpt-5.4-2026-03-05 --references --output work/food-estimation/repeat-reference
```

The acquisition receipts identify the ASA24 archive and metadata URLs; `basics prepare` consumes the downloaded 2022 metadata. Do not mix test-labelled images into a training/reference set merely because the fit is disappointing. Collect a new independent phone-photo test set before claiming the next candidate meets the target.
