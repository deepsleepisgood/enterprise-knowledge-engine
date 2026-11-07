"""Authority resolution: decide which claim is current for each (topic, parameter, client).

Pure function over ClaimRecs, so the precedence rules are unit-tested without a database.

Rules (BUILD_PLAN Phase 2):
1. A client-scoped claim overrides the general rule for that client only (claims are
   bucketed by client; the "all" bucket is never touched by a client bucket).
2. Within a bucket, the lowest authority_rank among sources with status `current` wins
   (ties: the later valid_at). Its invalid_at is the source's valid_to (memo expiry).
3. A claim from another source that states the same value is `corroborating`.
4. A claim that states a different value is `superseded`: invalid_at is the day before the
   winner took effect (or its own start, if it started later), and the winner records
   `supersedes_key`. Two *current* sources that disagree also open a `value` conflict.
5. `practice` claims never compete with rules. They stay `current` as expert tips; if one
   contradicts the current rule it opens a `practice_vs_rule` conflict for the owner.
6. Expiry (valid_to in the past) is applied on read by rules.py, not here.
A bucket with no claim from a current source gets status `pending` (nothing
authoritative says it), unless a general current rule settles it.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

from app.graph.compare import Comparator, deterministic
from app.graph.schema import ClaimRec, ConflictRec, ResolveResult

AUTHORITATIVE_STATUSES = {"current"}


def _winner_key(c: ClaimRec) -> tuple[int, int]:
    return (c.authority_rank, -(c.valid_at.toordinal() if c.valid_at else 0))


def _retire(loser: ClaimRec, winner: ClaimRec, why: str) -> None:
    loser.status = "superseded"
    if winner.valid_at and loser.valid_at and loser.valid_at < winner.valid_at:
        loser.invalid_at = winner.valid_at - timedelta(days=1)
    else:
        loser.invalid_at = loser.valid_at
    loser.reason = why
    if winner.supersedes_key is None:
        winner.supersedes_key = loser.key


def _settle_against(
    others: list[ClaimRec],
    winner: ClaimRec,
    compare: Comparator,
    conflicts: list[ConflictRec],
) -> None:
    for other in sorted(others, key=_winner_key):
        verdict = compare(other, winner)
        if verdict in ("same", "narrower"):
            other.status = "corroborating"
            other.reason = f"agrees with {winner.source_id}"
            continue
        other_is_current = other.source_status in AUTHORITATIVE_STATUSES
        if verdict == "unknown" and other_is_current:
            # Two current documents worded differently: assume consistent; the conflict
            # scan (Phase 6) judges these with the LLM.
            other.status = "corroborating"
            other.reason = f"current source; wording differs from {winner.source_id}"
            continue
        _retire(
            other, winner, f"{winner.source_id} (rank {winner.authority_rank}) takes precedence"
        )
        if other_is_current and verdict == "different":
            conflicts.append(
                ConflictRec(
                    topic=winner.topic,
                    parameter=winner.parameter,
                    client=winner.client,
                    a_key=winner.key,
                    b_key=other.key,
                    kind="value",
                    authoritative_key=winner.key,
                    reason=f"Both sources are current; {winner.source_id} has higher authority.",
                )
            )


def resolve(claims: list[ClaimRec], compare: Comparator = deterministic) -> ResolveResult:
    conflicts: list[ConflictRec] = []
    groups: dict[tuple[str, str], list[ClaimRec]] = defaultdict(list)
    for c in claims:
        groups[(c.topic, c.parameter)].append(c)

    for (_topic, _param), group in groups.items():
        rules = [c for c in group if c.kind != "practice"]
        practices = [c for c in group if c.kind == "practice"]

        buckets: dict[str, list[ClaimRec]] = defaultdict(list)
        for c in rules:
            buckets[c.client].append(c)

        winners: dict[str, ClaimRec] = {}
        # General bucket first so client buckets can fall back to it.
        for client in sorted(buckets, key=lambda k: (k != "all", k)):
            bucket = buckets[client]
            eligible = [c for c in bucket if c.source_status in AUTHORITATIVE_STATUSES]
            if eligible:
                winner = min(eligible, key=_winner_key)
                winner.status = "current"
                winner.invalid_at = winner.source_valid_to
                winner.reason = "highest-authority current source" + (
                    f" for {client}" if client != "all" else ""
                )
                winners[client] = winner
                _settle_against([c for c in bucket if c is not winner], winner, compare, conflicts)
            elif client != "all" and "all" in winners:
                # e.g. an outdated client-specific claim when only the general rule is current
                _settle_against(bucket, winners["all"], compare, conflicts)
            else:
                for c in bucket:
                    c.status = "pending"
                    c.reason = "no current source states this; needs owner review"

        for p in practices:
            p.status = "current"
            p.reason = "expert practice (attached as a tip, never overrides a rule)"
            rule = winners.get(p.client) or winners.get("all")
            if rule is not None and compare(p, rule) == "different":
                conflicts.append(
                    ConflictRec(
                        topic=p.topic,
                        parameter=p.parameter,
                        client=p.client,
                        a_key=rule.key,
                        b_key=p.key,
                        kind="practice_vs_rule",
                        authoritative_key=rule.key,
                        reason=f"Practice in {p.source_id} differs from {rule.source_id}.",
                    )
                )
    return ResolveResult(claims=claims, conflicts=conflicts)


def summarise(result: ResolveResult) -> dict[str, int]:
    out: dict[str, int] = defaultdict(int)
    for c in result.claims:
        out[c.status] += 1
    out["conflicts"] = len(result.conflicts)
    return dict(out)
