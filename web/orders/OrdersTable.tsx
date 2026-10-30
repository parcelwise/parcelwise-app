import { useState } from "react";
import { Order } from "@/lib/api";
import { OrderRow } from "./OrderRow";

type Props = {
  orders: Order[];
  onBuyLabel: (order: Order) => void;
  // Opens the bulk confirm dialog for the selected orders, in table order.
  onBuyLabels: (orders: Order[]) => void;
};

// One row per unfulfilled order. Labels are bought from a row's button, or for every selected row at once.
export function OrdersTable({ orders, onBuyLabel, onBuyLabels }: Props) {
  const [selected, setSelected] = useState<Set<string>>(new Set());

  if (orders.length === 0) {
    return <p className="empty">No unfulfilled orders. New Shopify orders show up here within a minute.</p>;
  }

  // Select-all covers this page only.
  const chosen = orders.filter((o) => selected.has(o.id));
  const allSelected = chosen.length === orders.length;

  function select(order: Order, on: boolean) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (on) next.add(order.id);
      else next.delete(order.id);
      return next;
    });
  }

  return (
    <>
      <div className="bulk-bar">
        <button disabled={chosen.length === 0} onClick={() => onBuyLabels(chosen)}>
          Buy {chosen.length || ""} labels
        </button>
      </div>
      <table className="orders">
        <thead>
          <tr>
            <th>
              <input
                type="checkbox"
                aria-label="Select all orders on this page"
                checked={allSelected}
                onChange={(e) => setSelected(e.target.checked ? new Set(orders.map((o) => o.id)) : new Set())}
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
              onSelect={select}
              onBuyLabel={onBuyLabel}
            />
          ))}
        </tbody>
      </table>
    </>
  );
}
