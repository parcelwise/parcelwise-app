import { Order } from "@/lib/api";
import { OrderRow } from "./OrderRow";

type Props = {
  orders: Order[];
  onBuyLabel: (order: Order) => void;
  selected: Set<string>;
  onSelectionChange: (selected: Set<string>) => void;
  // Total unfulfilled orders and the ids "select all matching" takes (capped at 200 by the server).
  matching?: { total: number; ids: string[] };
};

// One row per unfulfilled order. Labels are bought from the row's button, or in bulk from the checked rows.
export function OrdersTable({ orders, onBuyLabel, selected, onSelectionChange, matching }: Props) {
  if (orders.length === 0) {
    return <p className="empty">No unfulfilled orders. New Shopify orders show up here within a minute.</p>;
  }
  const allSelected = orders.every((o) => selected.has(o.id));
  const toggle = (id: string) => {
    const next = new Set(selected);
    if (!next.delete(id)) next.add(id);
    onSelectionChange(next);
  };
  const pageSelected = allSelected && matching && selected.size < matching.ids.length;
  return (
    <>
    {pageSelected && (
      <p className="select-matching">
        {selected.size} selected.{" "}
        <button type="button" onClick={() => onSelectionChange(new Set(matching.ids))}>
          Select {matching.ids.length} matching{matching.total > matching.ids.length ? ` (limit ${matching.ids.length} of ${matching.total})` : ""}
        </button>
      </p>
    )}
    <table className="orders">
      <thead>
        <tr>
          <th>
            <input
              type="checkbox"
              aria-label="Select all on this page"
              checked={allSelected}
              onChange={() => onSelectionChange(allSelected ? new Set() : new Set(orders.map((o) => o.id)))}
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
            onBuyLabel={onBuyLabel}
            selected={selected.has(order.id)}
            onToggle={() => toggle(order.id)}
          />
        ))}
      </tbody>
    </table>
    </>
  );
}
