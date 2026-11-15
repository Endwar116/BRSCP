"""
brscp_v07.py — BRSCP v0.7 參考實作

兩件事：
  1. select_tier()   依風險訊號決定載入哪一層（fail-safe：不確定 → L2）
  2. build_prompt()  組裝 prompt，協議一律置於最末（緊貼行動點）

設計約束（來自 2026-07-25 實測）：
  · L0 永遠在場，不進動態
  · 分層依風險／不可逆性，不依任務大小
  · 執行任務的 agent 不得自行降級
  · 訊號未知時預設最高層（誤判高只多花 token，誤判低會出事）
"""
import os, json

HERE = os.path.dirname(os.path.abspath(__file__))
TIER_DIR = os.path.join(HERE, "tiers")

# ── 風險訊號 ────────────────────────────────────────────────────────────
# ★ 訊號：任一命中即 L2
STAR_SIGNALS = {
    "irreversible_action":  "不可逆動作（刪除／覆寫／送出／發布／轉帳）",
    "external_effect":      "對外產生影響（發布／寄送／公開／對客戶交付）",
    "money_or_pricing":     "金流／計價／額度相關",
    "security_or_privacy":  "安全／權限／憑證／隱私資料",
}
# 一般訊號：一項 → L1，兩項以上 → L2
NORMAL_SIGNALS = {
    "writes_files":    "寫入或修改檔案／設定／資料庫",
    "production_path": "觸及 production／正式環境",
    "multi_party":     "多方協作（多 agent 或多人依賴此產物）",
}
# 迴圈訊號：任一命中 → 至少 L1（scaffolding 才有意義）
LOOP_SIGNALS = {
    "turn_ge_2":              "已進入第二輪以上",
    "prev_verdict_continue":  "上一輪判定為 continue",
    "has_verifiable_artifact":"已產出可驗證的產物",
}

ALL_SIGNALS = {**STAR_SIGNALS, **NORMAL_SIGNALS, **LOOP_SIGNALS}
TIER_ORDER = {"L0": 0, "L1": 1, "L2": 2}


def select_tier(signals=None, task_priority=None, user_override=None, active_tier=None):
    """
    signals: dict[str, bool|None]。None 或缺項 = 未知 → 觸發 fail-safe。
    task_priority: SIC-JS task.priority，"P0" → L2
    user_override: 用戶明示指定層級，最高優先
    active_tier: 本任務已啟用的層級（用於禁止降級）

    回傳 (tier, reasons)
    """
    signals = signals or {}
    reasons = []

    # 1) 用戶明示最優先
    if user_override in TIER_ORDER:
        return _no_downgrade(user_override, active_tier, ["用戶明示指定"])

    # 2) 訊號未知 → fail-safe 預設最高
    unknown = [k for k in ALL_SIGNALS if signals.get(k) is None]
    if unknown:
        reasons.append(f"有 {len(unknown)} 個風險訊號未判定 → fail-safe 預設 L2")
        return _no_downgrade("L2", active_tier, reasons)

    # 3) SIC-JS P0
    if task_priority == "P0":
        reasons.append("SIC-JS task.priority = P0")
        return _no_downgrade("L2", active_tier, reasons)

    # 4) ★ 訊號任一命中
    hit_star = [k for k in STAR_SIGNALS if signals.get(k)]
    if hit_star:
        reasons += [f"★ {STAR_SIGNALS[k]}" for k in hit_star]
        return _no_downgrade("L2", active_tier, reasons)

    # 5) 一般訊號兩項以上
    hit_normal = [k for k in NORMAL_SIGNALS if signals.get(k)]
    if len(hit_normal) >= 2:
        reasons += [NORMAL_SIGNALS[k] for k in hit_normal]
        reasons.append("一般訊號 ≥2 項")
        return _no_downgrade("L2", active_tier, reasons)

    # 6) 一項一般訊號，或有迴圈
    hit_loop = [k for k in LOOP_SIGNALS if signals.get(k)]
    if hit_normal or hit_loop:
        reasons += [NORMAL_SIGNALS[k] for k in hit_normal]
        reasons += [LOOP_SIGNALS[k] for k in hit_loop]
        return _no_downgrade("L1", active_tier, reasons)

    # 7) 全部明確為否
    reasons.append("無風險訊號、無迴圈")
    return _no_downgrade("L0", active_tier, reasons)


def _no_downgrade(proposed, active_tier, reasons):
    """agent 可向上升級，不可向下降級。降級只能由用戶明示。"""
    if active_tier and TIER_ORDER.get(proposed, 0) < TIER_ORDER.get(active_tier, 0):
        reasons.append(f"提議 {proposed} 低於已啟用的 {active_tier} → 拒絕降級，維持 {active_tier}")
        return active_tier, reasons
    return proposed, reasons


def load_tier(tier):
    path = os.path.join(TIER_DIR, f"{tier}.md")
    with open(path, encoding="utf-8") as f:
        return f.read()


def build_prompt(task_text, signals=None, task_priority=None,
                 user_override=None, active_tier=None):
    """
    協議一律置於 prompt 最末，緊貼行動點。
    （v0.6 把綁定規則埋在 4000 字中段，同時損失 recency 與清晰度。）
    """
    tier, reasons = select_tier(signals, task_priority, user_override, active_tier)
    protocol = load_tier(tier)
    prompt = f"{task_text}\n\n---\n\n{protocol}"
    return prompt, tier, reasons


# ── 自測 ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    ALL_FALSE = {k: False for k in ALL_SIGNALS}

    cases = [
        ("純問答，無任何訊號",
         dict(signals=ALL_FALSE), "L0"),
        ("小任務但涉及計價（task_b 那類）",
         dict(signals={**ALL_FALSE, "money_or_pricing": True}), "L2"),
        ("只是寫個檔案",
         dict(signals={**ALL_FALSE, "writes_files": True}), "L1"),
        ("寫檔 + production",
         dict(signals={**ALL_FALSE, "writes_files": True, "production_path": True}), "L2"),
        ("第二輪對話",
         dict(signals={**ALL_FALSE, "turn_ge_2": True}), "L1"),
        ("訊號未知（fail-safe）",
         dict(signals={}), "L2"),
        ("SIC-JS P0",
         dict(signals=ALL_FALSE, task_priority="P0"), "L2"),
        ("已啟用 L2，訊號變乾淨也不准降",
         dict(signals=ALL_FALSE, active_tier="L2"), "L2"),
        ("用戶明示 L0",
         dict(signals=ALL_FALSE, user_override="L0"), "L0"),
    ]

    print("=" * 66)
    print("  分層選擇自測")
    print("=" * 66)
    ok = 0
    for label, kwargs, expected in cases:
        tier, reasons = select_tier(**kwargs)
        good = tier == expected
        ok += good
        print(f"\n  [{'PASS' if good else 'FAIL'}] {label}")
        print(f"         → {tier}（預期 {expected}）")
        for r in reasons[:2]:
            print(f"           · {r}")

    print(f"\n  ── {ok}/{len(cases)} 通過 ──\n")

    # 示範組裝
    p, tier, _ = build_prompt("修好這段程式的 bug。",
                              signals={**ALL_FALSE, "money_or_pricing": True})
    print(f"  build_prompt 示範：tier={tier}, 總長 {len(p)} codepoints")
    print(f"  協議是否在最末：{p.rstrip().endswith('這是違規。')}")

    raise SystemExit(0 if ok == len(cases) else 1)
