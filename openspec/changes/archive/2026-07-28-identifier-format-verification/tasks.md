## 1. 格式樣本機制

- [x] 1.1 新增 `src/yedai/formats.py`：載入樣本檔（類型 → 樣本清單）
- [x] 1.2 `check_coverage(tokenizer, samples)` 回傳每個樣本的判定：`full` / `partial` / `none`
- [x] 1.3 `partial` 的判定必須嚴格：命中超過一段，或命中範圍未涵蓋整個樣本
- [x] 1.4 樣本檔不存在時回報「無樣本」而非拋錯；路徑指定了但檔案不存在則明確失敗

## 2. 設定與資料安全

- [x] 2.1 `config.py` 新增 `identifier_samples_path`
- [x] 2.2 `.gitignore` 加入 `*-samples.local.yaml`
- [x] 2.3 新增 `identifier-samples.example.yaml`（**編造值**）
- [x] 2.4 `config.example.yaml` 補上設定與說明

## 3. CLI

- [x] 3.1 `yedai check-formats`：逐類型列出 full / partial / none
- [x] 3.2 未涵蓋或部分涵蓋時列出該樣本的實際斷詞結果
- [x] 3.3 存在 partial 或 none 時以非零狀態碼結束
- [x] 3.4 無樣本的類型單獨列出，讓缺口可見

## 4. 已確定格式的樣式

- [x] 4.1 `op no`：`0000.000` / `000.000`，整段圈出且**不展開**
- [x] 4.2 `lot` / `wafer`：`xxxxxx.NN` 整段圈出，並展開出批號層
- [x] 4.3 `tech`：`N` 起始三碼
- [x] 4.4 確認新樣式的優先順序不破壞既有的 `#` 與長樣式優先

## 5. 展開規則分化

- [x] 5.1 `expand_hierarchy` 支援 `.` 分隔
- [x] 5.2 純數字識別碼（op no）不展開——小數點在此不是父子關係
- [x] 5.3 `INDEX_FORMAT_VERSION` 4 → 5

## 6. 測試

- [x] 6.1 三種判定各自的案例（含「被切成兩段」必須是 partial 而非 full）
- [x] 6.2 op no 不被切開、且不產生父層詞元
- [x] 6.3 wafer 展開出 lot；不同 lot 的同號 wafer 不混淆
- [x] 6.4 tech 被當成識別碼
- [x] 6.5 CLI 在有未涵蓋樣本時回非零狀態碼
- [x] 6.6 範例樣本檔本身全部通過（讓機制在 CI 有涵蓋）

## 7. 文件

- [x] 7.1 `docs/indexing.md` 說明樣本檔的用途、格式與為何不能進版控
- [x] 7.2 `README.md` 的調參旋鈕補上「樣式涵蓋率由 check-formats 驗證」
- [x] 7.3 記錄尚缺格式的類型清單，讓下一次接手的人知道缺口在哪

## 8. 驗證

- [x] 8.1 `uv run pytest` 全綠
- [x] 8.2 以範例樣本檔跑 `check-formats`，確認輸出與狀態碼

## 9. 過程中發現並修正的既有缺陷

- [x] 9.1 `XTR-05#PM1` 被咬成 `ID:XTR05` + `ID:PM1`——`#` 樣式不允許父層含 `-`，
      而含連字號的機台是既有語料裡就有的形狀（`tools.example.csv` 裡就有一筆）。
      **這是上一個 commit（`94a2ffa`）留下的缺陷，由 `check-formats` 在啟用後數分鐘內抓到。**
