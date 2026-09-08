"""
Ranking: order evaluated jobs into the shortlist proposed to the candidate.

Compatibility and commute are stored as independent, incommensurable axes -
`compatibility_score` is 0-100 and higher is better, `commute_score` is weighted minutes
and lower is better, with 0 meaning fully remote. Ranking needs one ordering, so commute is
applied as a modifier to compatibility rather than as a second sort key.

`combined_score()` is pure and deterministic. `rank_evaluations()` computes it from each
row's `compatibility_score` and `commute_score`; it is never persisted, so a change to the
modifier constants takes effect on the next rank with no cache to invalidate. `propose()`
cuts the ranked list to m, dropping rows already applied to or discarded.

The pool `propose()` ranks over is the caller's choice. `propose_jobs.py` calls it twice,
once over every saved evaluation and once over the current run's, and renders each result
under its own heading.
"""

# Commute modifier anchors, in weighted minutes as commute_score() reports them:
#   0 -> +15, COMMUTE_NEUTRAL -> 0, 60 -> -15, COMMUTE_CUTOFF -> -25, beyond -> score 0.
# The four anchors are colinear, so the modifier is a single line through them (slope -0.5
# per weighted minute) rather than a piecewise table.
#
# These thresholds encode how much commute this candidate tolerates, which is
# personalization: they should eventually become user parameters, read from
# job_preferences.md alongside Scoring Notes rather than fixed here.
COMMUTE_NEUTRAL = 30
COMMUTE_BONUS_AT_ZERO = 15
COMMUTE_CUTOFF = 80

SCORE_MIN = 0
SCORE_MAX = 100


def commute_modifier(commute_score):
    """ the adjustment a commute applies to a compatibility score, in compatibility points.
        returns None when the commute exceeds COMMUTE_CUTOFF, which zeroes the job rather
        than penalizing it.
    """
    if commute_score > COMMUTE_CUTOFF:
        return None
    return COMMUTE_BONUS_AT_ZERO * (1 - commute_score / COMMUTE_NEUTRAL)


def combined_score(compatibility_score, commute_score):
    """ the single 0-100 value jobs are ranked by: compatibility adjusted by the commute
        modifier, clamped to [SCORE_MIN, SCORE_MAX].

        A commute beyond COMMUTE_CUTOFF returns SCORE_MIN regardless of compatibility.
        commute_score of None means figure_address() could not resolve an office, which is a
        data failure rather than evidence about the job: it scores as COMMUTE_NEUTRAL, the
        modifier's zero point, so compatibility passes through unchanged and the job is
        neither rewarded nor punished for the failure. The caller reports it as unknown.
    """
    if commute_score is None:
        commute_score = COMMUTE_NEUTRAL

    modifier = commute_modifier(commute_score)
    if modifier is None:
        return SCORE_MIN

    return max(SCORE_MIN, min(SCORE_MAX, round(compatibility_score + modifier)))


# application_status values that keep a job out of a proposal: the user has already acted on it
EXCLUDED_STATUSES = {"applied", "discarded"}


def rank_evaluations(evaluations):
    """ order evaluated jobs by descending combined_score, then by descending
        compatibility_score for ties. evaluations are storage rows carrying at least
        "compatibility_score" and "commute_score"; each returned row gains a "combined_score"
        and "commute_known".
    """
    ranked = [
        {
            **e,
            "combined_score": combined_score(e["compatibility_score"], e["commute_score"]),
            "commute_known": e["commute_score"] is not None,
        }
        for e in evaluations
    ]
    ranked.sort(key=lambda e: (e["combined_score"], e["compatibility_score"]), reverse=True)
    return ranked


def propose(evaluations, m):
    """ the shortlist: the m highest-ranked jobs whose application_status is not in
        EXCLUDED_STATUSES. returns

            {"proposed": [ranked evaluation, ...],          # <= m
             "excluded": [{"evaluation": {...}, "reason": str}, ...]}

        Every input row appears once across the two lists. "reason" is the excluding status
        for an already-actioned job, otherwise "ranked below the top m".
    """
    proposed, excluded = [], []
    for e in rank_evaluations(evaluations):
        status = e.get("application_status")
        if status in EXCLUDED_STATUSES:
            excluded.append({"evaluation": e, "reason": status})
        elif len(proposed) < m:
            proposed.append(e)
        else:
            excluded.append({"evaluation": e, "reason": f"ranked below the top {m}"})
    return {"proposed": proposed, "excluded": excluded}


def _proposal_line(rank, e):
    """ one proposed job as a terminal block: rank, combined score, title, fit and commute """
    if not e.get("commute_known"):
        commute = "commute unknown"
    elif e.get("commute_score"):
        commute = f"commute {e['commute_score']:.0f} (weighted min)"
    else:
        commute = "no commute (remote)"
    return "\n".join([
        f"{rank}. [{e['combined_score']}] {e.get('job_title') or '(untitled)'} "
        f"at {e.get('company') or '(unknown company)'}",
        f"   fit {e.get('compatibility_score')}/100 | {commute}",
        f"   {e.get('url') or ''}",
    ])


def format_proposal(result, m, heading=None):
    """ render a propose() result for the terminal: an optional heading naming the pool, the
        proposed jobs in rank order, then a count of what was held back and why.
    """
    total = len(result["proposed"]) + len(result["excluded"])
    lines = []
    if heading:
        lines.append(f"\n=== {heading} ===")
    lines.append(f"\n{len(result['proposed'])} job(s) proposed out of {total} evaluated:\n")
    for i, e in enumerate(result["proposed"], 1):
        lines.append(_proposal_line(i, e))

    actioned = [x for x in result["excluded"] if x["reason"] in EXCLUDED_STATUSES]
    below = [x for x in result["excluded"] if x["reason"] not in EXCLUDED_STATUSES]
    if actioned:
        lines.append(f"\n{len(actioned)} excluded as already applied to or discarded:\n")
        for x in actioned:
            e = x["evaluation"]
            lines.append(f"- {e.get('job_title') or '(untitled)'} "
                         f"at {e.get('company') or '(unknown company)'} - {x['reason']}")
    if below:
        lines.append(f"\n{len(below)} evaluated but ranked below the top {m}.")
    return "\n".join(lines)
