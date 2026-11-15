# 第二部分：新基準與可調閥（2026-10-18）

> 設計與分析：協德（AI agent）。報告：[`20_結果報告_v0.2.md`](20_結果報告_v0.2.md)。

## 一句話

四家免費雲端模型 × 九格組合 × 100 題，一次跑完 3,600 次呼叫。一般與交付導向場景，四家成本最低的都是第 ⑨ 格；但協議沒有讓模型挑出自己的錯，交出去的錯答案也沒有變少。

## 這裡有什麼

| 檔 | 是什麼 |
|---|---|
| `00_預先登錄.md` | 開跑前寫死的設計、判準、場景倍數 |
| `PREREG_LOCK.json` | 預先登錄凍結時各檔的 sha256（見下面「雜湊怎麼對」） |
| `run_part2.py` | 跑手：九格怎麼組 prompt、怎麼呼叫 |
| `analyze_part2.py` | 照預先登錄算判定 |
| `diff_ci_part2.py` | 事後補算主要比較的差與 95% 區間 |
| `data/summary.json`、`data/summary_tables.md` | 九格完整數字 |
| `data/diff_ci.json`、`data/diff_ci_tables.md` | 差與區間 |
| `20_結果報告_v0.2.md` | 結果報告第二版 |

九格怎麼組：見 [`../../docs/VERSIONS_AND_VALVE.zh-TW.md`](../../docs/VERSIONS_AND_VALVE.zh-TW.md) 第四節。

## 沒有公開的東西

- **題庫**（排序題 80 道子題的兩種寫法）與 **原始作答紀錄**（`data/results.jsonl` 等）。題庫取材自內部工作紀錄，含不公開的內部內容；原始作答會引用題目原文，所以一起不公開。
- `run_part2.py` 匯入的 1.0 驗收實驗凍結跑手（`run_accept.py`）。
- 所以這裡的程式**無法單獨重跑**。公開的是方法與彙總數字。要重跑的人可以用自己的題庫：設環境變數 `BRSCP_QBANK_DIR` 與 `BRSCP_ACCEPT_DIR` 指到自己的資料夾。

## 雜湊怎麼對

- `PREREG_LOCK.json` 的 sha256 是內部未去識別原檔的雜湊。
- 公開副本的 `00_預先登錄.md` 和 `run_part2.py` 換掉了內部路徑與專案負責人的暱稱，所以雜湊不同；替換次數見 [`../../REDACTION_LOG.md`](../../REDACTION_LOG.md)。
- `tiers/G.md` 與 `tiers/primer_poolA.txt` 沒改，可以直接對 [`../../protocol/v1.0-rc1/`](../../protocol/v1.0-rc1/) 的檔驗。

## 限制（摘自報告第七節）

只有一種題型；四家都是免費雲端模型，沒有本機錨點；不加協議那組交得太少；99 筆解析失敗集中在一家；區間是事後補算；做和驗都是同一個 agent，沒有第三方覆核。
