from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from geotrade_ai import vocabulary
from geotrade_ai.models import ArticleScore
from geotrade_ai.repos.reference import seed_reference
from geotrade_ai.worker import explain, llm_link
from geotrade_ai.worker.linker import LinkResult, get_linker
from tests.test_pipeline import add, drain


class Fake:
    model = "fake"

    def __init__(self, reply: dict[str, Any]) -> None:
        self.reply = reply
        self.calls = 0

    def complete_json(self, system: str, user: str) -> dict[str, Any]:
        self.calls += 1
        return self.reply


def test_vocabulary_checks() -> None:
    assert vocabulary.banned_terms("Analysts recommend you BUY now") == ["buy", "recommend"]
    assert vocabulary.banned_terms("Shares rose after the order") == []
    assert vocabulary.tickers_in("INFY and TCS gained, Infosys led") == {"INFY", "TCS"}


def test_why_validator() -> None:
    assert explain.valid("A large order adds to INFY's revenue visibility.", {"INFY"})
    assert not explain.valid("Investors should buy INFY now.", {"INFY"})
    assert not explain.valid("This also helps TCS.", {"INFY"})
    assert not explain.valid("word " * 31, {"INFY"})


def test_why_this_matters_writes_llm_sentence_once(session: Session) -> None:
    seed_reference(session)
    a = add(session, "SEBI slaps penalty on Adani Enterprises over disclosure lapses", minutes=0)
    session.commit()
    drain(session, datetime.now(UTC) + timedelta(seconds=1))
    fake = Fake(
        {"results": [{"id": 0, "sentence": "A regulatory penalty can weigh on ADANIENT's reputation."}]}
    )
    assert explain.run(session, fake) == 1
    sc = session.get(ArticleScore, a.id)
    assert sc is not None and sc.explanation_source == "llm"
    assert sc.explanation.startswith("A regulatory penalty")
    assert explain.run(session, fake) == 0  # nothing left to explain


def test_banned_sentence_keeps_template(session: Session) -> None:
    seed_reference(session)
    a = add(session, "SEBI slaps penalty on Adani Enterprises over disclosure lapses", minutes=0)
    session.commit()
    drain(session, datetime.now(UTC) + timedelta(seconds=1))
    assert explain.run(session, Fake({"results": [{"id": 0, "sentence": "Time to sell ADANIENT."}]})) == 0
    sc = session.get(ArticleScore, a.id)
    assert sc is not None and sc.explanation_source == "template"


def test_link_fallback_only_when_unsure_and_only_known_tickers(session: Session) -> None:
    seed_reference(session)
    sure = get_linker().link("Infosys Q2 profit rises 12%")
    assert not llm_link.unsure(sure, 0.9)
    empty = LinkResult()
    assert llm_link.unsure(empty, 0.5) and not llm_link.unsure(empty, 0.2)
    chosen = llm_link.pick(
        session, "Country's largest IT exporter wins deal", empty, Fake({"tickers": ["infy", "FAKECO"]})
    )
    assert chosen == ["INFY"]
    llm_link.apply(empty, chosen)
    assert empty.primary_tickers == ["INFY"]
