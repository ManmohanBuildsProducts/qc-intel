"use client";

import type { BrandGaps } from "@/types";

const PLATFORMS = ["blinkit", "zepto", "instamart"] as const;
const PLATFORM_LABELS: Record<string, string> = {
  blinkit: "Blinkit",
  zepto: "Zepto",
  instamart: "Instamart",
};

interface Props {
  gaps: BrandGaps;
}

export default function DistributionGaps({ gaps }: Props) {
  const { platform_matrix, summary } = gaps;
  const totalGaps =
    summary.total_products - summary.on_all;

  return (
    <div className="rounded-xl border border-gray-800 bg-gray-900 p-5">
      <h4 className="text-xs font-semibold uppercase tracking-wider text-gray-500 mb-3">
        Distribution Gaps
      </h4>

      {totalGaps > 0 && (
        <div className="mb-4 rounded-lg border border-amber-500/20 bg-amber-500/5 px-4 py-3">
          <p className="text-sm text-amber-300">
            <span className="font-bold">{totalGaps}</span> products missing from
            at least one platform.{" "}
            {summary.on_one > 0 && (
              <span className="text-amber-400">
                {summary.on_one} only on a single platform.
              </span>
            )}
          </p>
        </div>
      )}

      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-gray-700 text-gray-500">
              <th className="pb-2 text-left font-medium">Product</th>
              {PLATFORMS.map((p) => (
                <th key={p} className="pb-2 text-center font-medium">
                  {PLATFORM_LABELS[p]}
                </th>
              ))}
              <th className="pb-2 text-center font-medium">Gaps</th>
            </tr>
          </thead>
          <tbody>
            {platform_matrix.map((row) => (
              <tr key={row.product_name} className="border-b border-gray-800">
                <td className="py-2 text-gray-300 max-w-[200px] truncate">
                  {row.product_name}
                </td>
                {PLATFORMS.map((p) => {
                  const cell = row[p];
                  return (
                    <td key={p} className="py-2 text-center">
                      {cell.present ? (
                        <span className="text-emerald-400">
                          ✓{" "}
                          {cell.price !== null && (
                            <span className="text-gray-500">
                              ₹{cell.price}
                            </span>
                          )}
                        </span>
                      ) : (
                        <span className="text-red-400">✗</span>
                      )}
                    </td>
                  );
                })}
                <td className="py-2 text-center">
                  <span
                    className={
                      row.gap_count > 0
                        ? "text-amber-400 font-bold"
                        : "text-gray-600"
                    }
                  >
                    {row.gap_count}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
