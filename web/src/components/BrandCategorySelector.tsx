"use client";

import { useEffect, useRef, useState } from "react";
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
  const [brandInput, setBrandInput] = useState("");
  const [category, setCategory] = useState("");
  const [showSuggestions, setShowSuggestions] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const suggestionsRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    fetchBrands()
      .then((res) => setBrands(res.data))
      .catch(() => setBrands([]));
    fetchCategories()
      .then((res) => setCategories(res.data))
      .catch(() => setCategories([]));
  }, []);

  // Close suggestions on outside click
  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (
        suggestionsRef.current &&
        !suggestionsRef.current.contains(e.target as Node) &&
        inputRef.current &&
        !inputRef.current.contains(e.target as Node)
      ) {
        setShowSuggestions(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  // When a category is selected, restrict suggestions to brands in that category
  const categoryBrands = category
    ? brands.filter((b) => b.categories.includes(category))
    : brands;

  const filtered = brandInput.trim()
    ? categoryBrands.filter((b) =>
        b.name.toLowerCase().includes(brandInput.toLowerCase())
      )
    : categoryBrands.slice(0, 8);

  const canSubmit = brandInput.trim().length > 0 && category.length > 0;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-4">
        {/* Brand combobox */}
        <div className="relative min-w-[220px]">
          <label className="mb-1 block text-sm text-gray-400">Brand</label>
          <input
            ref={inputRef}
            type="text"
            value={brandInput}
            onChange={(e) => {
              setBrandInput(e.target.value);
              setShowSuggestions(true);
            }}
            onFocus={() => setShowSuggestions(true)}
            placeholder="Type any brand name..."
            className="w-full rounded-lg border border-gray-700 bg-gray-800 px-3 py-2 text-sm text-gray-200 placeholder-gray-500 focus:border-emerald-500 focus:outline-none"
          />
          {showSuggestions && (
            <div
              ref={suggestionsRef}
              className="absolute z-10 mt-1 max-h-52 w-full overflow-auto rounded-lg border border-gray-700 bg-gray-900 shadow-lg"
            >
              {filtered.length > 0 ? (
                filtered.map((b) => (
                  <button
                    key={b.name}
                    type="button"
                    onMouseDown={(e) => e.preventDefault()}
                    onClick={() => {
                      setBrandInput(b.name);
                      setShowSuggestions(false);
                    }}
                    className="flex w-full items-center justify-between px-3 py-2 text-left text-sm text-gray-300 hover:bg-gray-800"
                  >
                    <span>{b.name}</span>
                    <span className="text-xs text-gray-500">
                      {b.product_count} products
                    </span>
                  </button>
                ))
              ) : (
                <div className="px-3 py-2 text-xs text-gray-500">
                  No match — will run opportunity analysis for &ldquo;{brandInput}&rdquo;
                </div>
              )}
            </div>
          )}
        </div>

        {/* Category select */}
        <div className="min-w-[200px]">
          <label className="mb-1 block text-sm text-gray-400">Category</label>
          <select
            value={category}
            onChange={(e) => setCategory(e.target.value)}
            className="w-full rounded-lg border border-gray-700 bg-gray-800 px-3 py-2 text-sm text-gray-200 focus:border-emerald-500 focus:outline-none"
          >
            <option value="">Select category...</option>
            {categories.map((c) => (
              <option key={c.name} value={c.name}>
                {c.name} ({c.product_count})
              </option>
            ))}
          </select>
        </div>

        <button
          disabled={!canSubmit}
          onClick={() => onSelect(brandInput.trim(), category)}
          className="rounded-lg bg-emerald-500 px-5 py-2 text-sm font-medium text-white transition-colors hover:bg-emerald-600 disabled:cursor-not-allowed disabled:opacity-50"
        >
          Analyze Opportunities
        </button>
      </div>

      {brandInput.trim() && !categoryBrands.find((b) => b.name === brandInput.trim()) && (
        <p className="text-xs text-amber-400">
          ⚡ &ldquo;{brandInput.trim()}&rdquo; is not in{category ? ` ${category}` : " the database"} — generating market entry
          opportunity analysis based on competitor landscape.
        </p>
      )}
    </div>
  );
}
