import { Order } from "@/lib/api";
import { OrderRow } from "./OrderRow";

// What the merchant has picked: specific orders, or every order matching the current filter (which can be more
// than one page) except the ones they unticked. Unticking one of 450 matching leaves 449, like Gmail (Lena Park,
// Raven 2fec207a36f7). Whoever turns "all matching" into order ids for the confirm screen must leave `excluded` out.
export type Selection = { kind: "ids"; ids: Set<string> } | { kind: "allMatching"; excluded: Set<string> };

export const emptySelection = (): Selection => ({ kind: "ids", ids: new Set() });

// Most orders one label purchase can cover. Mistakes here cost real money (Lena Park, Raven 21777abe92a1);
// the server refuses bigger batches too (app/labels/batch.py MAX_BATCH_ORDERS).
export const MAX_LABEL_BATCH = 500;

export const isSelected = (selection: Selection, order: Order) =>
  selection.kind === "allMatching" ? !selection.excluded.has(order.id) : selection.ids.has(order.id);

export const selectedCount = (selection: Selection, totalMatching: number) =>
  selection.kind === "allMatching" ? totalMatching - selection.excluded.size : selection.ids.size;

type Props = {
  orders: Order[];
  // Every order matching the current filter, across all pages.
  totalMatching: number;
  selection: Selection;
  onSelectionChange: (selection: Selection) => void;
  onBuyLabel: (order: Order) => void;
  onBuySelected: () => void;
};

// One row per unfulfilled order. Merchants buy one label from a row's button, or select orders and buy them all.
export function OrdersTable({ orders, totalMatching, selection, onSelectionChange, onBuyLabel, onBuySelected }: Props) {
  if (orders.length === 0) {
    return <p className="empty">No unfulfilled orders. New Shopify orders show up here within a minute.</p>;
  }

  const pageIds = orders.map((o) => o.id);
  const count = selectedCount(selection, totalMatching);
  const wholePageSelected = orders.every((o) => isSelected(selection, o));

  function toggle(order: Order) {
    if (selection.kind === "allMatching") {
      // Unticking one order out of "all matching" leaves every other matching order selected.
      const excluded = new Set(selection.excluded);
      if (excluded.has(order.id)) excluded.delete(order.id);
      else excluded.add(order.id);
      onSelectionChange({ kind: "allMatching", excluded });
      return;
    }
    const ids = new Set(selection.ids);
    if (ids.has(order.id)) ids.delete(order.id);
    else ids.add(order.id);
    onSelectionChange({ kind: "ids", ids });
  }

  function togglePage() {
    if (wholePageSelected) {
      onSelectionChange(emptySelection());
      return;
    }
    if (selection.kind === "allMatching") {
      const excluded = new Set(selection.excluded);
      pageIds.forEach((id) => excluded.delete(id));
      onSelectionChange({ kind: "allMatching", excluded });
      return;
    }
    const ids = new Set(selection.ids);
    pageIds.forEach((id) => ids.add(id));
    onSelectionChange({ kind: "ids", ids });
  }

  return (
    <>
      {count > 0 && (
        <div className="bulk-bar" role="region" aria-label="Selected orders">
          <span>
            {count} {count === 1 ? "order" : "orders"} selected
          </span>
          {selection.kind === "ids" &&
            wholePageSelected &&
            totalMatching > orders.length &&
            (totalMatching <= MAX_LABEL_BATCH ? (
              <button className="link" onClick={() => onSelectionChange({ kind: "allMatching", excluded: new Set() })}>
                Select all {totalMatching} matching
              </button>
            ) : (
              <span className="muted">
                {totalMatching} orders match. Narrow the filter to {MAX_LABEL_BATCH} or fewer to buy them all at once.
              </span>
            ))}
          <button className="link" onClick={() => onSelectionChange(emptySelection())}>
            Clear
          </button>
          <button onClick={onBuySelected} disabled={count > MAX_LABEL_BATCH}>
            Buy {count} {count === 1 ? "label" : "labels"}
          </button>
        </div>
      )}
      <table className="orders">
        <thead>
          <tr>
            <th>
              <input
                type="checkbox"
                aria-label="Select all orders on this page"
                checked={wholePageSelected}
                onChange={togglePage}
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
              selected={isSelected(selection, order)}
              onToggle={toggle}
              onBuyLabel={onBuyLabel}
            />
          ))}
        </tbody>
      </table>
    </>
  );
}
