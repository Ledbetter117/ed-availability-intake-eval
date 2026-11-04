#!/usr/bin/env python3
"""probe_decide.py -- the document-level decision rules of docs/PROBE-AMENDMENT-01.md §4 (CANDIDATE, 2026-10-26).

One place for the rules both arms use, so that a scorer cannot drift from the amendment:
  - the unit is the DOCUMENT; a document is an error document if it has at least one status error;
  - Fisher exact tests are two-sided;
  - Arm A  PROCEED: p < 0.05 on error documents, authored > copyist, and the two Wilson 95% intervals
                    do not overlap. CONTINUE otherwise. Stage 1 (3 per arm) cannot reach PROCEED; it is a
                    pilot and is labelled PILOT, with no verdict.
  - Arm B  B-PROCEED: p < 0.05 on error documents, real > synthetic (the same model's own synthetic run),
                    and the Wilson 95% lower bound of the real error-document rate is above 1%. G3 is excluded
                    from the decision denominator (reported in full). B-CONTINUE otherwise.
  - CLOSE and B-CLOSE are retired: no function here can return them.
Cell-level rates are descriptive and never decide.
Run:  python3 probe_decide.py --selftest     (reproduces every number in Amendment 01 §3 and §4)
      python3 probe_decide.py --reachability (Arm B minimums for every possible synthetic baseline k/40)
"""
import math, sys
from math import comb

ALPHA = 0.05
ARM_B_FLOOR = 0.01
RETIRED = ("CLOSE", "B-CLOSE")


def wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def fisher_2x2(a, b, c, d):
    """Two-sided Fisher exact p for [[a, b], [c, d]]."""
    n = a + b + c + d
    r1, c1 = a + b, a + c

    def pmf(x):
        return comb(c1, x) * comb(n - c1, r1 - x) / comb(n, r1)

    p0 = pmf(a)
    return min(1.0, sum(pmf(x) for x in range(max(0, r1 + c1 - n), min(r1, c1) + 1) if pmf(x) <= p0 + 1e-12))


def error_document(status_errors):
    return status_errors >= 1


def decide_arm_a(auth_err, auth_n, copy_err, copy_n, stage):
    """Arm A, document level. stage is 1 or 2 (from the protocol, not from the data)."""
    p = fisher_2x2(auth_err, auth_n - auth_err, copy_err, copy_n - copy_err) if auth_n and copy_n else None
    wa, wc = wilson(auth_err, auth_n), wilson(copy_err, copy_n)
    direction = auth_n and copy_n and (auth_err / auth_n) > (copy_err / copy_n)
    no_overlap = wa[0] > wc[1]
    proceed = bool(p is not None and p < ALPHA and direction and no_overlap)
    verdict = "PROCEED" if proceed else "CONTINUE"
    out = {"verdict": verdict, "stage": stage, "authored": [auth_err, auth_n], "copyist": [copy_err, copy_n],
           "fisher_p_two_sided": None if p is None else round(p, 6),
           "wilson_authored": [round(wa[0], 4), round(wa[1], 4)], "wilson_copyist": [round(wc[0], 4), round(wc[1], 4)],
           "intervals_overlap": not no_overlap, "close": "RETIRED (Amendment 01 §3: unreachable at any feasible n)"}
    if stage == 1:
        out["label"] = ("PILOT: Stage 1 cannot fire PROCEED under the document unit (the most extreme table, 3/3 vs 0/3, "
                        "gives p = 0.10). No verdict may be reported from Stage 1.")
        out["verdict"] = "CONTINUE"
    assert out["verdict"] not in RETIRED
    return out


def decide_arm_b(real_err, real_n, synth_err, synth_n):
    """Arm B, document level: real grid documents (G3 excluded), LEGEND-BLIND, best model, against that model's
    own synthetic run. synth_err/synth_n None means no baseline is on file: fails closed (B-CONTINUE)."""
    if synth_err is None or synth_n in (None, 0):
        return {"verdict": "B-CONTINUE", "reason": "no synthetic baseline on file for this model; B-PROCEED cannot fire",
                "real": [real_err, real_n], "synthetic": None, "close": "RETIRED"}
    p = fisher_2x2(real_err, real_n - real_err, synth_err, synth_n - synth_err)
    lo, hi = wilson(real_err, real_n)
    direction = real_n and (real_err / real_n) > (synth_err / synth_n)
    proceed = bool(p < ALPHA and direction and lo > ARM_B_FLOOR)
    out = {"verdict": "B-PROCEED" if proceed else "B-CONTINUE", "real": [real_err, real_n],
           "synthetic": [synth_err, synth_n], "fisher_p_two_sided": round(p, 6),
           "wilson_real": [round(lo, 4), round(hi, 4)], "floor": ARM_B_FLOOR, "close": "RETIRED"}
    assert out["verdict"] not in RETIRED
    return out


def arm_b_minimum(synth_err, synth_n=40, real_n=6):
    """Smallest number of real error documents (of real_n) that fires B-PROCEED; None if unreachable."""
    for x in range(real_n + 1):
        if decide_arm_b(x, real_n, synth_err, synth_n)["verdict"] == "B-PROCEED":
            return x
    return None


def reachability_table(synth_n=40, real_n=6):
    return [(k, arm_b_minimum(k, synth_n, real_n)) for k in range(synth_n + 1)]


def selftest():
    ok = []

    def t(name, cond):
        ok.append((name, bool(cond)))

    # Amendment 01 §3, Arm A Stage 1: the most extreme table gives p = 0.10 and cannot proceed
    a1 = decide_arm_a(3, 3, 0, 3, stage=1)
    t("A §3 Stage 1, 3/3 vs 0/3: p = 0.10, CONTINUE, labelled PILOT", abs(a1["fisher_p_two_sided"] - 0.1) < 1e-9
      and a1["verdict"] == "CONTINUE" and "PILOT" in a1["label"])
    # Arm A Stage 2 table
    for k, p_exp, fires in ((7, 0.00058, True), (6, 0.0047, True), (5, 0.021, True), (4, 0.070, False)):
        r = decide_arm_a(k, 7, 0, 7, stage=2)
        t(f"A §3 Stage 2, {k}/7 vs 0/7: p ~ {p_exp}, {'PROCEED' if fires else 'CONTINUE'}",
          abs(r["fisher_p_two_sided"] - p_exp) < 5e-4 and (r["verdict"] == "PROCEED") == fires)
    # §4: 6/7 vs 1/7 has p < .05 but overlapping intervals -> CONTINUE
    r = decide_arm_a(6, 7, 1, 7, stage=2)
    t("A §4 6/7 vs 1/7: p = 0.029 but intervals overlap -> CONTINUE",
      abs(r["fisher_p_two_sided"] - 0.029) < 1e-3 and r["intervals_overlap"] and r["verdict"] == "CONTINUE")
    w5, w0 = wilson(5, 7), wilson(0, 7)
    t("A §4 Wilson 5/7 = [35.9%, 91.8%], 0/7 = [0.0%, 35.4%]", abs(w5[0] - 0.359) < 1e-3 and abs(w5[1] - 0.918) < 1e-3
      and abs(w0[1] - 0.354) < 1e-3)
    t("A equal error in both arms never proceeds (the level-test defect)", decide_arm_a(5, 7, 5, 7, 2)["verdict"] == "CONTINUE")
    t("A direction: copyist worse than authored never proceeds", decide_arm_a(0, 7, 7, 7, 2)["verdict"] == "CONTINUE")
    # Arm B §3 against 0/40 synthetic
    t("B §3 1/6 vs 0/40: p = 0.130, B-CONTINUE", abs(decide_arm_b(1, 6, 0, 40)["fisher_p_two_sided"] - 0.130) < 1e-3
      and decide_arm_b(1, 6, 0, 40)["verdict"] == "B-CONTINUE")
    b2 = decide_arm_b(2, 6, 0, 40)
    t("B §3 2/6 vs 0/40: p = 0.014, Wilson lower 9.7% > 1%, B-PROCEED", abs(b2["fisher_p_two_sided"] - 0.014) < 1e-3
      and abs(b2["wilson_real"][0] - 0.097) < 1e-3 and b2["verdict"] == "B-PROCEED")
    t("B §3 against 9/40 synthetic the minimum is 4/6 (p = 0.045)", arm_b_minimum(9) == 4
      and abs(decide_arm_b(4, 6, 9, 40)["fisher_p_two_sided"] - 0.045) < 1e-3)
    t("B no synthetic baseline fails closed", decide_arm_b(6, 6, None, None)["verdict"] == "B-CONTINUE")
    big = decide_arm_b(3, 400, 0, 4000)
    t("B the 1% floor is implemented: it binds at large n (3/400 vs 0/4000: p < .05, Wilson lower < 1%)",
      big["fisher_p_two_sided"] < 0.05 and big["wilson_real"][0] < 0.01 and big["verdict"] == "B-CONTINUE")
    t("B fewer real errors than synthetic never proceeds", decide_arm_b(0, 6, 30, 40)["verdict"] == "B-CONTINUE")
    # CLOSE in both arms: 189 documents for an upper bound below 2% at zero errors
    n = 1
    while wilson(0, n)[1] >= 0.02:
        n += 1
    t("CLOSE arithmetic: Wilson upper < 2% at zero errors needs n = 189 (documents)", n == 189)
    t("§3 Wilson upper 0/3 = 56.2%, 0/6 = 39.0%", abs(wilson(0, 3)[1] - 0.562) < 1e-3 and abs(wilson(0, 6)[1] - 0.390) < 1e-3)
    every = [decide_arm_a(x, 7, y, 7, s)["verdict"] for x in range(8) for y in range(8) for s in (1, 2)] + \
            [decide_arm_b(x, 6, y, 40)["verdict"] for x in range(7) for y in range(41)]
    t("no input of either arm can return CLOSE or B-CLOSE (exhaustive over the design's tables)",
      not any(v in RETIRED for v in every))
    for name, res in ok:
        print(f"  {'PASS' if res else 'FAIL'}  {name}")
    good = all(r for _, r in ok)
    print(f"\nprobe_decide selftest: {'PASS' if good else 'FAIL'} ({sum(r for _, r in ok)}/{len(ok)})")
    return 0 if good else 1


if __name__ == "__main__":
    if "--reachability" in sys.argv:
        print("synthetic error-documents k/40 -> minimum real error-documents of 6 that fires B-PROCEED")
        for k, m in reachability_table():
            print(f"  {k:2d}/40 -> {'unreachable' if m is None else f'{m}/6'}")
        sys.exit(0)
    sys.exit(selftest())
