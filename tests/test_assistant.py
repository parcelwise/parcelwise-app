from dataclasses import dataclass

import pytest

from app.assistant.chat import AssistantUnavailable, ModelTimeout, ask


class FakeModel:
    def __init__(self, text="Two orders are waiting for labels.", fail=None, fail_times=99):
        self.text, self.fail, self.fail_times, self.calls = text, fail, fail_times, 0

    def answer(self, question, *, context):
        self.calls += 1
        if self.fail and self.calls <= self.fail_times:
            raise self.fail
        return self.text


class FakeUsage:
    def __init__(self):
        self.events = []

    def record(self, event):
        self.events.append(event)


@dataclass
class FakeMerchant:
    id: str = "m1"
    plan: str = "starter"


def test_answer_completes():
    answer = ask(FakeMerchant(), "What's waiting?", FakeModel())
    assert answer.completed and answer.text.startswith("Two orders")
    assert answer.request_id and answer.attempts == 1


def test_timeout_is_retried_once_with_the_same_request_id():
    usage = FakeUsage()
    model = FakeModel(fail=ModelTimeout(), fail_times=1)
    answer = ask(FakeMerchant(), "What's waiting?", model, usage=usage)
    assert answer.completed and answer.attempts == 2 and model.calls == 2
    assert [(e.status, e.attempt, e.request_id) for e in usage.events] == [
        ("timed_out", 1, answer.request_id),
        ("completed", 2, answer.request_id),
    ]


def test_second_timeout_gives_up():
    answer = ask(FakeMerchant(), "What's waiting?", FakeModel(fail=ModelTimeout()))
    assert answer.status == "timed_out" and answer.attempts == 2


def test_failure_is_not_retried_and_still_counts():
    usage = FakeUsage()
    answer = ask(FakeMerchant(), "What's waiting?", FakeModel(fail=RuntimeError("model down")), usage=usage)
    assert answer.status == "failed" and answer.attempts == 1
    assert [(e.status, e.attempt) for e in usage.events] == [("failed", 1)]


def test_free_plan_has_no_assistant():
    with pytest.raises(AssistantUnavailable):
        ask(FakeMerchant(plan="free"), "Hello?", FakeModel())
