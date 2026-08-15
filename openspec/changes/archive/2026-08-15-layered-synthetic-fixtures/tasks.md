## 1. defect 全集為單一來源

- [x] 1.1 在 `synthetic.py` 定義 defect 全集：識別碼、中文與英文別名、category（全部為編造值）
- [x] 1.2 全集中標記三種 taxonomy 狀態：有 method、有條目無 method、無條目
- [x] 1.3 測試：字典、兩份 CSV、taxonomy、defect 全集檔中的 defect 識別碼集合彼此相容

## 2. 分層語料

- [x] 2.1 定義層的宣告：層名、語料根目錄、模板集合、識別碼密度、bundle 數來源
- [x] 2.2 `library` 層模板：固定三段（形貌／常見成因／關聯），每個 defect 一條，識別碼稀少
- [x] 2.3 `heuristics` 層模板：自由段落，段數與標題不定，文本長，識別碼稀少
- [x] 2.4 `cases` 層模板：沿用既有七段查案模板，識別碼密集
- [x] 2.5 `concept_id` 命名空間納入層名（`ns = f"s{seed}-{layer}-"`）
- [x] 2.6 測試：任兩層之間不存在相同的 `concept_id`
- [x] 2.7 測試：各層 concept 的 `## ` 標題序列不出現另一層的模板
- [x] 2.8 測試：cases 層每篇平均識別碼數明顯高於 heuristics 層
- [x] 2.9 測試：library 層的 concept 涵蓋 defect 全集

## 3. 實體來源產物

- [x] 3.1 產出 `dictionary.yaml`（沿用既有內容，defect 段改由全集衍生）
- [x] 3.2 產出 `tools.csv`：單欄 `id_only`，含 `#` 層級列與其父層列
- [x] 3.3 產出 `defects.csv`：三欄 `Module, defect code, defect name`，由全集衍生
- [x] 3.4 測試：兩份 CSV 皆可被實體來源載入器讀入而不報錯
- [x] 3.5 測試：單欄 CSV 中每個層級列的父層識別碼亦單獨成列

## 4. 查表資源產物

- [x] 4.1 產出 `taxonomy.yaml`：鍵為 defect，欄位限於允許鍵
- [x] 4.2 產出 `defects.catalogue.yaml`：defect → category，涵蓋全集
- [x] 4.3 測試：三種 taxonomy 狀態皆存在，且有條目的 defect 數小於總數
- [x] 4.4 測試：taxonomy 載入器讀入產物時不產生 unknown key 警告

## 5. 識別碼樣本

- [x] 5.1 產出 `identifier-samples.yaml`：各類型取自實際產生的識別碼，涵蓋形狀變體
- [x] 5.2 測試：`check-formats` 可對產出樣本執行。不強求全數通過——`FL-A100` 這種
      「前綴 + 字母數字」的形狀不在內建預設樣式涵蓋範圍內，會被判為碎裂；把樣本改成
      剛好符合樣式等於讓程式跟自己對答案，那正是這個工具存在要防的事

## 6. 可直接使用的設定

- [x] 6.1 產出 `config.yaml`：三層宣告、兩個 CSV 實體來源、兩個查表路徑、識別碼樣本路徑，路徑寫絕對路徑（載入器把相對路徑接到工作目錄，不是設定檔所在目錄）
- [x] 6.2 各層宣告反映其性質：`keep_identifiers`、`default_mode`、`top_k`、`description`、`when_to_use`
- [x] 6.3 `heuristics` 與 `cases` 宣告 `depends_on: [library]`
- [x] 6.4 不寫入 `identifier_patterns`，沿用內建預設
- [x] 6.5 測試：以產出設定建構全部索引成功，無路徑錯誤
- [x] 6.6 測試：設定載入後各層的 `keep_identifiers` 與 `default_mode` 與宣告一致

## 7. 使用限制標示

- [x] 7.1 `DISCLAIMER` 寫進 `config.yaml` 與各查表資源的檔頭
- [x] 7.2 保留輸出目錄的 `README.txt` 與終端訊息
- [x] 7.3 測試：產出的設定檔與查表資源檔頭皆含限制說明

## 8. CLI 與回報

- [x] 8.1 `--bundles` 語意改為每層的 bundle 數，更新說明文字
- [x] 8.2 產生結果改為分層回報：各層的 bundle 數與 concept 數，及各產物路徑
- [x] 8.3 測試：相同種子執行兩次，輸出檔案內容完全相同

## 9. 文件與收尾

- [x] 9.1 README 的合成語料段落更新為分層流程
- [x] 9.2 `docs/indexing.md` 中引用 `gen-synthetic` 之處同步更新
- [x] 9.3 更新 `config.local.yaml` 指向新產出的分層資料集
- [x] 9.4 實際產生一份資料集並跑完索引與一次分層查詢，確認端到端可行
