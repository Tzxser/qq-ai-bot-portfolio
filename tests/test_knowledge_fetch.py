import pytest

from bot.knowledge.fetch import fetch_draft


def test_fetch_rejects_non_allowlisted_sources():
    with pytest.raises(ValueError, match="source_not_allowed"):
        fetch_draft("https://127.0.0.1/")
