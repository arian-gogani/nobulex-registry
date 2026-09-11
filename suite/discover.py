#!/usr/bin/env python3
"""Propose which tools to probe, from what the server says about itself.

Connecting a subject currently costs seven flags, and two of them are the
expensive ones: --tool-history and --tool-info require a human to read the
server's documentation, work out which tool returns price bars and which
returns company identity, and type the names exactly. That is the step where
onboarding dies. It is also unnecessary, because the server already answers
the question.

MCP's tools/list returns a name, a description and an inputSchema for every
tool. run.py asks for that list and keeps only the names (run.py:411), which
throws away the two fields that identify what each tool is for. This reads all
three and proposes a mapping.

What this is not: it does not decide. It scores every tool, prints the reasoning,
and proposes. A human confirms. The difference matters because a wrong mapping
does not produce a wrong verdict, it produces a verdict about the wrong tool,
which is worse: every downstream probe is sound and the whole record is about
something nobody asked about.

So this refuses in two situations rather than guessing:

  - no candidate scores above the floor, meaning nothing here looks like the
    tool we need, and the honest answer is that this server may not be in scope
  - the top two candidates are within MARGIN of each other, meaning the server
    has two plausible tools and picking one by a hair is a coin flip wearing a
    number

Both print what they saw and exit non-zero. An ambiguous proposal that a human
rubber-stamps is worse than no proposal, because it launders a guess into a
confirmation.
"""
import json
import re
import sys

# Scored against name, description and parameter names, in that order of
# weight. A name is a deliberate act by the author; a description is prose
# that may wander; a parameter list is structural and hard to fake.
_HISTORY = {
    "name": [("histor", 5), ("bars", 5), ("ohlc", 5), ("candle", 4),
             ("price", 3), ("quote", 2), ("chart", 3), ("series", 3),
             ("daily", 2), ("stock_data", 4)],
    "desc": [("historical", 4), ("ohlc", 4), ("open, high", 4), ("bars", 3),
             ("date range", 3), ("time series", 3), ("price", 2),
             ("interval", 2), ("period", 2)],
    "param": [("start", 3), ("end", 3), ("period", 3), ("interval", 3),
              ("start_date", 4), ("end_date", 4), ("range", 2)],
}
_INFO = {
    "name": [("info", 5), ("profile", 5), ("company", 4), ("entity", 4),
             ("detail", 3), ("about", 2), ("fundamental", 3), ("metadata", 3)],
    "desc": [("company name", 5), ("profile", 4), ("sector", 3),
             ("industry", 3), ("exchange", 3), ("company", 2), ("about", 2)],
    "param": [("symbol", 1), ("ticker", 1)],
}

FLOOR = 6          # below this, nothing here is the tool we are looking for
MARGIN = 3         # top two closer than this is a coin flip, so refuse


def _params(tool):
    """Parameter names from the inputSchema, empty when it is not readable.

    A tool is free to ship no schema, or a schema that is not an object, and
    neither is an error here. It only means this signal contributes nothing
    for that tool, which the score reflects on its own.
    """
    schema = tool.get("inputSchema")
    if not isinstance(schema, dict):
        return []
    props = schema.get("properties")
    if not isinstance(props, dict):
        return []
    return [str(k).lower() for k in props]


def score(tool, table):
    """Points, and the terms that earned them, so the number can be argued with.

    Returning the evidence alongside the score is the point. A bare number
    invites a human to accept it; a number with "matched 'histor' in the name"
    beside it invites them to check, and checking is the only thing standing
    between a confident proposal and a record about the wrong tool.
    """
    if not isinstance(tool, dict):
        return 0, []
    name = str(tool.get("name", "")).lower()
    desc = str(tool.get("description", "")).lower()
    params = _params(tool)
    total, why = 0, []
    for term, pts in table["name"]:
        if term in name:
            total += pts
            why.append(f"name~{term}+{pts}")
    for term, pts in table["desc"]:
        if term in desc:
            total += pts
            why.append(f"desc~{term}+{pts}")
    for term, pts in table["param"]:
        if any(term == p for p in params):
            total += pts
            why.append(f"param={term}+{pts}")
    return total, why


def propose(tools, table, label):
    """One proposal, or a refusal that says which of the two reasons applies."""
    ranked = sorted(((score(t, table), t) for t in tools),
                    key=lambda r: -r[0][0])
    if not ranked:
        return None, f"{label}: the server listed no tools"
    (top, why), tool = ranked[0]
    if top < FLOOR:
        best = str(tool.get("name", "?")) if isinstance(tool, dict) else "?"
        return None, (f"{label}: nothing scored above {FLOOR}. Closest was "
                      f"{best!r} at {top}. This server may not expose the "
                      f"shape this probe set assumes.")
    if len(ranked) > 1:
        second, stool = ranked[1][0][0], ranked[1][1]
        if top - second < MARGIN:
            sname = str(stool.get("name", "?")) if isinstance(stool, dict) else "?"
            return None, (f"{label}: {tool.get('name')!r} scored {top} and "
                          f"{sname!r} scored {second}. Too close to call, so "
                          f"this is a coin flip rather than a reading. Pass "
                          f"the right one by hand.")
    return {"tool": tool.get("name"), "score": top, "why": why}, None


def main(argv):
    if len(argv) != 2:
        sys.stderr.write(
            "usage: discover.py <tools-list.json>\n\n"
            "Reads a saved MCP tools/list result and proposes which tool is\n"
            "the history tool and which is the entity info tool. Proposes\n"
            "only. Confirm before passing them to run.py.\n")
        return 2
    with open(argv[1], encoding="utf-8") as fh:
        payload = json.load(fh)
    tools = payload.get("result", {}).get("tools", payload.get("tools", payload))
    if not isinstance(tools, list):
        sys.stderr.write("that file has no tools array this can read\n")
        return 2

    print(f"{len(tools)} tools listed by the server\n")
    refusals = []
    for label, table, flag in (("history", _HISTORY, "--tool-history"),
                               ("entity info", _INFO, "--tool-info")):
        got, why_not = propose(tools, table, label)
        if got:
            print(f"  {flag} {got['tool']}")
            print(f"      score {got['score']}: {' '.join(got['why'])}\n")
        else:
            print(f"  {flag} NOT PROPOSED")
            print(f"      {why_not}\n")
            refusals.append(label)

    if refusals:
        sys.stderr.write(
            "Refused to propose for: %s.\n"
            "A proposal a human rubber-stamps is worse than none, because it\n"
            "turns a guess into a confirmation. Pass those by hand.\n"
            % ", ".join(refusals))
        return 1
    print("Both proposed. Confirm these are right before running, because a\n"
          "wrong mapping yields a sound verdict about the wrong tool.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
