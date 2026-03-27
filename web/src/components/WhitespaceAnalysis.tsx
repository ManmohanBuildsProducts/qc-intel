"use client";

import type { CategoryWhitespace } from "@/types";

const DENSITY_STYLES: Record<string, { bg: string; text: string; label: string }> = {
  sparse: { bg: "bg-emerald-500/20", text: "text-emerald-400", label: "Opportunity" },
  moderate: { bg: "bg-gray-700/40", text: "text-gray-400", label: "Moderate" },
  crowded: { bg: "bg-amber-500/20", text: "text-amber-400", label: "Crowded" },
};

interface Props {
  data: CategoryWhitespace;
}

export default function WhitespaceAnalysis({ data }: Props) {
  const maxSku = Math.max(...data.price_bands.map((b) => b.sku_count), 1);
  const sparseBands = data.price_bands.filter((b) => b.density === "sparse");

  return (
    <div className="rounded-xl border border-gray-800 bg-gray-900 p-5">
      <h4 className="text-xs font-semibold uppercase tracking-wider text-gray-500 mb-4">
        Price Whitespace Analysis
      </h4>

      {/* Segmented bar */}
      <div className="flex gap-0.5 h-10 rounded-lg overflow-hidden mb-4">
        {data.price_bands.map((band) => {
          const style = DENSITY_STYLES[band.density] || DENSITY_STYLES.moderate;
          const width = Math.max((band.sku_count / maxSku) * 100, 5);
          return (
            <div
              key={band.range}
              className={`${style.bg} flex items-center justify-center relative group cursor-default`}
              style={{ width: `${width}%` }}
              title={`${band.range}: ${band.sku_count} SKUs, ${band.brand_count} brands`}
            >
              <span className={`text-[9px] font-bold ${style.text} truncate px-1`}>
                {band.sku_count}
              </span>
            </div>
          );
        })}
      </div>

      {/* Legend */}
      <div className="flex gap-4 mb-4 text-[10px]">
        {Object.entries(DENSITY_STYLES).map(([key, style]) => (
          <span key={key} className="flex items-center gap-1">
            <span className={`inline-block w-3 h-2 rounded-sm ${style.bg}`} />
            <span className={style.text}>{style.label}</span>
          </span>
        ))}
      </div>

      {/* Detail table */}
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-gray-700 text-gray-500">
              <th className="pb-2 text-left font-medium">Price Band</th>
              <th className="pb-2 text-right font-medium">SKUs</th>
              <th className="pb-2 text-right font-medium">Brands</th>
              <th className="pb-2 text-left font-medium pl-4">Top Brands</th>
              <th className="pb-2 text-center font-medium">Density</th>
            </tr>
          </thead>
          <tbody>
            {data.price_bands.map((band) => {
              const style = DENSITY_STYLES[band.density] || DENSITY_STYLES.moderate;
              return (
                <tr key={band.range} className="border-b border-gray-800">
                  <td className="py-2 text-gray-300">{band.range}</td>
                  <td className="py-2 text-right text-gray-300">
                    {band.sku_count}
                  </td>
                  <td className="py-2 text-right text-gray-300">
                    {band.brand_count}
                  </td>
                  <td className="py-2 text-gray-500 pl-4">
                    {band.top_brands.join(", ") || "—"}
                  </td>
                  <td className="py-2 text-center">
                    <span
                      className={`rounded-md px-2 py-0.5 text-[10px] font-medium ${style.bg} ${style.text}`}
                    >
                      {style.label}
                    </span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Opportunity callout */}
      {sparseBands.length > 0 && (
        <div className="mt-4 rounded-lg border border-emerald-500/20 bg-emerald-500/5 px-4 py-3">
          <p className="text-sm text-emerald-300">
            <span className="font-bold">{sparseBands.length}</span> price bands
            have low competition — potential entry opportunities at{" "}
            {sparseBands.map((b) => b.range).join(", ")}.
          </p>
        </div>
      )}
    </div>
  );
}
