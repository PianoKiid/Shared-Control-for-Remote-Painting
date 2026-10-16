# Transition-aware analysis of the LOPO Causal LSTM

- Data: 22 trials, 61 valid sequences, 115.3 min
- Stable detection: the predicted target phase persists for at least 150 ms
- This is causal offline replay; no robot controller or contact-force outcome is included.
- One saved checkpoint per LOPO fold was available; this is not a five-seed transition analysis.

## Phase episode duration and detectability

| Phase | Episodes | Median duration (s) | <0.5 s | Any detection | Stable 150-ms detection | Median occupancy recall |
|---|---:|---:|---:|---:|---:|---:|
| FREE_MOTION | 350 | 3.022 | 4.3% | 80.3% | 78.0% | 0.617 |
| APPROACH | 154 | 1.299 | 18.2% | 64.3% | 61.0% | 0.369 |
| PAINTING | 318 | 9.125 | 3.1% | 97.5% | 96.9% | 0.976 |
| RETRACT | 141 | 1.027 | 19.1% | 66.0% | 50.4% | 0.193 |

### Short transition-phase detectability

| Phase | Episode duration | N | Any detection | Stable 150-ms detection | Median occupancy recall |
|---|---|---:|---:|---:|---:|
| APPROACH | under_0.5s | 28 | 10.7% | 3.6% | 0.000 |
| APPROACH | 0.5_to_1.0s | 34 | 58.8% | 55.9% | 0.303 |
| APPROACH | 1.0_to_2.0s | 43 | 79.1% | 76.7% | 0.598 |
| APPROACH | 2.0s_or_more | 49 | 85.7% | 83.7% | 0.506 |
| RETRACT | under_0.5s | 27 | 44.4% | 11.1% | 0.000 |
| RETRACT | 0.5_to_1.0s | 41 | 70.7% | 53.7% | 0.267 |
| RETRACT | 1.0_to_2.0s | 47 | 63.8% | 55.3% | 0.193 |
| RETRACT | 2.0s_or_more | 26 | 84.6% | 76.9% | 0.215 |

### Label-chain coverage

- 139 of 318 Painting episodes (43.7%) were preceded by an explicit Approach label.
- 120 of 318 Painting episodes (37.7%) were followed by an explicit Retract label.
- Therefore, FREE-APPROACH-PAINTING-RETRACT-FREE is not a mandatory label chain in the current data.

## Canonical transition behavior

| Transition | N | Correct exactly at boundary | Stable detection in target episode | Median stable delay (s) | Median switches in +/-1 s |
|---|---:|---:|---:|---:|---:|
| FREE_MOTION->APPROACH | 127 | 4.7% | 61.4% | 0.302 | 1.0 |
| APPROACH->PAINTING | 139 | 53.2% | 94.2% | 0.000 | 1.0 |
| PAINTING->RETRACT | 120 | 1.7% | 45.8% | 0.393 | 1.5 |
| RETRACT->FREE_MOTION | 105 | 27.6% | 80.0% | 0.186 | 2.0 |

## Direct PAINTING-to-assistance mapping

- True phase transitions: 7.83/min
- Predicted phase switches: 18.24/min (2.33x the true count)
- Painting phase-gate toggles: 12.72/min
- True Painting gate toggles: 5.34/min (prediction: 2.38x)
- Closed phase gate during true Painting: 8.7%
- Open phase gate outside true Painting: 29.9%
- Actual assistance still depends on A/B; these are phase-gate errors, not measured robot actions.

### Open Painting phase gate by true phase

- FREE_MOTION: 605.2 s (29.8% of that phase; 78.8% of false-assist time)
- APPROACH: 69.5 s (20.1% of that phase; 9.0% of false-assist time)
- RETRACT: 93.4 s (49.0% of that phase; 12.2% of false-assist time)
