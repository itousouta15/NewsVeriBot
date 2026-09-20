# 資料管理

`raw/`、`interim/`、`processed/` 的實際資料預設不進 Git，只保留資料字典、產生腳本與不可逆雜湊。

## 原則

- 優先保存 URL、擷取時間、內容雜湊與必要短片段，不重新散布完整新聞正文。
- 每筆資料記錄來源、授權或使用依據。
- train/dev/test 依文章、事件與時間切分，避免同事件洩漏。
- 使用者輸入不得混入訓練集，除非另行取得明確同意並完成去識別化。
- API key、Discord token 和任何個資不得放入資料檔。

## 建議格式

主張資料使用 JSON Lines：

```json
{"id":"news_001_s003","article_id":"news_001","text":"2026年起新法上路。","label":1,"rationale":"具體時間與政策宣稱","source_url":"https://example.com/article"}
```

重排資料以 query group 保存，禁止將同一 query 的 candidates 拆到不同資料集合。
