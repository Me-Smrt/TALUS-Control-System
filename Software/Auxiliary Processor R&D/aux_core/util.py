from __future__ import annotations
import base64, json, time, urllib.error, urllib.request
from typing import Any

def now_stamp(source: str, sequence: int = 0) -> dict[str, Any]:
    return {"sequence": int(sequence), "monotonic_ns": time.monotonic_ns(), "unix_ns": time.time_ns(), "source": source}

def json_request(url: str, *, method: str = "GET", payload: Any = None, headers: dict[str,str] | None = None, timeout: float = 5.0) -> tuple[int, dict[str,Any], dict[str,str]]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req_headers = {"Accept": "application/json"}
    if data is not None: req_headers["Content-Type"] = "application/json"
    if headers: req_headers.update(headers)
    req = urllib.request.Request(url, data=data, headers=req_headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = json.loads(r.read().decode("utf-8"))
        return int(r.status), body, dict(r.headers.items())

def data_url_jpeg(jpeg: bytes) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(jpeg).decode("ascii")

def language_family(code: str | None) -> str:
    if not code: return "und"
    return code.replace("_", "-").split("-",1)[0].lower()
