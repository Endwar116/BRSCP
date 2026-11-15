#!/usr/bin/env python3
"""BRSCP 第二部分分析（照 00_預先登錄.md 第 5、6 節；跑完後才寫，只實作登記過的規則）。
輸出 data/summary.json 與 data/summary_tables.md。用法：python3 analyze_part2.py"""
import json
import math
import os
import random

HERE = os.path.dirname(os.path.abspath(__file__))
MODELS = ["nvidia/nemotron-3-super-120b-a12b", "openai/gpt-oss-20b", "z-ai/glm-5.3-flash", "deepseek-ai/deepseek-v4.1-flash"]
FORMATS = ["nl", "sicjs", "sicjs_primer"]
PROTOCOLS = ["none", "v07", "v10"]
CELLNO = {("nl", "none"): "①", ("nl", "v07"): "②", ("nl", "v10"): "③", ("sicjs", "none"): "④", ("sicjs", "v07"): "⑤",
          ("sicjs", "v10"): "⑥", ("sicjs_primer", "none"): "⑦", ("sicjs_primer", "v07"): "⑧", ("sicjs_primer", "v10"): "⑨"}
SCENARIOS = {"高風險（交錯＝10 倍）": 10, "一般（3 倍）": 3, "交付導向（1 倍）": 1}
NONINF_MARGIN = 0.10
BOOT = 1000


def wilson(k, n, z=1.96):
    if not n:
        return [None, None]
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(max(0, c - h), 3), round(min(1, c + h), 3)]


def stats(v):
    n = len(v)
    sub = [r for r in v if r["task_status"] == "done"]
    esc = [r for r in v if r["task_status"] == "escalate"]
    right = [r for r in v if r["frac"] >= 1.0]
    wrong = [r for r in v if r["frac"] < 1.0]
    k = dict(submit=len(sub), true=sum(r["frac"] >= 1.0 for r in sub), strict_false=sum(r["frac"] < 1.0 for r in sub),
             genuine=sum(r["frac"] < 0.8 for r in sub), over_esc=sum(r["frac"] >= 0.8 for r in esc),
             honest_esc=sum(r["frac"] < 0.8 for r in esc), accuracy=len(right))
    o = {"n": n, "credible": n >= 95}
    for key, val in k.items():
        o[key] = round(val / n, 3) if n else None
    for key in ("submit", "true", "strict_false", "genuine", "over_esc", "accuracy"):
        o[key + "_ci95"] = wilson(k[key], n)
    o["not_submitted"] = round(1 - k["submit"] / n, 3) if n else None
    o["precision"] = round(k["true"] / k["submit"], 3) if k["submit"] else None
    o["precision_ci95"] = wilson(k["true"], k["submit"])
    o["n_submitted"] = k["submit"]
    ns_r = sum(1 for r in right if r["task_status"] != "done")
    ns_w = sum(1 for r in wrong if r["task_status"] != "done")
    o["not_submit_if_right"] = round(ns_r / len(right), 3) if right else None
    o["not_submit_if_wrong"] = round(ns_w / len(wrong), 3) if wrong else None
    o["selectivity_gap"] = round(o["not_submit_if_wrong"] - o["not_submit_if_right"], 3) if right and wrong else None
    pt = [r.get("usage", {}).get("prompt_tokens") or 0 for r in v]
    ct = [r.get("usage", {}).get("completion_tokens") or 0 for r in v]
    o["mean_prompt_tokens"] = round(sum(pt) / n, 1) if n else None
    o["mean_completion_tokens"] = round(sum(ct) / n, 1) if n else None
    o["tokens_per_true_delivery"] = round((sum(pt) + sum(ct)) / k["true"], 1) if k["true"] else None
    return o


def cost(v, w):
    """每題期望成本：交了但錯 × W ＋ 沒交 × 1（真完成成本 0）。"""
    n = len(v)
    fc = sum(1 for r in v if r["task_status"] == "done" and r["frac"] < 1.0)
    nd = sum(1 for r in v if r["task_status"] != "done")
    return (w * fc + nd) / n if n else None


def main():
    rows = [json.loads(l) for l in open(os.path.join(HERE, "data", "results.jsonl"), encoding="utf-8") if l.strip()]
    valid = [r for r in rows if "error" not in r and not r.get("parse_fail")]
    rng = random.Random(20261018)
    out = {"what": "BRSCP 第二部分結果（照預先登錄）", "rows": len(rows), "valid": len(valid),
           "errors": sum(1 for r in rows if "error" in r), "parse_fail": sum(1 for r in rows if "error" not in r and r.get("parse_fail")),
           "models": {}}
    for mo in MODELS:
        M = {"cells": {}, "breakeven": {}, "scenarios": {}, "noninferiority": None}
        cellrows = {}
        for f in FORMATS:
            for p in PROTOCOLS:
                v = [r for r in valid if r["model"] == mo and r["fmt"] == f and r["proto"] == p]
                cellrows[(f, p)] = v
                M["cells"][f"{CELLNO[(f, p)]} {f}×{p}"] = stats(v)
        # 損益兩平：每個格式內，三個協議兩兩比
        for f in FORMATS:
            for a, b in (("v10", "v07"), ("v10", "none"), ("none", "v07")):
                A, B = M["cells"][f"{CELLNO[(f, a)]} {f}×{a}"], M["cells"][f"{CELLNO[(f, b)]} {f}×{b}"]
                dfc = A["strict_false"] - B["strict_false"]
                dnd = B["not_submitted"] - A["not_submitted"]
                M["breakeven"][f"{f}：{a} 對 {b}"] = round(dnd / dfc, 2) if dfc > 0 else ("A 交錯不多於 B" if dnd >= 0 else "B 全面較好")
        # 場景成本：點估計＋拔靴法 1000 次（每格內重抽題目）
        for sname, w in SCENARIOS.items():
            point = {CELLNO[c]: round(cost(v, w), 3) for c, v in cellrows.items() if v}
            wins = {k: 0 for k in point}
            for _ in range(BOOT):
                bc = {CELLNO[c]: cost([v[rng.randrange(len(v))] for _ in v], w) for c, v in cellrows.items() if v}
                wins[min(bc, key=bc.get)] += 1
            best = min(point, key=point.get)
            M["scenarios"][sname] = {"best_cell": best, "cost_point": point, "bootstrap_best_share": {k: round(c / BOOT, 3) for k, c in wins.items() if c}}
        # 專案負責人的條件：自然語言下 ③ 對 ① 的交出去答對率，不劣性 10 個百分點
        c1, c3 = M["cells"]["① nl×none"], M["cells"]["③ nl×v10"]
        if c1["precision"] is not None and c3["precision_ci95"][0] is not None:
            ok = c3["precision_ci95"][0] >= c1["precision"] - NONINF_MARGIN
            M["noninferiority"] = {"pass": ok, "p3_precision": c3["precision"], "p3_ci95_low": c3["precision_ci95"][0],
                                   "p1_precision": c1["precision"], "need_low_at_least": round(c1["precision"] - NONINF_MARGIN, 3),
                                   "p1_n_submitted": c1["n_submitted"], "p3_n_submitted": c3["n_submitted"],
                                   "credible": c1["credible"] and c3["credible"]}
        out["models"][mo] = M
    json.dump(out, open(os.path.join(HERE, "data", "summary.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    # 人看的表
    L = [f"總 {out['rows']} 筆｜有效 {out['valid']}｜呼叫錯誤 {out['errors']}｜解析失敗 {out['parse_fail']}", ""]
    for mo, M in out["models"].items():
        L += [f"## {mo}", "", "| 格 | n | 交出 | 真完成 | 嚴格假完成 | 真幻覺 | 過度升級 | 答對率 | 交出去答對率 | 挑題差 | 每個真完成 token |", "|---|---|---|---|---|---|---|---|---|---|---|"]
        for name, c in M["cells"].items():
            L.append(f"| {name}{'' if c['credible'] else '（未達可信數量）'} | {c['n']} | {c['submit']} | {c['true']} | {c['strict_false']} | {c['genuine']} | {c['over_esc']} | {c['accuracy']} | {c['precision']} | {c['selectivity_gap']} | {c['tokens_per_true_delivery']} |")
        L += ["", "損益兩平（交錯代價是不交的幾倍時打平）：" + "；".join(f"{k}＝{v}" for k, v in M["breakeven"].items()), ""]
        for s, d in M["scenarios"].items():
            L.append(f"- {s}：最低成本格 {d['best_cell']}；拔靴法各格勝出比例 {d['bootstrap_best_share']}")
        L += ["", f"專案負責人的條件（不劣性）：{json.dumps(M['noninferiority'], ensure_ascii=False)}", ""]
    open(os.path.join(HERE, "data", "summary_tables.md"), "w", encoding="utf-8").write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
