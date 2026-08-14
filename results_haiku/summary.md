## Results — model: `claude-haiku-4-5` (40 cases)

| Metric | Overall | clean | handwritten | lowcontrast | rotated |
|---|---|---|---|---|---|
| Day-level accuracy | 97.9% | 100.0% | 100.0% | 94.2% | 97.4% |
| **Critical-error rate** (UNAVAILABLE→available) | 1.9% | 0.0% | 0.0% | 5.7% | 1.3% |
| Hallucination rate (notes) | 6.2% | 2.4% | 0.0% | 3.1% | 22.6% |
| Note fidelity (normalized match) | 93.2% | 97.6% | 100.0% | 96.9% | 75.0% |
| Format validity | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% |

Robustness delta vs clean: handwritten: 0.0%, lowcontrast: 5.8%, rotated: 2.6%

Critical flips: 6 across 316 gold-UNAVAILABLE days.
