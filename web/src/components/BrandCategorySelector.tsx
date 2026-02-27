"use client";

import { useEffect, useState } from "react";
import { fetchBrands, fetchCategories } from "@/lib/api";
import type { Brand, Category } from "@/types";

interface BrandCategorySelectorProps {
  onSelect: (brand: string, category: string) => void;
}

export default function BrandCategorySelector({
  onSelect,
}: BrandCategorySelectorProps) {
  const [brands, setBrands] = useState<Brand[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [brand, setBrand] = useState("");
  const [category, setCategory] = useState("");

  useEffect(() => {
    fetchBrands()
      .then((res) => setBrands(res.data))
      .catch(() => setBrands([]));
    fetchCategories()
      .then((res) => setCategories(res.data))
      .catch(() => setCategories([]));
  }, []);

  const selectedBrand = brands.find((b) => b.name === brand);
  const filteredCategories = selectedBrand
    ? categories.filter((c) => selectedBrand.categories.includes(c.name))
    : categories;

  return (
    <div className="flex flex-wrap items-end gap-4">
      <div>
        <label className="mb-1 block text-sm text-gray-400">Brand</label>
        <select
          value={brand}
          onChange={(e) => {
            setBrand(e.target.value);
            setCategory("");
          }}
          className="rounded-lg border border-gray-700 bg-gray-800 px-3 py-2 text-sm text-gray-200 focus:border-emerald-500 focus:outline-none"
        >
          <option value="">Select brand...</option>
          {brands.map((b) => (
            <option key={b.name} value={b.name}>
              {b.name} ({b.product_count})
            </option>
          ))}
        </select>
      </div>
      <div>
        <label className="mb-1 block text-sm text-gray-400">Category</label>
        <select
          value={category}
          onChange={(e) => setCategory(e.target.value)}
          className="rounded-lg border border-gray-700 bg-gray-800 px-3 py-2 text-sm text-gray-200 focus:border-emerald-500 focus:outline-none"
        >
          <option value="">Select category...</option>
          {filteredCategories.map((c) => (
            <option key={c.name} value={c.name}>
              {c.name} ({c.product_count})
            </option>
          ))}
        </select>
      </div>
      <button
        disabled={!brand || !category}
        onClick={() => onSelect(brand, category)}
        className="rounded-lg bg-emerald-500 px-5 py-2 text-sm font-medium text-white transition-colors hover:bg-emerald-600 disabled:cursor-not-allowed disabled:opacity-50"
      >
        Generate Report
      </button>
    </div>
  );
}
