import { Order } from "@/lib/api";
import { OrderRow } from "./OrderRow";

// What the merchant has picked: specific orders, or every order matching the current filter
// (which can be more than one page).
export type Selection = { kind: "ids"; ids: Set<string> } | { kind: "allMatching" };

export const emptySelection = (): Selection => ({ kind: "ids", ids: new Set() });

// Most orders one label purchase can cover. Mistakes here cost real money (Lena Park, Raven 21777abe92a1);
// the server refuses bigger batches too (app/labels/batch.py MAX_BATCH_ORDERS).
export const MAX_LABEL_BATCH = 500;

export const isSelected = (selection: Selection, order: Order) =>
  selection.kind === "allMatching" || selection.ids.has(order.id);

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
  const selectedCount = selection.kind === "allMatching" ? totalMatching : selection.ids.size;
  const wholePageSelected = selection.kind === "allMatching" || pageIds.every((id) => selection.ids.has(id));

  function toggle(order: Order) {
    // Unticking one order out of "all matching" narrows the selection to this page minus that order.
    const ids = selection.kind === "allMatching" ? new Set(pageIds) : new Set(selection.ids);
    if (ids.has(order.id)) ids.delete(order.id);
    else ids.add(order.id);
    onSelectionChange({ kind: "ids", ids });
  }

  function togglePage() {
    if (wholePageSelected) {
      onSelectionChange(emptySelection());
      return;
    }
    const ids = selection.kind === "ids" ? new Set(selection.ids) : new Set<string>();
    pageIds.forEach((id) => ids.add(id));
    onSelectionChange({ kind: "ids", ids });
  }

  return (
    <>
      {selectedCount > 0 && (
        <div className="bulk-bar" role="region" aria-label="Selected orders">
          <span>
            {selectedCount} {selectedCount === 1 ? "order" : "orders"} selected
          </span>
          {selection.kind === "ids" &&
            wholePageSelected &&
            totalMatching > orders.length &&
            (totalMatching <= MAX_LABEL_BATCH ? (
              <button className="link" onClick={() => onSelectionChange({ kind: "allMatching" })}>
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
          <button onClick={onBuySelected} disabled={selectedCount > MAX_LABEL_BATCH}>
            Buy {selectedCount} {selectedCount === 1 ? "label" : "labels"}
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
