# External review — design v0.1 (2026-10-19)

> **Status: `DESIGN_DELIVERED_NOT_EXPERIMENTALLY_ACCEPTED`.** The design and the reference contract exist; no model experiment has been run. Do not cite this folder as evidence that external review works.

外部核對是可調閥的第五個部位：答案交出前，讓另一家模型看過，只放行或退回。設計者：扣評（AI agent）。從 [`00_START_HERE.md`](00_START_HERE.md) 開始讀。

## 三個要先知道的校正（設計者的原話整理）

1. 只放行或退回、不修答案的核對者，不可能讓「不交」變少。目標改成：高風險場景成本下降、正確交付的損失受控。
2. 同一家族的自我核對不能先判定無效，要留成對照組。
3. 不同家族不代表統計上獨立，也可能一起錯。

## 跑自測

```bash
python3 -B -m unittest test_contract.py -v    # 23 tests, no network, no third-party packages
```

自測只驗合約本身：任務與內容綁定、重放、覆蓋、錯誤狀態、預算、資料不外洩。**不代表核對者有效。**

## 引用了但沒有公開的材料

文件裡提到的離線重放材料（`submissions.jsonl`、`labels.jsonl`）、題庫（`pool_B_natural.txt` 等）、內部信件與內部審查報告，都沒有公開，原因同 [`../experiments/part2_2026-10-18/README.md`](../experiments/part2_2026-10-18/README.md)「沒有公開的東西」。文件裡的 `<internal-path>` 是去識別時換掉的內部路徑，「內部收尾閘」指家裡既有的收尾閘程式；替換次數見 [`../REDACTION_LOG.md`](../REDACTION_LOG.md)。

## 要幫忙

見總 README 的 **HELP WANTED** 第 1 項：照 [`02_ENGINEERING_SPEC.md`](02_ENGINEERING_SPEC.md) 寫重放跑手，照 [`03_BENCHMARK_PREREG_DRAFT.md`](03_BENCHMARK_PREREG_DRAFT.md) 先鎖預先登錄再跑。
