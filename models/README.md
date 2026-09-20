# 模型產物

模型權重與 joblib artifact 不進 Git。使用 `newsveribot-claims train` 在本機產生，正式發布時上傳至具版本與雜湊驗證的模型儲存空間。

Joblib 載入時可能執行序列化內容，只能使用自己訓練或已驗證來源的 artifact。
