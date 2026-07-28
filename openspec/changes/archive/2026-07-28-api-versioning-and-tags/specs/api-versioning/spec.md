## ADDED Requirements

### Requirement: 功能端點置於版本前綴之下

所有描述 API 契約的端點 SHALL 掛載於版本前綴 `/v1` 之下。未帶版本前綴的舊路徑 MUST NOT 繼續提供服務。

#### Scenario: 版本化路徑可用

- **WHEN** 呼叫 `/v1/search` 並提供合法查詢
- **THEN** 回應 HTTP 200

#### Scenario: 未版本化的舊路徑不再提供服務

- **WHEN** 呼叫未帶版本前綴的 `/search`
- **THEN** 回應 HTTP 404

#### Scenario: 所有功能端點皆在前綴之下

- **WHEN** 檢視 API 結構描述
- **THEN** 除服務層端點外，所有端點路徑皆以 `/v1` 開頭

### Requirement: 服務層端點不版本化

描述服務自身狀態的端點 SHALL 維持於未版本化的根路徑，使監控與部署不受 API 改版影響。此類端點為健康檢查與版本查詢。

#### Scenario: 健康檢查在根路徑

- **WHEN** 呼叫 `/healthz`
- **THEN** 回應 HTTP 200 並含索引載入狀態

#### Scenario: 版本查詢在根路徑

- **WHEN** 呼叫 `/version`
- **THEN** 回應 HTTP 200

#### Scenario: 語料統計屬於 API 契約，仍須版本化

- **WHEN** 呼叫 `/v1/stats`
- **THEN** 回應 HTTP 200；呼叫未版本化的 `/stats` 則回應 HTTP 404

### Requirement: 版本資訊查詢

系統 SHALL 提供版本查詢端點，回報套件版本、API 版本、本程式支援的索引格式版本，以及目前載入索引的格式版本與簽章。索引未載入時，索引相關欄位 MUST 為空值而非造成錯誤。

#### Scenario: 索引已載入

- **WHEN** 索引正常載入後呼叫版本查詢
- **THEN** 回應含套件版本、API 版本、支援的索引格式版本，以及已載入索引的格式版本與簽章

#### Scenario: 索引未載入仍可查詢

- **WHEN** 索引載入失敗後呼叫版本查詢
- **THEN** 回應 HTTP 200，索引相關欄位為空值

#### Scenario: 支援版本與載入版本可分別辨識

- **WHEN** 檢視版本查詢的回應
- **THEN** 「本程式支援的索引格式版本」與「目前載入索引的格式版本」為兩個獨立欄位

### Requirement: API 結構描述標示版本

系統的 API 結構描述 SHALL 以套件版本作為其版本欄位。

#### Scenario: 結構描述含版本

- **WHEN** 取得 API 結構描述
- **THEN** 其版本欄位等於套件版本

### Requirement: 端點依用途分類

所有端點 SHALL 依用途歸入下列分類之一：檢索、內容、關聯、遙測、服務。每個分類 MUST 附帶說明，並於互動式文件頁顯示。

#### Scenario: 分類涵蓋所有端點

- **WHEN** 檢視 API 結構描述
- **THEN** 每個端點恰好屬於上述分類之一

#### Scenario: 檢索與內容分屬不同類

- **WHEN** 檢視查詢端點與取全文端點的分類
- **THEN** 兩者屬於不同分類

#### Scenario: 遙測獨立成類

- **WHEN** 檢視點選回饋與統計報告端點的分類
- **THEN** 兩者同屬遙測分類，且不與檢索或內容混同

#### Scenario: 分類附帶說明

- **WHEN** 檢視 API 結構描述中的分類定義
- **THEN** 每個分類含非空的說明文字
