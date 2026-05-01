from dataclasses import dataclass

import pytest

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


def test_answer_completes():
    answer = ask(FakeMerchant(), "What's waiting?", FakeModel())
    assert answer.completed and answer.text.startswith("Two orders")
    assert answer.request_id


def test_timeout_is_recorded_not_raised():
    answer = ask(FakeMerchant(), "What's waiting?", FakeModel(fail=ModelTimeout()))
    assert answer.status == "timed_out" and not answer.completed


def test_free_plan_has_no_assistant():
    with pytest.raises(AssistantUnavailable):
        ask(FakeMerchant(plan="free"), "Hello?", FakeModel())
