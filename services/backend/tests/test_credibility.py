from geotrade_ai.credibility import credibility, hedge_score, unconfirmed


def test_hedge_cues() -> None:
    assert hedge_score("Infosys Q2 profit rises 12%") == 0
    assert hedge_score("Reliance may consider stake sale, sources say") == 0.7
    assert hedge_score("Is HDFC Bank planning a merger?") == 0.35


def test_credibility_rises_with_sources_and_falls_with_hedging() -> None:
    assert credibility(1, 0) == 0.6
    assert credibility(3, 0) == 1.0
    assert credibility(1, 0.7) < credibility(4, 0.7)
    assert unconfirmed(1, 0.35) and not unconfirmed(1, 0) and not unconfirmed(3, 0.7)
