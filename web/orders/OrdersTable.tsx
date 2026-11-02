import { useState } from "react";
import { Order, listUnfulfilledOrderIds } from "@/lib/api";
import { OrderRow } from "./OrderRow";

type Props = {
  orders: Order[];
  // Every unfulfilled order, across pages. The table shows one page of them.
  unfulfilledCount: number;
  onBuyLabel: (order: Order) => void;
  onBuySelected: (orderIds: string[]) => void;
};

// One row per unfulfilled order. Buy one label from the row, or select orders and buy their labels together.
// Selection follows bulk packing slips: a checkbox for this page, then a link to select every unfulfilled order.
export function OrdersTable({ orders, unfulfilledCount, onBuyLabel, onBuySelected }: Props) {
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [loadingAll, setLoadingAll] = useState(false);

  if (orders.length === 0) {
    return <p className="empty">No unfulfilled orders. New Shopify orders show up here within a minute.</p>;
  }

  const pageSelected = orders.every((o) => selected.has(o.id));
  const allSelected = selected.size >= unfulfilledCount;

  function toggle(order: Order) {
    const next = new Set(selected);
    if (next.has(order.id)) next.delete(order.id);
    else next.add(order.id);
    setSelected(next);
  }

  function togglePage() {
    const next = new Set(selected);
    for (const o of orders) {
      if (pageSelected) next.delete(o.id);
      else next.add(o.id);
    }
    setSelected(next);
  }

  async function selectEveryUnfulfilled() {
    setLoadingAll(true);
    try {
      setSelected(new Set(await listUnfulfilledOrderIds()));
    } finally {
      setLoadingAll(false);
    }
  }

  return (
    <>
      {selected.size > 0 && (
        <div className="bulk-bar">
          <span>{selected.size} selected</span>
          {pageSelected && !allSelected && (
            <button className="link" disabled={loadingAll} onClick={selectEveryUnfulfilled}>
              Select all {unfulfilledCount} unfulfilled orders
            </button>
          )}
          <button className="link" onClick={() => setSelected(new Set())}>
            Clear
          </button>
          <button onClick={() => onBuySelected(Array.from(selected))}>Buy {selected.size} labels</button>
        </div>
      )}
      <table className="orders">
        <thead>
          <tr>
            <th>
              <input type="checkbox" aria-label="Select this page" checked={pageSelected} onChange={togglePage} />
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
              onToggle={toggle}
              onBuyLabel={onBuyLabel}
            />
          ))}
        </tbody>
      </table>
    </>
  );
}
