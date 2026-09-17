#!/usr/bin/env python3
"""Tests for the HTTP surface.

The important ones are the failure paths. An inline gateway that answers
PERMIT because its own handler raised has done the thing this repository
exists to catch, so every malformed, oversized, unparseable and unexpected
input is checked to produce a non-permit.

    python3 gateway/selftest_serve.py
"""

import json
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "suite"))

from decide import (  # noqa: E402
    BLOCK, ESCALATE, EV_INDETERMINATE, MODE_ENFORCE, MODE_OBSERVE, PERMIT,
)
from harness import AuthorityUnavailable  # noqa: E402
import serve  # noqa: E402
from serve import build_server  # noqa: E402

FAILURES = []
POLICY = json.loads((Path(__file__).parent / "policy.example.json").read_text())
BASE = None


def check(label, got, want):
    if got != want:
        FAILURES.append(f"{label}\n      got  {got!r}\n      want {want!r}")
        print(f"  FAIL  {label}")
    else:
        print(f"  ok    {label}")


def post(path, payload, raw=None):
    data = raw if raw is not None else json.dumps(payload).encode()
    req = urllib.request.Request(f"{BASE}{path}", data=data,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def get(path):
    with urllib.request.urlopen(f"{BASE}{path}", timeout=5) as r:
        return r.status, json.loads(r.read())


OK_CTX = {"action": {"notional_usd": 24130},
          "evidence": {"quote": {"age_ms": 84, "deviation_bps": 2.1}},
          "portfolio": {"daily_turnover_pct": 1.2}}
ACTION = {"type": "broker.order.create", "symbol": "AAPL", "quantity": 100}


def main():
    global BASE
    httpd = build_server(POLICY, port=0, mode=MODE_OBSERVE)
    BASE = f"http://127.0.0.1:{httpd.server_address[1]}"
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    print("Health\n")
    code, h = get("/healthz")
    check("healthz responds", code, 200)
    check("and reports observe mode by default", h["mode"], MODE_OBSERVE)
    check("and says it is not enforcing", h["enforcing"], False)
    check("and reports signing off when no key was given",
          h["signing"], "disabled")
    check("and discloses the live-check cache TTL",
          isinstance(h.get("live_check_cache_ttl_s"), (int, float)), True)

    print("\nDeciding\n")
    code, r = post("/v1/decisions",
                   {"action": ACTION, "outcomes": ["PASS"], "context": OK_CTX})
    check("a clean request decides", code, 200)
    check("and permits", r["decision"], PERMIT)
    check("and returns a receipt", r["receipt"]["receipt_hash"][:7], "sha256:")
    check("unsigned receipts say so",
          r["receipt"]["signature"]["status"], "UNSIGNED")

    code, r = post("/v1/decisions",
                   {"action": ACTION, "outcomes": ["FAIL_UNSAFE"],
                    "context": OK_CTX})
    check("a quiet lie blocks", r["decision"], BLOCK)
    check("and observe mode does not claim it enforced", r["enforced"], False)
    check("but does report it would have blocked", r["would_block"], True)

    code, r = post("/v1/decisions",
                   {"action": ACTION, "outcomes": [], "context": OK_CTX})
    check("zero checks escalates, never permits", r["decision"], ESCALATE)

    print("\nThe gateway failing is not an approval\n")
    for label, payload, raw in [
        ("malformed JSON", None, b"{not json"),
        ("empty body", None, b""),
        ("a JSON array instead of an object", None, b"[1,2,3]"),
        ("a missing action", {"outcomes": ["PASS"], "context": OK_CTX}, None),
        ("an action with no type",
         {"action": {}, "outcomes": ["PASS"], "context": OK_CTX}, None),
        ("a missing context", {"action": ACTION, "outcomes": ["PASS"]}, None),
        ("outcomes that are not a list",
         {"action": ACTION, "outcomes": "PASS", "context": OK_CTX}, None),
        ("an outcome string the suite does not define",
         {"action": ACTION, "outcomes": ["DEFINITELY_FINE"],
          "context": OK_CTX}, None),
    ]:
        code, r = post("/v1/decisions", payload, raw)
        check(f"{label} is rejected", code, 400)
        check(f"{label} does not return PERMIT",
              r.get("decision") == PERMIT, False)
        check(f"{label} reports would_block", r.get("would_block"), True)
        check(f"{label} is INDETERMINATE, not PASS",
              r.get("evidence_status"), EV_INDETERMINATE)

    body = json.dumps({"action": ACTION, "outcomes": ["PASS"],
                       "context": OK_CTX, "pad": "x" * (1 << 21)}).encode()
    code, r = post("/v1/decisions", None, body)
    check("an oversized body is rejected with 413, not a reset", code, 413)
    check("and is not an approval", r.get("decision") == PERMIT, False)

    print("\nIdempotency and chaining\n")
    req = {"action": ACTION, "outcomes": ["PASS"], "context": OK_CTX,
           "idempotency_key": "ord-1"}
    _, a = post("/v1/decisions", req)
    _, b = post("/v1/decisions", req)
    check("the same key returns the same receipt",
          a["receipt"]["receipt_hash"], b["receipt"]["receipt_hash"])

    _, c = post("/v1/decisions",
                {"action": ACTION, "outcomes": ["PASS"], "context": OK_CTX,
                 "idempotency_key": "ord-2"})
    check("a new key chains onto the previous receipt",
          c["receipt"]["chain"]["previous_receipt_hash"],
          a["receipt"]["receipt_hash"])
    check("and a new key is a different receipt",
          c["receipt"]["receipt_hash"] != a["receipt"]["receipt_hash"], True)

    print("\nEnforce mode is opt-in\n")
    # Build with no mode argument at all. Every other test in this file names
    # the mode explicitly, so a change to the default would have gone
    # unnoticed by all of them. "Observe is the default" is a safety claim and
    # it has to be tested where the default actually lives.
    default = build_server(POLICY, port=0)
    check("a server built with no mode argument observes",
          default.gateway.mode, MODE_OBSERVE)
    check("and does not enforce", default.gateway.health()["enforcing"], False)
    default.server_close()

    enf = build_server(POLICY, port=0, mode=MODE_ENFORCE)
    eb = f"http://127.0.0.1:{enf.server_address[1]}"
    threading.Thread(target=enf.serve_forever, daemon=True).start()
    with urllib.request.urlopen(f"{eb}/healthz", timeout=5) as resp:
        eh = json.loads(resp.read())
    check("an enforcing gateway says it is enforcing", eh["enforcing"], True)
    check("and the observing one still is not", get("/healthz")[1]["enforcing"],
          False)
    enf.shutdown()

    print("\nSigned receipts over HTTP\n")
    try:
        import base64
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PrivateKey)
        from decide import ed25519_signer
        k = Ed25519PrivateKey.generate()
        s = build_server(POLICY, port=0, mode=MODE_OBSERVE,
                         signer=ed25519_signer(k.private_bytes_raw(), "t1"))
        sb = f"http://127.0.0.1:{s.server_address[1]}"
        threading.Thread(target=s.serve_forever, daemon=True).start()

        req2 = urllib.request.Request(
            f"{sb}/v1/decisions",
            data=json.dumps({"action": ACTION, "outcomes": ["PASS"],
                             "context": OK_CTX}).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req2, timeout=5) as resp:
            signed = json.loads(resp.read())
        check("receipts are signed when a key is present",
              signed["receipt"]["signature"]["status"], "SIGNED")

        pub = base64.urlsafe_b64encode(
            k.public_key().public_bytes_raw()).decode()
        vreq = urllib.request.Request(
            f"{sb}/v1/receipts/verify",
            data=json.dumps({"receipt": signed["receipt"],
                             "public_key": pub}).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(vreq, timeout=5) as resp:
            v = json.loads(resp.read())
        check("and verify independently", v["verified"], True)

        tampered = dict(signed["receipt"])
        tampered["decision"] = BLOCK
        vreq2 = urllib.request.Request(
            f"{sb}/v1/receipts/verify",
            data=json.dumps({"receipt": tampered, "public_key": pub}).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(vreq2, timeout=5) as resp:
            v2 = json.loads(resp.read())
        check("a tampered decision does not verify", v2["verified"], False)
        s.shutdown()
    except ImportError:
        print("  skip  signing tests, cryptography not installed")

    print("\nLive check, stubbed at the network boundary\n")
    # /v1/live-check reaches a live endpoint in production, so this test must
    # not, or the suite fails on a plane. Only authority_bars is stubbed;
    # everything below the fetch runs for real against it, same discipline
    # as selftest_live.py.
    real_authority_bars = serve.authority_bars
    stub_now = datetime(2026, 9, 17, 20, 0, tzinfo=timezone.utc)
    stub_dates = ["2026-08-31", "2026-09-01", "2026-09-02", "2026-09-03",
                  "2026-09-04", "2026-09-08", "2026-09-09", "2026-09-10",
                  "2026-09-11", "2026-09-14", "2026-09-15", "2026-09-16",
                  "2026-09-17"]
    stub_auth = [{"date": d, "close": round(330.0 + i * 0.4, 2)}
                 for i, d in enumerate(stub_dates)]

    real_ttl = serve.AUTH_CACHE_TTL_S
    try:
        serve.authority_bars = lambda ticker: stub_auth
        serve.datetime = type("_D", (datetime,), {
            "now": staticmethod(lambda tz=None: stub_now)})

        code, r = post("/v1/live-check", {"ticker": "AAPL", "context": OK_CTX})
        check("a faithful live check decides", code, 200)
        check("and permits", r["decision"], PERMIT)
        check("noting the subject is the authority's own series",
              "faithful" in r["subject_note"], True)
        check("and carries a receipt", r["receipt"]["receipt_hash"][:7],
              "sha256:")

        corrupted = [{"Date": b["date"], "Open": b["close"], "High": b["close"],
                     "Low": b["close"], "Close": b["close"]} for b in stub_auth]
        corrupted[-1]["Close"] = round(corrupted[-1]["Close"] * 1.02, 4)
        code, r = post("/v1/live-check",
                       {"ticker": "AAPL", "subject": corrupted, "context": OK_CTX})
        check("a caller-supplied subject is judged, not trusted", code, 200)
        check("and a 2% deviation is not permitted", r["decision"] != PERMIT,
              True)
        check("caught by fidelity",
              r["checks"]["fidelity"]["outcome"] != "PASS", True)
        check("subject_note says caller-supplied",
              r["subject_note"], "subject supplied by caller")

        code, r = post("/v1/live-check", {})
        check("a missing ticker is rejected", code, 400)
        check("and is not a permit", r.get("decision") == PERMIT, False)

        code, r = post("/v1/live-check", {"ticker": "AAPL", "subject": "nope"})
        check("a non-list subject is rejected", code, 400)

        minimal_policy = {
            "id": "live-check-minimal", "version": 1,
            "on_evidence": {"PASS": PERMIT, "FAIL": BLOCK,
                            "INDETERMINATE": ESCALATE},
            "on_limit_violation": BLOCK,
            "limits": [{"field": "action.notional_usd", "op": "lte",
                       "value": 50000, "code": "NOTIONAL_OK"}],
        }
        mp = build_server(minimal_policy, port=0, mode=MODE_OBSERVE)
        mp_base = f"http://127.0.0.1:{mp.server_address[1]}"
        threading.Thread(target=mp.serve_forever, daemon=True).start()
        mreq = urllib.request.Request(
            f"{mp_base}/v1/live-check",
            data=json.dumps({"ticker": "AAPL"}).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(mreq, timeout=5) as resp:
            mr = json.loads(resp.read())
        check("without a context, notional_usd defaults and still permits",
              mr["decision"], PERMIT)
        mp.shutdown()

        print("\nThe authority fetch is cached, so a burst does not "
              "re-hit the network\n")
        calls = {"n": 0}

        def counting(ticker):
            calls["n"] += 1
            return stub_auth
        serve.authority_bars = counting

        cache_server = build_server(minimal_policy, port=0, mode=MODE_OBSERVE)
        cb = f"http://127.0.0.1:{cache_server.server_address[1]}"
        threading.Thread(target=cache_server.serve_forever, daemon=True).start()

        def live_check(base, ticker="AAPL"):
            req = urllib.request.Request(
                f"{base}/v1/live-check",
                data=json.dumps({"ticker": ticker}).encode(),
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                return json.loads(resp.read())

        live_check(cb)
        live_check(cb)
        live_check(cb)
        check("three quick requests for the same ticker fetch once",
              calls["n"], 1)

        live_check(cb, ticker="MSFT")
        check("a different ticker is its own fetch", calls["n"], 2)

        # A fresh ticker, and a TTL with real margin either side of the
        # sleep, so this is not a race against how long the HTTP round
        # trips above happened to take.
        serve.AUTH_CACHE_TTL_S = 1.0
        calls["n"] = 0
        live_check(cb, ticker="NFLX")
        live_check(cb, ticker="NFLX")
        check("immediately again, still within the TTL, no refetch",
              calls["n"], 1)
        time.sleep(1.2)
        live_check(cb, ticker="NFLX")
        check("past the TTL, the same ticker fetches again", calls["n"], 2)
        serve.AUTH_CACHE_TTL_S = real_ttl
        cache_server.shutdown()

        # A ticker not already touched by an earlier test in this run, so
        # this is not accidentally served from a still-warm cache entry.
        down_ticker = "ZZZQ-UNCACHED"

        def unavailable(ticker):
            raise AuthorityUnavailable(f"https://example/{ticker}", status=503)
        serve.authority_bars = unavailable
        code, r = post("/v1/live-check", {"ticker": down_ticker})
        check("an unreachable authority is not a gateway crash", code, 502)
        check("and is not a permit", r.get("decision") == PERMIT, False)
        check("and says why", r.get("error", {}).get("code"),
              "AUTHORITY_UNAVAILABLE")

        # A failed fetch must never be cached as a real answer, or an
        # upstream outage would look permanently down even after it
        # recovered. Swap a working authority back in for the same ticker
        # the failure was just reported for, and confirm it is used.
        calls["n"] = 0
        serve.authority_bars = counting
        code, r = post("/v1/live-check", {"ticker": down_ticker})
        check("a working authority right after a failure is not blocked "
              "by a cached-down verdict", code, 200)
        check("and it actually fetched", calls["n"], 1)
    finally:
        serve.authority_bars = real_authority_bars
        serve.datetime = datetime
        serve.AUTH_CACHE_TTL_S = real_ttl

    print("\nRefusing to run a policy it cannot evaluate\n")
    from decide import PolicyError
    try:
        build_server({"id": "bad", "version": 1,
                      "on_evidence": {"PASS": "PERMIT"}}, port=0)
        FAILURES.append("a policy missing an evidence branch was accepted")
        print("  FAIL  an incomplete policy is refused at startup")
    except PolicyError:
        print("  ok    an incomplete policy is refused at startup")

    httpd.shutdown()
    print()
    if FAILURES:
        print(f"{len(FAILURES)} failed:\n")
        for f in FAILURES:
            print("  " + f)
        return 1
    print("all http checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
