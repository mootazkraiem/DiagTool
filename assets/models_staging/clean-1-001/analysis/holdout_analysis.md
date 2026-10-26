# clean-1-001 — holdout analysis (read-only)

Generated for Step 10E. No model, scaler, threshold, manifest or production file was changed. Data: `holdout_analysis.json` (holdout vs training) and `training_id_analysis.json` (training-side per-CAN-ID results); scripts: `step10e_analyze.py`, `step10e_supp.py`, `step10e_report.py`.

A row is *flagged* when the family's normalised score is >= 0.5, i.e. its IsolationForest decision value is below the family threshold. Holdout recordings are unlabelled captures assumed to be normal operation, so the rates below are **holdout flagged rates** (unseen normal traffic flagged), not false-positive rates.

## Summary

| Family | Holdout flagged | Training flagged | Holdout IDs unseen in training | Training IDs flagged 100% in training | Top-10 IDs' share of holdout flags |
|---|---|---|---|---|---|
| jaguar_ipace | 6,651/48,993 (13.58%) | 10.81% | 4/135 (75 rows) | 29/143 | 64.6% |
| kia_ev6 | 24,443/436,455 (5.60%) | 7.39% | 0/170 (0 rows) | 2/187 | 70.5% |
| mg_zs_ev | 3,058/99,619 (3.07%) | 1.16% | 29/38 (81,909 rows) | 0/76 | 97.4% |
| nissan_leaf | 6,317/6,317 (100.00%) | 9.37% | 0/21 (0 rows) | 13/48 | 87.9% |
| nissan_leaf_2019 | 73,277/491,821 (14.90%) | 16.42% | 0/14 (0 rows) | 13/14 | 89.7% |
| road_ambient | 7,072/148,944 (4.75%) | 4.17% | 0/105 (0 rows) | 7/106 | 66.9% |

Families without a holdout (training flagged rate only): hyundai_ioniq5 5.01%, kaggle_normal 8.48%, tesla 23.90%.

## Findings

**1. Model and threshold behaviour — every family.** Each model flags its own training rows at 1.2–23.9%, not the ~2% the contamination setting suggests. Where a holdout exists, the holdout rate tracks the training rate: jaguar_ipace 13.58% vs 10.81%, kia_ev6 5.60% vs 7.39%, nissan_leaf_2019 14.90% vs 16.42%, road_ambient 4.75% vs 4.17%. Those holdout rates are therefore mostly not distribution shift. Two measurable mechanisms:

- *Low-volume CAN IDs are isolated as outliers.* One pooled model per vehicle, with no identifier context, learns the feature region of the IDs that dominate the row count. In training itself the flagged rate falls with ID volume in every family (table "Training flagged rate by CAN-ID volume"). nissan_leaf_2019 is the extreme: 0x9 holds 86% of training rows (3.2% flagged) and **all 13 other IDs are flagged 100% in training** (179,321 rows). tesla: 32 of 44 IDs flagged 100% in training (23.9% overall). kaggle_normal: IDs with < 1% of rows flagged 100%.
- *The threshold sits above the 2% point.* `decision_function` is offset so its 2nd percentile is 0 (contamination 0.02). The median − 3·MAD threshold is positive in 8 of 9 families (0.040–0.163), so it cuts deeper than that point: the decision distribution has a long left tail (median − p01 = 0.185–0.289) and a short right tail (p99 − median = 0.043–0.093), which makes 3·MAD small relative to the tail. mg_zs_ev is the only family whose threshold is below 0 (−0.025, 1.16% flagged in training).

**2. nissan_leaf — recording-source heterogeneity and vehicle mixing (6,317/6,317 holdout rows flagged).** Training is 98.8% one SavvyCAN recording (file name: ZE1 62 kWh; 245,277 rows; 1,197 frames/s; µs timestamps, 0% whole-ms steps) and 1.2% one BusMon recording (file name: ZE0 30 kWh; 2,891 rows). That BusMon training recording is itself **99.9% flagged in training**: the model has learned only the SavvyCAN capture. The holdout is the second BusMon recording: 80 frames/s, millisecond-resolution timestamps (100% whole-ms steps). All 21 holdout IDs exist in training, but their periods differ by source: 0x1DB 11.7 ms (SavvyCAN) / 46.5 ms (BusMon, training) / 76.0 ms (BusMon, holdout); 0x50A 101.6 / 455 / 825 ms. Timing features are displaced (KS: time_diff 0.750, rolling_mean_time_diff 0.762, rolling_std_time_diff 0.988; 64% of holdout rolling_std_time_diff values fall outside the training 0.5–99.5% range). Payload features are not (KS 0.157–0.251; < 1% outside). No single feature reset to its training median un-flags the rows (best: rolling_std_time_diff, 17.5%); the whole timing block is shifted. The same IDs appearing at 4–7× longer periods in both BusMon captures, with a different ratio in each, is consistent with a logger that does not record every bus frame; the recordings are also, by file name, from a different Leaf generation. The data cannot separate those two causes. Either way, these recordings do not form one family.

**3. nissan_leaf_2019 (14.90%).** One car, one logger type (MF4), 8 training recordings with consistent per-recording training flagged rates (14.7–18.6%), no unseen IDs, identical per-ID periods in training and holdout (0x10 200.0 ms; 0x1–0x5 ≈ 1005 ms). 89.7% of holdout flags come from IDs that are also flagged 100% in training (0x10, 0x7BB, 0x1–0x5, ...); the dominant ID 0x9 (422,863 holdout rows) is flagged 1.0%. Feature shift is small (timing KS ≤ 0.035; payload KS 0.147–0.212, < 0.6% outside the training range) and single-feature ablation un-flags ≤ 2.4%. Cause: finding 1 (ID-volume imbalance), not drift.

**4. jaguar_ipace (13.58%).** Training flagged rate 10.81%, per recording 1.27–13.78%. 4 holdout IDs are unseen in training (75 rows, all flagged). The top flagged ID 0x7EC (diagnostic-response range) has 26 training rows at a 24.6 ms period and 908 holdout rows at 4.9 ms: a diagnostic exchange present in the holdout and barely in training. The other top IDs have the same period in training and holdout (0xDB 20.0, 0xFB 40.0, 0x1A1 40.0, 0xEC 50.0 ms) and are low-volume. Causes: finding 1, plus insufficient coverage of diagnostic traffic.

**5. kia_ev6 (5.60%).** The holdout ("Vehicle everything on", 174 IDs, 932 frames/s) resembles the main training recording ("Ignition On, Motor Off", 174 IDs, 930 frames/s; 5.18% flagged in training). The second training recording, "OnlyBattery" (18 IDs, 216 frames/s, a battery-only bench setup), is 30.83% flagged in training: two configurations in one family. No unseen IDs; per-ID periods match (0x419 38.9 / 38.9 ms).

**6. mg_zs_ev (3.07%).** The rate is low but **coverage is poor**: 29 of 38 holdout IDs never occur in training and carry 81,909 of 99,619 holdout rows (82%); 2,334 of the 3,058 flags are on those unseen IDs. Training (2 kW charge, 78 IDs) and holdout (6 kW charge, 39 IDs) expose different identifier sets, and only 9 IDs are shared. A low flagged rate here does not show that the model has learned this traffic.

**7. road_ambient (4.75%).** Consistent with training (4.17%; per recording 2.28–6.51%), no unseen IDs, identical per-ID periods. Flags concentrate on low-volume IDs (training: IDs with < 0.1% of rows flagged 55.3%). Among flagged holdout rows the byte features are most often outside the training range (13–16%), but ablation shows the timing features carry more of the decision (20–31% un-flagged).

## Cause attribution

| Cause | Families | Evidence |
|---|---|---|
| Model/threshold behaviour: ID-volume imbalance in a pooled model; threshold above the 2% point | all | training flagged rate 1.2–23.9%; flagged rate falls with ID volume in every family; threshold > decision p02 (= 0) in 8/9 |
| Recording-tool difference | nissan_leaf | BusMon: ms timestamps, 80–117 frames/s; SavvyCAN: µs, 1,197 frames/s; same IDs at 4–7× the period |
| Vehicle-family mixing | nissan_leaf | ZE0 30 kWh and ZE1 62 kWh recordings in one family; BusMon training recording 99.9% flagged in training |
| Data heterogeneity (configurations) | kia_ev6, jaguar_ipace | kia OnlyBattery 30.8% vs 5.2% flagged in training; jaguar per-recording 1.3–13.8% |
| Insufficient training coverage | mg_zs_ev, jaguar_ipace | mg: 82% of holdout rows on IDs absent from training; jaguar 0x7EC: 26 training rows |
| Feature instability | none found | canonical features reproduce identical per-ID periods across recordings of the same source; KS is small except where sources differ |


## Training flagged rate by CAN-ID volume (training rows)

| Family | IDs < 0.1% of rows | 0.1-1% | 1-5% | >= 5% |
|---|---|---|---|---|
| hyundai_ioniq5 | — | — | 100.00% (2 IDs, 1,489 rows) | 2.26% (2 IDs, 51,508 rows) |
| jaguar_ipace | 65.80% (42 IDs, 5,123 rows) | 27.18% (68 IDs, 55,320 rows) | 4.19% (32 IDs, 156,184 rows) | 0.02% (1 IDs, 14,176 rows) |
| kaggle_normal | 100.00% (2 IDs, 994 rows) | 100.00% (3 IDs, 15,170 rows) | 45.25% (5 IDs, 111,373 rows) | 2.01% (17 IDs, 861,064 rows) |
| kia_ev6 | 18.22% (25 IDs, 7,210 rows) | 4.22% (141 IDs, 303,081 rows) | 13.88% (21 IDs, 136,024 rows) | — |
| mg_zs_ev | 0.00% (2 IDs, 48 rows) | 6.76% (41 IDs, 16,990 rows) | 0.00% (33 IDs, 82,192 rows) | — |
| nissan_leaf | 100.00% (6 IDs, 330 rows) | 27.29% (32 IDs, 56,702 rows) | 63.10% (1 IDs, 5,122 rows) | 2.26% (9 IDs, 186,014 rows) |
| nissan_leaf_2019 | 100.00% (2 IDs, 36 rows) | 100.00% (9 IDs, 97,020 rows) | 100.00% (2 IDs, 82,265 rows) | 3.24% (1 IDs, 1,136,705 rows) |
| road_ambient | 55.32% (34 IDs, 23,603 rows) | 12.94% (41 IDs, 225,411 rows) | 1.60% (30 IDs, 1,083,924 rows) | 0.03% (1 IDs, 93,684 rows) |
| tesla | 100.00% (3 IDs, 178 rows) | 100.00% (26 IDs, 9,882 rows) | 35.06% (13 IDs, 41,123 rows) | 5.47% (2 IDs, 66,430 rows) |

## Threshold position per family (training decision values)

| Family | Threshold | Median | MAD | Decision p02 | Median - p01 | p99 - median | Training flagged |
|---|---|---|---|---|---|---|---|
| hyundai_ioniq5 | 0.0990 | 0.2473 | 0.0494 | -0.0000 | 0.289 | 0.071 | 5.01% |
| jaguar_ipace | 0.0660 | 0.1504 | 0.0281 | 0.0000 | 0.185 | 0.057 | 10.81% |
| kaggle_normal | 0.0660 | 0.1475 | 0.0271 | 0.0000 | 0.185 | 0.070 | 8.48% |
| kia_ev6 | 0.0431 | 0.1726 | 0.0432 | 0.0000 | 0.196 | 0.069 | 7.39% |
| mg_zs_ev | -0.0245 | 0.1727 | 0.0658 | 0.0000 | 0.199 | 0.093 | 1.16% |
| nissan_leaf | 0.0673 | 0.1661 | 0.0329 | -0.0000 | 0.193 | 0.052 | 9.37% |
| nissan_leaf_2019 | 0.1634 | 0.2422 | 0.0263 | 0.0000 | 0.267 | 0.048 | 16.42% |
| road_ambient | 0.0396 | 0.1515 | 0.0373 | 0.0000 | 0.187 | 0.079 | 4.17% |
| tesla | 0.1519 | 0.2165 | 0.0215 | 0.0000 | 0.228 | 0.043 | 23.90% |

## jaguar_ipace

Features used: time_diff, rolling_mean_time_diff, rolling_std_time_diff, byte_diff, rolling_mean_byte_diff, rolling_std_byte_diff, rolling_max_byte_diff, changed_bytes_count, payload_entropy. Threshold 0.066000.

| Recording | Role | Format | Frames | Duration s | Frames/s | IDs | Whole-ms steps | Training flagged |
|---|---|---|---|---|---|---|---|---|
| EV-CANlogs-main/Jaguar IPACE/battery_canbus_5s_suspending.csv | train | savvycan_csv | 15,373 | 7.4 | 2068.6 | 18 | 0.000 | 1.27% |
| EV-CANlogs-main/Jaguar IPACE/canbus_car_turning_on_off_lots2.csv | train | savvycan_csv | 72,243 | 24.1 | 3002.6 | 134 | 0.000 | 13.78% |
| EV-CANlogs-main/Jaguar IPACE/canbus_turning_on.csv | train | savvycan_csv | 145,982 | 51.2 | 2850.8 | 137 | 0.000 | 10.36% |
| EV-CANlogs-main/Jaguar IPACE/canbus_turningon_quickly.csv | holdout | savvycan_csv | 50,361 | 16.6 | 3028.2 | 146 | 0.000 | — |

| Score | p1 | p5 | p25 | p50 | p75 | p95 | p99 |
|---|---|---|---|---|---|---|---|
| training, normalised | 0.000 | 0.000 | 0.000 | 0.000 | 0.124 | 0.762 | 1.000 |
| holdout, normalised | 0.000 | 0.000 | 0.000 | 0.000 | 0.175 | 0.932 | 1.000 |
| training, decision | -0.035 | 0.031 | 0.116 | 0.150 | 0.175 | 0.201 | 0.207 |
| holdout, decision | -0.060 | 0.009 | 0.109 | 0.152 | 0.178 | 0.203 | 0.207 |

Training rows scored for percentiles: 230,803 of 230,803 (every 1th row); training flagged rate above uses all rows.

| Feature | KS | Train p50 | Holdout p50 | Holdout outside train p0.5-p99.5 | Flagged rows outside | Flagged rows un-flagged when set to train median |
|---|---|---|---|---|---|---|
| time_diff | 0.061 | 3.035 | 3.039 | 0.45% | 2.95% | 17.0% |
| rolling_mean_time_diff | 0.061 | 3.044 | 3.044 | 0.39% | 2.53% | 11.7% |
| rolling_std_time_diff | 0.065 | 0.238 | 0.239 | 0.77% | 3.74% | 19.8% |
| byte_diff | 0.061 | 0.405 | 1.253 | 0.88% | 6.50% | 0.0% |
| rolling_mean_byte_diff | 0.061 | 1.078 | 1.960 | 0.77% | 5.22% | 0.0% |
| rolling_std_byte_diff | 0.060 | 0.532 | 0.697 | 0.85% | 6.25% | 0.0% |
| rolling_max_byte_diff | 0.061 | 2.630 | 2.918 | 0.70% | 5.19% | 1.0% |
| changed_bytes_count | 0.061 | 2.000 | 2.000 | 0.63% | 4.66% | 7.8% |
| payload_entropy | 0.074 | 1.549 | 2.000 | 0.00% | 0.00% | 10.2% |

CAN IDs: training 143, holdout 135, shared 131, holdout-only: 0x27C, 0x77D, 0x7E5, 0x7ED.

| CAN ID | Holdout rows | Flagged | Holdout flagged rate | Training rows | Training flagged rate | Period ms per training recording | Period ms holdout |
|---|---|---|---|---|---|---|---|
| 0x7EC | 908 | 908 | 100.0% | 26 | 53.85% | 24.6 | 4.9 |
| 0xBF | 924 | 596 | 64.5% | 2,049 | 30.16% | 11.0, 10.2 | 10.2 |
| 0xDB | 822 | 512 | 62.3% | 3,743 | 66.44% | 20.0, 20.0 | 20.0 |
| 0x44 | 1,653 | 494 | 29.9% | 7,507 | 33.50% | 10.0, 10.0 | 10.0 |
| 0xFB | 406 | 406 | 100.0% | 1,861 | 94.84% | 40.0, 40.0 | 40.0 |
| 0x1A1 | 406 | 406 | 100.0% | 1,862 | 91.84% | 40.0, 40.0 | 39.9 |
| 0xEC | 323 | 306 | 94.7% | 1,485 | 77.44% | 50.0, 50.0 | 50.0 |
| 0x104 | 406 | 273 | 67.2% | 2,022 | 62.36% | 20.0, 40.0, 40.0 | 40.0 |
| 0x135 | 198 | 198 | 100.0% | 921 | 100.00% | 80.0, 80.0 | 80.0 |
| 0x2DD | 1,362 | 196 | 14.4% | 6,120 | 13.59% | 13.7, 11.0 | 10.6 |

Top-10 IDs account for 64.6% of holdout flags. Full per-ID table: `holdout_analysis.json`.

## kia_ev6

Features used: time_diff, rolling_mean_time_diff, rolling_std_time_diff, byte_diff, rolling_mean_byte_diff, rolling_std_byte_diff, rolling_max_byte_diff, changed_bytes_count, payload_entropy. Threshold 0.043085.

| Recording | Role | Format | Frames | Duration s | Frames/s | IDs | Whole-ms steps | Training flagged |
|---|---|---|---|---|---|---|---|---|
| EV-CANlogs-main/Kia EV6/Ignition On, Motor Off.asc | train | vector_asc | 409,416 | 440.3 | 929.9 | 174 | 0.004 | 5.18% |
| EV-CANlogs-main/Kia EV6/OnlyBattery.asc | train | vector_asc | 38,782 | 179.4 | 216.2 | 18 | 0.001 | 30.83% |
| EV-CANlogs-main/Kia EV6/Vehicle everthing on.asc | holdout | vector_asc | 438,170 | 470.0 | 932.3 | 174 | 0.004 | — |

| Score | p1 | p5 | p25 | p50 | p75 | p95 | p99 |
|---|---|---|---|---|---|---|---|
| training, normalised | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.662 | 1.000 |
| holdout, normalised | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.545 | 1.000 |
| training, decision | -0.024 | 0.029 | 0.121 | 0.173 | 0.213 | 0.236 | 0.241 |
| holdout, decision | -0.001 | 0.039 | 0.127 | 0.177 | 0.214 | 0.237 | 0.241 |

Training rows scored for percentiles: 446,315 of 446,315 (every 1th row); training flagged rate above uses all rows.

| Feature | KS | Train p50 | Holdout p50 | Holdout outside train p0.5-p99.5 | Flagged rows outside | Flagged rows un-flagged when set to train median |
|---|---|---|---|---|---|---|
| time_diff | 0.032 | 4.617 | 4.629 | 0.57% | 5.22% | 27.3% |
| rolling_mean_time_diff | 0.035 | 4.615 | 4.615 | 0.74% | 6.88% | 19.7% |
| rolling_std_time_diff | 0.066 | 3.174 | 3.294 | 1.41% | 10.97% | 24.2% |
| byte_diff | 0.062 | 0.000 | 0.000 | 0.01% | 0.09% | 9.4% |
| rolling_mean_byte_diff | 0.068 | 0.000 | 0.000 | 0.00% | 0.00% | 20.8% |
| rolling_std_byte_diff | 0.061 | 0.000 | 0.000 | 0.00% | 0.05% | 23.0% |
| rolling_max_byte_diff | 0.065 | 0.000 | 0.000 | 0.01% | 0.11% | 15.3% |
| changed_bytes_count | 0.065 | 0.000 | 0.000 | 0.00% | 0.05% | 14.6% |
| payload_entropy | 0.029 | 2.000 | 1.750 | 0.00% | 0.00% | 22.2% |

CAN IDs: training 187, holdout 170, shared 170, holdout-only: none.

| CAN ID | Holdout rows | Flagged | Holdout flagged rate | Training rows | Training flagged rate | Period ms per training recording | Period ms holdout |
|---|---|---|---|---|---|---|---|
| 0x419 | 8,537 | 4,293 | 50.3% | 7,967 | 49.25% | 38.9 | 38.9 |
| 0xEC | 4,744 | 3,186 | 67.2% | 4,345 | 66.77% | 49.7 | 49.4 |
| 0x4E | 5,288 | 2,324 | 43.9% | 4,869 | 39.60% | 49.5 | 49.2 |
| 0x4C | 5,288 | 1,956 | 37.0% | 4,869 | 36.68% | 49.1 | 49.0 |
| 0x41C | 5,508 | 1,159 | 21.0% | 5,274 | 19.81% | 41.2 | 41.1 |
| 0x30E | 1,190 | 991 | 83.3% | 1,090 | 82.29% | 200.0 | 200.1 |
| 0x2FC | 1,316 | 938 | 71.3% | 1,210 | 75.95% | 200.0 | 200.1 |
| 0x30D | 1,190 | 900 | 75.6% | 1,090 | 75.23% | 200.1 | 200.2 |
| 0x4F0 | 1,670 | 818 | 49.0% | 1,589 | 47.95% | 77.3 | 76.9 |
| 0x25E | 1,316 | 664 | 50.5% | 1,210 | 46.86% | 200.0 | 200.1 |

Top-10 IDs account for 70.5% of holdout flags. Full per-ID table: `holdout_analysis.json`.

## mg_zs_ev

Features used: time_diff, rolling_mean_time_diff, rolling_std_time_diff, byte_diff, rolling_mean_byte_diff, rolling_std_byte_diff, rolling_max_byte_diff, changed_bytes_count, payload_entropy. Threshold -0.024546.

| Recording | Role | Format | Frames | Duration s | Frames/s | IDs | Whole-ms steps | Training flagged |
|---|---|---|---|---|---|---|---|---|
| EV-CANlogs-main/MG ZS EV/Charging_2kW_CAN1_Test1.asc | train | vector_asc | 100,000 | 35.1 | 2845.8 | 78 | 0.007 | 1.16% |
| EV-CANlogs-main/MG ZS EV/Charging_6kW_CAN1_Test2.asc | holdout | vector_asc | 100,000 | 68.0 | 1471.2 | 39 | 0.014 | — |

| Score | p1 | p5 | p25 | p50 | p75 | p95 | p99 |
|---|---|---|---|---|---|---|---|
| training, normalised | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.542 |
| holdout, normalised | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.121 | 0.811 |
| training, decision | -0.027 | 0.035 | 0.116 | 0.173 | 0.244 | 0.260 | 0.265 |
| holdout, decision | -0.040 | -0.006 | 0.087 | 0.118 | 0.203 | 0.260 | 0.266 |

Training rows scored for percentiles: 99,230 of 99,230 (every 1th row); training flagged rate above uses all rows.

| Feature | KS | Train p50 | Holdout p50 | Holdout outside train p0.5-p99.5 | Flagged rows outside | Flagged rows un-flagged when set to train median |
|---|---|---|---|---|---|---|
| time_diff | 0.124 | 2.493 | 2.442 | 0.14% | 1.24% | 89.9% |
| rolling_mean_time_diff | 0.146 | 2.410 | 2.407 | 0.93% | 3.37% | 95.1% |
| rolling_std_time_diff | 0.160 | 0.322 | 0.345 | 1.98% | 34.47% | 52.5% |
| byte_diff | 0.214 | 0.000 | 0.223 | 0.00% | 0.10% | 10.4% |
| rolling_mean_byte_diff | 0.229 | 0.000 | 0.405 | 0.00% | 0.00% | 32.2% |
| rolling_std_byte_diff | 0.145 | 0.000 | 0.000 | 0.01% | 0.36% | 67.8% |
| rolling_max_byte_diff | 0.208 | 0.000 | 0.811 | 0.02% | 0.69% | 45.3% |
| changed_bytes_count | 0.231 | 0.000 | 2.000 | 0.01% | 0.20% | 7.5% |
| payload_entropy | 0.189 | 0.811 | 1.500 | 0.00% | 0.00% | 9.6% |

CAN IDs: training 76, holdout 38, shared 9, holdout-only: 0x14B, 0x171, 0x172, 0x173, 0x293, 0x295, 0x299, 0x29C, 0x2A0, 0x2B5, 0x2B6, 0x394, 0x396, 0x39A, 0x3A6, 0x3B8, 0x3BA, 0x3BC, 0x3BE, 0x43C, 0x692, 0x88, 0x8A, 0x8D, 0x8E, 0x8F, 0x99, 0x9B, 0xDF.

| CAN ID | Holdout rows | Flagged | Holdout flagged rate | Training rows | Training flagged rate | Period ms per training recording | Period ms holdout |
|---|---|---|---|---|---|---|---|
| 0x2B5 | 508 | 508 | 100.0% | 0 | — | — | 100.9 |
| 0x2A0 | 664 | 502 | 75.6% | 0 | — | — | 101.0 |
| 0x2B6 | 508 | 462 | 90.9% | 0 | — | — | 101.0 |
| 0x299 | 1,336 | 459 | 34.4% | 0 | — | — | 50.5 |
| 0x39B | 506 | 396 | 78.3% | 336 | 0.00% | 101.0 | 100.9 |
| 0x29B | 1,337 | 262 | 19.6% | 686 | 75.22% | 50.5 | 50.5 |
| 0x3BE | 664 | 147 | 22.1% | 0 | — | — | 100.9 |
| 0x3B8 | 664 | 106 | 16.0% | 0 | — | — | 100.9 |
| 0x394 | 662 | 103 | 15.6% | 0 | — | — | 101.0 |
| 0x297 | 1,337 | 33 | 2.5% | 686 | 0.00% | 50.5 | 50.5 |

Top-10 IDs account for 97.4% of holdout flags. Full per-ID table: `holdout_analysis.json`.

## nissan_leaf

Features used: time_diff, rolling_mean_time_diff, rolling_std_time_diff, byte_diff, rolling_mean_byte_diff, rolling_std_byte_diff, rolling_max_byte_diff, changed_bytes_count, payload_entropy. Threshold 0.067270.

| Recording | Role | Format | Frames | Duration s | Frames/s | IDs | Whole-ms steps | Training flagged |
|---|---|---|---|---|---|---|---|---|
| EV-CANlogs-main/Nissan LEAF/62kWh/Nissan leaf 62kwh fast charging from 80ish soc , car is off and charger wakes car up, charging , then charger ends session v2.csv | train | savvycan_csv | 245,708 | 205.3 | 1196.6 | 44 | 0.000 | 8.30% |
| EV-CANlogs-main/Nissan LEAF/Special Logs from battery upgraded LEAFs/QC_ZE0_30kWhABB_FAIL.txt | train | busmon | 3,099 | 26.5 | 116.8 | 21 | 1.000 | 99.90% |
| EV-CANlogs-main/Nissan LEAF/Special Logs from battery upgraded LEAFs/QC_ZE0_30kWhABB_SUCCESS_PER.txt | holdout | busmon | 6,529 | 81.5 | 80.1 | 23 | 1.000 | — |

| Score | p1 | p5 | p25 | p50 | p75 | p95 | p99 |
|---|---|---|---|---|---|---|---|
| training, normalised | 0.000 | 0.000 | 0.000 | 0.000 | 0.125 | 0.682 | 1.000 |
| holdout, normalised | 0.993 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| training, decision | -0.027 | 0.043 | 0.118 | 0.166 | 0.192 | 0.209 | 0.218 |
| holdout, decision | -0.103 | -0.086 | -0.056 | -0.028 | -0.013 | -0.003 | 0.001 |

Training rows scored for percentiles: 248,168 of 248,168 (every 1th row); training flagged rate above uses all rows.

| Feature | KS | Train p50 | Holdout p50 | Holdout outside train p0.5-p99.5 | Flagged rows outside | Flagged rows un-flagged when set to train median |
|---|---|---|---|---|---|---|
| time_diff | 0.750 | 2.543 | 4.407 | 19.12% | 19.12% | 0.0% |
| rolling_mean_time_diff | 0.762 | 2.412 | 4.422 | 19.47% | 19.47% | 0.0% |
| rolling_std_time_diff | 0.988 | 1.069 | 3.048 | 64.35% | 64.35% | 17.5% |
| byte_diff | 0.171 | 1.139 | 2.485 | 0.09% | 0.09% | 0.0% |
| rolling_mean_byte_diff | 0.197 | 2.239 | 2.304 | 0.00% | 0.00% | 0.0% |
| rolling_std_byte_diff | 0.183 | 2.041 | 2.078 | 0.19% | 0.19% | 0.0% |
| rolling_max_byte_diff | 0.197 | 2.803 | 2.876 | 0.65% | 0.65% | 0.0% |
| changed_bytes_count | 0.157 | 2.000 | 2.000 | 0.16% | 0.16% | 0.0% |
| payload_entropy | 0.251 | 2.406 | 2.750 | 0.00% | 0.00% | 0.0% |

CAN IDs: training 48, holdout 21, shared 21, holdout-only: none.

| CAN ID | Holdout rows | Flagged | Holdout flagged rate | Training rows | Training flagged rate | Period ms per training recording | Period ms holdout |
|---|---|---|---|---|---|---|---|
| 0x1DB | 1,020 | 1,020 | 100.0% | 20,749 | 2.22% | 11.7, 46.5 | 76.0 |
| 0x1DC | 1,020 | 1,020 | 100.0% | 20,750 | 4.41% | 11.7, 46.0 | 76.0 |
| 0x1D4 | 1,011 | 1,011 | 100.0% | 21,041 | 2.48% | 11.7, 44.0 | 77.0 |
| 0x1F2 | 1,011 | 1,011 | 100.0% | 21,040 | 6.10% | 11.7, 44.0 | 77.0 |
| 0x1DA | 1,007 | 1,007 | 100.0% | 20,905 | 2.46% | 11.7, 43.0 | 76.0 |
| 0x380 | 109 | 109 | 100.0% | 46 | 100.00% | 448.0 | 784.5 |
| 0x50A | 94 | 94 | 100.0% | 2,086 | 45.54% | 101.6, 455.0 | 825.0 |
| 0x54A | 94 | 94 | 100.0% | 2,074 | 100.00% | 101.6, 464.0 | 799.0 |
| 0x54B | 94 | 94 | 100.0% | 2,074 | 2.03% | 101.6, 464.0 | 799.0 |
| 0x54C | 94 | 94 | 100.0% | 2,075 | 3.13% | 101.6, 449.5 | 799.0 |

Top-10 IDs account for 87.9% of holdout flags. Full per-ID table: `holdout_analysis.json`.

## nissan_leaf_2019

Features used: time_diff, rolling_mean_time_diff, rolling_std_time_diff, byte_diff, rolling_mean_byte_diff, rolling_std_byte_diff, rolling_max_byte_diff, changed_bytes_count. Threshold 0.163357.

| Recording | Role | Format | Frames | Duration s | Frames/s | IDs | Whole-ms steps | Training flagged |
|---|---|---|---|---|---|---|---|---|
| Train/Nissan Leaf 2019/LOG/2F6913DB/00000014/00000001-61D93E3C.MF4 | train | mf4 | 26,378 | 244.8 | 107.8 | 16 | 0.452 | 15.23% |
| Train/Nissan Leaf 2019/LOG/2F6913DB/00000014/00000002-61D93E42.MF4 | train | mf4 | 34,317 | 300.0 | 114.4 | 12 | 0.452 | 14.73% |
| Train/Nissan Leaf 2019/LOG/2F6913DB/00000014/00000003-61D93E49.MF4 | train | mf4 | 19,385 | 169.5 | 114.3 | 12 | 0.455 | 15.26% |
| Train/Nissan Leaf 2019/LOG/2F6913DB/00000016/00000001-61D94900.MF4 | train | mf4 | 2,685 | 38.7 | 69.3 | 11 | 0.462 | 18.64% |
| Train/Nissan Leaf 2019/LOG/2F6913DB/00000017/00000001-61D9D6F7.MF4 | train | mf4 | 585,160 | 5170.0 | 113.2 | 16 | 0.467 | 15.84% |
| Train/Nissan Leaf 2019/LOG/2F6913DB/00000017/00000002-61D9D7B9.MF4 | train | mf4 | 281,826 | 2466.1 | 114.3 | 12 | 0.449 | 17.82% |
| Train/Nissan Leaf 2019/LOG/2F6913DB/00000019/00000001-61D9D80A.MF4 | train | mf4 | 154,896 | 1368.8 | 113.2 | 16 | 0.459 | 16.76% |
| Train/Nissan Leaf 2019/LOG/2F6913DB/00000020/00000001-61D9D830.MF4 | train | mf4 | 212,423 | 1870.5 | 113.6 | 16 | 0.457 | 16.43% |
| Train/Nissan Leaf 2019/LOG/2F6913DB/00000021/00000001-61D9D9BA.MF4 | holdout | mf4 | 491,969 | 4312.7 | 114.1 | 16 | 0.469 | — |

| Score | p1 | p5 | p25 | p50 | p75 | p95 | p99 |
|---|---|---|---|---|---|---|---|
| training, normalised | 0.112 | 0.132 | 0.191 | 0.259 | 0.372 | 0.912 | 1.000 |
| holdout, normalised | 0.108 | 0.125 | 0.170 | 0.226 | 0.326 | 0.917 | 1.000 |
| training, decision | -0.025 | 0.029 | 0.205 | 0.242 | 0.264 | 0.283 | 0.290 |
| holdout, decision | -0.026 | 0.027 | 0.220 | 0.253 | 0.271 | 0.286 | 0.292 |

Training rows scored for percentiles: 438,676 of 1,316,026 (every 3th row); training flagged rate above uses all rows.

| Feature | KS | Train p50 | Holdout p50 | Holdout outside train p0.5-p99.5 | Flagged rows outside | Flagged rows un-flagged when set to train median |
|---|---|---|---|---|---|---|
| time_diff | 0.035 | 2.398 | 2.398 | 0.96% | 4.49% | 2.0% |
| rolling_mean_time_diff | 0.022 | 2.416 | 2.416 | 0.82% | 3.38% | 2.0% |
| rolling_std_time_diff | 0.010 | 0.598 | 0.590 | 0.91% | 5.50% | 2.0% |
| byte_diff | 0.147 | 3.102 | 3.434 | 0.36% | 2.43% | 2.2% |
| rolling_mean_byte_diff | 0.212 | 3.375 | 3.581 | 0.18% | 1.17% | 0.8% |
| rolling_std_byte_diff | 0.201 | 2.791 | 2.966 | 0.59% | 2.95% | 1.5% |
| rolling_max_byte_diff | 0.212 | 4.067 | 4.234 | 0.11% | 0.76% | 1.1% |
| changed_bytes_count | 0.156 | 4.000 | 5.000 | 0.00% | 0.00% | 2.4% |

CAN IDs: training 14, holdout 14, shared 14, holdout-only: none.

| CAN ID | Holdout rows | Flagged | Holdout flagged rate | Training rows | Training flagged rate | Period ms per training recording | Period ms holdout |
|---|---|---|---|---|---|---|---|
| 0x10 | 21,526 | 21,526 | 100.0% | 57,929 | 100.00% | 200.0, 200.0, 200.0, 200.0, 200.0, 200.0, 200.0, 200.0 | 200.0 |
| 0x7BB | 11,118 | 11,118 | 100.0% | 24,336 | 100.00% | 12.0, 12.0, 12.0, 12.0, 12.0, 12.1, 12.0 | 12.0 |
| 0x9 | 422,863 | 4,319 | 1.0% | 1,136,705 | 3.24% | 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0 | 10.0 |
| 0x1 | 4,106 | 4,106 | 100.0% | 10,974 | 100.00% | 1007.2, 1006.1, 1004.5, 998.2, 1005.3, 1005.2, 1005.3, 1005.6 | 1005.4 |
| 0x2 | 4,106 | 4,106 | 100.0% | 10,974 | 100.00% | 1007.1, 1006.1, 1004.4, 998.1, 1005.3, 1005.2, 1005.4, 1005.6 | 1005.4 |
| 0x3 | 4,106 | 4,106 | 100.0% | 10,974 | 100.00% | 1007.1, 1006.0, 1004.4, 998.2, 1005.3, 1005.2, 1005.4, 1005.6 | 1005.4 |
| 0x4 | 4,106 | 4,106 | 100.0% | 10,974 | 100.00% | 1007.1, 1006.0, 1004.4, 998.1, 1005.3, 1005.2, 1005.3, 1005.6 | 1005.4 |
| 0x5 | 4,106 | 4,106 | 100.0% | 10,974 | 100.00% | 1007.1, 1006.1, 1004.4, 998.1, 1005.3, 1005.2, 1005.3, 1005.6 | 1005.4 |
| 0x6 | 4,106 | 4,106 | 100.0% | 10,974 | 100.00% | 1007.1, 1006.0, 1004.4, 998.2, 1005.3, 1005.3, 1005.3, 1005.6 | 1005.4 |
| 0x7 | 4,106 | 4,106 | 100.0% | 10,974 | 100.00% | 1007.1, 1006.1, 1004.4, 998.2, 1005.3, 1005.2, 1005.3, 1005.6 | 1005.4 |

Top-10 IDs account for 89.7% of holdout flags. Full per-ID table: `holdout_analysis.json`.

## road_ambient

Features used: time_diff, rolling_mean_time_diff, rolling_std_time_diff, byte_diff, rolling_mean_byte_diff, rolling_std_byte_diff, rolling_max_byte_diff, changed_bytes_count, payload_entropy. Threshold 0.039567.

| Recording | Role | Format | Frames | Duration s | Frames/s | IDs | Whole-ms steps | Training flagged |
|---|---|---|---|---|---|---|---|---|
| road/road/ambient/ambient_dyno_drive_basic_long.log | train | candump_ts | 150,000 | 62.7 | 2391.6 | 106 | 0.000 | 3.94% |
| road/road/ambient/ambient_dyno_drive_basic_short.log | train | candump_ts | 150,000 | 62.7 | 2392.5 | 106 | 0.000 | 5.40% |
| road/road/ambient/ambient_dyno_drive_extended_long.log | train | candump_ts | 150,000 | 117.8 | 1273.0 | 106 | 0.000 | 3.62% |
| road/road/ambient/ambient_dyno_drive_extended_short.log | train | candump_ts | 150,000 | 76.0 | 1972.7 | 106 | 0.000 | 3.27% |
| road/road/ambient/ambient_dyno_drive_radio_infotainment.log | train | candump_ts | 150,000 | 62.8 | 2390.1 | 106 | 0.000 | 2.28% |
| road/road/ambient/ambient_dyno_drive_winter.log | train | candump_ts | 114,148 | 47.7 | 2391.5 | 106 | 0.000 | 5.08% |
| road/road/ambient/ambient_dyno_exercise_all_bits.log | train | candump_ts | 150,000 | 189.0 | 793.8 | 106 | 0.000 | 4.95% |
| road/road/ambient/ambient_dyno_idle_radio_infotainment.log | train | candump_ts | 150,000 | 63.5 | 2363.3 | 106 | 0.000 | 3.11% |
| road/road/ambient/ambient_dyno_reverse.log | train | candump_ts | 123,047 | 51.4 | 2392.3 | 106 | 0.000 | 3.72% |
| road/road/ambient/ambient_highway_street_driving_diagnostics.log | train | candump_ts | 150,000 | 62.7 | 2393.7 | 106 | 0.000 | 6.51% |
| road/road/ambient/ambient_highway_street_driving_long.log | holdout | candump_ts | 150,000 | 62.7 | 2392.0 | 106 | 0.000 | — |

| Score | p1 | p5 | p25 | p50 | p75 | p95 | p99 |
|---|---|---|---|---|---|---|---|
| training, normalised | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.394 | 1.000 |
| holdout, normalised | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.470 | 1.000 |
| training, decision | -0.035 | 0.048 | 0.118 | 0.152 | 0.191 | 0.227 | 0.231 |
| holdout, decision | -0.024 | 0.042 | 0.109 | 0.145 | 0.176 | 0.223 | 0.230 |

Training rows scored for percentiles: 475,541 of 1,426,622 (every 3th row); training flagged rate above uses all rows.

| Feature | KS | Train p50 | Holdout p50 | Holdout outside train p0.5-p99.5 | Flagged rows outside | Flagged rows un-flagged when set to train median |
|---|---|---|---|---|---|---|
| time_diff | 0.041 | 3.042 | 3.035 | 0.99% | 4.43% | 26.8% |
| rolling_mean_time_diff | 0.032 | 3.044 | 3.044 | 1.09% | 3.11% | 30.9% |
| rolling_std_time_diff | 0.063 | 0.483 | 0.500 | 0.25% | 4.40% | 20.3% |
| byte_diff | 0.104 | 0.000 | 0.405 | 0.66% | 13.83% | 3.2% |
| rolling_mean_byte_diff | 0.126 | 0.336 | 1.030 | 0.74% | 15.60% | 0.4% |
| rolling_std_byte_diff | 0.126 | 0.238 | 0.920 | 0.57% | 9.05% | 1.1% |
| rolling_max_byte_diff | 0.120 | 0.754 | 1.891 | 0.63% | 13.09% | 0.2% |
| changed_bytes_count | 0.094 | 0.000 | 1.000 | 0.16% | 3.39% | 14.0% |
| payload_entropy | 0.076 | 2.500 | 2.750 | 0.00% | 0.00% | 19.2% |

CAN IDs: training 106, holdout 105, shared 105, holdout-only: none.

| CAN ID | Holdout rows | Flagged | Holdout flagged rate | Training rows | Training flagged rate | Period ms per training recording | Period ms holdout |
|---|---|---|---|---|---|---|---|
| 0x434 | 3,125 | 1,420 | 45.4% | 35,454 | 29.32% | 20.0, 20.0, 20.0, 20.0, 20.0, 20.0, 20.0, 20.0, 20.0, 20.0 | 20.0 |
| 0x2C1 | 587 | 574 | 97.8% | 4,569 | 96.17% | 105.0, 105.0, 105.0, 105.0, 105.0, 105.0, 105.1, 105.0, 105.0, 105.0 | 105.0 |
| 0x3D | 617 | 476 | 77.1% | 5,414 | 47.14% | 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0 | 100.0 |
| 0x33 | 6,260 | 405 | 6.5% | 54,091 | 2.97% | 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 9.9, 10.0, 10.1, 10.0 | 10.0 |
| 0x2D2 | 617 | 403 | 65.3% | 5,414 | 57.19% | 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0 | 100.0 |
| 0x498 | 3,125 | 349 | 11.2% | 35,455 | 0.67% | 20.0, 20.0, 20.0, 20.0, 20.0, 20.0, 20.0, 20.0, 20.0, 20.0 | 20.0 |
| 0x6E0 | 6,261 | 324 | 5.2% | 71,006 | 4.46% | 10.4, 10.0, 9.7, 9.9, 10.0, 10.0, 9.7, 10.0, 9.7, 10.1 | 10.1 |
| 0x51B | 303 | 303 | 100.0% | 3,748 | 100.00% | 200.0, 200.0, 200.0, 200.0, 200.0, 200.0, 200.1, 200.0, 200.0, 200.0 | 200.0 |
| 0x1C4 | 240 | 240 | 100.0% | 2,979 | 100.00% | 250.0, 250.0, 250.0, 250.0, 250.0, 250.0, 250.1, 250.0, 249.9, 250.0 | 250.0 |
| 0x2A4 | 240 | 240 | 100.0% | 2,977 | 100.00% | 250.0, 249.7, 250.0, 250.1, 250.0, 250.4, 250.1, 249.9, 250.0, 250.0 | 250.0 |

Top-10 IDs account for 66.9% of holdout flags. Full per-ID table: `holdout_analysis.json`.
