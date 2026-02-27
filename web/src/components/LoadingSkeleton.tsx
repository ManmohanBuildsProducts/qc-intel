"use client";

export function LoadingSkeleton({ lines = 4 }: { lines?: number }) {
  return (
    <div className="space-y-3">
      {Array.from({ length: lines }).map((_, i) => (
        <div
          key={i}
          className="h-4 animate-pulse rounded bg-gray-800"
          style={{ width: `${85 - i * 10}%` }}
        />
      ))}
    </div>
  );
}

export function CardSkeleton() {
  return (
    <div className="rounded-xl border border-gray-800 bg-gray-900 p-6">
      <div className="mb-2 h-4 w-24 animate-pulse rounded bg-gray-800" />
      <div className="h-8 w-16 animate-pulse rounded bg-gray-800" />
    </div>
  );
}

export function ReportSkeleton() {
  return (
    <div className="space-y-6">
      {Array.from({ length: 3 }).map((_, i) => (
        <div
          key={i}
          className="rounded-xl border border-gray-800 bg-gray-900 p-6"
        >
          <div className="mb-4 h-6 w-48 animate-pulse rounded bg-gray-800" />
          <div className="space-y-2">
            <div className="h-4 w-full animate-pulse rounded bg-gray-800" />
            <div className="h-4 w-5/6 animate-pulse rounded bg-gray-800" />
            <div className="h-4 w-4/6 animate-pulse rounded bg-gray-800" />
          </div>
        </div>
      ))}
    </div>
  );
}
