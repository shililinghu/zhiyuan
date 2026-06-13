from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError
import html
import json
import os
import re


ROOT = Path(__file__).resolve().parent / "public-demo"


def number(value, default=0):
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def pick(source, *keys, default=""):
    for key in keys:
        if key in source and source[key] not in (None, ""):
            return source[key]
    return default


def normalize_candidate(item):
    return {
        "school": pick(item, "school", "schoolName", "college", "collegeName", "院校", "学校"),
        "group": pick(item, "group", "groupName", "majorGroup", "专业组"),
        "major": pick(item, "major", "majorName", "subject", "专业"),
        "city": pick(item, "city", "cityName", "城市"),
        "minScore": number(pick(item, "minScore", "lowestScore", "score", "最低分")),
        "minRank": number(pick(item, "minRank", "lowestRank", "rank", "最低位次")),
        "plan": number(pick(item, "plan", "planCount", "招生计划", "计划")),
        "type": pick(item, "type", "schoolType", "性质"),
        "userSchoolRating": "",
        "userMajorRating": "",
        "userCityRating": "",
        "userNote": "",
    }


def provider_request(payload):
    api_url = os.environ.get("ADMISSION_API_URL", "").strip()
    api_key = os.environ.get("ADMISSION_API_KEY", "").strip()
    if not api_url:
        bocha_configured = bool(os.environ.get("BOCHA_API_KEY", "").strip())
        deepseek_configured = bool(os.environ.get("DEEPSEEK_API_KEY", "").strip())
        if bocha_configured and deepseek_configured:
            return built_in_admission_request(payload)
        return {
            "ok": False,
            "error": "后端未配置招生数据源。请设置 ADMISSION_API_URL，或配置 BOCHA_API_KEY 与 DEEPSEEK_API_KEY 以启用联网抽取。",
            "candidates": [],
        }, 503

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urlrequest.Request(api_url, data=body, headers=headers, method="POST")

    try:
        with urlrequest.urlopen(req, timeout=20) as response:
            raw = response.read().decode("utf-8")
            data = json.loads(raw) if raw else {}
    except HTTPError as exc:
        return {"ok": False, "error": f"真实数据 API 返回 HTTP {exc.code}", "candidates": []}, 502
    except URLError as exc:
        return {"ok": False, "error": f"真实数据 API 无法访问：{exc.reason}", "candidates": []}, 502
    except json.JSONDecodeError:
        return {"ok": False, "error": "真实数据 API 返回的不是合法 JSON。", "candidates": []}, 502

    rows = data.get("candidates") or data.get("data") or data.get("records") or data
    if not isinstance(rows, list):
        return {"ok": False, "error": "真实数据 API 返回格式不符合预期，需要数组或包含 candidates/data/records 的对象。", "candidates": []}, 502

    candidates = [normalize_candidate(row) for row in rows if isinstance(row, dict)]
    candidates = [row for row in candidates if row["school"] and row["minScore"] and row["minRank"]]
    return {"ok": True, "source": api_url, "count": len(candidates), "candidates": candidates}, 200


def normalize_summary_item(item, fallback_name=""):
    if isinstance(item, str):
        return {"name": fallback_name, "summary": item, "sources": []}
    if not isinstance(item, dict):
        return {"name": fallback_name, "summary": "", "sources": []}
    sources = item.get("sources") or item.get("links") or item.get("citations") or []
    if isinstance(sources, str):
        sources = [sources]
    if not isinstance(sources, list):
        sources = []
    return {
        "name": pick(item, "name", "title", "school", "major", "city", default=fallback_name),
        "summary": pick(item, "summary", "content", "text", "description", default=""),
        "sources": sources,
    }


def normalize_summary_list(value, fallback_names):
    if isinstance(value, dict):
        return [normalize_summary_item(v, k) for k, v in value.items()]
    if isinstance(value, list):
        return [normalize_summary_item(item, fallback_names[i] if i < len(fallback_names) else "") for i, item in enumerate(value)]
    return []


def empty_summaries():
    return {"schools": [], "majors": [], "cities": []}


def post_json(api_url, payload, headers=None, timeout=45):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req_headers = {"Content-Type": "application/json"}
    if headers:
        req_headers.update(headers)
    req = urlrequest.Request(api_url, data=body, headers=req_headers, method="POST")
    with urlrequest.urlopen(req, timeout=timeout) as response:
        raw = response.read().decode("utf-8")
        return json.loads(raw) if raw else {}


def bocha_search(query, count=5, freshness="oneYear"):
    api_key = os.environ.get("BOCHA_API_KEY", "").strip()
    api_url = os.environ.get("BOCHA_API_URL", "https://api.bochaai.com/v1/web-search").strip()
    if not api_key:
        raise RuntimeError("BOCHA_API_KEY is not configured.")

    search_payload = {"query": query, "summary": True, "count": count}
    if freshness:
        search_payload["freshness"] = freshness
    data = post_json(
        api_url,
        search_payload,
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=30,
    )
    pages = ((data.get("webPages") or {}).get("value") or [])
    results = []
    for page in pages[:count]:
        if not isinstance(page, dict):
            continue
        results.append({
            "title": pick(page, "name", "title"),
            "url": pick(page, "url"),
            "siteName": pick(page, "siteName"),
            "snippet": pick(page, "summary", "snippet", "description"),
            "datePublished": pick(page, "datePublished"),
        })
    return results


def fetch_page_text(url, limit=3000):
    if not url or not str(url).startswith(("http://", "https://")):
        return ""
    req = urlrequest.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; ZhiyuanResearchBot/1.0)",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
        method="GET",
    )
    try:
        with urlrequest.urlopen(req, timeout=12) as response:
            content_type = response.headers.get("Content-Type", "")
            if "text/html" not in content_type and "text/plain" not in content_type:
                return ""
            raw = response.read(600000)
    except (HTTPError, URLError, TimeoutError):
        return ""

    text = raw.decode("utf-8", errors="replace")
    text = re.sub(r"(?is)<script.*?</script>|<style.*?</style>|<noscript.*?</noscript>", " ", text)
    text = re.sub(r"(?is)<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def parse_json_object(text):
    if not isinstance(text, str):
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        return {}
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return {}


def summarize_with_deepseek(payload, research_context):
    api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    api_url = os.environ.get("DEEPSEEK_API_URL", "https://api.deepseek.com/chat/completions").strip()
    model = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash").strip()
    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY is not configured.")

    prompt = {
        "task": "把联网搜索结果整理成高考志愿辅助调研摘要。只做信息汇总，不替用户打分，不替用户做主观偏好判断。",
        "output_schema": {
            "summaries": {
                "schools": [{"name": "院校名", "summary": "200字以内中文摘要", "sources": [{"title": "来源标题", "url": "https://..."}]}],
                "majors": [{"name": "专业名", "summary": "200字以内中文摘要", "sources": [{"title": "来源标题", "url": "https://..."}]}],
                "cities": [{"name": "城市名", "summary": "200字以内中文摘要", "sources": [{"title": "来源标题", "url": "https://..."}]}],
            }
        },
        "student": payload.get("student", {}),
        "profile": payload.get("profile", {}),
        "items": payload.get("items", {}),
        "search_results": research_context,
    }
    data = post_json(
        api_url,
        {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": "你是严谨的高考志愿信息整理助手。只能依据给定搜索结果总结，必须返回合法 JSON，不要输出 Markdown。",
                },
                {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
            ],
            "response_format": {"type": "json_object"},
            "stream": False,
        },
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=60,
    )
    choices = data.get("choices") or []
    content = ""
    if choices and isinstance(choices[0], dict):
        content = ((choices[0].get("message") or {}).get("content") or "")
    parsed = parse_json_object(content)
    return parsed.get("summaries", parsed)


def extract_candidates_with_deepseek(payload, search_results):
    api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    api_url = os.environ.get("DEEPSEEK_API_URL", "https://api.deepseek.com/chat/completions").strip()
    model = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash").strip()
    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY is not configured.")

    prompt = {
        "task": "依据联网搜索结果抽取高考志愿候选数据。只抽取资料中出现或可以直接对应的院校/专业/城市/最低分/最低位次/计划数/性质，不要编造。用户评价字段留空。",
        "rules": [
            "优先使用目标省份、目标年份附近的普通本科批/本科批数据。",
            "如果无法确定专业组或专业，可以使用资料中更明确的招生类别名称。",
            "minScore 和 minRank 必须是数字；缺少这两个字段的行不要输出。",
            "返回 6 到 20 条候选，覆盖冲稳保的不同分数/位次区间。",
            "不要对候选打分，不要输出综合分。",
        ],
        "output_schema": {
            "candidates": [
                {
                    "school": "院校",
                    "group": "专业组或类别",
                    "major": "专业",
                    "city": "城市",
                    "minScore": 580,
                    "minRank": 32000,
                    "plan": 50,
                    "type": "公办/民办/中外合作等",
                }
            ]
        },
        "student": payload,
        "search_results": search_results,
    }
    data = post_json(
        api_url,
        {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": "你是严谨的高考招生数据抽取助手。只能依据给定搜索结果抽取结构化候选数据，必须返回合法 JSON，不要输出 Markdown。",
                },
                {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
            ],
            "response_format": {"type": "json_object"},
            "stream": False,
        },
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=60,
    )
    choices = data.get("choices") or []
    content = ""
    if choices and isinstance(choices[0], dict):
        content = ((choices[0].get("message") or {}).get("content") or "")
    parsed = parse_json_object(content)
    rows = parsed.get("candidates") or parsed.get("data") or parsed.get("records") or []
    if not isinstance(rows, list):
        rows = []
    candidates = [normalize_candidate(row) for row in rows if isinstance(row, dict)]
    return [row for row in candidates if row["school"] and row["minScore"] and row["minRank"]]


def built_in_admission_request(payload):
    province = pick(payload, "province", default="")
    year = pick(payload, "year", default="")
    subjects = pick(payload, "subjects", default="")
    batch = pick(payload, "batch", default="")
    score = pick(payload, "score", default="")
    rank = pick(payload, "rank", default="")
    preferred_cities = ((payload.get("profile") or {}).get("preferredCities") or "").strip()
    preferred_majors = ((payload.get("profile") or {}).get("preferredMajors") or "").strip()
    reference_year = year
    try:
        if str(year).isdigit():
            reference_year = str(int(year) - 1)
    except (TypeError, ValueError):
        reference_year = year

    base_query = " ".join(str(part) for part in [
        province,
        reference_year,
        batch,
        subjects,
        score,
        rank,
        preferred_cities,
        preferred_majors,
        "高考 录取分数线 最低位次 招生计划 院校专业组",
    ] if part)
    if not base_query:
        base_query = "高考 本科批 录取分数线 最低位次 招生计划 院校专业组"

    queries = [
        base_query,
        f"{province} {reference_year} 高考 本科批 投档线 最低位次 院校专业组",
        f"{province} {reference_year} {rank} 位次 可报大学 {score} 分 录取分数线",
        f"{province} {reference_year} {preferred_majors} {preferred_cities} 高考 录取分数线 位次",
    ]
    search_results = []
    for query in queries:
        query = " ".join(query.split())
        if query:
            results = bocha_search(query, 10, freshness=None)
            for result in results[:2]:
                result["pageText"] = fetch_page_text(result.get("url"), 3000)
            search_results.append({"query": query, "results": results})

    candidates = extract_candidates_with_deepseek(payload, search_results)
    if not candidates:
        return {
            "ok": False,
            "error": "联网搜索已完成，但没有抽取到同时包含最低分和最低位次的候选数据。请补充省份、年份、科类、分数/位次，或导入官方 CSV。",
            "source": "bocha+deepseek",
            "candidates": [],
        }, 502
    return {"ok": True, "source": "bocha+deepseek", "count": len(candidates), "candidates": candidates}, 200


def built_in_research_request(payload):
    items = payload.get("items") or {}
    schools = [name for name in items.get("schools", []) if name][:6]
    majors = [name for name in items.get("majors", []) if name][:6]
    cities = [name for name in items.get("cities", []) if name][:6]

    research_context = {"schools": {}, "majors": {}, "cities": {}}
    for school in schools:
        research_context["schools"][school] = bocha_search(f"{school} 高考 招生章程 优势学科 校区 官方", 5)
    for major in majors:
        research_context["majors"][major] = bocha_search(f"{major} 专业 就业方向 课程 高考 报考", 5)
    for city in cities:
        research_context["cities"][city] = bocha_search(f"{city} 城市 大学 生活成本 交通 气候 就业", 5)

    summaries = summarize_with_deepseek(payload, research_context)
    result = {
        "schools": normalize_summary_list(summaries.get("schools") or summaries.get("schoolSummaries") or [], schools),
        "majors": normalize_summary_list(summaries.get("majors") or summaries.get("majorSummaries") or [], majors),
        "cities": normalize_summary_list(summaries.get("cities") or summaries.get("citySummaries") or [], cities),
    }
    return {"ok": True, "source": "bocha+deepseek", "summaries": result}, 200


def research_request(payload):
    bocha_configured = bool(os.environ.get("BOCHA_API_KEY", "").strip())
    deepseek_configured = bool(os.environ.get("DEEPSEEK_API_KEY", "").strip())
    if bocha_configured or deepseek_configured:
        if not (bocha_configured and deepseek_configured):
            missing = []
            if not bocha_configured:
                missing.append("BOCHA_API_KEY")
            if not deepseek_configured:
                missing.append("DEEPSEEK_API_KEY")
            return {
                "ok": False,
                "error": f"Research API is partly configured. Missing: {', '.join(missing)}.",
                "summaries": empty_summaries(),
            }, 503
        try:
            return built_in_research_request(payload)
        except HTTPError as exc:
            return {"ok": False, "error": f"Research provider returned HTTP {exc.code}", "summaries": empty_summaries()}, 502
        except URLError as exc:
            return {"ok": False, "error": f"Research provider is unavailable: {exc.reason}", "summaries": empty_summaries()}, 502
        except json.JSONDecodeError:
            return {"ok": False, "error": "Research provider did not return valid JSON.", "summaries": empty_summaries()}, 502
        except RuntimeError as exc:
            return {"ok": False, "error": str(exc), "summaries": empty_summaries()}, 503

    api_url = os.environ.get("RESEARCH_API_URL", "").strip()
    api_key = os.environ.get("RESEARCH_API_KEY", "").strip()
    if not api_url:
        return {
            "ok": False,
            "error": "Research API is not configured. Set BOCHA_API_KEY and DEEPSEEK_API_KEY, or set RESEARCH_API_URL.",
            "summaries": empty_summaries(),
        }, 503

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urlrequest.Request(api_url, data=body, headers=headers, method="POST")

    try:
        with urlrequest.urlopen(req, timeout=45) as response:
            raw = response.read().decode("utf-8")
            data = json.loads(raw) if raw else {}
    except HTTPError as exc:
        return {"ok": False, "error": f"Research API returned HTTP {exc.code}", "summaries": empty_summaries()}, 502
    except URLError as exc:
        return {"ok": False, "error": f"Research API is unavailable: {exc.reason}", "summaries": empty_summaries()}, 502
    except json.JSONDecodeError:
        return {"ok": False, "error": "Research API did not return valid JSON.", "summaries": empty_summaries()}, 502

    summaries = data.get("summaries", data)
    items = payload.get("items", {})
    result = {
        "schools": normalize_summary_list(summaries.get("schools") or summaries.get("schoolSummaries") or [], items.get("schools", [])),
        "majors": normalize_summary_list(summaries.get("majors") or summaries.get("majorSummaries") or [], items.get("majors", [])),
        "cities": normalize_summary_list(summaries.get("cities") or summaries.get("citySummaries") or [], items.get("cities", [])),
    }
    return {"ok": True, "source": api_url, "summaries": result}, 200


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json(self):
        length = int(self.headers.get("Content-Length", "0") or 0)
        raw = self.rfile.read(length).decode("utf-8") if length else "{}"
        return json.loads(raw or "{}")

    def do_GET(self):
        if self.path == "/api/health":
            admission_configured = bool(os.environ.get("ADMISSION_API_URL", "").strip())
            research_configured = bool(os.environ.get("RESEARCH_API_URL", "").strip())
            bocha_configured = bool(os.environ.get("BOCHA_API_KEY", "").strip())
            deepseek_configured = bool(os.environ.get("DEEPSEEK_API_KEY", "").strip())
            return self.send_json(200, {
                "ok": True,
                "admissionApiConfigured": admission_configured or (bocha_configured and deepseek_configured),
                "externalAdmissionApiConfigured": admission_configured,
                "researchApiConfigured": research_configured or (bocha_configured and deepseek_configured),
                "bochaConfigured": bocha_configured,
                "deepseekConfigured": deepseek_configured,
            })
        return super().do_GET()

    def do_POST(self):
        if self.path == "/api/admissions/search":
            try:
                payload = self.read_json()
            except json.JSONDecodeError:
                return self.send_json(400, {"ok": False, "error": "请求体不是合法 JSON。", "candidates": []})
            response, status = provider_request(payload)
            return self.send_json(status, response)
        if self.path == "/api/research/summary":
            try:
                payload = self.read_json()
            except json.JSONDecodeError:
                return self.send_json(400, {"ok": False, "error": "Request body is not valid JSON.", "summaries": {"schools": [], "majors": [], "cities": []}})
            response, status = research_request(payload)
            return self.send_json(status, response)
        return self.send_json(404, {"ok": False, "error": "API endpoint not found"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "4173"))
    host = os.environ.get("HOST", "0.0.0.0")
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"Serving {ROOT} and API on http://{host}:{port}", flush=True)
    server.serve_forever()
