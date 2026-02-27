"use client";

interface StatsCardProps {
  icon: string;
  label: string;
  value: number | string;
}

export default function StatsCard({ icon, label, value }: StatsCardProps) {
  return (
    <div className="rounded-xl border border-gray-800 bg-gray-900 p-6">
      <div className="mb-1 text-sm text-gray-400">
        <span className="mr-2">{icon}</span>
        {label}
      </div>
      <div className="text-3xl font-bold text-gray-100">{value}</div>
    </div>
  );
}
