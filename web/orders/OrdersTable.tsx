import { useState } from "react";
import { BulkJob, Order, pendingBulkOrders } from "@/lib/api";
import { BulkJobStatus } from "./BulkJobStatus";
import { OrderRow } from "./OrderRow";

// 'Select all matching' stops at 200 orders: a label costs real money, and 200 is the most one bulk buy takes
// (Raven decisions b090d951fd5e, Lena Park, and dd18542dfb3e, Ana Ruiz).
export const MAX_SELECTED = 200;

type Props = {
  orders: Order[];
  totalMatching: number;
  onSelectAllMatching: (limit: number) => void;
  selected: Set<string>;
  onSelectionChange: (selected: Set<string>) => void;
  onBuyLabel: (order: Order) => void;
  onBuySelected: () => void;
};

// One row per unfulfilled order. Merchants buy one label from a row's button, or tick rows and buy them together:
// a checkbox per row, 'select all on this page' and 'select all N matching' (Raven decision 4f27c3207067, Lena
// Park; the same pattern as packing slips, per b090d951fd5e).
export function OrdersTable({
  orders,
  totalMatching,
  onSelectAllMatching,
  selected,
  onSelectionChange,
  onBuyLabel,
  onBuySelected,
}: Props) {
  // Orders the running bulk buy will buy; their row's Buy label is blocked until it finishes (Raven 55ebbf4c3071).
  const [inBulkBuy, setInBulkBuy] = useState<Set<string>>(new Set());

  function onJob(job: BulkJob | null) {
    if (job?.status === "pending") {
      pendingBulkOrders()
        .then((ids) => setInBulkBuy(new Set(ids)))
        .catch(() => setInBulkBuy(new Set()));
    } else {
      setInBulkBuy(new Set());
    }
  }

  if (orders.length === 0) {
    return <p className="empty">No unfulfilled orders. New Shopify orders show up here within a minute.</p>;
  }
  const allOnPage = orders.every((o) => selected.has(o.id));

  function toggle(order: Order, on: boolean) {
    const next = new Set(selected);
    if (on && next.size >= MAX_SELECTED) return;
    if (on) next.add(order.id);
    else next.delete(order.id);
    onSelectionChange(next);
  }

  function toggleAllOnPage(on: boolean) {
    const next = new Set(selected);
    for (const o of orders) {
      if (on && next.size >= MAX_SELECTED) break;
      if (on) next.add(o.id);
      else next.delete(o.id);
    }
    onSelectionChange(next);
  }

  return (
    <>
      {/* The merchant's latest bulk buy, running or finished, when they come back to the page. */}
      <BulkJobStatus onJob={onJob} />
      {selected.size > 0 && (
        <div className="bulk-bar">
          {selected.size} selected
          {allOnPage && totalMatching > selected.size && selected.size < MAX_SELECTED && (
            <>
              {" · "}
              <button className="link" onClick={() => onSelectAllMatching(MAX_SELECTED)}>
                {totalMatching > MAX_SELECTED
                  ? `Select the first ${MAX_SELECTED} of ${totalMatching} matching`
                  : `Select all ${totalMatching} matching`}
              </button>
            </>
          )}
          {" · "}
          <button onClick={onBuySelected}>Buy {selected.size} labels</button>
        </div>
      )}
      <table className="orders">
        <thead>
          <tr>
            <th>
              <input
                type="checkbox"
                aria-label="Select all on this page"
                checked={allOnPage}
                onChange={(e) => toggleAllOnPage(e.target.checked)}
              />
            </th>
            <th>Order</th>
            <th>Customer</th>
            <th>Item</th>
            <th>Weight</th>
            <th>Waiting</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {orders.map((order) => (
            <OrderRow
              key={order.id}
              order={order}
              selected={selected.has(order.id)}
              inBulkBuy={inBulkBuy.has(order.id)}
              onSelect={toggle}
              onBuyLabel={onBuyLabel}
            />
          ))}
        </tbody>
      </table>
    </>
  );
}
