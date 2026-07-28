# 設計

## 一、`response_model_exclude_unset=True` 是必要的，不是優化

把回傳的 dict 交給 Pydantic 驗證後，序列化預設會輸出**模型宣告的全部欄位**，缺的補成 `null`。這會改變既有契約，遷移時實測到兩處：

```
POST /v1/concepts  include_raw=false
  before:  concept 物件沒有 raw 這個鍵
  after :  raw: null            ← 多出來的

GET /v1/report     無點選紀錄時
  before:  clicked_rank_distribution = {"n": 0}
  after :  {"n": 0, "min": null, "p25": null, ...}   ← 多出來的
```

`include_raw=false` 的用途正是「省掉全文的體積」，回一個 `raw: null` 讓 `"raw" in concept` 這種判斷從 False 變成 True。這不是美觀問題，是行為改變。

考慮過的替代方案與否決理由：

- **`response_model_exclude_none=True`** — 會連帶刪掉**本來就該是 null** 的欄位（`kendall_tau`、`display_order`、`version.index`、concept 的 `confidence` 等）。從「多加欄位」變成「少掉欄位」，更糟。
- **把可選欄位宣告成必填** — 那是拿型別去遷就序列化行為，且 `raw` 本來就依參數決定存在與否。

`exclude_unset` 的語義剛好對上需求：只輸出**輸入 dict 裡實際出現過**的鍵。模型因此純粹是描述層，不參與決定回應內容。

## 二、`extra="allow"` 的理由

所有模型設 `extra="allow"`。回應是手寫的 dict，模型漏列一個欄位是可能的；預設的 `ignore` 會讓那個欄位**被靜默裁掉**。

比較兩種失敗：

- 模型漏列 → schema 少一個欄位的描述（文件不完整，但回應仍正確）
- 模型漏列 + 裁切 → 呼叫端收不到那個欄位（回應錯誤，且沒有任何錯誤訊息）

第二種嚴重得多，而且症狀出現在呼叫端、成因在服務端，極難追。所以寧可 schema 不完整，也不要回應被裁。

`test_response_fields_are_documented` 從另一個方向補上：schema 有的欄位文件必須提到，所以 schema 的完整性有獨立的壓力來源。

## 三、`/v1/report` 為什麼不完整建模

報告含三種動態鍵的映射：`entities.by_type`（鍵是實體類型）、`mode_overlap`（鍵是模式組合）、`clicks_per_mode`（鍵是模式），以及會隨實驗調整而增減的指標。

若把每個指標寫成欄位，「加一個統計數字」就變成要同步改模型、測試與文件三處。而報告的指標**不是契約**——它是實驗產物，本來就該隨著問題演進而變。

所以只建模頂層區塊（`corpus` / `entities` / `queries` / `modes` / `mode_overlap` / `feedback` / `experiment_params`）與 `Distribution`。前者告訴讀者報告分成哪幾塊，後者出現十餘次、形狀穩定，值得一個名字。

## 四、沒有抽出 `ConceptSummary`

`HitOut` 與 `NeighborOut` 有六個同名欄位（`concept_id` / `bundle_id` / `type` / `title` / `description` / `path` / `index_line`），看起來可以抽共用基底。沒有這麼做。

兩者的其餘欄位語義完全不同：一個帶排名與三種分數，一個帶跳數與來源邊。它們同形是因為都描述「一筆 concept 的摘要」，但演化方向不同——檢索結果會增加分數相關欄位，關聯結果會增加路徑相關欄位。綁在一起之後，任何一邊的變動都要考慮另一邊。

在 schema 這種**描述用**的型別上，重複比錯誤的抽象便宜。
