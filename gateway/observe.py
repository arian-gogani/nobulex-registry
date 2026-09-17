#!/usr/bin/env python3
"""Mirror one path: the integration story, as one wrapper.

    from observe import guard

    fetch_bars = guard(
        fetch_bars,                    # the call you already make
        checks=my_checks,              # (result, context) -> suite outcomes
        policy=my_policy,
        on_decision=log_or_webhook,    # receives the decision + receipt
    )

In observe mode, which is the default, the wrapped call is byte-for-byte
the call it was before: same result, same exceptions, same timing to within
the cost of the checks. The wrapper computes the full decision, hands it to
`on_decision`, and stays out of the way. That is the entire deployment ask
for a shadow pilot, and it is why the ask is small.

Two properties are load-bearing, and the tests exist to pin them:

1. In observe mode, NOTHING the gateway does can change what the wrapped
   call returns. Not a fault, not a blocked verdict, not the gateway's own
   code raising. A shadow that can break production is not a shadow.

2. In enforce mode, the gateway's own failure is not an approval. What it
   is instead is the caller's stated choice, made in advance per wrapper,
   because "what happens when the control fails" decided silently is the
   defect class this repository documents.
"""

from __future__ import annotations

import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "suite"))

from decide import (  # noqa: E402
    ESCALATE, EV_INDETERMINATE, MODE_ENFORCE, MODE_OBSERVE, decide, receipt,
)

OBSERVE = MODE_OBSERVE
ENFORCE = MODE_ENFORCE


class Blocked(Exception):
    """Raised in enforce mode when the decision is not PERMIT."""

    def __init__(self, decision):
        self.decision = decision
        reasons = ", ".join(
            r.get("code", "?") for r in decision.get("reasons", [])
            if r.get("status") != "SATISFIED") or decision["evidence_status"]
        super().__init__(f"{decision['decision']}: {reasons}")


def _error_decision(mode, detail):
    """The gateway's own failure, as an explicit non-permit decision."""
    return {
        "mode": mode,
        "evidence_status": EV_INDETERMINATE,
        "decision": ESCALATE,
        "would_block": True,
        "enforced": mode == ENFORCE,
        "reasons": [{"code": "GATEWAY_ERROR", "status": "UNEVALUATED",
                     "detail": detail}],
        "checks_run": 0,
        "unevaluated_limits": 0,
        "policy": {"id": "?", "version": "?", "content_hash": "?"},
    }


def guard(fn, checks, policy, on_decision=None, mode=OBSERVE,
          context_fn=None, action_fn=None, on_gateway_error="block",
          signer=None):
    """Wrap `fn` so every call is decided, and in enforce mode, gated.

    fn               the call being mirrored. Its result is the subject.
    checks           (result, context) -> list of suite outcomes.
    policy           the bounded policy decide() validates and runs.
    on_decision      called with (decision, receipt_obj) after every call.
                     Exceptions inside it are contained: a broken log line
                     must not break the path being observed.
    mode             OBSERVE (default) or ENFORCE. Enforce is a choice,
                     never a fallback.
    context_fn       (args, kwargs, result) -> context dict for limits.
    action_fn        (args, kwargs) -> action dict for the receipt.
    on_gateway_error enforce mode only: "block" (default) raises Blocked
                     when the gateway itself fails, "allow" lets the call
                     through while still reporting the error decision.
                     Stated per wrapper, in advance, on purpose.
    signer           optional Ed25519 signer for receipts.
    """
    if mode not in (OBSERVE, ENFORCE):
        raise ValueError(f"mode must be {OBSERVE!r} or {ENFORCE!r}")
    if on_gateway_error not in ("block", "allow"):
        raise ValueError("on_gateway_error must be 'block' or 'allow'")
    # Refuse a bad policy at wrap time, not at call time in production.
    decide(policy, [], {}, mode=mode)

    state = {"previous_hash": None}

    def _emit(decision, action, refs):
        try:
            r = receipt(decision, action, refs,
                        previous_hash=state["previous_hash"], signer=signer)
            state["previous_hash"] = r["receipt_hash"]
        except Exception:  # noqa: BLE001
            r = None
        if on_decision is not None:
            try:
                on_decision(decision, r)
            except Exception:  # noqa: BLE001
                # A broken consumer must not break the observed path.
                traceback.print_exc(file=sys.stderr)

    def wrapped(*args, **kwargs):
        # The wrapped call itself is never inside the gateway's try. If it
        # raises, it raises exactly as it did before the wrapper existed.
        result = fn(*args, **kwargs)

        action = {"type": getattr(fn, "__name__", "call")}
        try:
            if action_fn is not None:
                action = action_fn(args, kwargs)
            context = (context_fn(args, kwargs, result)
                       if context_fn is not None else {})
            t0 = time.perf_counter()
            outcomes = checks(result, context)
            decision = decide(policy, outcomes, context, mode=mode)
            decision["gateway_ms"] = round(
                (time.perf_counter() - t0) * 1000.0, 3)
            _emit(decision, action, [])
        except Exception:  # noqa: BLE001
            traceback.print_exc(file=sys.stderr)
            decision = _error_decision(mode, "checks or policy raised; "
                                             "this is not an approval")
            _emit(decision, action, [])
            if mode == ENFORCE and on_gateway_error == "block":
                raise Blocked(decision) from None
            return result

        if mode == ENFORCE and decision["decision"] != "PERMIT":
            raise Blocked(decision)
        return result

    wrapped.__name__ = getattr(fn, "__name__", "wrapped")
    wrapped.__doc__ = fn.__doc__
    return wrapped
