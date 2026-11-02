import { Order } from "@/lib/api";
import { age } from "@/lib/time";

type Props = {
  order: Order;
  onBuyLabel: (order: Order) => void;
  checked?: boolean;
  onToggle?: () => void; // present only when bulk selection is on
};

export function OrderRow({ order, onBuyLabel, checked, onToggle }: Props) {
  return (
    <tr>
      {onToggle && (
        <td>
          <input type="checkbox" aria-label={`Select #${order.shopifyId}`} checked={!!checked} onChange={onToggle} />
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
