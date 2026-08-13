# V2 Difficulty Tier — Design (roadmap; v1 stays frozen)

**Motivation:** the 2026-08-13 scored run shows `claude-sonnet-5` saturating v1 (100% day accuracy, 0 flips, all slices). v1 stays **frozen** as the published benchmark; v2 is an additive tier that restores discrimination at the frontier and widens the failure surface for harness search.

## Design constraints (inherited, non-negotiable)

Ground truth by construction (pattern generated first, then rendered — zero labeling). 100% synthetic, no PHI possible. Byte-for-byte reproducible from a seed. v1 slice names and files untouched; v2 slices get new names. Every v2 knob maps to a real-world artifact property a charge nurse actually receives.

## Current v1 constants (from `generate_dataset.py`)

Rotation: fixed −4° (`rotated`). Lowcontrast: bg (224,224,224) / fg (110,110,110) — luminance gap ~114. Notes: p=0.10 per day; global note p=0.6, max 1. One degradation per slice, never combined.

## Proposed v2 slices

| Slice | Knobs | Real-world analog |
|---|---|---|
| `rot-var` | random rotation ±3–9° per case (rng-seeded), expand-fill | phone photo, no flatbed |
| `faint2` | bg 210 / fg 165 (gap ~45, vs v1's 114) | third-generation photocopy |
| `hand-photo` | handwritten + random rotation ±3–7° | **the actual field artifact: pen-filled sheet, photographed** |
| `hand-faint` | handwritten + faint2 palette | pencil-filled, poor scan |
| `dense-notes` | note p 0.10→0.25, note strings 2–4 words, 2 global notes | real availability sheets are margin-scribbled |
| `degraded` | clean render → GaussianBlur(r=1.5) → JPEG q=40 re-encode | email-compressed photo |

Highest-value additions are the **combined** slices (`hand-photo`, `hand-faint`): v1's one-factor-per-slice design is exactly what Sonnet saturated, and Haiku's failures (grid shift under faintness, row misindex under rotation) predict combined degradations compound superlinearly.

**v2.1 (needs new render code, deferred):** correction marks — a status written, struck through, rewritten; the gold takes the rewrite. Tests exactly the ambiguity human schedulers resolve by asking.

## Protocol

Generate v2 with a fresh seed; publish both-model baselines (Sonnet + Haiku) with the tier, same metrics, same honesty rules. For harness search: search set = v2 generation under seed A; held-out = v2 under seed B (+ frozen v1 as a no-regression check). Decontamination is inherent — different seeds share no bytes.

## Acceptance criteria for shipping v2

At least one frontier model below 100% day accuracy (tier discriminates again). Critical-error rate observable (>0) for at least one deployable-class model. All v1 results and files bit-identical after the change (`--seed 7` regeneration verified).
