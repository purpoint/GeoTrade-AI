"""Related stocks to watch (P2-BE-07): not held, related to a holding (sector, group, co-mentions),
with positive news momentum and enough coverage. Reasons are always listed; never a recommendation."""

from dataclasses import dataclass, field

SAME_GROUP = 0.8
SAME_SECTOR = 0.6
MIN_STORIES_3D = 2
DISCLAIMER = (
    "Stocks with rising news sentiment related to what you hold. Shown for research, not as recommendations."
)


@dataclass
class Candidate:
    ticker: str
    relatedness: float = 0.0
    reasons: list[str] = field(default_factory=list)
    index: float = 0.0
    delta_24h: float = 0.0
    stories_3d: int = 0
    score: float = 0.0


def candidates(
    held: list[str], companies: dict[str, dict[str, str]], co_mentions: list[tuple[str, str, float, int]]
) -> dict[str, Candidate]:
    """Stocks not held that relate to a holding, with relatedness and the reasons."""
    held_set = set(held)
    cands: dict[str, Candidate] = {}

    def relate(ticker: str, strength: float, reason: str) -> None:
        if ticker in held_set or ticker not in companies:
            return
        c = cands.setdefault(ticker, Candidate(ticker))
        c.relatedness = max(c.relatedness, strength)
        if reason not in c.reasons:
            c.reasons.append(reason)

    for h in held:
        info = companies.get(h)
        if info is None:
            continue
        for t, other in companies.items():
            if info.get("group_name") and other.get("group_name") == info["group_name"] and t != h:
                relate(t, SAME_GROUP, f"Same group as {h} ({info['group_name']})")
            elif other["sector_id"] == info["sector_id"] and t != h:
                relate(t, SAME_SECTOR, f"Same sector as {h}")
    for h, peer, rate, n in co_mentions:
        if n >= 2:
            relate(peer, min(0.4 + rate, 0.9), f"Often in the news with {h} ({n} shared stories)")
    return cands


def rank(
    held: list[str],
    companies: dict[str, dict[str, str]],
    co_mentions: list[tuple[str, str, float, int]],
    signals: dict[str, tuple[float, float]],
    stories_3d: dict[str, int],
    limit: int = 5,
) -> list[Candidate]:
    """companies: ticker -> {name, sector_id, group_name}; signals: ticker -> (index, delta_24h)."""
    out = []
    for c in candidates(held, companies, co_mentions).values():
        c.index, c.delta_24h = signals.get(c.ticker, (0.0, 0.0))
        c.stories_3d = stories_3d.get(c.ticker, 0)
        if c.index <= 0 or c.delta_24h <= 0 or c.stories_3d < MIN_STORIES_3D:
            continue  # positive momentum and adequate coverage only
        c.score = round(0.5 * c.relatedness + 0.3 * min(c.index / 50, 1) + 0.2 * min(c.delta_24h / 20, 1), 3)
        c.reasons.append(
            f"Sentiment {c.index:+.0f}, up {c.delta_24h:.0f} in 24h, {c.stories_3d} stories in 3 days"
        )
        out.append(c)
    return sorted(out, key=lambda c: -c.score)[:limit]
