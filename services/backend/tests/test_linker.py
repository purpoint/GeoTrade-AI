import pytest

from geotrade_ai.worker.linker import (
    Match,
    case_matches,
    corroborated,
    get_linker,
    has_stock_context,
    hit_negative_context,
    on_word_boundary,
    rank_stocks,
    resolve_overlaps,
)
from geotrade_ai.worker.relevance import hard_drop_reason, relevance


def m(ticker: str, alias: str, start: int, field: str = "title", ambiguous: bool = False) -> Match:
    return Match(ticker, alias, start, start + len(alias), field, ambiguous, False)


# ---------- each rule on its own ----------


def test_word_boundary() -> None:
    assert on_word_boundary("ITC shares", 0, 3)
    assert not on_word_boundary("BITCOIN", 1, 4)


def test_case_sensitive_alias() -> None:
    cs = Match("BEL", "BEL", 0, 3, "title", False, True)
    assert case_matches("BEL wins order", cs)
    assert not case_matches("bel wins order", cs)


def test_longest_match_wins() -> None:
    kept, dropped = resolve_overlaps([m("SBIN", "SBI", 0), m("SBILIFE", "SBI Life", 0)])
    assert [k.ticker for k in kept] == ["SBILIFE"] and dropped[0].ticker == "SBIN"


def test_negative_context() -> None:
    text = "Reliance Power shares surge"
    assert hit_negative_context(text, m("RELIANCE", "Reliance", 0), {"RELIANCE": ["Reliance Power"]})
    assert not hit_negative_context(
        "Reliance Industries up", m("RELIANCE", "Reliance", 0), {"RELIANCE": ["Reliance Power"]}
    )


def test_stock_context_and_corroboration() -> None:
    amb = m("HDFCBANK", "HDFC", 0, ambiguous=True)
    assert has_stock_context("HDFC shares fall 2%", amb)
    assert not has_stock_context("HDFC chairman speaks", amb)
    assert corroborated(amb, [amb, m("HDFCBANK", "HDFC Bank", 20)])
    assert not corroborated(amb, [amb])


def test_rank_caps_primary() -> None:
    matches = [m(t, t, i * 10) for i, t in enumerate(["TCS", "INFY", "WIPRO", "HCLTECH"])]
    ranked = rank_stocks(matches)
    assert sum(p for _, p, _ in ranked) == 3 and len(ranked) == 4


# ---------- end to end ----------


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Infosys bags $1.5 billion deal from European client", ["INFY"]),
        ("SBI Life Q2 profit rises 12%", ["SBILIFE"]),
        ("Reliance Power shares hit upper circuit", []),
        ("L&T Finance raises Rs 2,000 crore via NCDs", []),
        ("L&T wins mega order for Middle East project", ["LT"]),
        ("ITC Hotels demerger: what shareholders get", []),
        ("Tata Motors, Tata Steel drag Nifty lower", ["TATAMOTORS", "TATASTEEL"]),
        ("Kotak Mahindra Bank names new CEO", ["KOTAKBANK"]),
        ("HDFC shares slip after Q2 numbers", ["HDFCBANK"]),
        ("Zomato parent Eternal posts profit jump", ["ETERNAL"]),
    ],
)
def test_linker_examples(title: str, expected: list[str]) -> None:
    assert sorted(get_linker().link(title).primary_tickers) == sorted(expected)


def test_sector_and_market_inference() -> None:
    r = get_linker().link("PSU banks rally as Sensex climbs 500 points")
    assert ("banking", 0.6) in r.sectors and r.market


def test_relevance() -> None:
    assert hard_drop_reason("Today's horoscope for Leo") == "horoscope"
    linker = get_linker()
    assert relevance("TCS Q2 profit up", "", linker.link("TCS Q2 profit up")) >= 0.7
    assert relevance("Monsoon arrives in Kerala", "", linker.link("Monsoon arrives in Kerala")) < 0.25
