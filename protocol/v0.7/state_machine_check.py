"""
state_machine_check.py v2 — BRSCP 閉環性 + 分層完整性機械檢查

v2 相對 v1 的改動（修掉 v1 自我紅隊列出的問題）：
  · 路由表改為從 routing.json 解析，不再硬編碼 → 消滅 spec drift
  · 新增 C7 反向檢查：routing.json 宣告的狀態必須真的出現在載入文字裡
  · C4 升級：不只數 claimed_status 次數，檢查它是否落在綁定語境中
  · 新增 C8/C9：分層單調包含、觸發 fail-safe

原則不變：檢查必須抓得到 v0.6 的洞，否則沒有鑑別力。
"""
import os, sys, json, re

HERE = os.path.dirname(os.path.abspath(__file__))
TERMINAL = {"complete", "continue", "escalate"}
VALID_TARGETS = TERMINAL | {"PASS"}
BINDING_WORDS = ["必須", "不得", "=", "→"]


def load_v07():
    with open(os.path.join(HERE, "routing.json"), encoding="utf-8") as f:
        r = json.load(f)
    tiers = {t: open(os.path.join(HERE, "tiers", f"{t}.md"), encoding="utf-8").read()
             for t in ("L0", "L1", "L2")}
    return {"name": "v0.7", "routing": r["routing"],
            "escalate_entries": r["escalate_entries"], "tiers": tiers,
            "loaded_text": tiers["L1"], "single_turn": r.get("single_turn", {})}


V06 = {
    "name": "v0.6",
    "routing": {
        "G1_intent":     {"aligned": "PASS", "deviated": "continue"},
        "G2_pending":    {"none_pending": "PASS", "has_pending": "continue"},
        "G3_evidence":   {"has_evidence": "PASS", "no_evidence": "continue"},
        "G4G5_redteam":  {"fewer_than_3_flaws": "continue", "flaws_non_fatal": "PASS",
                          "flaws_fatal_fixable": "continue",
                          "flaws_fatal_unfixable": "continue"},
        "G6_confidence": {"confident": "PASS", "not_confident": "continue"},
    },
    "escalate_entries": [
        {"name": "G3 重試 2 次仍無證據", "requires_retry": True},
        {"name": "反覆嘗試仍搞不定",     "requires_retry": True},
    ],
    "tiers": None, "loaded_text": None, "single_turn": {},
}


def _v06_text():
    p = "/mnt/user-data/outputs/BRSCP_PROTOCOL_v0.1.md"
    return open(p, encoding="utf-8").read() if os.path.exists(p) else ""


def c1(s):
    bad = [f"{g}.{o} → {t}" for g, outs in s["routing"].items()
           for o, t in outs.items() if t not in VALID_TARGETS]
    return (not bad, bad)


def c2(s):
    free = [e["name"] for e in s["escalate_entries"] if not e["requires_retry"]]
    if free:
        return (True, [f"單輪可用入口：{'、'.join(free)}"])
    names = [e["name"] for e in s["escalate_entries"]]
    return (False, [f"全部 {len(names)} 個入口都需 retry 歷史：{'、'.join(names)}",
                    "→ 單輪情境下 escalate 為不可達狀態"])


def c3(s):
    unfix = [(g, o) for g, outs in s["routing"].items() for o in outs
             if any(k in o for k in ("unfixable", "self_contradictory",
                                     "blocked_externally", "unobtainable", "unverifiable"))]
    esc_ok, _ = c2(s)
    bad = []
    for g, o in unfix:
        if s["routing"][g][o] == "continue":
            bad.append(f"{g}.{o} → continue，此處境不可修" +
                       ("，且 escalate 單輪不可達 → 死路，只能掉回 complete"
                        if not esc_ok else "（應為 escalate）"))
    return (not bad, bad)


def c4(s):
    text = s["loaded_text"] if s["loaded_text"] is not None else _v06_text()
    if not text:
        return (False, ["找不到協議文字"])
    hits = [m.start() for m in re.finditer("claimed_status", text)]
    if not hits:
        return (False, ["載入文字未出現 claimed_status → 控制一個從未指名的變數"])
    bound = sum(1 for i in hits
                if any(w in text[max(0, i - 40):i + 40] for w in BINDING_WORDS))
    if bound == 0:
        return (False, [f"出現 {len(hits)} 次但都不在綁定語境"])
    return (True, [f"claimed_status 出現 {len(hits)} 次，{bound} 次在綁定語境中"])


def c5(s):
    r = s["routing"].get("G4G5_redteam", {})
    t = r.get("flaws_fatal_unfixable")
    if t is None:
        return (False, ["G4G5 無『致命且不可修』outcome → 未涵蓋 B-4 處境"])
    if t == "escalate":
        return (True, ["G4G5(致命,不可修) → escalate ✓ 與正確答案一致"])
    esc_ok, _ = c2(s)
    tr = [f"G4G5(致命,不可修) → {t}", "  規格矛盾不可修，continue 無事可做",
          f"  改走 escalate？單輪可達 = {esc_ok}"]
    if not esc_ok:
        tr += ["  → 無合法出口，只能掉回 complete = 假完成",
               "  → 這正是 B-4 實測發生的事"]
    return (False, tr)


def c6(s):
    st = s.get("single_turn") or {}
    if st.get("continue_semantics") and st.get("continue_overflow"):
        return (True, [f"{st['continue_semantics']}；溢出 → {st['continue_overflow']}"])
    text = s["loaded_text"] if s["loaded_text"] is not None else _v06_text()
    if text and "單輪" in text and "降級" in text:
        return (True, ["協議文字已定義單輪 continue 語意"])
    return (False, ["未定義單輪下 continue 語意 → 標了就結束 = 換標籤的假完成"])


def c7(s):
    if s["tiers"] is None:
        return (True, ["v0.6 無 routing.json（歷史檔案），不適用"])
    text = s["tiers"]["L1"]
    declared = {t for outs in s["routing"].values() for t in outs.values()} & TERMINAL
    missing = [d for d in declared if d not in text]
    if missing:
        return (False, [f"routing.json 宣告但 L1 未出現：{'、'.join(missing)}"])
    return (True, [f"宣告的 {len(declared)} 個終止狀態全部出現在 L1 文字中"])


def c8(s):
    if s["tiers"] is None:
        return (True, ["v0.6 無分層，不適用"])
    t = s["tiers"]
    bad = []
    core = "claimed_status 不得為 complete"
    if core not in t["L1"]:
        bad.append("L1 未包含 L0 核心約束")
    if core not in t["L2"]:
        bad.append("L2 未包含 L0 核心約束")
    if "自檢六門" not in t["L2"]:
        bad.append("L2 未包含 L1 六門")
    sz = [len(t["L0"]), len(t["L1"]), len(t["L2"])]
    if not (sz[0] < sz[1] < sz[2]):
        bad.append(f"長度非單調遞增：{sz}")
    return (not bad, bad or [f"L0({sz[0]}) ⊂ L1({sz[1]}) ⊂ L2({sz[2]}) codepoints"])


def c9(s):
    if s["tiers"] is None:
        return (True, ["v0.6 無分層，不適用"])
    sys.path.insert(0, HERE)
    from brscp_v07 import select_tier, ALL_SIGNALS
    bad = []
    if select_tier(signals={})[0] != "L2":
        bad.append("訊號未知時未落到 L2（fail-safe 失效）")
    af = {k: False for k in ALL_SIGNALS}
    if select_tier(signals=af, active_tier="L2")[0] != "L2":
        bad.append("允許從 L2 降級")
    if select_tier(signals={**af, "money_or_pricing": True})[0] != "L2":
        bad.append("小任務涉金流未升到 L2")
    return (not bad, bad or ["fail-safe ✓　不可降級 ✓　小任務高風險正確升級 ✓"])


CHECKS = [("C1 無未定義轉移", c1), ("C2 escalate 單輪可達", c2), ("C3 無死路", c3),
          ("C4 綁定輸出欄位", c4), ("C5 B-4 情境重放", c5),
          ("C6 continue 單輪有義", c6), ("C7 無 spec drift", c7),
          ("C8 分層單調包含", c8), ("C9 分層 fail-safe", c9)]


def run(spec):
    print(f"\n{'='*64}\n  {spec['name']} 檢查\n{'='*64}")
    res = {}
    for label, fn in CHECKS:
        ok, detail = fn(spec)
        res[label] = ok
        print(f"\n  [{'PASS' if ok else 'FAIL'}] {label}")
        for d in detail:
            print(f"         {d}")
    print(f"\n  ── {sum(res.values())}/{len(CHECKS)} ──")
    return res


if __name__ == "__main__":
    r06, r07 = run(V06), run(load_v07())
    print(f"\n{'='*64}\n  對照\n{'='*64}")
    print(f"  {'檢查項':<26}{'v0.6':<10}{'v0.7'}\n  {'-'*46}")
    for label, _ in CHECKS:
        print(f"  {label:<26}{'PASS' if r06[label] else 'FAIL':<10}"
              f"{'PASS' if r07[label] else 'FAIL'}")
    n06, n07 = sum(r06.values()), sum(r07.values())
    print(f"\n  v0.6: {n06}/{len(CHECKS)}    v0.7: {n07}/{len(CHECKS)}")
    if n06 == len(CHECKS):
        print("\n  ⚠️ 檢查通過了 v0.6 → 無鑑別力"); sys.exit(1)
    if n07 < len(CHECKS):
        print("\n  ❌ v0.7 仍有洞"); sys.exit(1)
    print("\n  ✅ 檢查有鑑別力，且 v0.7 全數通過")
    json.dump({"v0.6": r06, "v0.7": r07},
              open(os.path.join(HERE, "closure_check_results.json"), "w"),
              ensure_ascii=False, indent=2)
