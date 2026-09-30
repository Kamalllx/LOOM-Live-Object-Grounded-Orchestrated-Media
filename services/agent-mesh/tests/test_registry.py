import pytest

from app.registry import AgentCard, AgentRegistry, default_registry


def test_default_registry_contains_all_four_agents():
    registry = default_registry()

    assert [card.name for card in registry.all()] == [
        "curator",
        "pedagogy",
        "personalizer",
        "assessment",
    ]


def test_registry_returns_card_by_name():
    registry = default_registry()

    card = registry.get("curator")

    assert card.url == "http://127.0.0.1:8101"
    assert card.capabilities == ["select_threads"]


def test_registry_rejects_duplicate_agents():
    registry = AgentRegistry()
    card = AgentCard(
        name="curator",
        version="1.0",
        url="http://127.0.0.1:8101",
    )
    registry.register(card)

    with pytest.raises(ValueError, match="already registered"):
        registry.register(card)


def test_registry_rejects_unknown_agent():
    registry = default_registry()

    with pytest.raises(KeyError, match="Unknown agent"):
        registry.get("missing")
