"use client";

import type { DiscountBattle as DiscountBattleType } from "@/types";

interface Props {
  data: DiscountBattleType;
}

export default function DiscountBattle({ data }: Props) {
  const { brands, category_avg_discount } = data;
  const maxDiscount = Math.max(
    ...brands.map((b) => b.avg_discount_pct),
    1
  );

  return (
    <div className="rounded-xl border border-gray-800 bg-gray-900 p-5">
      <h4 className="text-xs font-semibold uppercase tracking-wider text-gray-500 mb-3">
        Discount Battle
      </h4>
      <div className="text-xs text-gray-500 mb-4">
        Category avg:{" "}
        <span className="text-gray-400 font-medium">
          {category_avg_discount}%
        </span>
      </div>
      <div className="space-y-2">
        {brands.map((b) => (
          <div key={b.brand} className="flex items-center gap-3">
            <div
              className={`w-28 shrink-0 text-xs truncate ${
                b.is_target
                  ? "text-emerald-400 font-semibold"
                  : "text-gray-300"
              }`}
            >
              {b.brand}
            </div>
            <div className="flex-1 h-3 rounded-full bg-gray-800 overflow-hidden relative">
              {/* Category avg marker */}
              <div
                className="absolute top-0 bottom-0 w-px bg-red-500/60 z-10"
                style={{
                  left: `${(category_avg_discount / maxDiscount) * 100}%`,
                }}
              />
              <div
                className={`h-full rounded-full ${
                  b.is_target ? "bg-emerald-500" : "bg-gray-600"
                }`}
                style={{
                  width: `${(b.avg_discount_pct / maxDiscount) * 100}%`,
                }}
              />
            </div>
            <div className="w-12 text-right text-xs text-gray-400 shrink-0">
              {b.avg_discount_pct}%
            </div>
            <div className="w-10 text-right text-[10px] text-gray-600 shrink-0">
              {b.sku_count} SKU
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
