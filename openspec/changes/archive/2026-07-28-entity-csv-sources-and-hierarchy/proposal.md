## Why

**一、`#` 不是識別碼分隔符，腔體層被切碎。**

真實語料的機台與腔體寫在同一張表，以 `#` 區分：`aepol1` 是機台，`aepol1#pm1` 是它的腔體。現有斷詞器不認得 `#`：

```
aepol1#pm1  →  ['ID:AEPOL1', 'ID:PM1']
aepol6#pm1  →  ['ID:AEPOL6', 'ID:PM1']
```

`ID:PM1` 因此在所有機台之間共用——高頻、低鑑別力，正是模式 A 才該有的病。**模式 B 存在的唯一理由是「識別碼不被切碎」，而它在腔體層是失效的。**

這會扭曲消融實驗的結論。缺陷讓模式 B 被低估，`A-B` 的 jaccard 因而偏高，而 README 對此的判讀規則是「接近 1 → 天真斷詞已經夠好，後面所有機制都是過度設計」。**在修好之前收集的數據會導出相反的結論。**

現有樣式之所以漏掉這個形狀，是因為它們照著 `TEL-05` 這類**虛構識別碼**寫成，而合成語料的產生器產出的 id 剛好符合那些樣式——程式一直在跟自己對答案。

**二、真實字典是 CSV，不是 YAML。**

機台清單由 MES 匯出（單欄）；缺陷清單已有既有維護者，格式為 `Module, defect code, defect name`。要求維護者改寫成 YAML 等於要他們手工轉檔，實務上不會發生，字典就會過期。

缺陷清單尤其關鍵：`defect name` 就是別名欄，而「微粒」「刮傷」這類**一般詞沒有任何結構可讓正則辨識**，只有字典能對到正規名稱。這是模式 C 唯一真正由字典驅動的一條腿。

**三、字典覆蓋率是單一全域數字，無法解讀。**

模式 C 的兩條腿性質完全不同：

| 腿 | 字典的作用 | 沒有字典時 |
|---|---|---|
| 缺陷詞 | 語義正規化 | **歸零** |
| 機台／腔體 | 擋掉 regex 誤圈 | 精確度下降 |

單一比例會把兩者平均掉。「fallback 佔 60%」可能是「集中在未維護清單的類型」（符合預期）或「集中在 tool」（字典有洞），兩者意義相反卻無法區分。

## What Changes

- 識別碼樣式納入 `#`；正規化保留 `#`（`aepol1#pm1` → `AEPOL1#PM1`），與 `- _ 空白` 的移除規則不同
- **層級展開**：含 `#` 的識別碼同時產生子層與父層詞元（`ID:AEPOL1#PM1` 與 `ID:AEPOL1`），使「查機台命中腔體文件」成立
- 新增 **CSV 實體來源**，於設定宣告，依類型各自解析：
  - `id_only`：單欄識別碼（機台與腔體同表，以 `#` 判定類型）
  - `module_code_name`：三欄（`Module` 為中繼資料不進 key；`code` 全域唯一；`name` 為別名）
- 別名語言處理：整格註冊，同時將中文段與拉丁段各自註冊——不需事先知道混合形式
- YAML 字典保留，與 CSV 並存
- 字典覆蓋率統計**依實體類型拆解**
- `*.local.csv` 進 `.gitignore`；repo 只放編造值的範例檔

## Capabilities

### New Capabilities
- `entity-csv-sources`: 以 CSV 為實體字典來源，依類型宣告 schema 並各自解析

### Modified Capabilities
- `keyword-retrieval`: 識別碼保護斷詞支援 `#` 與父子層級展開
- `entity-matching`: 實體來源新增 CSV；類型由來源宣告而非推測
- `retrieval-telemetry`: 字典覆蓋率依實體類型拆解

## Impact

- **修改**：`tokenizer.py`（`#` 樣式、層級展開）、`entities.py`（CSV 載入器）、`config.py`（`entity_sources`）、`index.py`（per-type 統計聚合、格式版本）、`telemetry.py`（per-type 報告欄位）、`.gitignore`
- **新增**：`tools.example.csv`、`defects.example.csv`（**編造值**，與合成語料同等地位）
- **索引必須重建**：斷詞行為改變 → `INDEX_FORMAT_VERSION` 3 → 4，舊快取明確拒絕載入並提示重建
- **字典指紋不需另外處理**：`EntityDictionary.fingerprint()` 由 `_alias` 內容導出，CSV 載入後自動生效，換字典仍會使索引簽章失效
- **資料安全**：真實機台與缺陷清單屬敏感資料，`*.local.csv` MUST 進 `.gitignore`。本 repo 為公開，這是硬性條件而非選項
- **報告洩漏面**：per-type 欄位只含**類型名稱**（schema），不含正規名稱（內容）。`test_report_leaks_no_corpus_content` 需涵蓋新欄位

## 不在本次範圍

`flow` / `process` 的正則修正、`op no`、`lot` 長度語義、`drbl`、`recipe` 複合分解、`layer`、機台碼的欄位分解。這些屬同一份斷詞器的後續工作，待其格式規格齊備後另案處理。
