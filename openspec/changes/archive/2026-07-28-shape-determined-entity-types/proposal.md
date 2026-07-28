## Why

`entities_by_type` 是用來判斷「這個類型的字典值不值得維護」的依據。它現在對**每一個**具名類型都回報 `dictionary_coverage: 1.0`，而且結構上不可能回報別的數字。

成因在 `entities.py:257`：類型只有字典能給，regex fallback 一律標成 `unknown`。於是每個具名類型的 `regex` 計數恆為 0，比例恆為 1.0；所有未覆蓋的實體都掉進 `unknown` 這個無法歸屬的大桶。

合成語料正好證明了這件事。`_dictionary_chambers()` 刻意只把一半的機台腔體放進字典，就是為了讓覆蓋率缺口有東西可看：

```
chamber_id   total 180   dict 180   regex 0   dictionary_coverage 1.0
unknown      total 957   dict   0   regex 957
```

那 957 個 `unknown` 裡，**恰好 180 個含 `#`**——就是字典沒收的另一半腔體。真實的 chamber_id 覆蓋率是 180/360 = 50%，報告寫 1.0。

一個被設計來暴露缺口的量測，看不到刻意為它準備的缺口。這與先前「合成語料剛好符合樣式，測試全綠」是同一種病：量測只能確認自己。

## What Changes

- 識別碼樣式可宣告**形狀決定的類型**。regex fallback 命中該樣式時，實體帶該類型而非 `unknown`
- 層級展開的父層可宣告自己的類型（`X#Y` 的父層是 `tool_id`，晶圓的父層是 `lot`）
- 三個形狀已能唯一決定類型的樣式帶上宣告：`X#Y` → `chamber_id`、`xxxxxx.NN` → `lot`（`.00`）／`wafer`（其餘）、`\d+.\d{3}` → `op_no`
- 形狀不決定類型的樣式（`[A-Za-z]{2,5}\d{1,4}` 之類多型別共用者）維持 `unknown`——猜一個型別會產出**自信而錯誤**的分母，比沒有分母更糟
- `dictionary_coverage` 改為 `float | None`。**只有形狀完整決定的類型才給比例**；其餘只給計數並明確給 `null`

  「形狀完整」指該類型的每一次出現都必然被對應樣式圈到。`chamber_id`、`wafer`、`op_no` 成立。`tool_id`、`lot` 不成立——它們可以裸寫（`AEPOL1`、`AB1234`），而裸寫的形狀與其他類型無法區分，分母只會是下界，比例因此偏高。偏高的方向正好是「字典夠用、不必維護」，是最危險的偏誤方向。

## Capabilities

### Modified Capabilities
- `entity-matching`: regex fallback 可帶形狀決定的類型；覆蓋率比例只在分母可測時給出

## Impact

- **修改**：`tokenizer.py`（樣式宣告與類型回傳）、`entities.py`（抽取時採用）、`index.py`（覆蓋率比例可為 null）、`telemetry.py`、`schemas.py`、`docs/`
- **實體鍵改變**：`unknown:TSK04#PM3` → `chamber_id:TSK04#PM3`。查詢端與文件端**同步**改變，比對結果不變；`ID:` 詞元完全不動，模式 B 不受影響
- **索引必須重建**：`INDEX_FORMAT_VERSION` 6 → 7

## 為何 lot／wafer 依 `.00` 後綴分流

樣本檔裡使用者填的是 `lot: AB12345.00`、`wafer: AB12EX34.01`——`.00` 是批本身，`.NN` 是第幾片晶圓。這是依樣本而非依推測。

即使這個分流判斷錯了，代價也有上限：兩者的 `ID:` 詞元一字不改，錯的只是統計桶的標籤，檢索行為完全不變。而 `check-formats` 會立刻讓錯誤現形。
