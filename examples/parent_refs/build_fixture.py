#!/usr/bin/env python3
"""parent_refs fan-in fixture: real signed artifacts, not a spec snippet.

    python3 examples/parent_refs/build_fixture.py

Promised in OWASP/www-project-agentic-skills-top-10#44 on 10 Sept 2026:
implement `parent_refs` as a canonicalized array, sorted ascending as UTF-8
byte strings and deduplicated, with a 64-parent fan-in cap enforced at
CONSTRUCTION time so a receipt exceeding it is never signed in the first
place, rather than merely rejected at verification. Published as actual
signed objects so the cap-exceeded case is a real rejected artifact and not
documented behaviour.

Writes to examples/parent_refs/vectors/ and verifies every artifact it
writes before exiting. Exits nonzero if any expectation fails.

WHAT IS AND IS NOT RFC 8785 HERE, STATED RATHER THAN IMPLIED

The sort rule for `parent_refs` is the one proposed in the thread and it is
implemented exactly: UTF-8 byte strings, ascending, deduplicated. That is
this file's own rule and it is fully tested below, including against inputs
where byte order and Python's default string order disagree.

The whole-object serialization reuses the suite's `_canonical`, which is
`json.dumps(sort_keys=True, separators=(",",":"), ensure_ascii=False)` over
UTF-8. That agrees with RFC 8785 for every value in these fixtures, and the
test at the bottom checks the properties that matter here: stable key order,
no insignificant whitespace, UTF-8 output, and byte-identical output across
runs and across dict insertion orders.

It is NOT a general RFC 8785 implementation and this file does not claim to
be one. Two known divergences, neither reachable by these fixtures:

  - JCS orders object keys by UTF-16 code unit; Python's sort_keys orders by
    Unicode code point. These differ only for keys containing characters
    above the BMP. Every key here is ASCII.
  - JCS pins number serialization to ECMAScript Number::toString. Python's
    repr agrees for the integers used here and can differ for some floats.
    No float appears in any fixture.

Anyone adopting this for arbitrary payloads needs a real JCS library. Said
here because a fixture published into a spec discussion that silently
approximated the spec would be the exact failure this project exists to name.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "gateway"))
sys.path.insert(0, str(ROOT / "suite"))

from decide import _canonical, sha256  # noqa: E402

OUT = Path(__file__).resolve().parent / "vectors"

# The cap proposed in the thread. Enforced at construction, below.
MAX_PARENTS = 64


class FanInCapExceeded(ValueError):
    """Raised at construction. A receipt over the cap is never signed.

    This is the whole point of the cap living here rather than in a
    verifier. A verifier-side cap still lets an over-cap object exist as a
    signed artifact that some other verifier, or an older one, may accept.
    Refusing before the signature means the object a producer could hand
    anyone was never valid to begin with.
    """


def canonical_parent_refs(refs):
    """Dedupe, then sort ascending as UTF-8 byte strings.

    Byte order, not Python's default str order. They agree across ASCII and
    diverge above it, so the rule is implemented on the bytes the spec names
    rather than on whatever ordering the host language happens to give.
    """
    if not all(isinstance(r, str) for r in refs):
        raise TypeError("every parent ref must be a string")
    unique = set(refs)
    ordered = sorted(unique, key=lambda s: s.encode("utf-8"))
    if len(ordered) > MAX_PARENTS:
        raise FanInCapExceeded(
            f"{len(ordered)} distinct parent refs exceeds the {MAX_PARENTS} "
            f"cap; this object is refused before signing, so no signed "
            f"artifact with this fan-in exists")
    return ordered


def build_receipt(action_ref, parent_refs, signer=None):
    """A receipt whose parentage is inside the signed preimage.

    parent_refs sits in the signed body deliberately. Outside it, parentage
    is rewritable after the fact: a runtime could relabel which upstream
    triggered an execution without invalidating any identifier. Inside, the
    causal claim is as tamper-evident as the rest of the record.
    """
    body = {
        "receipt_version": "parent-refs-fixture-2",
        "action_ref": action_ref,
        "parent_refs": canonical_parent_refs(parent_refs),
    }
    if signer is None:
        body["signature"] = {"status": "UNSIGNED",
                             "detail": "no signing key supplied"}
        body["preimage_sha256"] = sha256(body)
        return body
    # The signature METADATA goes into the body before the preimage is
    # computed, so alg, key_id and public_key are covered by the signature.
    # In fixture-1 they sat outside it and were freely editable: swapping
    # public_key to an attacker value and alg to "none" left verify()
    # returning ok. Only `sig` itself is added afterwards, because a
    # signature cannot cover itself.
    body["signature"] = dict(signer.meta)
    body["preimage_sha256"] = sha256(body)
    body["signature"]["sig"] = signer(_canonical(body))
    return body


def adversarial_build_receipt(action_ref, parent_refs, signer):
    """Build and sign an over-cap receipt, the way an attacker would.

    This deliberately does NOT call canonical_parent_refs, so the cap never
    fires. It exists because the constructor-side cap proves only that a
    CONFORMING producer will not emit an over-cap object. It says nothing
    about an attacker, who does not use our constructor and has no reason
    to honour a limit that lives in it.

    The sort and dedupe rules are still applied, so the resulting object is
    well-formed in every respect except the one under test. An artifact
    that failed two rules at once would not isolate which one the verifier
    caught it on.
    """
    unique = sorted(set(parent_refs), key=lambda s: s.encode("utf-8"))
    return adversarial_sign({
        "receipt_version": "parent-refs-fixture-2",
        "action_ref": action_ref,
        "parent_refs": unique,
    }, signer)


def adversarial_sign(body, signer):
    """Sign an arbitrary body, applying no rule whatsoever.

    The generic form of adversarial_build_receipt. An attacker's producer is
    just this: a signing key and no constraints. Every structural rule the
    verifier claims to enforce gets a vector built through here, because a
    rule only checked in the constructor is not enforced at all.
    """
    body = dict(body)
    body["signature"] = dict(signer.meta)
    body["preimage_sha256"] = sha256(body)
    body["signature"]["sig"] = signer(_canonical(body))
    return body


def _signer():
    """Ed25519 over the canonical preimage, or None if unavailable."""
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PrivateKey)
    except ImportError:
        return None, None
    import base64
    # Fixed seed so the artifacts are reproducible byte for byte. This key
    # signs fixtures and nothing else; it is published with them on purpose.
    key = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    pub = base64.urlsafe_b64encode(key.public_key().public_bytes_raw()).decode()

    def sign(preimage: bytes):
        """Return only the signature value. Metadata is sign.meta."""
        return base64.urlsafe_b64encode(key.sign(preimage)).decode()

    # Static, and placed in the body BEFORE the preimage is computed so it is
    # signed over. public_key is carried for provenance only; verify() below
    # refuses to resolve a key from it, which is the property the negative
    # vectors in ScopeBlind #24 exist to pin.
    sign.meta = {"status": "SIGNED", "alg": "Ed25519", "key_id": "fixture-1",
                 "public_key": pub}
    return sign, key


def check_parent_refs(refs):
    """Every structural rule, re-checked from scratch. Returns None or why.

    This exists because fixture-1 enforced all of these in the CONSTRUCTOR
    and none of them in the verifier. A reviewer on AST09 #44 pointed out
    that a constructor-side cap binds conforming producers only, which was
    correct; the fix added a verifier cap and stopped there, reproducing the
    identical error on four other rules. An audit then walked through the
    door: unsorted, duplicated, non-string and absent parent_refs all
    verified `ok`, and 1000 refs nested inside one list element passed the
    cap because len() saw a single slot.

    So the rule here is not "check the cap too". It is that a verifier
    re-derives every property it depends on, from the object in front of it,
    trusting no producer. Each rule below is one an attacker's producer
    would simply not apply.
    """
    if refs is None:
        return "parent_refs absent; the field is required, and its absence " \
               "is not the same claim as an empty list"
    if not isinstance(refs, list):
        return f"parent_refs is {type(refs).__name__}, not a list"
    for i, r in enumerate(refs):
        if not isinstance(r, str):
            # The nesting bypass lived here. A list inside the list is one
            # slot to len() and any number of parents to a reader.
            return (f"parent_refs[{i}] is {type(r).__name__}, not a string; "
                    f"a nested container would let len() undercount the "
                    f"real fan-in")
    if len(refs) > MAX_PARENTS:
        return f"fan_in_cap_exceeded: {len(refs)} parents, cap is {MAX_PARENTS}"
    if len(set(refs)) != len(refs):
        return "parent_refs contains duplicates"
    if refs != sorted(refs, key=lambda s: s.encode("utf-8")):
        return "parent_refs is not sorted ascending as UTF-8 byte strings"
    return None


def verify(obj, key, embedded_key_is_untrusted=True):
    """Check signature and structure. Returns (ok, why). Never raises.

    `key` is supplied by the caller, out of band, always. The object may
    carry a public_key for provenance and this function will not resolve
    one from it: a signature that verifies under a key the object supplied
    proves only that one party wrote both halves. That is the property
    ScopeBlind's negative vectors pin, and publishing a fixture that
    violated it while contributing those vectors would have been absurd.
    """
    if not isinstance(obj, dict):
        return False, f"receipt is {type(obj).__name__}, not an object"
    sig_block = obj.get("signature")
    if not isinstance(sig_block, dict):
        return False, "signature block missing or not an object"
    if sig_block.get("status") != "SIGNED":
        return False, "unsigned"
    if sig_block.get("alg") != "Ed25519":
        return False, f"unsupported alg {sig_block.get('alg')!r}"
    import base64

    # Rebuild exactly what was signed: everything except `sig`, which cannot
    # cover itself. alg, key_id and public_key ARE inside, so swapping them
    # now breaks the signature rather than going unnoticed.
    body = {k: v for k, v in obj.items() if k != "signature"}
    meta = {k: v for k, v in sig_block.items() if k != "sig"}
    body["signature"] = meta
    stated = body.pop("preimage_sha256", None)
    if sha256(body) != stated:
        return False, "preimage_sha256 does not match the body"
    body["preimage_sha256"] = stated
    try:
        key.public_key().verify(
            base64.urlsafe_b64decode(sig_block.get("sig") or ""),
            _canonical(body))
    except Exception:
        return False, "signature does not verify"

    if embedded_key_is_untrusted and sig_block.get("public_key"):
        # Present, signed over, and deliberately not used to verify anything.
        pass

    # Structure is checked AFTER the signature so that reaching here proves
    # the signature was cryptographically valid. An object refused below was
    # signed correctly by someone holding the key and is still rejected,
    # which is the entire claim. Checking structure first would leave "was
    # the signature even good?" unanswered.
    # Wrapped, because "returns a verdict, never raises" must hold even if
    # check_parent_refs itself has a gap. Found by mutation: disabling the
    # string-type check let a nested list reach `set(refs)`, which raises
    # TypeError on an unhashable element. The guard ordering happened to
    # prevent it, which is not the same as the contract holding. A verifier
    # that raises on hostile input hands the attacker a crash instead of a
    # rejection, and a harness looping over receipts dies mid-batch.
    try:
        why = check_parent_refs(obj.get("parent_refs"))
    except Exception as e:  # noqa: BLE001
        return False, f"parent_refs could not be checked: {type(e).__name__}"
    if why:
        return False, why
    return True, "ok"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    sign, key = _signer()
    if sign is None:
        print("cryptography is not installed, so nothing here can be signed.")
        print("Refusing to write unsigned artifacts described as signed.")
        return 2

    failures = []

    def check(label, got, want):
        if got != want:
            failures.append(f"{label}: got {got!r}, want {want!r}")
            print(f"  FAIL  {label}")
        else:
            print(f"  ok    {label}")

    print("Sort rule: UTF-8 bytes ascending, deduplicated\n")
    check("duplicates collapse",
          canonical_parent_refs(["a", "a", "b"]), ["a", "b"])
    check("ascending by byte, not by insertion",
          canonical_parent_refs(["b", "a"]), ["a", "b"])
    # 'Z' is 0x5A, 'a' is 0x61. Byte order puts 'Z' first. A case-insensitive
    # or locale-aware sort would not, which is why the rule names bytes.
    check("uppercase sorts before lowercase, as bytes do",
          canonical_parent_refs(["a", "Z"]), ["Z", "a"])
    # U+00E9 encodes to two bytes, 0xC3 0xA9, so it sorts after any ASCII.
    check("non-ASCII sorts by its UTF-8 encoding",
          canonical_parent_refs(["é", "z"]), ["z", "é"])

    print("\nThe cap is enforced at construction, before signing\n")
    at_cap = [f"sha256:{i:064x}" for i in range(MAX_PARENTS)]
    over_cap = [f"sha256:{i:064x}" for i in range(MAX_PARENTS + 1)]
    check("exactly at the cap is accepted",
          len(canonical_parent_refs(at_cap)), MAX_PARENTS)
    try:
        build_receipt("sha256:child", over_cap, sign)
        failures.append("an over-cap receipt was built")
        print("  FAIL  one over the cap refuses to build")
    except FanInCapExceeded:
        print("  ok    one over the cap refuses to build")
    # The claim is not merely that it raises. It is that no signed artifact
    # exists FROM A CONFORMING PRODUCER, which is what the raise is for.
    # This used to assert that a file named 04-fan-in-cap-exceeded.json did
    # not exist. Nothing ever writes that name (the refusal record is
    # ...REFUSAL.json), so it passed unconditionally and would have passed
    # just as happily if an over-cap object HAD been signed and written. A
    # test that cannot fail, in a file arguing that tests must be able to
    # fail. It now asserts the thing actually meant: no artifact this
    # producer emits carries more than the cap.
    def _parents(p):
        try:
            return len(json.loads(p.read_text()).get("parent_refs") or [])
        except Exception:
            return 0
    emitted = [p for p in OUT.glob("*.json") if "ADVERSARIAL" not in p.name]
    check("and no artifact this producer emitted is over the cap",
          max([_parents(p) for p in emitted] or [0]) <= MAX_PARENTS, True)

    print("\nBut a conforming producer is not the threat model\n")
    # Raised in review on AST09 #44: the constructor cap binds only
    # producers who use this constructor. An attacker writes their own.
    # Until the verifier refuses an already-signed over-cap object, the
    # cap is a coding convention, not a property of the format.
    adv = adversarial_build_receipt("sha256:" + "44" * 32, over_cap, sign)
    check("an attacker can build and sign 65 parents anyway",
          len(adv["parent_refs"]), MAX_PARENTS + 1)

    # The signature on it is genuinely valid. Proven by checking it directly,
    # so "rejected" cannot be confused with "malformed". The preimage is
    # rebuilt exactly as verify() rebuilds it: everything except `sig`,
    # signature metadata included, since that metadata is now signed over.
    import base64 as _b64
    _body = {k: v for k, v in adv.items() if k != "signature"}
    _body["signature"] = {k: v for k, v in adv["signature"].items()
                          if k != "sig"}
    _stated = _body.pop("preimage_sha256")
    _body["preimage_sha256"] = _stated
    try:
        key.public_key().verify(
            _b64.urlsafe_b64decode(adv["signature"]["sig"]),
            _canonical(_body))
        sig_ok = True
    except Exception:
        sig_ok = False
    check("and its signature is cryptographically valid", sig_ok, True)

    ok, why = verify(adv, key)
    check("yet the verifier refuses it", ok, False)
    check("and refuses it for the cap, not for a bad signature",
          why.startswith("fan_in_cap_exceeded"), True)

    (OUT / "05-fan-in-cap-exceeded.SIGNED-ADVERSARIAL.json").write_text(
        json.dumps(adv, indent=2) + "\n")

    print("\nEvery other construction rule, attacked the same way\n")
    # An audit of the previous version walked straight through all of these.
    # Each was enforced in the constructor and unchecked in the verifier,
    # which is the identical error the reviewer had already named once about
    # the cap. Fixing only the instance you are shown reproduces the class.
    ok3 = "sha256:" + "aa" * 32
    attacks = [
        ("nested", [[f"sha256:{i:064x}" for i in range(1000)]],
         "not a string", "1000 parents hidden in one list slot"),
        ("unsorted", ["sha256:zzz", "sha256:aaa"],
         "not sorted", "byte order violated"),
        ("duplicated", [ok3, ok3, ok3],
         "duplicates", "same parent claimed three times"),
        ("non-string", [1, 2, 3],
         "not a string", "integers where refs belong"),
        ("wrong-type", "sha256:abc",
         "not a list", "a bare string counted by character"),
    ]
    for name, refs, expect, why_it_matters in attacks:
        o = adversarial_sign({"receipt_version": "parent-refs-fixture-2",
                              "action_ref": "sha256:" + "55" * 32,
                              "parent_refs": refs}, sign)
        ok, why = verify(o, key)
        check(f"{name}: refused ({why_it_matters})", ok, False)
        check(f"{name}: and for the right reason", expect in why, True)

    # Absent is its own case: the field is required, and its absence is a
    # different claim from an empty list. Both must be decidable.
    o = adversarial_sign({"receipt_version": "parent-refs-fixture-2",
                          "action_ref": "sha256:" + "66" * 32}, sign)
    ok, why = verify(o, key)
    check("absent parent_refs is refused, not treated as zero parents",
          (ok, "absent" in why), (False, True))

    print("\nThe signature block is inside the preimage now\n")
    # fixture-1 signed the body and left alg, key_id and public_key outside
    # it. Swapping public_key to an attacker value and alg to "none" left
    # verify() returning ok, on an artifact that advertises an embedded key.
    # That is exactly what ScopeBlind #24's negative vectors forbid, and it
    # was published here while contributing those vectors.
    tampered = json.loads(json.dumps(
        build_receipt("sha256:" + "77" * 32, [ok3], sign)))
    check("baseline verifies", verify(tampered, key)[0], True)
    tampered["signature"]["public_key"] = "ATTACKER-CONTROLLED"
    ok, why = verify(tampered, key)
    # Caught by the preimage comparison, which runs first, rather than by the
    # signature check. Either would be correct; what matters is that it is
    # caught at all. In fixture-1 it was caught by neither and returned ok.
    check("swapping the embedded public_key is detected",
          (ok, "preimage_sha256" in why or "signature does not verify" in why),
          (False, True))
    tampered2 = json.loads(json.dumps(
        build_receipt("sha256:" + "88" * 32, [ok3], sign)))
    tampered2["signature"]["alg"] = "none"
    ok2, why2 = verify(tampered2, key)
    check("and so does downgrading alg to none", ok2, False)

    print("\nverify() returns, it does not raise\n")
    # A harness looping over untrusted receipts must get a verdict, not a
    # traceback. parent_refs: 5 used to raise TypeError out of len().
    for bad in (5, None, {"a": 1}, True):
        o = adversarial_sign({"receipt_version": "parent-refs-fixture-2",
                              "action_ref": "sha256:" + "99" * 32,
                              "parent_refs": bad}, sign)
        try:
            ok, why = verify(o, key)
            check(f"parent_refs={bad!r} returns a verdict", ok, False)
        except Exception as e:
            check(f"parent_refs={bad!r} returns a verdict",
                  f"RAISED {type(e).__name__}", False)

    print("\nArtifacts\n")
    vectors = [
        ("01-single-parent.json", "sha256:" + "11" * 32, ["sha256:" + "aa" * 32]),
        ("02-fan-in-three.json", "sha256:" + "22" * 32,
         ["sha256:" + "cc" * 32, "sha256:" + "aa" * 32, "sha256:" + "bb" * 32]),
        ("03-fan-in-at-cap.json", "sha256:" + "33" * 32, at_cap),
    ]
    for name, action_ref, parents in vectors:
        r = build_receipt(action_ref, parents, sign)
        ok, why = verify(r, key)
        check(f"{name} verifies", (ok, why), (True, "ok"))
        (OUT / name).write_text(json.dumps(r, indent=2) + "\n")

    # Determinism: the same inputs in a different order must produce the same
    # bytes, or the fixture is not a fixture.
    a = build_receipt("sha256:x", ["sha256:b", "sha256:a"], sign)
    b = build_receipt("sha256:x", ["sha256:a", "sha256:b", "sha256:a"], sign)
    check("shuffled and duplicated input yields byte-identical output",
          _canonical(a), _canonical(b))

    # Tamper: reordering parent_refs after signing must break the signature,
    # which is the property that makes parentage tamper-evident at all.
    t = json.loads(json.dumps(a))
    t["parent_refs"] = list(reversed(t["parent_refs"]))
    ok, _ = verify(t, key)
    check("reordering parent_refs after signing breaks verification", ok, False)

    rejected = {
        "note": "There is deliberately no signed artifact for the over-cap "
                "case. The cap is enforced at construction, so the object "
                "below was refused before a signature existed. This file "
                "records the refusal; it is not a receipt.",
        "attempted_parent_count": len(over_cap),
        "cap": MAX_PARENTS,
        "error": "FanInCapExceeded",
        "why_not_verifier_side": "A verifier-side cap still permits a signed "
                                 "over-cap object to exist, which a different "
                                 "or older verifier may accept. Refusing "
                                 "before signing means it never existed.",
    }
    (OUT / "04-fan-in-cap-exceeded.REFUSAL.json").write_text(
        json.dumps(rejected, indent=2) + "\n")
    print(f"  ok    refusal record written, and it is not a receipt")

    print()
    for p in sorted(OUT.iterdir()):
        print(f"  {p.relative_to(ROOT)}  ({p.stat().st_size} bytes)")

    print()
    if failures:
        print(f"{len(failures)} failed:")
        for f in failures:
            print("  " + f)
        return 1
    print("every artifact written was verified after writing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
