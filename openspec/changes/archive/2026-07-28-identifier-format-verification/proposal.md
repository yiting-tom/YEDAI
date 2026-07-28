## Why

識別碼樣式是這個實驗的地基：模式 B 與模式 C 的全部效果都建立在「識別碼被當成一個整體」之上。而目前沒有任何機制能回答一個基本問題——**這些樣式涵蓋得了真實語料裡的識別碼嗎？**

已經有兩次證據顯示答案是「不能」：

1. `#`（機台#腔體）不在任何樣式裡，腔體層在模式 B 完全失效。修掉了，但它存在了整段開發期。
2. 220 個測試全綠的同時，樣式其實一條也沒對上真實形狀——因為合成語料的產生器產出的 id 剛好符合那些樣式。**程式在跟自己對答案。**

這不是「還有幾個樣式要補」的問題。補完這一批，下一次語料引入新的識別碼形狀時，同樣的失效會再發生一次，而且同樣沒有任何測試會紅。

問題的根源是**驗證方式**：正確性的唯一判準應該是「真實形狀有沒有被完整圈出」，但真實形狀屬敏感資料，不能進版控，於是從來沒有被拿來驗證過。

## What Changes

- 新增**格式樣本**機制：使用者在本機維護一份各類型的識別碼樣本，系統驗證每個樣本是否被當成單一識別碼完整圈出
- 新增 `yedai check-formats` 指令，逐類型列出覆蓋與未覆蓋的樣本，未覆蓋時以非零狀態碼結束
- 樣本檔進 `.gitignore`；repo 內附一份**編造值**的範例檔，讓機制本身在 CI 有測試涵蓋
- 依已明確提供的格式新增樣式：
  - `op no`：`0000.000` / `000.000`
  - `lot` / `wafer`：`xxxxxx.NN`，並沿用既有的父子展開機制（wafer → lot）
  - `tech`：`N` 起始的三碼

## Capabilities

### New Capabilities
- `identifier-format-verification`: 以本機樣本驗證識別碼樣式的涵蓋率，不需將真實識別碼納入版控

### Modified Capabilities
- `keyword-retrieval`: 識別碼樣式涵蓋 op no、lot／wafer 與 tech；wafer 沿用父子展開

## Impact

- **新增**：`src/yedai/formats.py`（樣本載入與涵蓋率檢查）、`identifier-samples.example.yaml`（編造值）
- **修改**：`tokenizer.py`（新樣式與 `.` 分隔的展開）、`config.py`（`identifier_samples_path`）、`cli.py`（`check-formats`）、`.gitignore`
- **索引必須重建**：新增樣式改變斷詞結果 → `INDEX_FORMAT_VERSION` 4 → 5
- **資料安全**：樣本是真實識別碼，屬敏感資料。`*-samples.local.yaml` MUST 進 gitignore

## 不在本次範圍，且**擋在缺少格式規格上**

`part6` / `part7`、`route`、`stage`、`subroute`、`layer` 目前只有名稱與意義，**沒有字元組成**。`recipe` 與 `drbl` 的欄位結構已知，但它們內嵌 `part6` 與 `layer`，同樣被擋住。

這些不寫進來是刻意的：照猜測的形狀寫樣式，正是本提案要根除的失效模式。`check-formats` 會把它們列為「無樣本」，補上樣本之後缺口就會自己浮出來。

機台碼的欄位分解（`[phase][area][process][vendor][series]`）也不在本次——區段對照表尚不完整（area 的清單以 `…` 結尾），且它是檢索功能而非缺陷修復。
