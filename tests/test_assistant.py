from dataclasses import dataclass

import pytest

from app.assistant import chat
from app.assistant.chat import AssistantUnavailable, ModelTimeout, ask


class FakeModel:
    def __init__(self, text="Two orders are waiting for labels.", fail=None):
        self.text, self.fail, self.calls = text, fail, 0

    def answer(self, question, *, context):
        self.calls += 1
        if self.fail:
            raise self.fail
        return self.text


@dataclass
class FakeMerchant:
    id: str = "m1"
    plan: str = "starter"


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setattr(chat, "available", lambda merchant: True)


def test_answer_completes(on):
    answer = ask(FakeMerchant(), "What's waiting?", FakeModel())
    assert answer.completed and answer.text.startswith("Two orders")
    assert answer.request_id


def test_timeout_is_recorded_not_raised(on):
    answer = ask(FakeMerchant(), "What's waiting?", FakeModel(fail=ModelTimeout()))
    assert answer.status == "timed_out" and not answer.completed


def test_off_by_default():
    with pytest.raises(AssistantUnavailable):
        ask(FakeMerchant(), "Hello?", FakeModel())
