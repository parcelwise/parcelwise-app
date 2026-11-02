// Thin client for the merchant API. Every call goes through here so auth and errors stay in one place.
export type Order = {
  id: string;
  shopifyId: number;
  customer: string;
  sku: string;
  quantity: number;
  weightOz: number;
  status: "unfulfilled" | "fulfilled" | "cancelled";
  createdAt: string;
};

export type Label = { orderId: string; carrier: string; trackingNumber: string; price: string; pdfUrl: string };

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, { credentials: "include", ...init });
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json() as Promise<T>;
}

export const listOrders = () => call<Order[]>("/orders");

export const buyLabel = (orderId: string, rateId: string, shownPrice: string) =>
  call<Label>(`/orders/${orderId}/label`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ rate_id: rateId, shown_price: shownPrice }),
  });

export const searchOrders = (q: string) => call<Order[]>(`/orders/search?q=${encodeURIComponent(q)}`);

// Bulk label purchases. The server buys one label per order in a background job and reports each order's outcome.
export type BatchSelection = {
  orderId: string;
  carrier: string;
  service: string;
  rateId: string;
  price: string;
  quotedAt: string;
};

export type BatchItemStatus =
  | "queued"
  | "bought"
  | "failed"
  | "already_labeled"
  | "over_allowance"
  | "needs_price_approval";

export type BatchItem = {
  orderId: string;
  position: number;
  carrier: string;
  service: string;
  price: string;
  status: BatchItemStatus;
  trackingNumber: string;
  error: string;
};

export type LabelBatch = { batchId: number; status?: "queued" | "running" | "done"; items: BatchItem[] };

export const listUnfulfilledOrderIds = () => call<string[]>("/orders/unfulfilled-ids");

export const createLabelBatch = (selections: BatchSelection[]) =>
  call<LabelBatch>("/label-batches", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      selections: selections.map((s) => ({
        order_id: s.orderId,
        carrier: s.carrier,
        service: s.service,
        rate_id: s.rateId,
        price: s.price,
        quoted_at: s.quotedAt,
      })),
    }),
  });

export const getLabelBatch = (batchId: number) => call<LabelBatch>(`/label-batches/${batchId}`);
