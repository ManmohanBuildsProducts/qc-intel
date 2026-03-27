"use client";

import Link from "next/link";
import type { ScorecardCategory } from "@/types";

interface Props {
  brand: string;
  category: ScorecardCategory;
}

export default function CategoryCard({ brand, category: cat }: Props) {
  const priceComparison = cat.avg_price - cat.category_avg_price;
  const priceLabel =
    priceComparison > 0
      ? `+₹${priceComparison.toFixed(0)} vs avg`
      : `₹${priceComparison.toFixed(0)} vs avg`;

  return (
    <Link
      href={`/brand/${encodeURIComponent(brand)}/${encodeURIComponent(cat.category)}`}
      className="group rounded-xl border border-gray-800 bg-gray-900 p-5 transition-colors hover:border-gray-700 hover:bg-gray-800/50"
    >
      <div className="flex items-start justify-between mb-3">
        <h3 className="text-sm font-medium text-gray-200 group-hover:text-gray-100">
          {cat.category}
        </h3>
        <span className="rounded-md bg-emerald-500/10 px-2 py-0.5 text-xs font-bold text-emerald-400 border border-emerald-500/20">
          #{cat.rank}
        </span>
      </div>

      <div className="space-y-2">
        <div className="flex justify-between text-xs">
          <span className="text-gray-500">Share</span>
          <span className="text-gray-300">{cat.share_pct}%</span>
        </div>
        <div className="flex justify-between text-xs">
          <span className="text-gray-500">SKUs</span>
          <span className="text-gray-300">
            {cat.sku_count} / {cat.category_total}
          </span>
        </div>
        <div className="flex justify-between text-xs">
          <span className="text-gray-500">Avg Price</span>
          <span
            className={
              priceComparison > 0 ? "text-amber-400" : "text-emerald-400"
            }
          >
            ₹{cat.avg_price} ({priceLabel})
          </span>
        </div>
      </div>

      {cat.missing_platforms.length > 0 && (
        <div className="mt-3 pt-3 border-t border-gray-800">
          <div className="text-[10px] text-red-400">
            Missing: {cat.missing_platforms.join(", ")}
          </div>
        </div>
      )}

      <div className="mt-3 text-[10px] text-gray-600 group-hover:text-gray-500">
        Click for competitive detail →
      </div>
    </Link>
  );
}
