"""The Parcelwise Assistant: a merchant asks about their orders, labels or plan and gets one answer.

One question in, one answer out. `status` says whether the answer finished. The model sits behind
`ModelClient` so tests never call one. Starter and Growth have it; Free does not (app/billing/plans.py).

A timeout is retried once with the same request id. Every attempt we make is a usage row with its status
and attempt number (Jordan, PR #216): the counter is what the model cost us, not what the merchant saw.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol

from app.billing.plans import has_assistant
from app.usage.events import UsageEvent, record

ATTEMPTS = 2


class ModelClient(Protocol):
    def answer(self, question: str, *, context: dict) -> str: ...


class ModelTimeout(Exception):
    """The model did not answer in time. One retry with the same question is safe."""


class AssistantUnavailable(Exception):
    """The assistant is off for this merchant."""


@dataclass
class Answer:
    merchant_id: str
    request_id: str
    question: str
    text: str = ""
    status: str = "pending"  # completed | failed | timed_out
    attempts: int = 0
    asked_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def completed(self) -> bool:
        return self.status == "completed"


def available(merchant) -> bool:
    return has_assistant(merchant.plan)


def ask(merchant, question: str, model: ModelClient, *, request_id: str = "", context: dict | None = None,
        usage=None) -> Answer:
    """Answer one question for one merchant, retrying a timeout once."""
    if not available(merchant):
        raise AssistantUnavailable(merchant.id)
    answer = Answer(merchant.id, request_id or uuid.uuid4().hex, question)
    for attempt in range(1, ATTEMPTS + 1):
        answer.attempts = attempt
        try:
            answer.text = model.answer(question, context=context or {})
            answer.status = "completed"
        except ModelTimeout:
            answer.status = "timed_out"
        except Exception:
            answer.status = "failed"
        if usage is not None:
            record(usage, UsageEvent(merchant.id, "assistant", answer.request_id, at=answer.asked_at,
                                     status=answer.status, attempt=attempt))
        if answer.status != "timed_out":
            break
    return answer
