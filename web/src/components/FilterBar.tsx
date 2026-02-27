"use client";

import { useEffect, useState } from "react";
import { fetchBrands, fetchCategories } from "@/lib/api";
import type { Brand, Category } from "@/types";

const PLATFORMS = [
  { name: "Blinkit", color: "bg-[#F8CB46] text-gray-900" },
  { name: "Zepto", color: "bg-[#7B2FBF] text-white" },
  { name: "Instamart", color: "bg-[#FC8019] text-white" },
];

interface FilterBarProps {
  onFilterChange: (filters: {
    brand: string;
    category: string;
    platform: string;
  }) => void;
}

export default function FilterBar({ onFilterChange }: FilterBarProps) {
  const [brands, setBrands] = useState<Brand[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [brand, setBrand] = useState("");
  const [category, setCategory] = useState("");
  const [platform, setPlatform] = useState("");

  useEffect(() => {
    fetchBrands()
      .then((res) => setBrands(res.data))
      .catch(() => setBrands([]));
    fetchCategories()
      .then((res) => setCategories(res.data))
      .catch(() => setCategories([]));
  }, []);

  useEffect(() => {
    onFilterChange({ brand, category, platform });
  }, [brand, category, platform, onFilterChange]);

  return (
    <div className="flex flex-wrap items-center gap-3">
      <select
        value={brand}
        onChange={(e) => setBrand(e.target.value)}
        className="rounded-lg border border-gray-700 bg-gray-800 px-3 py-2 text-sm text-gray-200 focus:border-emerald-500 focus:outline-none"
      >
        <option value="">All Brands</option>
        {brands.map((b) => (
          <option key={b.name} value={b.name}>
            {b.name}
          </option>
        ))}
      </select>
      <select
        value={category}
        onChange={(e) => setCategory(e.target.value)}
        className="rounded-lg border border-gray-700 bg-gray-800 px-3 py-2 text-sm text-gray-200 focus:border-emerald-500 focus:outline-none"
      >
        <option value="">All Categories</option>
        {categories.map((c) => (
          <option key={c.name} value={c.name}>
            {c.name}
          </option>
        ))}
      </select>
      <div className="flex gap-1">
        {PLATFORMS.map((p) => (
          <button
            key={p.name}
            onClick={() => setPlatform(platform === p.name ? "" : p.name)}
            className={`rounded-lg px-3 py-2 text-xs font-medium transition-colors ${
              platform === p.name
                ? p.color
                : "border border-gray-700 bg-gray-800 text-gray-400 hover:text-gray-200"
            }`}
          >
            {p.name}
          </button>
        ))}
      </div>
    </div>
  );
}
