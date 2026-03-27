"use client";

import type { BrandScorecard as BrandScorecardType } from "@/types";

function StatPill({
  label,
  value,
  sub,
  highlight,
}: {
  label: string;
  value: string | number;
  sub?: string;
  highlight?: boolean;
}) {
  return (
    <div
      className={`rounded-xl border p-4 ${
        highlight
          ? "border-emerald-500/40 bg-emerald-500/10"
          : "border-gray-700 bg-gray-800/60"
      }`}
    >
      <div className="text-xs text-gray-400 mb-1">{label}</div>
      <div
        className={`text-2xl font-bold ${highlight ? "text-emerald-400" : "text-gray-100"}`}
      >
        {value}
      </div>
      {sub && <div className="text-xs text-gray-500 mt-0.5">{sub}</div>}
    </div>
  );
}

interface Props {
  scorecard: BrandScorecardType;
}

export default function BrandScorecardHeader({ scorecard }: Props) {
  const platformStr = `${scorecard.platform_count}/3`;

  return (
    <div className="rounded-xl border border-gray-800 bg-gray-900 p-6">
      <h2 className="text-2xl font-bold text-gray-100 mb-4">
        {scorecard.brand}
      </h2>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
        <StatPill label="Total SKUs" value={scorecard.total_skus} highlight />
        <StatPill label="Categories" value={scorecard.category_count} />
        <StatPill label="Platforms" value={platformStr} />
        <StatPill
          label="Avg Discount"
          value={`${scorecard.avg_discount_pct}%`}
        />
        <StatPill
          label="Price Range"
          value={`₹${scorecard.price_range.min}–${scorecard.price_range.max}`}
        />
      </div>
    </div>
  );
}
