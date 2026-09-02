"""
Ranking: order evaluated jobs into the shortlist proposed to the candidate.

`combined_score()` is real and complete. The selection orchestration around it is a MOCK,
in the same sense as jobsearch/preselection.py: final signatures and correctly shaped
output, no logic.

Compatibility and commute are stored as independent, incommensurable axes -
`compatibility_score` is 0-100 and higher is better, `commute_score` is weighted minutes
and lower is better, with 0 meaning fully remote. Ranking needs one ordering, so commute is
applied as a modifier to compatibility rather than as a second sort key.
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


def rank_evaluations(evaluations):
    """ order evaluated jobs by combined_score(), descending. evaluations are storage rows as
        get_evaluation() returns them; each gains "combined_score" and "commute_known".

        MOCK: returns the input order with the fields attached.
    """
    return [
        {
            **e,
            "combined_score": combined_score(e["compatibility_score"], e["commute_score"]),
            "commute_known": e["commute_score"] is not None,
        }
        for e in evaluations
    ]


def propose(evaluations, m):
    """ the final shortlist: the m highest-ranked jobs not already applied to or discarded.
        returns {"proposed": [ranked evaluation, ...], "excluded": [{"evaluation", "reason"}]}.

        MOCK: takes the first m, excludes nothing.
    """
    ranked = rank_evaluations(evaluations)
    return {"proposed": ranked[:m], "excluded": []}
