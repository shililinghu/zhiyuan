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
   - `RESEARCH_API_URL`：网络调研/搜索汇总 API 地址
   - `RESEARCH_API_KEY`：调研 API 的 key/token，没有鉴权可不填
   - `BOCHA_API_KEY`：博查 Web Search API key
   - `BOCHA_API_URL`：默认 `https://api.bochaai.com/v1/web-search`
   - `DEEPSEEK_API_KEY`：DeepSeek API key
   - `DEEPSEEK_API_URL`：默认 `https://api.deepseek.com/chat/completions`
   - `DEEPSEEK_MODEL`：默认 `deepseek-v4-flash`
6. 部署完成后，Render 会给一个公网 URL。

## 后端调用真实 API 的约定

前端会把考生信息发送给本服务：

```http
POST /api/admissions/search
Content-Type: application/json
```

如果配置了 `ADMISSION_API_URL`，本服务会把请求转发给该招生数据 API。
如果没有配置 `ADMISSION_API_URL`，但已配置 `BOCHA_API_KEY` 与 `DEEPSEEK_API_KEY`，本服务会使用博查联网搜索，再由 DeepSeek 抽取候选数据。

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

## 网络调研汇总 API

前端会把候选里的院校、专业、城市发给后端：

```http
POST /api/research/summary
Content-Type: application/json
```

后端优先使用内置闭环：博查 Web Search API 负责联网搜索，DeepSeek 负责把搜索结果整理成 JSON 摘要。
如果没有配置 `BOCHA_API_KEY` / `DEEPSEEK_API_KEY`，也兼容转发到自定义的 `RESEARCH_API_URL`。

请求体大致为：

```json
{
  "items": {
    "schools": ["郑州大学"],
    "majors": ["计算机类"],
    "cities": ["郑州"]
  },
  "student": {
    "year": "2026",
    "province": "河南",
    "subjects": "物理+化学+生物",
    "batch": "本科批"
  },
  "profile": {}
}
```

调研 API 推荐返回：

```json
{
  "summaries": {
    "schools": [
      {
        "name": "郑州大学",
        "summary": "院校定位、优势学科、校区、招生章程风险点等摘要。",
        "sources": [
          {"title": "学校官网", "url": "https://example.com"}
        ]
      }
    ],
    "majors": [],
    "cities": []
  }
}
```

也兼容 `schoolSummaries` / `majorSummaries` / `citySummaries` 字段。

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
$env:BOCHA_API_KEY="your-bocha-token"
$env:DEEPSEEK_API_KEY="your-deepseek-token"
python api_server.py
```

## 重要边界

系统不使用案例数据兜底。真实 API 没有配置或调用失败时，会明确报错，不会生成伪数据。
