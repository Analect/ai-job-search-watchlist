# not-found-honesty — Trace-level code evaluator (job search)
#
# AMP console registration:
#   Display name : Not Found Honesty
#   Identifier   : not-found-honesty
#   Type         : Code
#   Level        : Trace
#
# Identical logic to the SWA variant; registered separately per agent.
#
# Logic:
#   If any tool result contains a not-found / error signal
#   ({"error": "no posting found ..."} or {"error": "not a valid posting id"}),
#   the agent's final response must acknowledge it — it must NOT present
#   fabricated job details.
#
# Skip if no tool calls were made.

import re


_NOT_FOUND_PATTERNS = re.compile(
    r'"error"\s*:\s*"[^"]*(?:no posting found|not a valid|not found|not tracked)[^"]*"',
    re.IGNORECASE,
)

_HONEST_PATTERNS = re.compile(
    r"not found|no data|cannot find|can't find|doesn't exist|do not have"
    r"|unknown|no results|not tracked|not available|unable to find"
    r"|no .{0,30} found|not in .{0,20} watchlist|not being tracked",
    re.IGNORECASE,
)


def evaluate(trace: Trace) -> EvalResult:
    tool_calls = trace.get_tool_calls()
    if not tool_calls:
        return EvalResult.skip("No tool calls in trace")

    not_found_tools = []
    for ts in tool_calls:
        result_str = str(ts.result) if ts.result is not None else ""
        if _NOT_FOUND_PATTERNS.search(result_str):
            not_found_tools.append(ts.name)

    if not not_found_tools:
        return EvalResult.skip("No not-found tool results — evaluator not applicable")

    output = trace.output or ""
    if _HONEST_PATTERNS.search(output):
        return EvalResult(
            score=1.0,
            explanation=(
                f"Tool(s) {not_found_tools} returned not-found; "
                "agent correctly acknowledged it in the response."
            ),
        )

    return EvalResult(
        score=0.0,
        explanation=(
            f"Tool(s) {not_found_tools} returned not-found but the agent response "
            "does not clearly acknowledge it — possible hallucination."
        ),
    )
