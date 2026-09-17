#!/usr/bin/env python3
"""The decision layer: evidence status in, execution decision out.

The suite already answers "were these facts correct". This answers the
question a caller actually has to act on: may this specific action execute
right now.

Two surfaces, kept apart on purpose:

    evidence_status   PASS | FAIL | INDETERMINATE
    decision          PERMIT | BLOCK | ESCALATE

Collapsing them loses the distinction between "the facts are wrong" and
"your rule is strict", which need different responses from an operator.

Observe mode computes the whole decision and reports what it would have
done, without ever claiming the action was stopped. A gateway that quietly
starts enforcing is the same class of surprise this project exists to
prevent.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "suite"))
from harness import (  # noqa: E402
    PASS, FAIL_SAFE, FAIL_UNSAFE, INDETERMINATE, OUT_OF_SCOPE, aggregate,
)

# -- evidence statuses -------------------------------------------------------
EV_PASS = "PASS"
EV_FAIL = "FAIL"
EV_INDETERMINATE = "INDETERMINATE"

# -- decisions ---------------------------------------------------------------
PERMIT = "PERMIT"
BLOCK = "BLOCK"
ESCALATE = "ESCALATE"

MODE_OBSERVE = "observe"
MODE_ENFORCE = "enforce"


# The suite grades a tool. The gateway grades the facts in hand. The two
# differ on exactly one verdict, and it is worth stating why rather than
# leaving it in a mapping table.
#
#   FAIL_SAFE means the source refused, errored, or returned an explicit
#   null. As a verdict about a tool that is a failure: it did not do its
#   job. As a statement about the facts it is not FAIL, because nothing
#   false was asserted. We simply have no evidence, which is the definition
#   of INDETERMINATE here.
#
# Reading FAIL_SAFE as FAIL would block on every upstream hiccup and train
# operators to bypass the gateway. Reading it as PASS would be the defect
# this repository is about.
_EVIDENCE = {
    PASS: EV_PASS,
    FAIL_UNSAFE: EV_FAIL,
    FAIL_SAFE: EV_INDETERMINATE,
    INDETERMINATE: EV_INDETERMINATE,
    OUT_OF_SCOPE: EV_INDETERMINATE,
}


class PolicyError(ValueError):
    """Raised for a policy this evaluator refuses to run.

    Refusing loudly at load time is the whole point. A policy that cannot
    be understood must never degrade into a permissive default.
    """


# Bounded on purpose: a fixed operator set, no loops, no lookups outside the
# supplied context, no arithmetic that can fail to terminate. Over an
# authenticated context this makes evaluation deterministic and total.
_OPS = {
    "lte": lambda a, b: a <= b,
    "lt": lambda a, b: a < b,
    "gte": lambda a, b: a >= b,
    "gt": lambda a, b: a > b,
    "eq": lambda a, b: a == b,
    "in": lambda a, b: a in b,
}


def _canonical(obj) -> bytes:
    """One serialization, used for every hash and signature."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def sha256(obj) -> str:
    return "sha256:" + hashlib.sha256(_canonical(obj)).hexdigest()


def evidence_status(outcomes) -> str:
    """Collapse suite outcomes into one evidence status.

    Uses the suite's own aggregate(), so FAIL_UNSAFE still dominates and a
    single quiet lie is not averaged away by correct answers beside it.
    """
    if not outcomes:
        # No checks ran. This is the all([]) case, and it is not a pass.
        return EV_INDETERMINATE
    return _EVIDENCE[aggregate(list(outcomes))]


def validate_policy(policy) -> None:
    """Reject anything this evaluator cannot evaluate totally."""
    if not isinstance(policy, dict):
        raise PolicyError("policy must be an object")
    for field in ("id", "version", "on_evidence", "on_limit_violation"):
        if field not in policy:
            raise PolicyError(f"policy is missing required field {field!r}")

    on_ev = policy["on_evidence"]
    for status in (EV_PASS, EV_FAIL, EV_INDETERMINATE):
        if status not in on_ev:
            raise PolicyError(
                f"on_evidence must name a decision for {status}; leaving one "
                "unstated is how a permissive default gets in by accident")
        if on_ev[status] not in (PERMIT, BLOCK, ESCALATE):
            raise PolicyError(f"on_evidence[{status}] is not a decision")

    # PERMIT is a valid decision in general, but not here: a limit exists
    # to refuse an action that failed a numeric check, and permitting on
    # its own violation is not a policy choice, it is the limit doing
    # nothing while still being present in the file to be read as a
    # safeguard. This was reachable before this check existed: a policy
    # with on_limit_violation set to PERMIT validated cleanly and a
    # $999,999,999 order against a $1,000 cap decided PERMIT.
    if policy["on_limit_violation"] not in (BLOCK, ESCALATE):
        raise PolicyError(
            "on_limit_violation must be BLOCK or ESCALATE, not "
            f"{policy['on_limit_violation']!r}")

    for i, rule in enumerate(policy.get("limits", [])):
        if set(rule) - {"field", "op", "value", "code"}:
            raise PolicyError(f"limit {i} has unknown keys")
        for field in ("field", "op", "value", "code"):
            if field not in rule:
                raise PolicyError(f"limit {i} is missing {field!r}")
        if rule["op"] not in _OPS:
            raise PolicyError(
                f"limit {i} uses operator {rule['op']!r}, which is not in the "
                f"bounded set {sorted(_OPS)}")


def _lookup(context, dotted):
    """Read one dotted path out of the context. Missing is missing."""
    node = context
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return None, False
        node = node[part]
    return node, True


def evaluate_limits(policy, context):
    """Return (satisfied, reasons). A missing field never silently passes."""
    reasons = []
    satisfied = True
    for rule in policy.get("limits", []):
        observed, present = _lookup(context, rule["field"])
        if not present:
            satisfied = False
            reasons.append({
                "code": rule["code"],
                "status": "UNEVALUATED",
                "detail": f"{rule['field']} absent from the supplied context",
            })
            continue
        try:
            ok = _OPS[rule["op"]](observed, rule["value"])
        except TypeError:
            satisfied = False
            reasons.append({
                "code": rule["code"],
                "status": "UNEVALUATED",
                "detail": f"{rule['field']}={observed!r} is not comparable "
                          f"to {rule['value']!r}",
            })
            continue
        reasons.append({
            "code": rule["code"],
            "status": "SATISFIED" if ok else "VIOLATED",
            "observed": observed,
            "limit": rule["value"],
            "op": rule["op"],
        })
        if not ok:
            satisfied = False
    return satisfied, reasons


def decide(policy, outcomes, context, mode=MODE_OBSERVE):
    """Produce a decision. Never raises for ordinary input.

    A limit that could not be evaluated is not satisfied. That is the whole
    disagreement between this file and the defect class it guards against.
    """
    validate_policy(policy)

    ev = evidence_status(outcomes)
    ev_decision = policy["on_evidence"][ev]

    limits_ok, reasons = evaluate_limits(policy, context)

    if ev_decision != PERMIT:
        decision = ev_decision
    elif limits_ok:
        decision = PERMIT
    else:
        # validate_policy() above guarantees this key exists and is BLOCK
        # or ESCALATE. Indexing rather than .get(..., BLOCK) is deliberate:
        # a default here is exactly the permissive-default shape this file
        # exists to refuse, so if the invariant is ever broken this raises
        # instead of quietly supplying one.
        decision = policy["on_limit_violation"]

    unevaluated = [r for r in reasons if r["status"] == "UNEVALUATED"]

    return {
        "mode": mode,
        "evidence_status": ev,
        "decision": decision,
        "would_block": decision != PERMIT,
        "enforced": mode == MODE_ENFORCE,
        "reasons": reasons,
        "unevaluated_limits": len(unevaluated),
        "checks_run": len(list(outcomes)),
        "policy": {
            "id": policy["id"],
            "version": str(policy["version"]),
            "content_hash": sha256(policy),
        },
    }


def receipt(decision_obj, action, evidence_refs, previous_hash=None,
            signer=None):
    """Build a receipt. Signing is real or it is absent, never implied.

    Holds hashes and identifiers rather than payloads, so a receipt can be
    kept and shown without carrying licensed market data or customer data
    around with it.
    """
    body = {
        "receipt_version": "1.0",
        "action_hash": sha256(action),
        "action_type": action.get("type"),
        "policy": decision_obj["policy"],
        "evidence": evidence_refs,
        "evidence_status": decision_obj["evidence_status"],
        "decision": decision_obj["decision"],
        "mode": decision_obj["mode"],
        "enforced": decision_obj["enforced"],
        "chain": {"previous_receipt_hash": previous_hash},
    }
    body["receipt_hash"] = sha256(body)

    if signer is None:
        # Stated, not omitted. An unsigned receipt that looks signed is the
        # same failure shape as a guard that reports success without running.
        body["signature"] = {"status": "UNSIGNED",
                             "detail": "no signing key supplied"}
        return body

    body["signature"] = signer(_canonical(
        {k: v for k, v in body.items() if k != "signature"}))
    return body


def ed25519_signer(private_key_bytes, key_id):
    """Return a signer closure, or raise if the library is unavailable.

    Deliberately raises rather than falling back to an unsigned receipt.
    """
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey)
    import base64

    key = Ed25519PrivateKey.from_private_bytes(private_key_bytes)

    def sign(payload: bytes):
        return {
            "status": "SIGNED",
            "alg": "Ed25519",
            "key_id": key_id,
            "sig": base64.urlsafe_b64encode(key.sign(payload)).decode(),
        }
    return sign


def verify_receipt(rcpt, public_key_bytes):
    """Independent verification, so a receipt is checkable without us."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PublicKey)
    from cryptography.exceptions import InvalidSignature
    import base64

    sig = rcpt.get("signature") or {}
    if sig.get("status") != "SIGNED":
        return False, "receipt is not signed"

    body = {k: v for k, v in rcpt.items() if k != "signature"}
    try:
        Ed25519PublicKey.from_public_bytes(public_key_bytes).verify(
            base64.urlsafe_b64decode(sig["sig"]), _canonical(body))
    except InvalidSignature:
        return False, "signature does not verify over the receipt body"
    return True, "signature verifies; this establishes provenance, not truth"
