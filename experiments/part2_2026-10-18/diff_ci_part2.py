#!/usr/bin/env python3
"""BRSCP 第二部分：主要比較的「差」與 95% 信賴區間（事後補充分析）。

為什麼有這支：記錄本 <internal-event-id>（2026-10-18）要求「每個主要比較都附差與 95% 信賴區間」，
不顯著只能寫「沒有偵測到差別」。預先登錄（00_預先登錄.md）的判定不變；這支只補區間，不改判定。
方法：兩組獨立比例的差，用 Newcombe 混合分數區間（Wilson 為底，Newcombe 1998 方法 10）。
每個真完成的 token 倍數用拔靴法 2000 次（種子 20261018）取百分位區間。
輸入：data/results.jsonl（與 analyze_part2.py 同一套有效列）。輸出：data/diff_ci.json、data/diff_ci_tables.md。
用法：python3 diff_ci_part2.py        自測：python3 diff_ci_part2.py --selftest
"""
import json
import math
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MODELS = ["nvidia/nemotron-3-super-120b-a12b", "openai/gpt-oss-20b", "z-ai/glm-5.3-flash", "deepseek-ai/deepseek-v4.1-flash"]
CELL = {"①": ("nl", "none"), "②": ("nl", "v07"), "③": ("nl", "v10"), "⑦": ("sicjs_primer", "none"), "⑨": ("sicjs_primer", "v10")}
# 主要比較：(新格, 舊格, 指標)。指標都是「每題」的比例，分母＝該格有效題數；precision 的分母＝交出的題數
COMPARISONS = [
    ("⑨", "①", "true"), ("⑨", "①", "strict_false"), ("⑨", "①", "not_submitted"), ("⑨", "①", "accuracy"), ("⑨", "①", "precision"),
    ("③", "①", "true"), ("③", "①", "strict_false"), ("③", "①", "precision"),
    ("⑦", "①", "submit"), ("⑦", "①", "accuracy"),
    ("⑨", "⑦", "strict_false"), ("⑨", "⑦", "not_submitted"),
    ("②", "①", "submit"),
]
NAMES = {"true": "真完成", "strict_false": "交出但不全對", "not_submitted": "不交", "accuracy": "全部答對（不管交不交）",
         "precision": "交出去答對率", "submit": "交出"}


def wilson(k, n, z=1.96):
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def newcombe(k1, n1, k2, n2):
    """p1 − p2 的 95% 區間（Newcombe 方法 10）。"""
    p1, p2 = k1 / n1, k2 / n2
    l1, u1 = wilson(k1, n1)
    l2, u2 = wilson(k2, n2)
    d = p1 - p2
    lo = d - math.sqrt((p1 - l1) ** 2 + (u2 - p2) ** 2)
    hi = d + math.sqrt((u1 - p1) ** 2 + (p2 - l2) ** 2)
    return d, lo, hi


def counts(v, metric):
    """回傳 (k, n)。"""
    sub = [r for r in v if r["task_status"] == "done"]
    if metric == "true":
        return sum(r["frac"] >= 1.0 for r in sub), len(v)
    if metric == "strict_false":
        return sum(r["frac"] < 1.0 for r in sub), len(v)
    if metric == "not_submitted":
        return len(v) - len(sub), len(v)
    if metric == "submit":
        return len(sub), len(v)
    if metric == "accuracy":
        return sum(r["frac"] >= 1.0 for r in v), len(v)
    if metric == "precision":
        return sum(r["frac"] >= 1.0 for r in sub), len(sub)
    raise ValueError(metric)


def tok_per_true(v):
    t = sum(1 for r in v if r["task_status"] == "done" and r["frac"] >= 1.0)
    s = sum((r.get("usage", {}).get("prompt_tokens") or 0) + (r.get("usage", {}).get("completion_tokens") or 0) for r in v)
    return s / t if t else float("inf")


def selftest():
    ok = []
    # Newcombe 1998 表 II 例 (a)：56/70 對 48/80，差 0.2，區間 0.0524 到 0.3339
    d, lo, hi = newcombe(56, 70, 48, 80)
    ok.append(("Newcombe 教科書例 56/70 對 48/80", abs(lo - 0.0524) < 0.001 and abs(hi - 0.3339) < 0.001))
    # 反例：同比例時區間要跨 0
    d, lo, hi = newcombe(10, 100, 10, 100)
    ok.append(("同比例區間跨 0", lo < 0 < hi and d == 0))
    for name, r in ok:
        print(("✅ " if r else "❌ ") + name)
    print("RESULT", json.dumps({"suite": "diff_ci_part2", "passed": sum(r for _, r in ok), "total": len(ok)}))
    return all(r for _, r in ok)


def main():
    rows = [json.loads(l) for l in open(os.path.join(HERE, "data", "results.jsonl"), encoding="utf-8") if l.strip()]
    valid = [r for r in rows if "error" not in r and not r.get("parse_fail")]
    rng = random.Random(20261018)
    out = {"what": "第二部分主要比較的差與 95% 區間（事後補充，<internal-event-id>；不改預先登錄判定）",
           "method": "Newcombe 方法 10；token 倍數用拔靴法 2000 次百分位", "models": {}}
    L = ["# 第二部分：主要比較的差與 95% 信賴區間（事後補充分析）", "",
         "差＝新格減舊格，單位是百分點。區間不含 0 才算偵測到差別；含 0 只能寫「沒有偵測到差別」。", ""]
    for mo in MODELS:
        cells = {c: [r for r in valid if r["model"] == mo and (r["fmt"], r["proto"]) == fp] for c, fp in CELL.items()}
        M = {"comparisons": [], "token_ratio_1_over_9": None}
        L += [f"## {mo}", "", "| 比較 | 指標 | 新格 | 舊格 | 差（百分點） | 95% 區間 | 偵測到差別？ |", "|---|---|---|---|---|---|---|"]
        for a, b, m in COMPARISONS:
            k1, n1 = counts(cells[a], m)
            k2, n2 = counts(cells[b], m)
            if not n1 or not n2:
                continue
            d, lo, hi = newcombe(k1, n1, k2, n2)
            det = "是，變高" if lo > 0 else ("是，變低" if hi < 0 else "否")
            M["comparisons"].append({"new": a, "old": b, "metric": m, "k_new": k1, "n_new": n1, "k_old": k2, "n_old": n2,
                                     "diff": round(d, 4), "ci95": [round(lo, 4), round(hi, 4)], "detected": det})
            L.append(f"| {a} 對 {b} | {NAMES[m]} | {k1}/{n1} | {k2}/{n2} | {d*100:+.1f} | {lo*100:+.1f} 到 {hi*100:+.1f} | {det} |")
        # token 倍數：① 每個真完成的 token ÷ ⑨ 每個真完成的 token
        point = tok_per_true(cells["①"]) / tok_per_true(cells["⑨"])
        bs = []
        for _ in range(2000):
            r1 = [cells["①"][rng.randrange(len(cells["①"]))] for _ in cells["①"]]
            r9 = [cells["⑨"][rng.randrange(len(cells["⑨"]))] for _ in cells["⑨"]]
            t1, t9 = tok_per_true(r1), tok_per_true(r9)
            if math.isfinite(t1) and math.isfinite(t9):
                bs.append(t1 / t9)
        bs.sort()
        lo, hi = bs[int(0.025 * len(bs))], bs[int(0.975 * len(bs)) - 1]
        M["token_ratio_1_over_9"] = {"point": round(point, 2), "ci95": [round(lo, 2), round(hi, 2)], "valid_resamples": len(bs)}
        L += ["", f"每個真完成的 token，① 是 ⑨ 的 {point:.1f} 倍（95% 區間 {lo:.1f} 到 {hi:.1f}；有效重抽 {len(bs)} 次）", ""]
        out["models"][mo] = M
    json.dump(out, open(os.path.join(HERE, "data", "diff_ci.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    open(os.path.join(HERE, "data", "diff_ci_tables.md"), "w", encoding="utf-8").write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(0 if selftest() else 1)
    main()
