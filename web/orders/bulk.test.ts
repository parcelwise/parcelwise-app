import { describe, expect, it } from "vitest";
import { MAX_BULK_ORDERS, capSelection, totalPrice } from "./bulk";

describe("bulk selection", () => {
  it("stops select-all-matching at 200 orders", () => {
    const ids = Array.from({ length: 500 }, (_, i) => `o${i}`);
    expect(MAX_BULK_ORDERS).toBe(200);
    expect(capSelection(ids)).toHaveLength(200);
    expect(capSelection(ids.slice(0, 3))).toHaveLength(3);
  });

  it("adds prices without float drift", () => {
    expect(totalPrice(["0.10", "0.20"])).toBe("0.30");
    expect(totalPrice(Array(200).fill("5.40"))).toBe("1080.00");
  });
});
