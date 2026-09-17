#!/usr/bin/env python3
"""HTTP surface for the decision layer. Standard library only.

    python3 gateway/serve.py --policy gateway/policy.example.json
    python3 gateway/serve.py --policy p.json --enforce      # opt in explicitly

    POST /v1/decisions          decide one proposed action
    POST /v1/receipts/verify    verify a receipt against a public key
    GET  /healthz               liveness, and the mode it is actually in

The single most important property of this file is what it does when it
itself goes wrong. A gateway that answers PERMIT because its own handler
raised has not failed open by accident; it has done the exact thing this
repository exists to catch. So every error path here produces an explicit
non-permit result with a reason, and never a decision object that could be
mistaken for an approval.

Observe is the default and enforce requires a flag. A gateway that starts
enforcing because a config file changed shape is the same class of surprise.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "suite"))

from decide import (  # noqa: E402
    BLOCK, ESCALATE, EV_INDETERMINATE, MODE_ENFORCE, MODE_OBSERVE, PERMIT,
    PolicyError, decide, ed25519_signer, receipt, sha256, validate_policy,
    verify_receipt,
)
from harness import (  # noqa: E402
    FAIL_SAFE, FAIL_UNSAFE, INDETERMINATE, OUT_OF_SCOPE, PASS,
)

KNOWN_OUTCOMES = frozenset(
    (PASS, FAIL_SAFE, FAIL_UNSAFE, INDETERMINATE, OUT_OF_SCOPE))

MAX_BODY = 1 << 20   # 1 MiB. A decision request is small; larger is a mistake.
MAX_DRAIN = 1 << 24  # 16 MiB. Past this, close rather than keep reading.


class Gateway:
    """Holds the policy, the receipt chain and the signer.

    The chain lock matters: two concurrent requests must not both read the
    same previous hash and produce a fork that looks like a valid chain.
    """

    def __init__(self, policy, mode=MODE_OBSERVE, signer=None):
        validate_policy(policy)
        self.policy = policy
        self.mode = mode
        self.signer = signer
        self._lock = threading.Lock()
        self._previous_hash = None
        self._seen = {}          # idempotency_key -> response
        self.decisions = 0
        self.would_block = 0
        self.errors = 0

    def health(self):
        return {
            "status": "ok",
            "mode": self.mode,
            "enforcing": self.mode == MODE_ENFORCE,
            "policy": {"id": self.policy["id"],
                       "version": str(self.policy["version"]),
                       "content_hash": sha256(self.policy)},
            "decisions": self.decisions,
            "would_block": self.would_block,
            "handler_errors": self.errors,
            "signing": "enabled" if self.signer else "disabled",
        }

    def decide_request(self, body):
        key = body.get("idempotency_key")
        if key is not None:
            with self._lock:
                if key in self._seen:
                    return self._seen[key]

        action = body.get("action")
        if not isinstance(action, dict) or not action.get("type"):
            raise BadRequest("action.type is required")

        outcomes = body.get("outcomes") or []
        if not isinstance(outcomes, list):
            raise BadRequest("outcomes must be a list of suite verdicts")
        # An unrecognised verdict is safe by accident: aggregate() falls back
        # to OUT_OF_SCOPE, which resolves to INDETERMINATE and escalates. But
        # a caller who typed the verdict wrong would see every decision
        # escalate and nothing telling them why. Reject it instead, so the
        # integration bug is loud rather than a quiet permanent escalation.
        unknown = [o for o in outcomes if o not in KNOWN_OUTCOMES]
        if unknown:
            raise BadRequest(
                f"unknown outcome(s) {unknown!r}; expected any of "
                f"{sorted(KNOWN_OUTCOMES)}")

        context = body.get("context")
        if not isinstance(context, dict):
            raise BadRequest("context must be an object")

        try:
            d = decide(self.policy, outcomes, context, mode=self.mode)
        except KeyError as e:
            # An outcome string the suite does not define. Refusing is the
            # only safe answer: an unknown verdict must never map to PERMIT.
            raise BadRequest(f"unknown outcome {e.args[0]!r}") from None

        refs = body.get("evidence_refs") or []
        with self._lock:
            r = receipt(d, action, refs, previous_hash=self._previous_hash,
                        signer=self.signer)
            self._previous_hash = r["receipt_hash"]
            self.decisions += 1
            if d["would_block"]:
                self.would_block += 1
            response = {**d, "receipt": r}
            if key is not None:
                self._seen[key] = response
        return response


class BadRequest(ValueError):
    pass


class TooLarge(ValueError):
    pass


def _fail_closed(reason, detail, mode):
    """The shape returned whenever this gateway cannot decide.

    Deliberately carries the same field names as a real decision so a caller
    cannot accidentally read it as an approval, and an explicit non-permit
    decision so that a caller checking only `decision` still refuses.
    """
    return {
        "mode": mode,
        "evidence_status": EV_INDETERMINATE,
        "decision": ESCALATE,
        "would_block": True,
        "enforced": mode == MODE_ENFORCE,
        "error": {"code": reason, "detail": detail},
        "reasons": [{"code": reason, "status": "UNEVALUATED", "detail": detail}],
        "checks_run": 0,
        "unevaluated_limits": 0,
        "receipt": None,
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "nobulex-gateway/0.1"
    gateway: Gateway = None  # set on the server instance

    def log_message(self, fmt, *args):  # quieter default logging
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _send(self, code, payload):
        body = json.dumps(payload, indent=2).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _drain(self, length):
        """Consume an over-length body in bounded chunks so the refusal
        reaches the client instead of a reset. Past MAX_DRAIN, give up and
        let the connection close; at that point the peer is not behaving."""
        remaining = min(length, MAX_DRAIN)
        while remaining > 0:
            chunk = self.rfile.read(min(65536, remaining))
            if not chunk:
                break
            remaining -= len(chunk)

    def _read_json(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            raise BadRequest("empty body")
        if length > MAX_BODY:
            # Answer rather than reset. Responding without reading the body
            # leaves the client mid-send and it sees a connection reset
            # instead of the refusal, which reads like the gateway crashed.
            # Drain within a bound so memory stays capped either way.
            self._drain(length)
            raise TooLarge(f"body is {length} bytes, limit is {MAX_BODY}")
        raw = self.rfile.read(length)
        try:
            body = json.loads(raw)
        except json.JSONDecodeError as e:
            raise BadRequest(f"body is not valid JSON: {e}") from None
        if not isinstance(body, dict):
            raise BadRequest("body must be a JSON object")
        return body

    def do_GET(self):
        if self.path.split("?")[0] == "/healthz":
            self._send(200, self.gateway.health())
            return
        self._send(404, {"error": "not found"})

    def do_POST(self):
        path = self.path.split("?")[0]
        gw = self.gateway
        try:
            if path == "/v1/decisions":
                self._send(200, gw.decide_request(self._read_json()))
                return
            if path == "/v1/receipts/verify":
                body = self._read_json()
                import base64
                pub = base64.urlsafe_b64decode(body.get("public_key", ""))
                ok, why = verify_receipt(body.get("receipt") or {}, pub)
                self._send(200, {"verified": ok, "detail": why})
                return
            self._send(404, {"error": "not found"})
        except TooLarge as e:
            gw.errors += 1
            self._send(413, _fail_closed("BODY_TOO_LARGE", str(e), gw.mode))
        except BadRequest as e:
            # A malformed request is not an approval.
            gw.errors += 1
            self._send(400, _fail_closed("BAD_REQUEST", str(e), gw.mode))
        except Exception:  # noqa: BLE001
            # Anything unexpected in this handler resolves to a non-permit.
            gw.errors += 1
            traceback.print_exc(file=sys.stderr)
            self._send(500, _fail_closed(
                "GATEWAY_ERROR",
                "the gateway could not reach a decision; this is not an approval",
                gw.mode))


def build_server(policy, host="127.0.0.1", port=8830, mode=MODE_OBSERVE,
                 signer=None):
    gw = Gateway(policy, mode=mode, signer=signer)
    handler = type("BoundHandler", (Handler,), {"gateway": gw})
    httpd = ThreadingHTTPServer((host, port), handler)
    httpd.gateway = gw
    return httpd


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--policy", required=True, type=Path)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8830)
    ap.add_argument("--enforce", action="store_true",
                    help="block for real. Without this the gateway observes "
                         "and reports what it would have done.")
    ap.add_argument("--signing-key", type=Path,
                    help="raw 32-byte Ed25519 private key. Without it "
                         "receipts are emitted marked UNSIGNED.")
    ap.add_argument("--key-id", default="dev")
    args = ap.parse_args(argv)

    try:
        policy = json.loads(args.policy.read_text())
    except (OSError, json.JSONDecodeError) as e:
        print(f"cannot read policy: {e}", file=sys.stderr)
        return 2
    try:
        validate_policy(policy)
    except PolicyError as e:
        # Refusing to start is correct. A gateway running on a policy it
        # cannot evaluate is worse than no gateway, because it looks like one.
        print(f"refusing to start: {e}", file=sys.stderr)
        return 2

    signer = None
    if args.signing_key:
        signer = ed25519_signer(args.signing_key.read_bytes(), args.key_id)

    mode = MODE_ENFORCE if args.enforce else MODE_OBSERVE
    httpd = build_server(policy, args.host, args.port, mode, signer)
    print(f"nobulex gateway on http://{args.host}:{args.port}  mode={mode}  "
          f"policy={policy['id']} v{policy['version']}  "
          f"signing={'on' if signer else 'off'}")
    if mode == MODE_OBSERVE:
        print("observe mode: decisions are computed and reported, nothing is "
              "blocked. Pass --enforce to change that.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
