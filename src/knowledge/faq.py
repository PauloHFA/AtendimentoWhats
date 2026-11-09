from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

_TOKEN_PATTERN = re.compile(r"[a-z0-9]{2,}")
_STOP_WORDS = frozenset(
    {
        "a",
        "ao",
        "aos",
        "as",
        "com",
        "como",
        "da",
        "das",
        "de",
        "do",
        "dos",
        "e",
        "em",
        "essa",
        "esse",
        "esta",
        "este",
        "eu",
        "me",
        "meu",
        "minha",
        "na",
        "nas",
        "no",
        "nos",
        "o",
        "os",
        "para",
        "por",
        "qual",
        "quais",
        "que",
        "se",
        "um",
        "uma",
        "voce",
    }
)


class ArticleLike(Protocol):
    title: str
    content: str

    @property
    def tags(self) -> Sequence[str]: ...


@dataclass(frozen=True)
class KnowledgeDocument:
    title: str
    content: str
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class FAQAnswer:
    source_title: str
    content: str
    matched_terms: tuple[str, ...]

    @property
    def text(self) -> str:
        return f"{self.content}\n\nFonte: {self.source_title}"


class FAQService:
    def answer(
        self, question: str, articles: Sequence[ArticleLike]
    ) -> FAQAnswer | None:
        query_terms = _tokenize(question)
        if not query_terms:
            return None

        candidates: list[tuple[int, float, ArticleLike, tuple[str, ...]]] = []
        for article in articles:
            title_terms = _tokenize(article.title)
            content_terms = _tokenize(article.content)
            tag_terms = set().union(*(_tokenize(tag) for tag in article.tags))
            matched_terms = tuple(
                sorted(
                    term
                    for term in query_terms
                    if term in title_terms or term in content_terms or term in tag_terms
                )
            )
            coverage = len(matched_terms) / len(query_terms)
            if coverage < 0.5:
                continue

            score = sum(
                3 if term in title_terms else 2 if term in tag_terms else 1
                for term in matched_terms
            )
            candidates.append((score, coverage, article, matched_terms))

        if not candidates:
            return None

        candidates.sort(key=lambda candidate: (candidate[0], candidate[1]), reverse=True)
        best_score, best_coverage, best_article, best_terms = candidates[0]
        if any(
            score == best_score and coverage == best_coverage
            for score, coverage, _, _ in candidates[1:]
        ):
            return None

        return FAQAnswer(
            source_title=best_article.title,
            content=best_article.content,
            matched_terms=best_terms,
        )


def _tokenize(text: str) -> set[str]:
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii").lower()
    tokens = _TOKEN_PATTERN.findall(ascii_text)
    return {
        token[:-1] if token.endswith("s") and len(token) > 4 else token
        for token in tokens
        if token not in _STOP_WORDS
    }
