from typing import Any

import httpx
from pydantic import BaseModel, Field


class AgentCard(BaseModel):
    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    url: str = Field(min_length=1)
    capabilities: list[str] = Field(default_factory=list)


class AgentRegistry:
    def __init__(self, cards: list[AgentCard] | None = None):
        self._cards: dict[str, AgentCard] = {}
        for card in cards or []:
            self.register(card)

    def register(self, card: AgentCard) -> None:
        if card.name in self._cards:
            raise ValueError(f"Agent already registered: {card.name}")
        self._cards[card.name] = card

    def get(self, name: str) -> AgentCard:
        try:
            return self._cards[name]
        except KeyError as error:
            raise KeyError(f"Unknown agent: {name}") from error

    def all(self) -> list[AgentCard]:
        return list(self._cards.values())

    def check_health(self, name: str, timeout_seconds: float = 2.0) -> bool:
        card = self.get(name)
        response = httpx.get(
            f"{card.url}/health",
            timeout=timeout_seconds,
        )
        if response.status_code != 200:
            return False
        body: dict[str, Any] = response.json()
        return body.get("status") == "ok"


def default_registry() -> AgentRegistry:
    return AgentRegistry(
        [
            AgentCard(
                name="curator",
                version="1.0",
                url="http://127.0.0.1:8101",
                capabilities=["select_threads"],
            ),
            AgentCard(
                name="pedagogy",
                version="1.0",
                url="http://127.0.0.1:8102",
                capabilities=["choose_learning_action"],
            ),
            AgentCard(
                name="personalizer",
                version="1.0",
                url="http://127.0.0.1:8103",
                capabilities=["personalize_threads"],
            ),
            AgentCard(
                name="assessment",
                version="1.0",
                url="http://127.0.0.1:8104",
                capabilities=["create_quiz"],
            ),
        ]
    )
