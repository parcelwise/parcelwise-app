"""Values a charge depends on that nobody has decided yet.

An `Open` stands in for a price, an allowance, a start month or a merchant list until its owner answers the
Raven node named on it. The nightly job never posts a charge that depends on an `Open`: it holds the charge
and reports which node is holding it. Replace the `Open` with the answer; never with a guess.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Open:
    node: str  # the Raven decision node that answers it
    question: str

    def __str__(self) -> str:
        return f"open: {self.question} (Raven {self.node})"


def is_open(value) -> bool:
    return isinstance(value, Open)
