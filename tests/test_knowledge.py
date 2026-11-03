from datetime import datetime, timezone

from bot.knowledge.service import KnowledgeRecord, KnowledgeService, validate_source_url


def test_knowledge_source_allowlist_and_review_filter():
    assert validate_source_url("https://acm.xinciqq.top/guide")
    assert not validate_source_url("http://acm.xinciqq.top/guide")
    assert not validate_source_url("https://127.0.0.1/guide")
    records = KnowledgeService([
        KnowledgeRecord("a", "入门", "算法 入门", "stable", "site",
                         source_url="https://acm.xinciqq.top/", review_status="approved"),
        KnowledgeRecord("b", "待审核", "算法 入门", "stable", "site",
                         source_url="https://acm.xinciqq.top/", review_status="pending"),
    ])
    result = records.search("算法入门", now=datetime.now(timezone.utc))
    assert [item.id for item in result] == ["a"]
