# docs/ — methods, corrections, limitations, pre-registration

This folder links the methods, corrections, study plans, and software validation record.

| # | The question | Answered in |
|---|---|---|
| 1 | What did you build? | [`METHODS.md`](METHODS.md) · the top-level `README.md` |
| 2 | What did it measure? | [`METHODS.md`](METHODS.md) §4–5 · `../analysis-v2.md` |
| 3 | **Where were you wrong?** | [`CORRECTIONS.md`](CORRECTIONS.md) — and the preserved `v1.0.0` tag |
| 4 | How do you know the instrument was good enough to trust? | [`LIMITATIONS.md`](LIMITATIONS.md) · [`PROBE.md`](PROBE.md) |
| 5 | **What would have changed your mind?** | [`PROBE.md`](PROBE.md), [`PROBE-B.md`](PROBE-B.md), and adopted [`PROBE-AMENDMENT-01.md`](PROBE-AMENDMENT-01.md) preserve the planned photo study. Amendment 02 remains a draft; no completed photo endpoint is reported. |

The correction record and planned decision rules let readers inspect both the changes and the remaining work.

---

## Reading order

**If you have two minutes** — [`CORRECTIONS.md`](CORRECTIONS.md). It is the shortest route to knowing whether the rest is trustworthy, because it is where the project is wrong.

**If you are deciding whether to reuse this** — [`LIMITATIONS.md`](LIMITATIONS.md) first. The stored runs do not rank current frontier models or establish real-photograph performance.

**If you are reproducing it** — [`METHODS.md`](METHODS.md) and [`NUMERICAL-SOURCE-MAP.json`](NUMERICAL-SOURCE-MAP.json). Aggregate counts can be recomputed from the public records. Historical raw model text is **not** shipped; a new remote run would produce new observations and is not guaranteed to reproduce it.

**If you want to know whether the author changes his mind when the data says so** — [`PROBE.md`](PROBE.md) and [`PROBE-B.md`](PROBE-B.md), then check the commit dates.

---

## The short version

The saved synthetic runs contain 0 and 26 status errors in 1,240 cells per recorded model label. The second run includes 6 UNAVAILABLE-to-available flips; the first still contains a duplicated note.

One of this project's own headline metrics, a **"hallucination rate,"** was named for a failure it never tested. Every counted instance was text present on the page, attached to the wrong day. **Measured fabrication: 0 of 147 predicted note instances for Sonnet and 0 of 145 for Haiku** (Wilson 95% upper bound **2.5%** and **2.6%**; 0 of 292 pooled across both models, upper bound 1.30% — the pooled figure merges two different systems and is quoted only where that is stated). The metric is retired and the correction is public, with `v1.0.0` preserved so the two can be read side by side.

The synthetic results do not answer whether real authoring conditions change extraction. [`PROBE.md`](PROBE.md) records that planned test. [`PROBE-AMENDMENT-01.md`](PROBE-AMENDMENT-01.md) changes the unit to the document and retires CLOSE. Photo results remain unfinished; see [`RELEASE-STATUS.md`](RELEASE-STATUS.md).

---

*Author: Galen Coulter-Ledbetter, RN, Paramedic.*
