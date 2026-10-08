#!/usr/bin/env python3
"""A consumer for the E6 billing-evidence fixture, written from the artifact.

VeritasActa/e6-fixture v1.0.0 (commit 0770f61) asks a question this suite has
not been able to answer before: it is a named third party handing over a pinned
artifact and requesting a verdict. Every record this project has published so
far was Nobulex checking Nobulex.

INDEPENDENCE, STATED FIRST BECAUSE IT IS THE WHOLE POINT.

This does not call `npx @veritasacta/verify`. Signatures are checked here, with
`cryptography`, against a JCS preimage derived by trying candidate forms until
one verified: the signed bytes are `jcs(receipt["payload"])`, confirmed against
a real signature before any of this was written. So two implementations agree
or they do not, and a disagreement is informative rather than a bug in a
wrapper.

What that still does not establish: the fixture's author wrote the format, the
verifier and the fixture, and says so himself. Agreement between his
implementation and this one means the implementations agree. It says nothing
about whether the receipts describe what happened.

FOUR STATES, NOT THREE.

The fixture distinguishes ABSTAIN from NOT_EVALUATED and the rest of this suite
does not. ABSTAIN is "this was attempted and could not be established".
NOT_EVALUATED is "this was never attempted, because something decisive failed
upstream". harness.py collapses both into INDETERMINATE, which loses the
difference between a check that failed to run and a check that was never
reached. The fixture is right and the suite should follow; this module uses the
four-state model directly rather than mapping it onto the poorer one.

GATING, READ OUT OF THE ELEVEN CASES RATHER THAN GUESSED.

  keys, signatures, scope   always evaluated, never NOT_EVALUATED
  the remaining four        NOT_EVALUATED unless all three above are PASS
  amount                    always NOT_EVALUATED: it is a claim against a
                            contract, and there is no contract here
  decisive                  the claim that CAUSED the verdict, which is not
                            always the first failure. Case 08 has keys FAIL and
                            signatures FAIL and names keys, because wrong keys
                            caused the signature failure. Case 10 has both
                            ABSTAIN and names signatures, because the missing
                            verifier is a signature-checking problem and keys
                            abstains as a consequence.
"""
import hashlib
import json
import os
import sys

PASS, FAIL, ABSTAIN, NOT_EVALUATED = "PASS", "FAIL", "ABSTAIN", "NOT_EVALUATED"

CLAIM_ORDER = ["keys", "signatures", "scope", "coverage_bill_to_receipts",
               "coverage_receipts_to_bill", "uniqueness", "quantities",
               "amount"]
GATES = ("keys", "signatures", "scope")
DOWNSTREAM = ("coverage_bill_to_receipts", "coverage_receipts_to_bill",
              "uniqueness", "quantities")


def jcs(obj):
    """RFC 8785 canonical JSON, to the extent this fixture exercises it.

    Full JCS also pins number formatting and string escaping. These receipts
    carry integers, ISO strings and nested objects, so sorted keys with no
    whitespace is sufficient here and would not be for arbitrary input. Said
    plainly rather than left for someone to discover: this is a JCS subset.
    """
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def sha256_hex(b):
    return "sha256:" + hashlib.sha256(b).hexdigest()


def receipt_hash(receipt):
    """A receipt's ID, which is also the hash the NEXT receipt points at."""
    return sha256_hex(jcs(receipt))


def merkle_root(receipts):
    """RFC 6962 Merkle Tree Hash over the receipt IDs, in sequence order.

    Taken from the fixture README rather than reverse-engineered, after six
    guessed constructions all missed. The spec was written down and I tried to
    derive it from the artifact first, which cost more than reading would have.

      leaf  SHA-256(0x00 || the 32 raw bytes of the ID)
      node  SHA-256(0x01 || left || right)
      split at the largest power of two below the count, not pairwise from the
      left, which is the part the guesses got wrong
    """
    ids = [bytes.fromhex(receipt_hash(r).split(":")[1]) for r in receipts]

    def mth(xs):
        if len(xs) == 1:
            return hashlib.sha256(b"\x00" + xs[0]).digest()
        k = 1
        while k * 2 < len(xs):
            k *= 2
        return hashlib.sha256(b"\x01" + mth(xs[:k]) + mth(xs[k:])).digest()

    return "sha256:" + mth(ids).hex() if ids else None


def read_jsonl(path):
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def _seq(receipt):
    return receipt.get("payload", receipt).get("sequence")


# ----------------------------------------------------------------- the claims

def claim_keys(keys_doc, receipts, root_fingerprint):
    """Are the signing keys the ones this engagement is supposed to use?"""
    codes = []
    known = {k.get("kid"): k for k in keys_doc.get("keys", [])}
    if not known:
        return ABSTAIN, ["no_keys_supplied"]

    root = keys_doc.get("root", {})
    if root_fingerprint and root.get("fingerprint") != root_fingerprint:
        codes.append("root_fingerprint_mismatch")

    used = {r.get("signature", {}).get("kid") for r in receipts}
    for kid in sorted(k for k in used if k not in known):
        codes.append("unexpected_signer")
        break

    return (FAIL if codes else PASS), codes


def claim_signatures(keys_doc, receipts, verifier_available, manifest=None):
    """Ed25519 over jcs(payload), checked here rather than by their verifier."""
    if not verifier_available:
        # A missing verifier is not a pass and not a failure. Scoring it either
        # way is the defect this suite was corrected for a fortnight ago.
        return ABSTAIN, ["verifier_unavailable"]
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PublicKey)
        from cryptography.exceptions import InvalidSignature
    except ImportError:
        return ABSTAIN, ["verifier_unavailable"]

    pubs = {}
    for k in keys_doc.get("keys", []):
        hexkey = k.get("public_key_hex")
        if k.get("kid") and hexkey:
            try:
                pubs[k["kid"]] = Ed25519PublicKey.from_public_bytes(
                    bytes.fromhex(hexkey))
            except Exception:
                pass

    codes, bad = [], 0

    def check(obj, label):
        nonlocal bad
        sig = obj.get("signature", {})
        ok = False
        for kid, pub in pubs.items():
            if sig.get("kid") not in (None, kid) and len(pubs) > 1:
                pass
            try:
                pub.verify(bytes.fromhex(sig.get("sig", "")), jcs(obj["payload"]))
                ok = True
                break
            except Exception:
                continue
        if not ok:
            bad += 1
            if label not in codes:
                codes.append(label)

    for r in receipts:
        check(r, "invalid_signature")

    prev = None
    for r in receipts:
        stated = r.get("payload", {}).get("previousReceiptHash")
        if prev is not None and stated != prev:
            if "chain_break" not in codes:
                codes.append("chain_break")
                bad += 1
            break
        prev = receipt_hash(r)

    if manifest is not None:
        check(manifest, "manifest_signature_invalid")

    return (FAIL if bad else PASS), codes


def claim_scope(manifest, receipts, period_of_bill):
    """Does the supplied export match the manifest that fixed the period?

    This is the claim the fixture exists to make, and the one a consumer
    without the manifest cannot answer at all. A tail-truncated export links
    perfectly end to end; only a reference the producer does not control shows
    a receipt is missing. The same fact has turned up three times in a month,
    in three unrelated formats.
    """
    rng = manifest.get("payload", {}).get("range", {})
    pay = manifest.get("payload", {})
    codes = []

    if rng.get("outcome_receipts") != len(receipts):
        codes.append("count_mismatch")

    seqs = [s for s in (_seq(r) for r in receipts) if s is not None]
    if seqs:
        if rng.get("first_sequence") != min(seqs):
            codes.append("first_sequence_mismatch")
        if rng.get("last_sequence") != max(seqs):
            codes.append("sequence_mismatch")
    else:
        codes.append("no_readable_sequences")

    # Two different preimages, and assuming one was my first bug here. The
    # SIGNATURE is over jcs(payload). The CHAIN HASH is over jcs(whole
    # receipt), signature included, so the chain links signed receipts rather
    # than their contents. Confirmed against the manifest head before this
    # line was written, not inferred from the spec name.
    if receipts:
        head = receipt_hash(receipts[-1])
        declared = rng.get("head")
        if declared and head != declared:
            codes.append("head_mismatch")

        # Linkage, which the head check alone does not give. A chain can end
        # at the right head and still be broken in the middle.
        declared_root = rng.get("root")
        if declared_root and merkle_root(receipts) != declared_root:
            codes.append("root_mismatch")



    bill_period = period_of_bill
    man_period = (pay.get("period") or {}).get("id")
    if bill_period and man_period and bill_period != man_period:
        codes.append("period_mismatch")

    return (FAIL if codes else PASS), codes


def claim_scope_binding(manifest, bill):
    """Does the bill name THIS manifest, or a different one?

    A bill carries a hash of the period statement it was cut from. Case 06
    supplies the real August manifest and a bill naming the July statement, so
    every other check passes and the bill is still cut from a period nobody
    supplied evidence for. Checking the export against the manifest while never
    checking that the bill refers to that manifest leaves the join unverified.
    """
    named = bill.get("manifest")
    if not named:
        return []
    return [] if named == sha256_hex(jcs(manifest)) else ["manifest_mismatch"]


def _billed_ids(bill):
    out = []
    for line in bill.get("lines", []):
        out.extend(line.get("receipts", []) or [])
    return out


def _receipt_ids(receipts):
    """A receipt's id IS its chain hash: sha256 over jcs of the whole receipt.

    Derived by comparing a bill line's named ids against candidate hashes until
    one matched, not assumed from the field name. The first guess here was a
    `receipt_id` field, which does not exist, falling back to a hash of the
    payload, which is the SIGNATURE preimage and a different value. That made
    every coverage claim fail against a correct bill.
    """
    return [receipt_hash(r) for r in receipts]


def claim_coverage_bill_to_receipts(bill, receipts):
    """Every receipt a line bills must exist in the export."""
    have = set(_receipt_ids(receipts))
    missing = [i for i in _billed_ids(bill) if i not in have]
    return (FAIL, ["unknown_receipt"]) if missing else (PASS, [])


def claim_coverage_receipts_to_bill(bill, receipts):
    """EVERY receipt must be billed or explicitly excluded, with a reason.

    Not "every billable receipt is billed", which was the first rule here and
    is a weaker claim that case 05 walks straight through. A bill that simply
    omits a receipt it does not want to mention is indistinguishable, under
    that rule, from a bill that correctly left out a non-billable one. The
    exclusions block is what makes the omission a statement someone made rather
    than a silence, and silence is the thing this claim exists to refuse.

    Case 04 is the control in the other direction: a second bill that bills one
    receipt and explicitly excludes all fifty others passes this claim, because
    nothing was left unaccounted for. Its failure belongs to uniqueness.
    """
    billed = set(_billed_ids(bill))
    excluded = {e.get("receipt") for e in bill.get("exclusions", []) or []}
    unaccounted = [rid for rid in _receipt_ids(receipts)
                   if rid not in billed and rid not in excluded]
    return ((FAIL, ["unaccounted_receipt"])
            if unaccounted else (PASS, []))


def claim_uniqueness(bill, earlier_bills):
    """No receipt billed twice: not across lines, not against an earlier bill."""
    codes = []
    ids = _billed_ids(bill)
    if len(ids) != len(set(ids)):
        codes.append("listed_twice_in_bill")
    seen_before = set()
    for eb in earlier_bills or []:
        seen_before.update(_billed_ids(eb))
    if seen_before & set(ids):
        codes.append("billed_on_earlier_bill")
    return (FAIL if codes else PASS), codes


def claim_quantities(bill):
    """A line's quantity must equal the number of receipts it names."""
    for line in bill.get("lines", []):
        named = line.get("receipts")
        if named is None:
            continue
        if line.get("quantity") != len(named):
            return FAIL, ["quantity_mismatch"]
    return PASS, []


# ------------------------------------------------------------------- the run

def evaluate(receipts, manifest, bill, keys_doc, earlier_bills=None,
             root_fingerprint=None, verifier_available=True):
    claims, codes = {}, {}

    def put(name, result):
        claims[name], c = result[0], result[1]
        if c:
            codes[name] = c

    put("signatures", claim_signatures(keys_doc, receipts,
                                       verifier_available, manifest))
    if claims["signatures"] == ABSTAIN and \
            "verifier_unavailable" in codes.get("signatures", []):
        # Without a verifier the keys cannot be established either: a key
        # document is only confirmed by the signatures it validates. Asserting
        # the keys are right while unable to check anything with them is the
        # shape of overclaim this whole fixture is testing for.
        put("keys", (ABSTAIN, ["verifier_unavailable"]))
    else:
        put("keys", claim_keys(keys_doc, receipts, root_fingerprint))
    scope_result = claim_scope(manifest, receipts,
                               (bill.get("period") or {}).get("id")
                               if isinstance(bill.get("period"), dict)
                               else bill.get("period"))
    binding = claim_scope_binding(manifest, bill)
    if binding:
        scope_result = (FAIL, list(scope_result[1]) + binding)
    put("scope", scope_result)

    if all(claims[g] == PASS for g in GATES):
        put("coverage_bill_to_receipts",
            claim_coverage_bill_to_receipts(bill, receipts))
        put("coverage_receipts_to_bill",
            claim_coverage_receipts_to_bill(bill, receipts))
        put("uniqueness", claim_uniqueness(bill, earlier_bills))
        put("quantities", claim_quantities(bill))
    else:
        for name in DOWNSTREAM:
            claims[name] = NOT_EVALUATED

    # No contract is supplied, so price and amount are not a claim this
    # evidence can reach. Saying NOT_EVALUATED rather than PASS is the whole
    # discipline in one field.
    claims["amount"] = NOT_EVALUATED

    decisive = _decisive(claims, codes)
    if any(v == FAIL for v in claims.values()):
        verdict = FAIL
    elif any(v == ABSTAIN for v in claims.values()):
        verdict = ABSTAIN
    else:
        verdict = PASS

    return {"verdict": verdict, "decisive": decisive, "claims": claims,
            "codes": codes,
            # An evidence verdict is not authority to pay. Separate on purpose.
            "payment_ready": False}


def _decisive(claims, codes):
    """The claim that CAUSED the verdict, which is not always the first one.

    Case 08 fails keys and signatures and names keys, because the wrong signer
    caused the signature failure. Case 10 abstains on both and names
    signatures, because the missing verifier is a signature problem and keys
    abstains downstream of it.
    """
    if claims.get("signatures") == ABSTAIN and \
            "verifier_unavailable" in codes.get("signatures", []):
        return ["signatures"]
    for name in CLAIM_ORDER:
        if claims.get(name) in (FAIL, ABSTAIN):
            return [name]
    return []


# --------------------------------------------------------------- fixture run

def run_case(root, case_dir):
    """Run one fixture case, resolving its declared inputs."""
    spec = json.load(open(os.path.join(case_dir, "case.json"), encoding="utf-8"))
    inp = spec["inputs"]

    def resolve(rel):
        return os.path.normpath(os.path.join(case_dir, rel))

    receipts = read_jsonl(resolve(inp["receipts"]))
    manifest = json.load(open(resolve(inp["manifest"]), encoding="utf-8"))
    bill = json.load(open(resolve(inp["bill"]), encoding="utf-8"))
    keys_doc = json.load(open(resolve(inp["keys"]), encoding="utf-8"))
    earlier = [json.load(open(resolve(p), encoding="utf-8"))
               for p in inp.get("earlier_bills", [])]

    got = evaluate(receipts, manifest, bill, keys_doc, earlier,
                   root_fingerprint=inp.get("root_fingerprint"),
                   verifier_available=inp.get("verifier") != "unavailable")
    return spec, got


def main(root):
    cases_dir = os.path.join(root, "cases")
    agree = disagree = 0
    for name in sorted(os.listdir(cases_dir)):
        spec, got = run_case(root, os.path.join(cases_dir, name))
        exp = spec["expected"]
        diffs = [f"{k}: expected {exp['claims'][k]}, got {got['claims'][k]}"
                 for k in CLAIM_ORDER if exp["claims"][k] != got["claims"][k]]
        if exp["verdict"] != got["verdict"]:
            diffs.insert(0, f"verdict: expected {exp['verdict']}, "
                            f"got {got['verdict']}")

        for k in CLAIM_ORDER:
            want = set(exp.get("codes", {}).get(k, []))
            mine = set(got.get("codes", {}).get(k, []))
            if want - mine:
                diffs.append(f"{k} codes: missing {sorted(want - mine)}")
            if mine - want:
                diffs.append(f"{k} codes: extra {sorted(mine - want)}")
        if diffs:
            disagree += 1
            print(f"  DISAGREE  {name}")
            for d in diffs:
                print(f"              {d}")
        else:
            agree += 1
            print(f"  agree     {name}  {got['verdict']}"
                  f"{' decisive=' + got['decisive'][0] if got['decisive'] else ''}")
    print(f"\n  {agree} agree, {disagree} disagree, of {agree + disagree} cases")
    return 0 if disagree == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "."))
