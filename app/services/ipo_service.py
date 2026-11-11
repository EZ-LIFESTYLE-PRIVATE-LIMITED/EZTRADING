"""IPO listing and AI review."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from app.domain.models import Ipo, IpoAssessment, IpoReview, IpoVerdict
from app.domain.ports import IpoSourcePort, NewsPort
from app.repositories.users import SettingsRepository
from app.services.account_service import WalletService
from app.services.advice.prompts import headline
from app.services.advisor_resolver import AdvisorResolver

log = logging.getLogger(__name__)
NEWS_PER_IPO = 4


class IpoService:
    def __init__(
        self,
        user_id: int,
        source: IpoSourcePort,
        news: NewsPort,
        resolver: AdvisorResolver,
        wallet: WalletService,
        settings_repo: SettingsRepository,
        max_workers: int = 6,
    ) -> None:
        self._user_id = user_id
        self._source = source
        self._news = news
        self._resolver = resolver
        self._wallet = wallet
        self._settings = settings_repo
        self._max_workers = max_workers

    def list(self) -> list[Ipo]:
        return self._source.list_ipos()

    def review(self) -> IpoReview:
        ipos = [i for i in self._source.list_ipos() if i.status in ("open", "upcoming")]
        budget = self._wallet.deployable()
        advisor_id = self._settings.get(self._user_id).advisor_id
        advisor = self._resolver.ipo_advisor(advisor_id)
        if advisor is None:
            return IpoReview(ipos=ipos, overview="The Rules advisor cannot evaluate IPOs. Pick an AI advisor in the top bar.",
                             assessments=[], advisor="rules", budget=budget, generated_at=datetime.now())
        if not ipos:
            return IpoReview(ipos=[], overview="No open or upcoming IPOs right now.", assessments=[],
                             advisor=advisor.name, budget=budget, generated_at=datetime.now())

        with ThreadPoolExecutor(max_workers=self._max_workers) as pool:
            market = pool.submit(self._news.market_news, 10)
            news = dict(zip([i.symbol for i in ipos], pool.map(self._ipo_news, ipos)))
            headlines = [headline(n) for n in market.result()]

        advice = advisor.assess(ipos, news, budget, headlines)
        by_symbol = {i.symbol: i for i in ipos}
        assessments = [self._fit(a, by_symbol[a.symbol], budget) for a in advice.assessments if a.symbol in by_symbol]
        return IpoReview(ipos=ipos, overview=advice.overview, assessments=assessments, advisor=advisor.name,
                         budget=budget, generated_at=datetime.now())

    def _ipo_news(self, ipo: Ipo) -> list[str]:
        try:
            return [headline(n) for n in self._news.search(f'"{ipo.name}" IPO', NEWS_PER_IPO)]
        except Exception as exc:  # best-effort context
            log.warning("IPO news failed for %s: %s", ipo.symbol, exc)
            return []

    @staticmethod
    def _fit(assessment: IpoAssessment, ipo: Ipo, budget: float) -> IpoAssessment:
        lots = assessment.suggested_lots if assessment.verdict is IpoVerdict.APPLY else 0
        if lots and ipo.min_investment:
            lots = min(lots, int(budget // ipo.min_investment))
        return assessment.model_copy(update={"suggested_lots": max(lots, 0)})
