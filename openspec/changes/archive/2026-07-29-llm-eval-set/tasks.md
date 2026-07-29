## 1. Chat 客戶端

- [x] 1.1 `ChatClient` 協定，讓測試離線替換
- [x] 1.2 `HttpChatClient`：OpenAI 相容 `/chat/completions`，與 embedding 同結構
- [x] 1.3 金鑰只從環境變數；缺漏時指名該變數
- [x] 1.4 JSON 解析要容忍 ```json 圍欄與前後贅語
- [x] 1.5 落地快取，鍵含模型名稱

## 2. 評估集產生

- [x] 2.1 取樣 concept（跨 type／bundle 分散，不要全擠在同一類）
- [x] 2.2 提示：以「未讀過本文」的角度提問，並要求同時產出症狀式查詢
- [x] 2.3 每項帶 kind（identifier / symptom）
- [x] 2.4 解析失敗跳過該筆並計數，不中止整批
- [x] 2.5 產出 JSONL，預設路徑已 gitignore，檔頭記錄偏誤

## 3. 語料外流閘門

- [x] 3.1 `llm.trusted_endpoint` 獨立於 `embedding.trusted_endpoint`
- [x] 3.2 測試：embedding 可信不會讓 LLM 也可信

## 4. 指標

- [x] 4.1 recall@k 與 MRR，逐模式
- [x] 4.2 依 kind 拆解
- [x] 4.3 未命中計入分母
- [x] 4.4 輸出載明標籤只涵蓋單一相關文件、指標為下界

## 5. CLI 與報告

- [x] 5.1 `yedai gen-evalset`
- [x] 5.2 `yedai evaluate`
- [x] 5.3 `report` 納入評估結果，且不含查詢原文
- [x] 5.4 測試：報告仍然零語料內容

## 6. 測試（全部離線）

- [x] 6.1 假的 chat 客戶端
- [x] 6.2 JSON 圍欄與贅語的解析
- [x] 6.3 解析失敗不中止整批
- [x] 6.4 指標算式（含未命中計入分母）
- [x] 6.5 快取避免重複請求

## 7. 文件

- [x] 7.1 `docs/evaluation.md`：能回答什麼、標籤的兩個偏誤、怎麼讀
- [x] 7.2 README 流程補上 gen-evalset → evaluate
