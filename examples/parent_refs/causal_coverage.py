"""Bounded causal-coverage verifier for the parent_refs fixture.

This checks the supplied signed records, not whether they represent every
action that happened in the world. COMPLETE means every referenced parent in
this supplied graph was verified and traced to a root within the limits.
"""

from __future__ import annotations

from build_fixture import verify


def reconstruct(records, head_ref, key, *, fan_in_supported=True,
                max_ancestors=256, max_depth=32):
    """Return COMPLETE, INCOMPLETE, or REFUSED with an in-band reason.

    INCOMPLETE never means a valid complete history. The caller must not
    present it as a chain reconstructed to its root.
    """
    if not isinstance(records, dict) or not isinstance(head_ref, str):
        return {"status": "REFUSED", "reason": "invalid_input"}
    if not isinstance(fan_in_supported, bool):
        return {"status": "REFUSED", "reason": "invalid_mode"}
    if (type(max_ancestors) is not int or max_ancestors < 0 or
            type(max_depth) is not int or max_depth < 0):
        return {"status": "REFUSED", "reason": "invalid_limits"}

    active = set()
    visited = set()
    roots = set()

    def walk(ref, depth):
        if depth > max_depth:
            return "INCOMPLETE", "depth_limit"
        if ref in active:
            return "REFUSED", "cycle"
        if ref in visited:
            return None
        if depth > 0 and len(visited - {head_ref}) >= max_ancestors:
            return "INCOMPLETE", "ancestor_limit"
        obj = records.get(ref)
        if obj is None:
            return "INCOMPLETE", "missing_parent"
        ok, why = verify(obj, key)
        if not ok:
            return "REFUSED", f"invalid_receipt: {why}"
        if obj.get("action_ref") != ref:
            return "REFUSED", "action_ref_mismatch"
        parents = obj["parent_refs"]
        if len(parents) > 1 and not fan_in_supported:
            return "INCOMPLETE", "fan_in_unsupported"

        active.add(ref)
        visited.add(ref)
        if not parents:
            roots.add(ref)
        for parent in parents:
            problem = walk(parent, depth + 1)
            if problem is not None:
                return problem
        active.remove(ref)
        return None

    problem = walk(head_ref, 0)
    if problem is not None:
        status, reason = problem
        return {"status": status, "reason": reason,
                "visited": len(visited)}
    return {"status": "COMPLETE", "reason": "all_branches_to_roots",
            "roots": sorted(roots, key=lambda s: s.encode("utf-8")),
            "visited": len(visited)}
