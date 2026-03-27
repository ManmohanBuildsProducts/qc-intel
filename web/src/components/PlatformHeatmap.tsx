"use client";

import type { ScorecardCategory } from "@/types";

const PLATFORMS = ["blinkit", "zepto", "instamart"] as const;

const PLATFORM_LABELS: Record<string, string> = {
  blinkit: "Blinkit",
  zepto: "Zepto",
  instamart: "Instamart",
};

function intensityClass(count: number, max: number): string {
  if (count === 0) return "bg-red-900/20 text-red-400";
  const ratio = count / max;
  if (ratio > 0.7) return "bg-emerald-500/30 text-emerald-300";
  if (ratio > 0.3) return "bg-emerald-500/15 text-emerald-400";
  return "bg-emerald-500/8 text-emerald-500";
}

interface Props {
  categories: ScorecardCategory[];
}

export default function PlatformHeatmap({ categories }: Props) {
  // Compute per-category per-platform SKU counts from the categories data
  // We need to derive this from platform/missing_platforms info
  const maxCount = Math.max(
    ...categories.map((c) => c.sku_count),
    1
  );

  return (
    <div className="rounded-xl border border-gray-800 bg-gray-900 p-5">
      <h4 className="text-xs font-semibold uppercase tracking-wider text-gray-500 mb-4">
        Platform Coverage
      </h4>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-700">
              <th className="pb-3 text-left text-xs font-medium text-gray-500">
                Category
              </th>
              {PLATFORMS.map((p) => (
                <th
                  key={p}
                  className="pb-3 text-center text-xs font-medium text-gray-500"
                >
                  {PLATFORM_LABELS[p]}
                </th>
              ))}
              <th className="pb-3 text-center text-xs font-medium text-gray-500">
                Total
              </th>
            </tr>
          </thead>
          <tbody>
            {categories.map((cat) => (
              <tr key={cat.category} className="border-b border-gray-800/50">
                <td className="py-3 text-gray-300 font-medium">
                  {cat.category}
                </td>
                {PLATFORMS.map((p) => {
                  const present = cat.platforms.includes(p);
                  // Approximate per-platform count: distribute evenly if present
                  const platformCount = present
                    ? Math.max(
                        1,
                        Math.round(
                          cat.sku_count /
                            Math.max(cat.platforms.length, 1)
                        )
                      )
                    : 0;
                  return (
                    <td key={p} className="py-3 text-center">
                      <span
                        className={`inline-block min-w-[2.5rem] rounded-md px-2 py-1 text-xs font-bold ${intensityClass(platformCount, maxCount)}`}
                      >
                        {platformCount}
                      </span>
                    </td>
                  );
                })}
                <td className="py-3 text-center text-gray-400 font-medium">
                  {cat.sku_count}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
