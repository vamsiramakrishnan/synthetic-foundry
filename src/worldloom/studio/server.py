"""Loopback console with a fixed command boundary and a durable local worker."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from importlib.resources import files
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from .models import InterviewReply, ProjectSpec, RunOptions
from .service import Studio, preset
from .store import StudioConflict
from .worker import recover

MAX_BODY = 4_000_000


class StudioServer(HTTPServer):
    def __init__(self, root: str | Path, *, port: int = 8765,
                 harness_command: str | None = None, timeout: float = 600, launch_workers: bool = True) -> None:
        self.studio = Studio(root)
        self.harness_command = harness_command
        self.timeout = timeout
        self.launch_workers = launch_workers
        self.child: subprocess.Popen[bytes] | None = None
        recover(self.studio)
        super().__init__(("127.0.0.1", port), StudioHandler)

    def pump(self) -> None:
        if not self.launch_workers or (self.child is not None and self.child.poll() is None):
            return
        if self.child is not None:
            self.child.wait()
            self.child = None
            recover(self.studio)
        if any(job["status"] == "running" for job in self.studio.store.jobs()) and not recover(self.studio):
            return
        queued = [job for job in reversed(self.studio.store.jobs()) if job["status"] == "queued"]
        if not queued:
            return
        env = dict(os.environ)
        env.pop("WORLDLOOM_STUDIO_HARNESS", None)
        if self.harness_command:
            env["WORLDLOOM_STUDIO_HARNESS"] = self.harness_command
        self.child = subprocess.Popen(
            [sys.executable, "-m", "worldloom.studio.worker", str(self.studio.root), queued[0]["id"], "--timeout", str(self.timeout)],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env,
        )

    def service_actions(self) -> None:
        self.pump()


class StudioHandler(BaseHTTPRequestHandler):
    server: StudioServer

    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(10)

    def log_message(self, format: str, *args: Any) -> None:
        # Company names, interview text and run data never enter access logs.
        return

    def send(self, status: int, value: Any, *, content_type: str = "application/json") -> None:
        body = value if isinstance(value, bytes) else json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type + "; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        self.end_headers()
        self.wfile.write(body)

    def allowed(self, *, mutation: bool = False) -> bool:
        port = self.server.server_port
        hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        host = self.headers.get("Host", "")
        origin = self.headers.get("Origin")
        valid = host in hosts and (origin is None or origin == "http://" + host)
        if mutation:
            valid = valid and self.headers.get("X-Worldloom-Studio") == "1" and self.headers.get("Content-Type", "").split(";")[0] == "application/json"
        if not valid:
            # Closing with a normal POST body still unread can reset the TCP
            # connection on Windows before the client receives its 403. Drain
            # only bounded, explicitly sized bodies; never parse or dispatch them.
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = 0
            if 0 < length <= MAX_BODY and not self.headers.get("Transfer-Encoding"):
                try:
                    self.rfile.read(length)
                except (TimeoutError, OSError):
                    self.close_connection = True
            self.send(403, {"error": "This console accepts local, same-origin requests only"})
        return bool(valid)

    def body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length < 1 or length > MAX_BODY:
            raise ValueError("request body is empty or exceeds 4 MB")
        def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
            value: dict[str, Any] = {}
            for key, child in items:
                if key in value:
                    raise ValueError(f"duplicate JSON key: {key}")
                value[key] = child
            return value

        def invalid(value: str) -> None:
            raise ValueError(f"nonfinite JSON value: {value}")

        value = json.loads(self.rfile.read(length), object_pairs_hook=pairs, parse_constant=invalid)
        if not isinstance(value, dict):
            raise ValueError("request must be a JSON object")
        return value

    def do_GET(self) -> None:
        if self.allowed():
            self.dispatch("GET")

    def do_POST(self) -> None:
        if self.allowed(mutation=True):
            self.dispatch("POST")

    def dispatch(self, method: str) -> None:
        try:
            self.server.pump()
            path = urlsplit(self.path)
            parts = path.path.strip("/").split("/")
            query = parse_qs(path.query)
            studio = self.server.studio
            if method == "GET" and path.path in {"/", "/app.js", "/creation.js", "/style.css"}:
                asset = {"/": ("index.html", "text/html"), "/app.js": ("app.js", "text/javascript"),
                         "/creation.js": ("creation.js", "text/javascript"), "/style.css": ("style.css", "text/css")}[path.path]
                self.send(200, files("worldloom.studio").joinpath("static", asset[0]).read_bytes(), content_type=asset[1])
                return
            if method == "GET" and parts == ["api", "bootstrap"]:
                self.send(200, {"projects": studio.store.projects(), "catalogue": studio.catalogue(),
                                "harness_configured": bool(self.server.harness_command)})
                return
            if method == "GET" and parts == ["api", "preset"]:
                self.send(200, preset(query.get("engine", ["retail"])[0], query.get("name", ["Northstar Retail"])[0]).model_dump(mode="json"))
                return
            if method == "GET" and len(parts) == 3 and parts[:2] == ["api", "jobs"]:
                job = studio.store.job(parts[2])
                if job["options"]["operation"] == "foundry":
                    from .foundry import progress as foundry_progress
                    job["progress"] = foundry_progress(studio, job["id"])
                if job["options"]["operation"] == "compile":
                    from ..providers import digest
                    progress = studio.path("datasets", digest([job["project"], job["revision"]])) / "progress.json"
                    if progress.exists():
                        from ..evals.dataset import _read
                        job["progress"] = _read(progress)
                self.send(200, job)
                return
            if method == "GET" and len(parts) >= 3 and parts[:2] == ["api", "projects"]:
                project = parts[2]
                if len(parts) == 3:
                    self.send(200, studio.describe(project, query.get("revision", [None])[0], harness_configured=bool(self.server.harness_command)))
                    return
                if parts[3:] == ["workflow"]:
                    self.send(200, studio.workflow(project, query.get("revision", [None])[0],
                              harness_configured=bool(self.server.harness_command)).model_dump(mode="json"))
                    return
                if parts[3:] == ["creation"]:
                    self.send(200, studio.creation(project, query.get("revision", [None])[0]))
                    return
                if parts[3:] == ["native-sources"]:
                    self.send(200, studio.native_sources(project, query.get("revision", [None])[0],
                              offset=int(query.get("offset", ["0"])[0]), limit=int(query.get("limit", ["256"])[0]),
                              search=query.get("search", [""])[0], group_by=query.get("group_by", ["section"])[0]))
                    return
                if parts[3:] == ["native-queryset"]:
                    self.send(200, studio.native_queryset(project, query.get("job", [""])[0],
                              offset=int(query.get("offset", ["0"])[0]), limit=int(query.get("limit", ["25"])[0]),
                              operation=query.get("operation", [""])[0], format=query.get("format", [""])[0],
                              use_case_id=query.get("use_case_id", [""])[0]))
                    return
                if parts[3:] == ["native-artifact"]:
                    payload, format = studio.native_artifact(project, query.get("job", [""])[0], query.get("artifact", [""])[0])
                    types = {"docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                             "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                             "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}
                    self.send(200, payload, content_type=types[format])
                    return
                if parts[3:] == ["history"]:
                    self.send(200, studio.store.history(project))
                    return
                if parts[3:] == ["evidence"]:
                    current = studio.store.get(project, query.get("revision", [None])[0])
                    self.send(200, studio.evidence(project, current["revision"], query.get("id", [""])[0]))
                    return
                if parts[3:] == ["evals"]:
                    current = studio.store.get(project, query.get("revision", [None])[0])
                    from ..providers import digest
                    location = studio.dataset_location(project, current["revision"])
                    source = location / "queryset.jsonl"
                    complete = source.exists()
                    if not complete:
                        source = location / "candidates.jsonl"
                    offset = max(0, int(query.get("offset", ["0"])[0]))
                    count = min(100, max(1, int(query.get("limit", ["25"])[0])))
                    rows = []
                    if source.exists():
                        from itertools import islice
                        with source.open(encoding="utf-8") as stream:
                            rows = [json.loads(line) for line in islice(stream, offset, offset + count)]
                    self.send(200, {"rows": rows, "complete": complete, "offset": offset})
                    return
            if method == "POST":
                body = self.body()
                if parts == ["api", "projects"]:
                    self.send(201, studio.store.create(ProjectSpec.model_validate(body)))
                    return
                if len(parts) == 4 and parts[:2] == ["api", "jobs"] and parts[3] == "retry":
                    self.send(200, studio.store.retry(parts[2]))
                    self.server.pump()
                    return
                if len(parts) == 4 and parts[:2] == ["api", "projects"]:
                    project, action = parts[2:]
                    if action == "revise":
                        result = studio.store.revise(project, body["revision"], ProjectSpec.model_validate(body["spec"]), reason=body["reason"])
                    elif action == "interview-request":
                        result = studio.interview_request(project, body["revision"], body["message"])
                    elif action == "interview-accept":
                        result = studio.accept_interview(project, InterviewReply.model_validate(body))
                    elif action == "interview-apply":
                        result = studio.apply_interview(project, body["request_id"])
                    elif action == "select-narration":
                        result = studio.select_narration(project, body["revision"], body["job_id"])
                    elif action == "prepare-data":
                        result = studio.prepare_data(project, body["revision"], body["request"])
                    elif action == "prepare-native":
                        current = studio.store.get(project)
                        if current["revision"] != body["revision"]:
                            raise StudioConflict("company changed; reload before preparing native tasks")
                        options = RunOptions.model_validate({"operation": "prepare_native", "native_suite": body["request"]})
                        result = studio.store.enqueue(project, body["revision"], options)
                    elif action == "run":
                        options = RunOptions.model_validate(body["options"])
                        if options.operation in {"interview", "narrate", "foundry"} and not self.server.harness_command:
                            raise ValueError("start Studio with a coding harness command, or export a request for your harness")
                        from ..providers import digest
                        options = options.model_copy(update={"harness_identity":
                            digest(self.server.harness_command) if options.operation in {"interview", "narrate", "foundry", "native"} else ""})
                        result = studio.store.enqueue(project, body["revision"], options)
                        if result["status"] == "paused":
                            result = studio.store.retry(result["id"])
                    else:
                        raise KeyError("unknown project action")
                    self.send(200, result)
                    self.server.pump()
                    return
            self.send(404, {"error": "Route not found"})
        except StudioConflict as error:
            self.send(409, {"error": str(error)})
        except KeyError as error:
            self.send(404, {"error": str(error)})
        except (ValueError, OSError) as error:
            self.send(422, {"error": str(error)[:4000]})


__all__ = ["StudioServer"]
