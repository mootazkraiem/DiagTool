# clean-2-002 — validation and comparison with clean-2-001 (read-only)

clean-2-002 = clean-2-001 plus the sparse/unseen labelling fix and a recorded validation status. Scoring, canonical features, MIN_ID_ROWS = 1000, 200 trees and the calibration are unchanged; `models.joblib` is byte-identical to clean-2-001 for 8 of 8 families.

Holdout rates are **holdout flagged rates** on unlabelled recordings assumed normal, not false-positive rates.

## Comparison

| Family | Validation status | ID models | Sparse IDs 001 → 002 | Training flagged 001 / 002 | Holdout flagged (of scored) 002 | Scored 001 / 002 | Sparse 001 / 002 | Unseen 001 / 002 | models.joblib MB |
|---|---|---|---|---|---|---|---|---|---|
| hyundai_ioniq5 | unvalidated_no_holdout | 2 | 2 → 2 | 1.998% / 1.998% | no holdout | — / — | — / — | — / — | 1.2 |
| jaguar_ipace | holdout_evaluated | 46 | 97 → 110 | 1.986% / 1.986% | 1,249/40,477 (3.09%) | 82.6% / 82.6% | 17.2% / 17.2% | 0.2% / 0.1% | 28.8 |
| kaggle_normal | unvalidated_no_holdout | 25 | 2 → 2 | 1.999% / 1.999% | no holdout | — / — | — / — | — / — | 15.3 |
| kia_ev6 | holdout_evaluated | 161 | 26 → 30 | 1.978% / 1.978% | 11,109/429,524 (2.59%) | 98.4% / 98.4% | 1.6% / 1.6% | 0.0% / 0.0% | 78.8 |
| mg_zs_ev | held_back | 33 | 43 → 45 | 1.982% / 1.982% | 5,173/11,865 (43.60%) | 11.9% / 11.9% | 5.9% / 9.7% | 82.2% / 78.3% | 21.3 |
| nissan_leaf_2019 | holdout_evaluated | 12 | 2 → 4 | 1.999% / 1.999% | 2,951/491,797 (0.60%) | 100.0% / 100.0% | 0.0% / 0.0% | 0.0% / 0.0% | 8.3 |
| road_ambient | holdout_evaluated | 77 | 29 → 29 | 1.997% / 1.997% | 8,982/147,485 (6.09%) | 99.0% / 99.0% | 1.0% / 1.0% | 0.0% / 0.0% | 42.6 |
| tesla | unvalidated_no_holdout | 15 | 29 → 29 | 1.993% / 1.993% | no holdout | — / — | — / — | — / — | 8.4 |

Total model storage: 204.6 MB → 204.6 MB.

## Validation of clean-2-002

| Family | Training CAN IDs | Unlisted in manifest | Seen but reported unseen | Sparse with 0 rows | Calibration re-derived (mismatches) | Train/holdout overlap |
|---|---|---|---|---|---|---|
| hyundai_ioniq5 | 4 | 0 | 0 | 0 | 2 (0) | 0 |
| jaguar_ipace | 156 | 0 | 0 | 13 | 46 (0) | 0 |
| kaggle_normal | 27 | 0 | 0 | 0 | 25 (0) | 0 |
| kia_ev6 | 191 | 0 | 0 | 4 | 161 (0) | 0 |
| mg_zs_ev | 78 | 0 | 0 | 2 | 33 (0) | 0 |
| nissan_leaf_2019 | 16 | 0 | 0 | 2 | 12 (0) | 0 |
| road_ambient | 106 | 0 | 0 | 0 | 77 (0) | 0 |
| tesla | 44 | 0 | 0 | 0 | 15 (0) | 0 |

Calibration was re-derived from the training rows for every CAN-ID model: row count, k, threshold ((k+1)-th smallest score), flagged count, tie count and median all equal the manifest.

## Status notes

- **mg_zs_ev — held_back.** About 78% of its holdout rows are on CAN IDs that never occur in its single training recording (82% before the labelling fix, which moved IDs seen in training with fewer than 11 frames from unseen to sparse). Promotion refuses held-back families. Its corpus was not changed.
- **hyundai_ioniq5, kaggle_normal, tesla — unvalidated_no_holdout.** Each vehicle has one recording; the models have only been measured against their own training data and are not evidence of generalisation.
- **road_ambient — 0x193.** 58% of its holdout rows are flagged (clean-2-001 analysis). Its payload is static in every training recording (byte_diff median 0) and changes in the highway holdout (e.g. 00 08 08 03 E8 68 → 00 08 08 04 57 A8): a behaviour/coverage difference, not a threshold problem. The threshold was not tuned against the holdout.
