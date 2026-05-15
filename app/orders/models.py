"""Orders as we store them. Shopify is the source of truth; we keep what labels need."""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Order:
    id: str
    merchant: object
    shopify_id: int
    sku: str
    quantity: int
    weight_oz: float
    dims_in: tuple[float, float, float] = (0.0, 0.0, 0.0)
    created_at: datetime | None = None
    status: str = "unfulfilled"
    tags: list[str] = field(default_factory=list)

    @property
    def fulfilled(self) -> bool:
        return self.status == "fulfilled"
