# LinkedIn draft — hold for review

I audited an LLM evaluation I built for reading staff-availability calendars. One of its headline metrics was wrong.

The code counted a note as a “hallucination” whenever it appeared on the wrong day. That did not establish that the model invented the note. The typed audit found that every counted instance was text already present on the calendar, placed at the wrong location.

The distinction changed what the results meant. It also exposed a second problem: strong cell-level accuracy could hide a calendar that still needed correction. In the saved synthetic runs, one model had a status or note error in 1 of 40 calendars; the other in 12 of 40.

I preserved the original release and documented the corrections. The software now separates failed requests from scored answers, records attempts, and checks the integrity of its runnable package. The technical report explains both the results and the limits.

This is evidence from generated calendars and stored model outputs. Real-photograph probes remain unfinished; I am not presenting them as a result.

The work reinforced a practical lesson for me: checking an AI system includes checking whether the evaluation measures what its labels claim.

Repository: https://github.com/Ledbetter117/ed-availability-intake-eval

Galen Coulter-Ledbetter, RN, Paramedic

---

Draft only. No post was sent. The final release link must identify the reviewed public edition. Numeric claims map to `NUMERICAL-SOURCE-MAP.json`.
