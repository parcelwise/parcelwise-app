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

export type BulkResult = { orderId: string; status: "bought" | "skipped" | "failed"; label?: Label; reason?: string };

// One entry per order the merchant approved: the rate they were shown and its price.
export const buyLabelsBulk = (items: { orderId: string; rateId: string; shownPrice: string }[]) =>
  call<BulkResult[]>("/orders/labels/bulk", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ items: items.map((i) => ({ order_id: i.orderId, rate_id: i.rateId, shown_price: i.shownPrice })) }),
  });

// "Select all N matching": the total and the ids of the first 200 (the most one bulk action may take).
export const matchingOrders = () => call<{ total: number; ids: string[] }>("/orders/matching");
