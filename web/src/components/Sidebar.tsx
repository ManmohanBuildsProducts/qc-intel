"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const intelligenceItems = [
  { href: "/brand", label: "Brand HQ", icon: "◆" },
  { href: "/category", label: "Category Intel", icon: "▦" },
];

const navItems = [
  { href: "/", label: "Overview", icon: "|||" },
  { href: "/explorer", label: "Explorer", icon: "tbl" },
  { href: "/reports", label: "AI Reports", icon: "doc" },
];

export default function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="fixed left-0 top-0 flex h-screen w-64 flex-col border-r border-gray-800 bg-gray-900">
      <div className="border-b border-gray-800 px-6 py-5">
        <h1 className="text-lg font-bold tracking-tight text-gray-100">
          <span className="text-emerald-500">QC</span> Intel
        </h1>
        <p className="text-xs text-gray-500">Quick Commerce Intelligence</p>
      </div>
      <nav className="flex-1 px-3 py-4">
        <div className="mb-1 px-3 text-[10px] font-semibold uppercase tracking-widest text-gray-600">
          Intelligence
        </div>
        {intelligenceItems.map((item) => {
          const active = pathname === item.href || pathname.startsWith(item.href + "/");
          return (
            <Link
              key={item.href}
              href={item.href}
              className={`mb-1 flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors ${
                active
                  ? "bg-gray-800 text-emerald-500"
                  : "text-gray-400 hover:bg-gray-800/50 hover:text-gray-200"
              }`}
            >
              <span className="font-mono text-xs">{item.icon}</span>
              {item.label}
            </Link>
          );
        })}
        <div className="mb-1 mt-4 px-3 text-[10px] font-semibold uppercase tracking-widest text-gray-600">
          Data
        </div>
        {navItems.map((item) => {
          const active = pathname === item.href;
          return (
            <Link
              key={item.href}
              href={item.href}
              className={`mb-1 flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors ${
                active
                  ? "bg-gray-800 text-emerald-500"
                  : "text-gray-400 hover:bg-gray-800/50 hover:text-gray-200"
              }`}
            >
              <span className="font-mono text-xs">{item.icon}</span>
              {item.label}
            </Link>
          );
        })}
      </nav>
      <div className="border-t border-gray-800 px-6 py-4">
        <p className="text-xs text-gray-600">v0.1.0</p>
      </div>
    </aside>
  );
}
