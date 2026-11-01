"""Local UI: python -m app.chemcritic.server (loopback only)."""

import argparse
import getpass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
from urllib.parse import urlsplit

from .rules import ValidationError, review
from .sources import load_sources
from .storage import ReviewStore


ROOT = Path(__file__).resolve().parents[2]
STATIC = Path(__file__).parent / "static"
MAX_BODY = 2 * 1024 * 1024


def evaluate_payload(payload):
    if not isinstance(payload, dict):
        raise ValidationError("request", "expected JSON object")
    source_text = payload.get("sciencepal_text", "")
    if not isinstance(source_text, str):
        raise ValidationError("sciencepal_text", "expected the original JSON text")
    from . import schema_v2
    experiment = schema_v2.normalize(payload.get("experiment"))
    sources, retrieval = load_sources(source_text, experiment)
    result = review(experiment, sources)
    result["retrieval"].update(retrieval)
    return experiment, source_text, result


def create_server(port=8765, db_path=None, agent=None):
    store = ReviewStore(db_path or ROOT / "outputs" / "chemcritic.sqlite3")

    class Handler(BaseHTTPRequestHandler):
        def respond(self, status, body, content_type="application/json; charset=utf-8"):
            if isinstance(body, (dict, list)):
                body = json.dumps(body, ensure_ascii=False, allow_nan=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers()
            self.wfile.write(body)

        def local_request(self):
            port = self.server.server_port
            hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
            host = self.headers.get("Host", "")
            origin = self.headers.get("Origin")
            if host not in hosts or (origin is not None and origin != f"http://{host}"):
                # Drain a bounded submitted body before closing. Otherwise Windows
                # may reset the TCP connection and hide the intended 403 response.
                if self.command == "POST":
                    try:
                        size = int(self.headers.get("Content-Length", "0"))
                        if 0 < size <= MAX_BODY:
                            self.connection.settimeout(3)
                            self.rfile.read(size)
                    except (ValueError, OSError):
                        pass
                self.respond(403, {"error": "仅允许本地页面访问此服务。"})
                return False
            return True

        def do_GET(self):
            if not self.local_request():
                return
            path = urlsplit(self.path).path
            files = {"/": ("index.html", "text/html; charset=utf-8"),
                     "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                     "/style.css": ("style.css", "text/css; charset=utf-8")}
            if path in files:
                name, mime = files[path]
                return self.respond(200, (STATIC / name).read_bytes(), mime)
            if path == "/api/bootstrap":
                from . import schema_v2
                case = json.loads((ROOT / "cases/C2_simulated_42_goal60.json").read_text(encoding="utf-8"))
                return self.respond(200, {
                    "experiment": schema_v2.normalize(case),
                    "sciencepal_text": (ROOT / "cases/sciencepal/SM004_raw.json").read_text(encoding="utf-8"),
                })
            if path == "/api/history":
                return self.respond(200, store.list())
            if path == "/api/agent/config":
                return self.respond(200, agent.config() if agent else {"enabled": False})
            if path.startswith("/api/agent/reviews/"):
                job_id = path.rsplit("/", 1)[-1]
                item = (agent.check(job_id) if urlsplit(self.path).query == "check=1" else agent.snapshot(job_id)) if agent else None
                return self.respond(200, item) if item else self.respond(404, {"error": "Agent任务不存在。"})
            if path == "/api/library":
                return self.respond(200, json.loads((ROOT / "cases/library/suzuki_handoff_v1.json").read_text(encoding="utf-8")))
            if path.startswith("/api/history/"):
                snapshot = store.get(path.removeprefix("/api/history/"))
                if not snapshot:
                    return self.respond(404, {"error": "记录不存在。"})
                # Older snapshots stored v0.1 records; the page only handles v0.2.
                from . import schema_v2
                try:
                    snapshot["experiment"] = schema_v2.normalize(snapshot.get("experiment"))
                except ValueError as exc:
                    return self.respond(422, {"error": "历史记录格式无法升级为当前格式", "message": str(exc)})
                return self.respond(200, snapshot)
            self.respond(404, {"error": "页面不存在。"})

        def do_POST(self):
            if not self.local_request():
                return
            if self.path not in {"/api/review", "/api/reviews", "/api/agent/reviews", "/api/agent/recover"}:
                return self.respond(404, {"error": "接口不存在。"})
            if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
                return self.respond(415, {"error": "请发送JSON格式请求。"})
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= MAX_BODY:
                    return self.respond(413, {"error": "请求不能为空且不能超过2MB。"})
                payload = json.loads(self.rfile.read(size).decode("utf-8-sig"))
                if self.path == "/api/agent/recover":
                    if agent is None:
                        return self.respond(503, {"error": "请使用 --sciencepal 启用连接。"})
                    if not isinstance(payload, dict):
                        raise ValueError("请求必须为JSON对象。")
                    return self.respond(200, agent.recover(payload))
                if self.path == "/api/agent/reviews":
                    if agent is None:
                        return self.respond(503, {"error": "请使用 --sciencepal 启动服务以连接团队Agent。"})
                    if not isinstance(payload, dict):
                        raise ValueError("请求必须为JSON对象。")
                    if "request_text" in payload:
                        text = payload["request_text"]
                        if not isinstance(text, str) or not text.strip() or len(text) > 20000:
                            raise ValueError("请填写实验描述（最多20000字）。")
                        return self.respond(202, agent.start(payload.get("request_id", ""), request_text=text.strip()))
                    # Agent form submission is independent of optional local source files.
                    from . import schema_v2
                    experiment = schema_v2.normalize(payload.get("experiment"))
                    result = review(experiment, [])
                    return self.respond(202, agent.start(payload.get("request_id", ""), experiment, result))
                experiment, source_text, result = evaluate_payload(payload)
                if self.path == "/api/reviews":
                    # Always recompute before saving; never trust client-supplied verdicts.
                    return self.respond(201, store.save(experiment, source_text, result))
                self.respond(200, {"result": result})
            except (ValueError, TypeError, KeyError, OverflowError) as exc:
                message = {"error": "输入校验失败", "message": str(exc)}
                if isinstance(exc, ValidationError):
                    message["field"] = exc.field
                self.respond(400, message)

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="ChemCritic本地交互页面")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--sciencepal", action="store_true", help="启用团队Agent，启动时隐藏输入密钥")
    parser.add_argument('--engine-profile',choices=['team32','legacy8'],default='team32',help='固定新版32条记录工程修复版；legacy8仅用于旧版本回归')
    parser.add_argument('--agent-mode',choices=['research','remote_verified'],default='research',help='research日常科研；remote_verified保留原固定程序远端验收')
    args = parser.parse_args()
    if args.sciencepal and sys.version_info >= (3, 14):
        # The pinned engine is hash-locked; 3.14's argparse validates help strings
        # and rejects its literal '%'.  Say so at startup rather than at submit time.
        print("注意：当前 Python " + sys.version.split()[0] +
              "，固定判定引擎需要 3.11（3.14 的 argparse 会拒绝引擎帮助字符串中的 %）。"
              "结构化提交会在提交时被拒绝；请改用 Python 3.11 启动。", flush=True)
    try:
        agent = None
        if args.sciencepal:
            from .shared_agent import SharedAgent, AGENT_ID
            agent = SharedAgent(getpass.getpass("SciencePal API key (hidden; not saved): "),engine_profile=args.engine_profile,execution_mode=args.agent_mode)
            print('运行模式：'+args.agent_mode+'；本地辅助结果与远端实际执行核验分别标记。')
            print(f"团队Agent: ChemCrtic · {AGENT_ID}；点击页面按钮才创建任务。")
        server = create_server(args.port, agent=agent)
    except (ImportError, ValueError) as exc:
        parser.exit(1, f"Agent配置失败（{type(exc).__name__}），请使用已安装httpx的pytorch环境。\n")
    except OSError as exc:
        parser.exit(1, f"无法启动本地服务：{exc}\n可换端口：python -m app.chemcritic.server --port 8766\n")
    print(f"ChemCritic 已启动：http://127.0.0.1:{server.server_port}\n保持终端开启；按 Ctrl+C 停止。", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
