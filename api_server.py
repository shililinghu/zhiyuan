from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError
import json
import os


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
        return {
            "ok": False,
            "error": "后端未配置真实数据 API。请设置 ADMISSION_API_URL；如需要鉴权，同时设置 ADMISSION_API_KEY。",
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
            configured = bool(os.environ.get("ADMISSION_API_URL", "").strip())
            return self.send_json(200, {"ok": True, "admissionApiConfigured": configured})
        return super().do_GET()

    def do_POST(self):
        if self.path == "/api/admissions/search":
            try:
                payload = self.read_json()
            except json.JSONDecodeError:
                return self.send_json(400, {"ok": False, "error": "请求体不是合法 JSON。", "candidates": []})
            response, status = provider_request(payload)
            return self.send_json(status, response)
        return self.send_json(404, {"ok": False, "error": "API endpoint not found"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "4173"))
    host = os.environ.get("HOST", "0.0.0.0")
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"Serving {ROOT} and API on http://{host}:{port}", flush=True)
    server.serve_forever()
