## Why

修正後的樣本暴露了一個真的不一致：

```
BCSTD3    → 識別碼        series 是數字
BCSTDA    → ❌ 非識別碼   series 是字母
BCSTDA#1  → 識別碼        同一台機器，寫上腔體就變識別碼了
```

機台編碼的 series 位允許 `1~9` 與 `a~z`。現有的 `[A-Za-z]{2,5}\d{1,4}` 只抓得到數字結尾那種，於是**同一台機台單寫時不是識別碼、帶腔體寫時是**——正是 lot 在 6 碼與 7 碼之間表現不一致的同一種錯誤。這種不一致不會報錯，只會讓模式 B/C 在一部分機台上悄悄失效。

用完整的組成規則寫樣式可以修好它。誤圈量量過了：英文字典 236k 字中只中 9 個（`lastly`、`bustle`、`festal` 之類）。

**但那條樣式不能放進這個 repo。** 它是機台編碼的完整組成規則，比 `0000.000` 這種形狀具體得多，而這個 repo 是公開的。

現行的設定覆寫救不了這件事：`identifier_patterns` 只收字串，而字串承載不了類型宣告。把規則寫進 `config.local.yaml` 的結果是它的命中全部歸入 `unknown`——修好了斷詞，卻弄壞了覆蓋率統計。

## What Changes

- `identifier_patterns` 的每一項可以是字串，**或**一個帶宣告的 mapping：
  `{pattern, type, parent_type, shape_complete}`
- 敏感的組成規則因此可以住在 gitignored 的本機設定，公開 repo 只留機制
- 公開文件用**編造**的例子說明用法

## Capabilities

### Modified Capabilities
- `entity-matching`: 設定可為自訂樣式宣告類型，不再只能繼承內建宣告

## Impact

- **修改**：`tokenizer.py`（`resolve_specs` 接受 mapping）、`config.py`（驗證）、`docs/indexing.md`
- **不影響**：內建樣式、既有設定檔（字串形式照舊）、索引格式

## 為什麼不乾脆放進內建樣式

因為公開與私密的界線一旦鬆一次就回不去了。已經在 repo 裡的 `xxxxxx.NN`、`0000.000` 是形狀；機台的 phase／process／vendor 字元集是廠內分類法。兩者的敏感度不同，不該因為「反正都是格式」就一起放行。

而且這個機制本來就該存在：`route`、`stage`、`recipe`、`drbl` 的格式遲早也要進來，每一條都開一次 PR 到公開 repo 是錯的路徑。
