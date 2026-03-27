"use client";

import type { LandscapeBrand } from "@/types";

interface Props {
  brands: LandscapeBrand[];
}

export default function BrandRankings({ brands }: Props) {
  return (
    <div className="rounded-xl border border-gray-800 bg-gray-900 p-5">
      <h4 className="text-xs font-semibold uppercase tracking-wider text-gray-500 mb-4">
        Brand Rankings
      </h4>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-gray-700 text-gray-500">
              <th className="pb-2 text-left font-medium w-8">#</th>
              <th className="pb-2 text-left font-medium">Brand</th>
              <th className="pb-2 text-right font-medium">SKUs</th>
              <th className="pb-2 text-center font-medium">Platforms</th>
              <th className="pb-2 text-right font-medium">Avg Price</th>
              <th className="pb-2 text-right font-medium">Avg Discount</th>
            </tr>
          </thead>
          <tbody>
            {brands.map((b, i) => (
              <tr key={b.brand} className="border-b border-gray-800">
                <td className="py-2 text-gray-500">{i + 1}</td>
                <td className="py-2 text-gray-300 font-medium">{b.brand}</td>
                <td className="py-2 text-right text-gray-300">{b.sku_count}</td>
                <td className="py-2 text-center">
                  <span
                    className={`text-xs ${
                      b.platform_count >= 3
                        ? "text-emerald-400"
                        : b.platform_count >= 2
                          ? "text-blue-400"
                          : "text-gray-500"
                    }`}
                  >
                    {b.platforms.join(", ")}
                  </span>
                </td>
                <td className="py-2 text-right text-gray-300">
                  ₹{b.avg_price}
                </td>
                <td className="py-2 text-right text-gray-400">
                  {b.avg_discount_pct}%
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
