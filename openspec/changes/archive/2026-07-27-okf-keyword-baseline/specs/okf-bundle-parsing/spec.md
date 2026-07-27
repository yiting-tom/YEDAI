## ADDED Requirements

### Requirement: 解析 OKF bundle 目錄結構

系統 SHALL 掃描指定根目錄下的每個子目錄作為一個 bundle，讀取其 `manifest.json`（若存在）與 `okf/` 下的所有 `.md` 檔。`_assets/` 目錄 MUST 被排除在解析之外。若根目錄本身即為單一 bundle（含 `okf/` 或直接含 `.md`），系統 SHALL 將其視為單一 bundle 處理。

#### Scenario: 標準多 bundle 目錄

- **WHEN** 根目錄下有 30 個子目錄，每個含 `manifest.json` 與 `okf/` 子目錄
- **THEN** 系統回傳 30 個 bundle，每個 bundle 的 `bundle_id` 取自 manifest 的 `id` 或 `name`，缺少時退回目錄名稱

#### Scenario: 缺少 manifest.json

- **WHEN** 某個 bundle 目錄沒有 `manifest.json`
- **THEN** 系統仍解析該 bundle 的 concept，`bundle_id` 使用目錄名稱，且不產生錯誤

#### Scenario: manifest.json 格式損毀

- **WHEN** `manifest.json` 不是合法 JSON
- **THEN** 系統記錄一則警告到解析報告，並繼續解析該 bundle 的 concept

#### Scenario: _assets 目錄被排除

- **WHEN** `okf/_assets/` 下存在 `.md` 檔案
- **THEN** 該檔案不被解析為 concept

### Requirement: 解析 concept frontmatter 與 body

系統 SHALL 從每個非保留名稱的 `.md` 檔解析 YAML frontmatter 與 markdown body。frontmatter MUST 支援 `id`、`type`、`title`、`slug`、`description`、`generated`、`content_hash`、`confidence`、`resource`、`provenance`、`tags`、`related`、`model`、`timestamp`、`assets`、`subpath`、`figures` 欄位。未知欄位 MUST 保留於 `extra` 而非丟棄。

#### Scenario: 完整 frontmatter

- **WHEN** concept 檔含所有已知欄位
- **THEN** 每個欄位都被正確填入 Concept 模型，`figures` 被解析為含 `file_id`、`type`、`title`、`description`、`key_points` 的結構

#### Scenario: 缺少 id 欄位

- **WHEN** concept 的 frontmatter 沒有 `id`
- **THEN** 系統以 `path:<相對路徑>` 作為 `concept_id`，且該 concept 仍可被檢索

#### Scenario: 未知欄位保留

- **WHEN** frontmatter 含規格未定義的欄位
- **THEN** 該欄位被保留在 `extra` 字典中

### Requirement: 容忍缺少 frontmatter 分隔線的變體

系統 SHALL 支援兩種 frontmatter 寫法：標準的 `---` 包夾，以及 frontmatter 內容直接接在檔案開頭、後續才出現 markdown 標題的變體（使用者的 `summary.md` 即為此格式）。

#### Scenario: 標準分隔線格式

- **WHEN** 檔案以 `---` 開頭並以 `---` 結束 frontmatter
- **THEN** frontmatter 與 body 被正確切分

#### Scenario: 無分隔線格式

- **WHEN** 檔案開頭直接是 YAML 鍵值對，第一個 markdown 標題之後才是內容
- **THEN** 標題之前的內容被解析為 frontmatter，標題起為 body

#### Scenario: 完全沒有 frontmatter

- **WHEN** 檔案只有 markdown 內容
- **THEN** frontmatter 為空字典，全文為 body，且不產生錯誤

### Requirement: 切分 body 為 section

系統 SHALL 依 `## ` 層級標題將 body 切分為 section 清單，每個 section 保留其標題文字與內容。第一個 `## ` 之前的前言內容 MUST 保留為一個標題為空字串的 section。

#### Scenario: 多個二級標題

- **WHEN** body 含 `## 現象`、`## 根因`、`## 對策` 三個標題
- **THEN** 系統回傳三個 section，標題分別為「現象」「根因」「對策」

#### Scenario: 沒有二級標題

- **WHEN** body 完全沒有 `## ` 標題
- **THEN** 系統回傳單一 section，標題為空字串，內容為整份 body

### Requirement: 保留檔名分流

系統 SHALL 將 `summary.md`、`log.md`、`index.md` 視為保留檔名，不解析為 concept。`summary.md` MUST 被解析為 bundle 層級文件並附加至該 bundle。

#### Scenario: summary 被分流

- **WHEN** bundle 的 `okf/` 下含 `summary.md`
- **THEN** 該檔不出現在 concept 清單中，而是被解析為 bundle 的 summary 文件

#### Scenario: log 與 index 被略過

- **WHEN** bundle 的 `okf/` 下含 `log.md` 與 `index.md`
- **THEN** 兩者皆不出現在 concept 清單中

### Requirement: 單檔失敗不中斷整批解析

系統 SHALL 在單一檔案解析失敗時記錄該檔路徑與失敗原因至解析報告的 `skipped` 清單，並繼續解析其餘檔案。解析報告 MUST 包含 bundle 數、concept 數、skipped 清單與 warnings 清單。

#### Scenario: 單一 concept 檔損毀

- **WHEN** 30 個 bundle 中有 1 個 concept 檔含無法解析的 YAML
- **THEN** 該檔進入 `skipped` 清單，其餘 concept 全部解析成功，解析程序正常結束

#### Scenario: 解析報告可查

- **WHEN** 解析完成
- **THEN** 呼叫端可取得 bundle 數、concept 數、skipped 清單與 warnings 清單

### Requirement: 產出與 index.md 相同格式的摘要行

每個 concept SHALL 能產出一行 `<concept_id> . <type> . [<filename>](<path>) . <description>` 格式的摘要文字，與 bundle 內 `index.md` 的行格式一致。

#### Scenario: 摘要行格式

- **WHEN** 對某個 concept 請求其索引行
- **THEN** 回傳字串符合 `<id> . <type> . [<檔名>](<路徑>) . <描述>` 格式
