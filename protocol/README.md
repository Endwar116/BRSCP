# Prompt-protocol line

Text that is pasted into a prompt. It decides when a model may write `complete`.
This line has its own version numbers; do not compare them with the code-gate line in `src/`.

| Folder | Version | Status | Use it? |
|---|---|---|---|
| [`v0.7/`](v0.7/) | 0.7 (2026-07-26) | **Current candidate**, not finalized | Yes — this is what to paste today |
| [`v1.0-rc1/`](v1.0-rc1/) | 1.0 trial (2026-09-30) | Experimental; acceptance not passed; not released | Only for experiments |

## 怎麼用 0.7（中文）

1. 依風險選一層：不可逆、對外、金流、安全或隱私，任一項就用 L2；風險不明也用 L2。可以往上加層，不准往下降。選法寫在 `v0.7/routing.json`，參考實作是 `v0.7/brscp_v07.py` 的 `select_tier()`。
2. 把那一層的文字放在 prompt **最後**。L0 483 字元、L1 1,189 字元、L2 1,528 字元。
3. 讀模型回的 `claimed_status`：
   - `complete`：每一項標準都要舉得出證據。
   - `continue`：在同一次回應裡續做，做完重跑檢查；做不完就改成 `escalate`。
   - `escalate`：也要舉證，寫出①試過什麼②為什麼不通③需要誰提供什麼。

## 兩版的方向相反

- **0.7 是保守端**：沒把握就升級，但升級要舉證。實驗裡會讓模型不太敢交。
- **1.0 是交付端**：預設交出，只有寫得出「最小失敗案例」才准升級。實驗裡讓模型幾乎全交，但交出去的錯答案也變多。
- 兩版都只改「敢不敢交」，沒有讓模型挑出自己答錯的題。所以下一步是外部核對，見 [`../reviewer/`](../reviewer/)。

各版本的來歷、可調閥五個部位、各場景配方：[`../docs/VERSIONS_AND_VALVE.zh-TW.md`](../docs/VERSIONS_AND_VALVE.zh-TW.md)。
