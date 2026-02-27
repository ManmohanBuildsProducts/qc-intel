"use client";

import type { Product } from "@/types";

const PLATFORM_STYLES: Record<string, string> = {
  blinkit: "bg-[#F8CB46]/20 text-[#F8CB46]",
  zepto: "bg-[#7B2FBF]/20 text-[#7B2FBF]",
  instamart: "bg-[#FC8019]/20 text-[#FC8019]",
};

interface ProductTableProps {
  products: Product[];
  page: number;
  totalPages: number;
  onPageChange: (page: number) => void;
}

export default function ProductTable({
  products,
  page,
  totalPages,
  onPageChange,
}: ProductTableProps) {
  if (products.length === 0) {
    return (
      <div className="rounded-xl border border-gray-800 bg-gray-900 p-12 text-center text-gray-500">
        No products found. Try adjusting your filters.
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="overflow-x-auto rounded-xl border border-gray-800">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-gray-800 bg-gray-900/80">
            <tr>
              <th className="px-4 py-3 font-medium text-gray-400">Name</th>
              <th className="px-4 py-3 font-medium text-gray-400">Brand</th>
              <th className="px-4 py-3 font-medium text-gray-400">Platform</th>
              <th className="px-4 py-3 font-medium text-gray-400">Price</th>
              <th className="px-4 py-3 font-medium text-gray-400">MRP</th>
              <th className="px-4 py-3 font-medium text-gray-400">Stock</th>
              <th className="px-4 py-3 font-medium text-gray-400">Unit</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-800/50">
            {products.map((p) => (
              <tr
                key={p.id}
                className="bg-gray-900 transition-colors hover:bg-gray-800/50"
              >
                <td className="max-w-xs truncate px-4 py-3 text-gray-200">
                  {p.name}
                </td>
                <td className="px-4 py-3 text-gray-300">{p.brand || "\u2014"}</td>
                <td className="px-4 py-3">
                  <span
                    className={`inline-block rounded-md px-2 py-0.5 text-xs font-medium ${PLATFORM_STYLES[p.platform] || "bg-gray-800 text-gray-400"}`}
                  >
                    {p.platform}
                  </span>
                </td>
                <td className="px-4 py-3 text-gray-200">
                  {p.price != null ? `\u20b9${p.price.toFixed(2)}` : "\u2014"}
                </td>
                <td className="px-4 py-3 text-gray-400">
                  {p.mrp != null ? `\u20b9${p.mrp.toFixed(2)}` : "\u2014"}
                </td>
                <td className="px-4 py-3">
                  {p.in_stock ? (
                    <span className="inline-block h-2 w-2 rounded-full bg-emerald-500" />
                  ) : (
                    <span className="inline-block h-2 w-2 rounded-full bg-red-500" />
                  )}
                </td>
                <td className="px-4 py-3 text-gray-400">{p.unit || "\u2014"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      <div className="flex items-center justify-between">
        <p className="text-sm text-gray-500">
          Page {page} of {totalPages}
        </p>
        <div className="flex gap-2">
          <button
            disabled={page <= 1}
            onClick={() => onPageChange(page - 1)}
            className="rounded-lg border border-gray-700 bg-gray-800 px-3 py-1.5 text-sm text-gray-300 transition-colors hover:bg-gray-700 disabled:cursor-not-allowed disabled:opacity-40"
          >
            Previous
          </button>
          <button
            disabled={page >= totalPages}
            onClick={() => onPageChange(page + 1)}
            className="rounded-lg border border-gray-700 bg-gray-800 px-3 py-1.5 text-sm text-gray-300 transition-colors hover:bg-gray-700 disabled:cursor-not-allowed disabled:opacity-40"
          >
            Next
          </button>
        </div>
      </div>
    </div>
  );
}
