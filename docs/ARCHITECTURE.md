# 系統架構

## 請求流程

```text
Discord / LINE / HTTP client
             |
             v
       FastAPI /v1/analyze
             |
             v
  輸入驗證與安全 URL 擷取
             |
             v
  切句 + 主張偵測 baseline
             |
             v
 Google Fact Check Tools API
             |
             v
  字元 n-gram 重排 baseline
             |
             v
 結構化結果、來源連結與警告
```

## 邊界

- Bot adapter 不包含分析邏輯，只處理平台互動和結果排版。
- `AnalysisService` 負責協調擷取、主張偵測、查核檢索與重排。
- `FactCheckRetriever` 是可替換介面，後續可加入本地 ClaimReview 索引。
- 模型 A 只需實作與 baseline 相同的 `detect` 介面即可替換。
- 模型 B 只需實作與 baseline 相同的 `rank` 介面即可替換。
- 未設定 `NEWSVERIBOT_CLAIM_MODEL_PATH` 時使用透明規則 baseline；設定後載入本機訓練的 TF-IDF artifact。
- Joblib artifact 只能來自可信來源，因為反序列化不具備沙箱隔離。

## 標註工作台

- `newsveribot-annotate` 是獨立的本機 FastAPI 應用程式，不掛在正式分析 API。
- claim JSONL 視為唯讀；每次判斷以 append-only event 保存，修訂不刪除歷史。
- 顯示順序由 seed 與 claim ID 決定，避免所有標註者都受原文章順序影響。
- `agreement` 可比較兩位標註者，或同一標註者的 `initial`／`retest` 輪次。
- `finalize` 要求指定輪次全部完成，才會產生可供切分與訓練的標註 JSONL。

## RSS 資料收集

- `newsveribot-feeds` 只讀取 manifest 中明確允許的 RSS/Atom endpoint。
- feed URL 與每次 redirect 都經過公開 IP 驗證，並限制協定、內容類型、大小與 redirect 次數。
- 只保留 feed 提供的標題與摘要，不抓文章頁全文。
- 文章網址會移除常見追蹤參數；內容以 SHA-256 去重並記錄 provenance。
- 同事件跨媒體報導仍需人工設定相同 `group_id`，才可防止後續資料切分洩漏。

## 安全限制

- URL 僅接受 HTTP(S)，禁止帳密資訊與非標準 URL。
- 每次重新導向前都重新驗證目的主機解析結果。
- 私有、loopback、link-local、multicast、reserved IP 一律拒絕。
- 限制下載大小、重新導向次數、文章長度與逾時。
- URL 防護降低 SSRF 風險，但部署環境仍應使用 egress firewall 阻擋內網與 metadata endpoints。

## 非目標

- 系統不輸出最終真假判決。
- 網站來源線索不能取代逐篇內容查核。
- 翻譯痕跡不能視為內容錯誤的證據。
