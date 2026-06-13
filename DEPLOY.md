# 高考志愿辅助工作台部署说明

这是一个前后端一体的云端部署版本：

- 前端：`public-demo/index.html`
- 后端：`api_server.py`
- 数据入口：`POST /api/admissions/search`
- 健康检查：`GET /api/health`

## 推荐部署方案：Render

1. 把当前项目推到 GitHub 仓库。
2. 在 Render 新建 `Blueprint` 或 `Web Service`。
3. 选择这个仓库。
4. 如果用 Blueprint，Render 会读取 `render.yaml`。
5. 配置环境变量：
   - `ADMISSION_API_URL`：真实招生数据 API 地址
   - `ADMISSION_API_KEY`：真实 API 的 key/token，没有鉴权可不填
6. 部署完成后，Render 会给一个公网 URL。

## 后端调用真实 API 的约定

前端会把考生信息发送给本服务：

```http
POST /api/admissions/search
Content-Type: application/json
```

本服务再把请求转发给 `ADMISSION_API_URL`。

真实数据 API 返回格式支持以下任意一种：

```json
[
  {
    "school": "学校",
    "group": "专业组",
    "major": "专业",
    "city": "城市",
    "minScore": 580,
    "minRank": 32000,
    "plan": 50,
    "type": "公办"
  }
]
```

或：

```json
{
  "candidates": []
}
```

也兼容 `data` / `records` 字段。

## 本地运行

```bash
python api_server.py
```

打开：

```text
http://127.0.0.1:4173
```

本地测试真实 API：

```powershell
$env:ADMISSION_API_URL="https://your-api.example.com/search"
$env:ADMISSION_API_KEY="your-token"
python api_server.py
```

## 重要边界

系统不使用案例数据兜底。真实 API 没有配置或调用失败时，会明确报错，不会生成伪数据。
