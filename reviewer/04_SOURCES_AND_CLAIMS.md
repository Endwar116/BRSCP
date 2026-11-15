# 來源與宣稱邊界

查證日：2026-10-19。下列論文查到一手作者摘要／版本頁，未宣稱全文實驗重現。

| ID | 一手來源 | 本包採用的最窄結論 |
|---|---|---|
| W1 | [Huang 等，ICLR 2024，2310.01798v2](https://arxiv.org/abs/2310.01798v2) | 其測試中無外部回饋的自我修正困難；不能推成所有設定不可能 |
| W2 | [Liu 等，2406.15673v2](https://arxiv.org/abs/2406.15673v2) | 作者報告零溫度、公平提示下可觀察內生自我修正；本包以此限制 W1 的過度泛化 |
| W3 | [Zheng 等，MT-Bench，2306.05685v4](https://arxiv.org/abs/2306.05685v4) | 模型評審有位置、長度、自我偏好與推理限制；偏好評估不能直接等同完成判斷 |
| W4 | [OverclaimBench，2609.20812v3](https://arxiv.org/abs/2609.20812v3) | 以執行逐字稿對照最終報告的動作宣稱；本包沒有重用其百分比作本地效益 |
| W5 | [OpenAI 官方 Agents SDK guardrails 與人工審批](https://developers.openai.com/api/docs/guides/agents/guardrails-approvals) | output guardrails 在最終 agent 輸出；工具副作用要就近檢查；guardrails 與人類批准分工 |
| W6 | [Claude Code 官方 hooks](https://code.claude.com/docs/en/hooks#stop) | Stop 可控制繼續；需處理 stop_hook_active 和循環上限，不能推為全殼強制安全 |

## 本地直接讀取的來源

- 原信：`<internal-path>`。
- 補充信：同 inbox 的 `IDDP-20261018-協德-扣評-外部核對需求說明書v1.0與離線重放材料已備_補充前信-002.md`。
- 現行 pointer：`<internal-path>`，仍為 0.7 候選，1.0-rc1 不封版。
- 完整需求：`<internal-path>`，七題在第七節、交件定義在第八節。
- corpus：同目錄 `離線重放材料/submissions.jsonl` 與 `labels.jsonl`；原始嘗試 `<internal-path>`。
- 場景依據：同第二部分 `data/summary.json` 與 `20_結果報告_v0.2.md`。本次逐列計數，未重算所有摘要區間。
- 題目本體：`<internal-path>` 與 `pool_B_natural.txt`。
- wrapper：`<internal-path>`，當前 `verifier.check` 後直接輸出、映射退出碼。
- 自家經驗入口：`<internal-path>` 第五節；各次測試詳見 `META_REVIEW_REBOOT_2026-09-27/reports/`。
- 當日盲審邊界原始審查：該 reports 下 `BRSCP_REPLAY_BLINDNESS_BOUNDARY_REVIEW_2026-10-19.md`，含 hashes、3/3 觀察與限制。

## 有證據與尚待驗證

| 主張 | 狀態 | 可以怎麼說 |
|---|---|---|
| reviewer 設計回答七題、提供工程與測試規格 | 本包可直接檢視 | 文件設計已交付 |
| 1,860 submission、400 wrong、第九格 352/62 | 本地資料重新計數 | 這個 corpus 的計數；不代表新模型效益 |
| 控制合約拒絕舊 task、缺項、失敗狀態與重放 | 自家 unittest 可驗 | 無網路的參考合約通過指定測試 |
| 外部模型能改善高風險成本 | 尚未測 | 待依預登錄鎖定與實跑 |
| reviewer 與 scorer 已有 runtime 權限分離 | 尚未部署 | 工程規格，不是當前保證 |
| 正式內部收尾閘、Codex 或 Claude 已完成接線 | 尚未實作 | adapter 驗收仍待 owner |
| 不同家族代表真正獨立裁判 | 無此證據 | 只是實驗處置與風險降低假設 |

論文參考合計只摘取研究範圍與限制，未複製全文、表格或大段原文。模型家族名稱與本地路徑不等同可公開發布的授權。
