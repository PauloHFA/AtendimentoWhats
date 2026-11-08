from src.knowledge.faq import FAQService, KnowledgeDocument

ARTICLES = [
    KnowledgeDocument(
        title="Horários de atendimento",
        content="Atendemos de segunda a sexta, das 9h às 18h.",
        tags=("horário", "atendimento", "funcionamento"),
    ),
    KnowledgeDocument(
        title="Agendamento de serviços",
        content="Agende um horário disponível pelo menu de atendimento.",
        tags=("agendamento", "serviço"),
    ),
    KnowledgeDocument(
        title="Política de cancelamento",
        content="Para cancelar um agendamento, fale com nossa equipe.",
        tags=("cancelamento", "agendamento"),
    ),
]


def test_faq_returns_grounded_answer_with_article_title() -> None:
    answer = FAQService().answer("Qual é o horário de atendimento?", ARTICLES)

    assert answer is not None
    assert answer.source_title == "Horários de atendimento"
    assert answer.text == (
        "Atendemos de segunda a sexta, das 9h às 18h.\n\n"
        "Fonte: Horários de atendimento"
    )
    assert "horario" in answer.matched_terms
    assert "atendimento" in answer.matched_terms


def test_faq_normalizes_accents_and_plural_forms() -> None:
    answer = FAQService().answer("Quais são os horários de funcionamento?", ARTICLES)

    assert answer is not None
    assert answer.source_title == "Horários de atendimento"
    assert answer.matched_terms == ("funcionamento", "horario")


def test_faq_returns_no_answer_when_knowledge_does_not_cover_question() -> None:
    answer = FAQService().answer("Como faço um pagamento por cartão?", ARTICLES)

    assert answer is None


def test_faq_avoids_guessing_when_top_articles_are_ambiguous() -> None:
    ambiguous_articles = [
        KnowledgeDocument("Preço dos serviços", "A consulta custa R$ 100.", ("preço",)),
        KnowledgeDocument("Preço da avaliação", "A avaliação custa R$ 100.", ("preço",)),
    ]

    answer = FAQService().answer("Qual é o preço?", ambiguous_articles)

    assert answer is None


def test_faq_returns_no_answer_for_empty_or_stopword_only_question() -> None:
    service = FAQService()

    assert service.answer("", ARTICLES) is None
    assert service.answer("qual é a de", ARTICLES) is None


def test_faq_prefers_article_with_more_relevant_evidence() -> None:
    answer = FAQService().answer(
        "Qual é o horário de atendimento para funcionamento?",
        ARTICLES,
    )

    assert answer is not None
    assert answer.source_title == "Horários de atendimento"
