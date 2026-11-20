"""Verify hosted URLs. Use --live only when real model requests are intended.

Standard-library only. Does not read, accept, or transmit API secrets.
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import ProxyHandler, Request, build_opener


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", required=True)
    parser.add_argument("--frontend", required=True)
    parser.add_argument("--live", action="store_true", help="Make billable provider calls to verify live chat, cache, and key_2 fallback")
    parser.add_argument("--verify-session", help="Check a previous verification session after a host restart")
    args = parser.parse_args()
    backend, frontend = args.backend.rstrip("/"), args.frontend.rstrip("/")
    for address in (backend, frontend):
        parsed = urlparse(address)
        assert parsed.scheme in {"http", "https"} and parsed.netloc, "Provide complete HTTP(S) URLs"
        assert not parsed.username and not parsed.password, "URLs must not contain credentials"
    # Windows can proxy localhost incorrectly; preserve normal proxy behavior for
    # cloud endpoints, but connect directly for local verification.
    opener = build_opener(ProxyHandler({})) if urlparse(backend).hostname in {"127.0.0.1", "localhost"} else build_opener()

    def request(url, payload=None, headers=None, method=None):
        final_headers = dict(headers or {})
        if payload is not None:
            final_headers["Content-Type"] = "application/json"
        req = Request(url, data=json.dumps(payload).encode() if payload is not None else None, headers=final_headers, method=method)
        try:
            with opener.open(req, timeout=90) as response:
                return response.status, response.read(), response.headers
        except HTTPError as error:
            return error.code, error.read(), error.headers

    def json_request(path, payload=None, headers=None):
        status, raw, _ = request(backend + path, payload, headers)
        return status, json.loads(raw)

    status, health = json_request("/health")
    assert status == 200 and health["status"] == "ok", "Backend is not healthy"
    assert health["keys_configured"] >= 2 and health["cache_enabled"] is True
    print("PASS backend health, configured key pool, and cache")
    status, html, _ = request(frontend)
    assert status == 200 and b'id="root"' in html, "Frontend did not serve the React page"
    print("PASS public frontend")
    origin = f"{urlparse(frontend).scheme}://{urlparse(frontend).netloc}"
    status, _, headers = request(backend + "/chat", headers={"Origin": origin, "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type,x-simulate-failure"}, method="OPTIONS")
    assert status == 200 and headers.get("Access-Control-Allow-Origin") == origin, "Set ALLOWED_ORIGINS to the actual frontend origin"
    print("PASS frontend-to-backend browser permissions (CORS)")
    invalid_id = "verify-invalid-" + uuid.uuid4().hex
    status, error = json_request("/chat", {"session_id": invalid_id, "message": "   "})
    assert status == 422 and "detail" in error, "Invalid input must return JSON 422"
    assert json_request(f"/sessions/{invalid_id}/messages")[0] == 404
    print("PASS validation and rejected-turn history isolation")

    if args.verify_session:
        status, history = json_request(f"/sessions/{args.verify_session}/messages")
        assert status == 200 and len(history["messages"]) >= 2, "Stored history is missing after restart"
        print("PASS stored conversation remains available")
    if not args.live:
        print("Infrastructure checks passed. Add --live to verify provider responses.")
        return

    def chat(session, text, simulation=None):
        status, result = json_request("/chat", {"session_id": session, "message": text}, {"X-Simulate-Failure": simulation} if simulation else None)
        assert status == 200, f"Chat request returned HTTP {status}; inspect the hosting service logs"
        assert result["session_id"] == session and result["reply"].strip()
        metadata = result["metadata"]
        for field in ("latency_ms", "input_tokens", "output_tokens", "fallback_attempts"):
            assert type(metadata[field]) is int and metadata[field] >= 0
        assert metadata["resolution_source"] in {"LIVE_INFERENCE", "LLM_CACHE"}
        assert metadata["model"]
        return result

    marker = "LYFTR-" + uuid.uuid4().hex[:10]
    session = "verify-live-" + uuid.uuid4().hex
    first_message = f"Remember this verification code: {marker}. Reply with Saved."
    live = chat(session, first_message)
    assert live["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    print("PASS live inference and per-request metadata")
    cached = chat("verify-cache-" + uuid.uuid4().hex, first_message)
    assert cached["metadata"]["resolution_source"] == "LLM_CACHE" and cached["reply"] == live["reply"]
    assert cached["metadata"]["key_id"] is None and cached["metadata"]["fallback_attempts"] == 0
    for field in ("input_tokens", "output_tokens"):
        assert cached["metadata"][field] == live["metadata"][field]
    print("PASS identical cross-session cache reply and preserved token usage")
    recalled = chat(session, "What verification code did I ask you to remember? Reply with the code only.")
    assert marker in recalled["reply"], "Model did not recall the previous turn"
    print("PASS multi-turn conversation memory")
    fallback = chat("verify-fallback-" + uuid.uuid4().hex, "Reply with Backup verified.", "key_1=429")
    assert fallback["metadata"]["key_id"] == "key_2" and fallback["metadata"]["fallback_attempts"] == 1
    print("PASS real backup-key response after simulated primary failure")
    failed = "verify-unavailable-" + uuid.uuid4().hex
    status, error = json_request("/chat", {"session_id": failed, "message": "test"}, {"X-Simulate-Failure": "*=429"})
    assert status == 503 and error == {"detail": "all providers unavailable"}
    assert json_request(f"/sessions/{failed}/messages")[0] == 404
    print("PASS all-key failure and unchanged history")
    print(f"Persistence verification session: {session}")
    print("After restarting the hosted backend, rerun with --verify-session and this ID.")


if __name__ == "__main__":
    try:
        main()
    except (AssertionError, URLError, ValueError, KeyError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        sys.exit(1)
