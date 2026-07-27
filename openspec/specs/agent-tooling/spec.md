# agent-tooling Specification

## Purpose
TBD - created by archiving change agent-access-tools. Update Purpose after archive.
## Requirements
### Requirement: 提供 MCP server

系統 SHALL 提供以標準輸入輸出（stdio）通訊的 MCP server，可由 CLI 指令啟動，供支援 MCP 的 agent 直接連接。

#### Scenario: 啟動 MCP server

- **WHEN** 執行 MCP server 啟動指令
- **THEN** server 以 stdio 通訊並可回應工具列舉請求

#### Scenario: 索引未建立

- **WHEN** 在尚未建立索引的情況下啟動 MCP server
- **THEN** 系統回報明確錯誤並指示先建立索引

### Requirement: MCP 工具集

MCP server SHALL 提供下列工具：檢索、取單一 concept 全文、批次取 concept 全文、展開 concept 關聯、限定範圍字面搜尋、語料統計。每個工具 MUST 宣告其輸入結構描述。

#### Scenario: 列舉工具

- **WHEN** agent 請求工具清單
- **THEN** 清單含檢索、取全文、批次取全文、關聯展開、限定範圍搜尋與語料統計六項

#### Scenario: 工具具備輸入結構描述

- **WHEN** 檢視任一工具定義
- **THEN** 其含描述必填與選填參數的輸入結構描述

#### Scenario: 呼叫檢索工具

- **WHEN** agent 以查詢字串呼叫檢索工具
- **THEN** 回傳結果摘要清單，格式與檢索介面一致

#### Scenario: 呼叫取全文工具

- **WHEN** agent 以 concept id 呼叫取全文工具
- **THEN** 回傳該 concept 的完整內容

#### Scenario: 工具執行失敗

- **WHEN** 工具因參數錯誤或資源不存在而失敗
- **THEN** 回傳標示為錯誤的結果，並含可讀的原因說明，而非中斷連線

### Requirement: 工具說明引導正確用法

工具說明 SHALL 明確傳達下列三點：檢索工具只回摘要清單而不含內容、取得內容須另行呼叫取全文工具、限定範圍搜尋必須先有範圍且範圍應取自檢索結果。

#### Scenario: 檢索工具說明指向取全文

- **WHEN** 檢視檢索工具的說明
- **THEN** 說明指出其只回摘要，並指引呼叫取全文工具取得內容

#### Scenario: 搜尋工具說明要求先縮範圍

- **WHEN** 檢視限定範圍搜尋工具的說明
- **THEN** 說明指出必須提供範圍，且範圍應取自檢索結果

### Requirement: 兩個介面共用載入路徑

HTTP 介面與 MCP server SHALL 共用同一份設定、字典、索引、檢索器與遙測的載入實作，不得各自維護一份。

#### Scenario: 共用載入

- **WHEN** 檢視兩個介面的初始化流程
- **THEN** 兩者呼叫同一個載入進入點

#### Scenario: 兩介面結果一致

- **WHEN** 以相同查詢分別經由 HTTP 與 MCP 檢索
- **THEN** 回傳的 concept id 排序一致

