import { MAX_BULK_ORDERS } from "./bulk";

type Props = {
  selectedCount: number;
  pageCount: number;
  matchingTotal: number;
  onSelectPage: () => void;
  onSelectMatching: () => void;
  onClear: () => void;
  onBuy: () => void;
};

// Same selection pattern as packing slips, except "select all matching" stops at 200 because a label costs money.
export function SelectionBar({ selectedCount, pageCount, matchingTotal, onSelectPage, onSelectMatching, onClear, onBuy }: Props) {
  const capped = matchingTotal > MAX_BULK_ORDERS;
  return (
    <div className="selection-bar" role="toolbar">
      <span>{selectedCount} selected</span>
      <button onClick={onSelectPage}>Select all {pageCount} on this page</button>
      {matchingTotal > pageCount && (
        <button onClick={onSelectMatching}>
          {capped
            ? `Select the first ${MAX_BULK_ORDERS} of ${matchingTotal} matching orders`
            : `Select all ${matchingTotal} matching orders`}
        </button>
      )}
      {selectedCount > 0 && (
        <>
          <button onClick={onClear}>Clear</button>
          <button onClick={onBuy}>Buy labels for {selectedCount} orders</button>
        </>
      )}
    </div>
  );
}
