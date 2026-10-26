# clean-2-001 — holdout evaluation and performance/storage review (read-only)

Flagged = raw IsolationForest score strictly below the CAN ID's calibrated threshold. Holdout recordings are unlabelled captures assumed to be normal operation: rates are **holdout flagged rates**, not false-positive rates. clean-1-001 figures are its pooled per-family model on the same holdout recordings.

## Holdout

| Family | clean-1 flagged | clean-2 flagged (of scored) | Scored | Sparse ID | Unseen ID | CAN IDs > 50% flagged |
|---|---|---|---|---|---|---|
| jaguar_ipace | 13.58% | 1,249/40,477 (3.09%) | 82.6% | 17.2% | 0.2% | 0/45 |
| kia_ev6 | 5.60% | 11,109/429,524 (2.59%) | 98.4% | 1.6% | 0.0% | 0/149 |
| mg_zs_ev | 3.07% | 5,173/11,865 (43.60%) | 11.9% | 5.9% | 82.2% | 1/3 |
| nissan_leaf_2019 | 14.90% | 2,951/491,797 (0.60%) | 100.0% | 0.0% | 0.0% | 0/12 |
| road_ambient | 4.75% | 8,982/147,485 (6.09%) | 99.0% | 1.0% | 0.0% | 1/77 |

No holdout (single recording): hyundai_ioniq5, kaggle_normal, tesla.

## Training calibration

| Family | ID models | Sparse IDs | Training flagged | Max per ID | IDs with ties at threshold |
|---|---|---|---|---|---|
| hyundai_ioniq5 | 2 | 2 | 1,029/51,508 (2.00%) | 2.00% | 0 |
| jaguar_ipace | 46 | 97 | 3,829/192,753 (1.99%) | 2.00% | 0 |
| kaggle_normal | 25 | 2 | 19,740/987,607 (2.00%) | 2.00% | 0 |
| kia_ev6 | 161 | 26 | 8,672/438,418 (1.98%) | 2.00% | 7 |
| mg_zs_ev | 33 | 43 | 1,629/82,192 (1.98%) | 2.00% | 2 |
| nissan_leaf_2019 | 12 | 2 | 26,312/1,315,990 (2.00%) | 2.00% | 2 |
| road_ambient | 77 | 29 | 28,139/1,408,887 (2.00%) | 2.00% | 5 |
| tesla | 15 | 29 | 2,144/107,553 (1.99%) | 2.00% | 0 |

## Performance and storage

| Family | models.joblib MB | Load s | score_one ms | Batch µs/row (holdout) |
|---|---|---|---|---|
| hyundai_ioniq5 | 1.2 | 2.5 | 23.5 |  |
| jaguar_ipace | 28.8 | 4.0 | 23.8 | 37.2 |
| kaggle_normal | 15.3 | 2.1 | 23.8 |  |
| kia_ev6 | 78.8 | 13.3 | 24.9 | 18.1 |
| mg_zs_ev | 21.3 | 2.9 | 23.1 | 13.5 |
| nissan_leaf_2019 | 8.3 | 1.0 | 24.1 | 10.6 |
| road_ambient | 42.6 | 6.4 | 23.7 | 23.2 |
| tesla | 8.4 | 1.3 | 24.9 |  |

Total: 371 CAN-ID models, 204.6 MB.

## Top flagged CAN IDs per holdout

- **jaguar_ipace**: 0xA2 1,653 rows 27.0%, 0x2DD 1,362 rows 8.4%, 0x41 1,653 rows 4.6%, 0x8C 822 rows 9.2%, 0xA8 821 rows 6.2%, 0xD 1,653 rows 3.0%
- **kia_ev6**: 0x1CF 21,529 rows 2.7%, 0x2BE 5,931 rows 4.6%, 0x2BC 5,931 rows 4.4%, 0x2BD 5,931 rows 4.4%, 0x419 8,537 rows 2.3%, 0xA3 5,290 rows 2.9%
- **mg_zs_ev**: 0x94 5,162 rows 100.0%, 0x1F1 3,352 rows 0.3%, 0x1F2 3,351 rows 0.0%
- **nissan_leaf_2019**: 0x9 422,863 rows 0.5%, 0x10 21,526 rows 1.3%, 0x1 4,106 rows 2.9%, 0x7BB 11,118 rows 1.1%, 0x4 4,106 rows 2.5%, 0x2 4,106 rows 1.8%
- **road_ambient**: 0x193 3,125 rows 58.2%, 0x125 6,260 rows 21.4%, 0x498 3,125 rows 23.2%, 0x69E 3,125 rows 18.2%, 0x5E1 6,260 rows 8.6%, 0x28B 3,125 rows 13.6%
