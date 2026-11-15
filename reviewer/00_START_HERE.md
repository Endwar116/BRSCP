# BRSCP 外部核對：扣評三項設計交付

作者：扣評。版本：0.1，2026-10-19。狀態：`DESIGN_DELIVERED_NOT_EXPERIMENTALLY_ACCEPTED`。

BRSCP 是交付前判斷完成程度的提示協議；本包設計其第五個可選部位：外部核對。

| 交付 | 入口 | 完成範圍 |
|---|---|---|
| 包一：技術範圍研究 | [01_SCOPE_RESEARCH.md](01_SCOPE_RESEARCH.md) | 七題答覆、文獻校正、替代方案與事故經驗 |
| 包二：可執行工程規格 | [02_ENGINEERING_SPEC.md](02_ENGINEERING_SPEC.md) | 輸入輸出、有限狀態、成本、接線、失敗與回復 |
| 包三：地獄級測試預先登錄草稿 | [03_BENCHMARK_PREREG_DRAFT.md](03_BENCHMARK_PREREG_DRAFT.md) | 六組比較、二十類成對案例、樣本、統計與停止規則 |
| 可執行合約參考 | [contract.py](contract.py) | 無模型呼叫的裁定合約與匿名投影；不負責正式部署 |
| 合約驗收 | [test_contract.py](test_contract.py) | 任務與內容綁定、重放、覆蓋、錯誤狀態、預算與資料洩漏 |
| 一手來源與本地證據 | [04_SOURCES_AND_CLAIMS.md](04_SOURCES_AND_CLAIMS.md) | 來源、核對程度、允許宣稱 |
| 執行與限制 | [05_VALIDATION.md](05_VALIDATION.md) | 實跑結果、仍未實作的整合邊界 |

接續對象：協德整合研究；重放跑手作者依工程規格實作；管雞評估內部收尾閘接線。本包不改共享正本。

核心選擇：先以程式檢查結構與證據，再用一次無工具、不同模型家族的呼叫判斷內容；控制程式處理綁定與交付。沒有把 reviewer 改成第二個任意工具 agent。

三個必要校正：只退回不修復的 reviewer 不會減少「不交」；同家族自我核對是待測的對照組，不能先判定無效；不同家族不代表統計獨立。

開始重跑：在本目錄執行 `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_contract.py -v`。無第三方相依套件、無網路呼叫。研究實驗尚未執行，不能用這個本地結果宣稱 reviewer 有效。
