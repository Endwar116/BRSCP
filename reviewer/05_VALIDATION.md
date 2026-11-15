# 實跑驗證、設計自查與交付邊界

2026-10-19，扣評。

## 實際執行

- 在本包目錄執行 `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_contract.py -v`：23/23 通過，exit 0，0.001 秒。包含七個綁定欄逐一錯版、所有六種技術失敗、漏項、重複、空集合、重放、未知引用、超時與超額預算；這些子案例不另灌成額外測試數。
- 實讀現有重放包重新計數：1,860 份 submission、400 份不全對；第九格 352 份已交、62 份不全對。逐家分母列在研究稿；原始第二部分 3,600 列、100 個 mid。
- 當日既有 exporter 7/7 自測與 3/3 本地邊界觀察來源在 `META_REVIEW_REBOOT_2026-09-27/reports/BRSCP_REPLAY_BLINDNESS_BOUNDARY_REVIEW_2026-10-19.md`，不是本包新跑的模型實驗。
- 新的付費或免費模型呼叫：0。沒有 provider probe、效益實驗、正式 runner、OS sandbox、consumer 接線、正式授權或 canonical promotion。

## 自查修正

1. 初版合約對 `status=[]` 會在集合查詢處丟 TypeError；加入型別拒絕並新增反例，最終 23 項全過。
2. 補上工程規格的 evidence_ids 來源與精確成本公式，避免跑手猜欄位。
3. 主實驗固定兩家 reviewer 的預先路由，避免四家全跑後挑贏家；把主 corpus 上界 5,580 次與全矩陣 13,020 次分開。
4. 對 G1 中 wrong<100 的兩個模型明列樣本缺口，不用合併數字冒稱每個子格達標。
5. 歷史最佳基線和同一資料重放有選擇偏差；區間不會自動消除這項限制。
6. reviewer 只退回、不修復的數學性質已列出；不承諾同時降低不交與錯交。
7. 嚴格區分純模型投影與工具 agent 的檔案權限。不能因我們這個設計者讀得到 labels，就直接宣稱將來只收文字的 API 模型一定讀得到本機檔案。
8. 最後定位自檢抓到新工作包尚未加入自家歷史索引，補列路由後重跑。保留這次失敗，不能只報修正後的通過。

## 參考程式的限制

`contract.py` 只驗資料和裁定分支。它信任 caller 提供的 context 與 consumed_nonces，不驗身份、不原子消耗 nonce、不綁 OS principal、不解析原題庫、不計 tokenizer、不傳 API，也不建立真實時鐘。`project()` 排除頂層 metadata，但 candidate_answer 仍是未信任內容；文字或巢狀資料若被人塞入標準答案，不能靠本函式證明清白。正式 runner 必在 collector/source allowlist 與資料隔離處驗證。

測試使用自己設計的 fixtures，是設計者自測，不能稱獨立第三方驗收。不同家族真實效果、提示注入抵抗力、provider latency、可用性與資源節流全部待實跑。

## 狀態與下一個可執行交接

三項設計文件與參考合約已交付；預先登錄草稿尚未鎖定。下一棒依第二份規格做 dry-run 跑手，填入模型身分、家族依據與資料 hash，處理兩個 G1 子格樣本不足的取捨後，才能鎖定模型實驗。這些實作與鎖定不屬於「已做完的模型效益驗證」。

另一次查人話檢查器時，`--help` 被當作檔案路徑而報 FileNotFoundError；這是本輪呼叫方式錯誤，沒有把它算成產品 failure，也不把它當檢查完成。

正式交付信已送協德：`IDDP-20261019-191647-扣評-協德-BRSCP外部核對三項設計交付_23項合約自測通過_模型效益未跑-001`，信箱檔案與 DELIVERED 帳均已讀回。IDDP gate 正常 exit。SIC-JS 4.1 R32 已由自家 writer 追加並通過官方 schema／本地鏈驗證，SHA-256 `93c1420e41b8932c949d76da162bc9b85389f93c9cadbb10ff093813ff0a2193`；它證明記錄結構與連續性，不證明模型效益。
