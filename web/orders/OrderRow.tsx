import { Order } from "@/lib/api";
import { age } from "@/lib/time";

type Props = {
  order: Order;
  selected: boolean;
  // Left out while bulk buying is switched off; the row then has no checkbox.
  onToggle?: (order: Order) => void;
  onBuyLabel: (order: Order) => void;
};

export function OrderRow({ order, selected, onToggle, onBuyLabel }: Props) {
  return (
    <tr className={selected ? "selected" : undefined}>
      {onToggle && (
        <td>
          <input
            type="checkbox"
            aria-label={`Select order #${order.shopifyId}`}
            checked={selected}
            onChange={() => onToggle(order)}
          />
        </td>
      )}
      <td>#{order.shopifyId}</td>
      <td>{order.customer}</td>
      <td>
        {order.quantity} × {order.sku}
      </td>
      <td>{(order.weightOz / 16).toFixed(1)} lb</td>
      <td className="muted">{age(order.createdAt)}</td>
      <td>
        <button onClick={() => onBuyLabel(order)}>Buy label</button>
      </td>
    </tr>
  );
}
