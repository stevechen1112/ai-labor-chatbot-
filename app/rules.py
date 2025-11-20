from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional


@dataclass
class TopicRule:
    name: str
    preferred_laws: List[str]
    blocked_laws: List[str]
    required_phrases: List[str]
    prior_articles: List[str]


RULESET: List[TopicRule] = [
    TopicRule(
        name="severance_procedure",
        preferred_laws=["勞動基準法", "就業服務法"],
        blocked_laws=["民法"],
        required_phrases=["資遣", "預告", "通報"],
        prior_articles=["11", "16", "17", "33"],
    ),
    TopicRule(
        name="pregnancy_protection",
        preferred_laws=["性別平等工作法", "勞動基準法"],
        blocked_laws=[],
        required_phrases=["懷孕", "孕婦", "歧視", "母性"],
        prior_articles=["11", "51"],
    ),
    TopicRule(
        name="overtime",
        preferred_laws=["勞動基準法", "勞動基準法施行細則"],
        blocked_laws=[
            "民法",
            "勞工安全衛生法", "勞工安全衛生法施行細則",
            "性別平等工作法施行細則",
            "勞工保險條例", "勞工保險條例施行細則",
            "勞工請假規則", "勞工請假規則及請假基準管理辦法",
            "勞工職業災害保險及保護法", "勞工職業災害保險職業病審查準則",
            "中華民國工會法施行細則",
        ],
        required_phrases=["加班", "延長工時", "加班費", "補休", "工資", "給付", "延時", "工時", "計算"],
        prior_articles=["24", "32"],
    ),
    TopicRule(
        name="annual_leave",
        preferred_laws=["勞動基準法"],
        blocked_laws=["民法"],
        required_phrases=["特別休假", "年假", "年資"],
        prior_articles=[],
    ),
    TopicRule(
        name="wage_deduction",
        preferred_laws=["勞動基準法"],
        blocked_laws=["民法"],
        required_phrases=["工資", "扣款", "薪水", "罰款", "違規", "帳罰", "曠職"],
        prior_articles=[],
    ),
    TopicRule(
        name="parental_leave",
        preferred_laws=["育嬰留職停薪實施辦法", "性別平等工作法"],
        blocked_laws=[],
        required_phrases=["育嬰", "留職停薪"],
        prior_articles=[],
    ),
    TopicRule(
        name="labor_dispute",
        preferred_laws=["勞資爭議處理法", "勞資爭議調解辦法"],
        blocked_laws=[],
        required_phrases=["勞資爭議", "調解"],
        prior_articles=[],
    ),
]


def resolve_topic(q_norm: str) -> Optional[TopicRule]:
    s = q_norm.strip()
    # Simple heuristic matching by required phrases
    for rule in RULESET:
        if any(p in s for p in rule.required_phrases):
            return rule
    # Fallback for specific keywords
    if "OT" in s.upper():
        return RULESET[0]
    return None

