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
