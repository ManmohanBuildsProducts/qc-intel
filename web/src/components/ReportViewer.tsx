"use client";

import ReactMarkdown from "react-markdown";

interface ReportViewerProps {
  content: string;
  compact?: boolean;
}

export default function ReportViewer({ content, compact = false }: ReportViewerProps) {
  if (compact) {
    return (
      <div className="prose prose-sm prose-invert max-w-none prose-headings:text-gray-200 prose-p:text-gray-300 prose-strong:text-gray-200 prose-li:text-gray-300">
        <ReactMarkdown>{content}</ReactMarkdown>
      </div>
    );
  }

  const sections = content.split(/(?=^## )/m).filter(Boolean);

  if (sections.length <= 1) {
    return (
      <div className="rounded-xl border border-gray-800 bg-gray-900 p-6">
        <div className="prose prose-invert max-w-none prose-headings:text-gray-100 prose-p:text-gray-300 prose-strong:text-gray-200 prose-li:text-gray-300">
          <ReactMarkdown>{content}</ReactMarkdown>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {sections.map((section, i) => (
        <div
          key={i}
          className="rounded-xl border border-gray-800 bg-gray-900 p-6"
        >
          <div className="prose prose-invert max-w-none prose-headings:text-gray-100 prose-p:text-gray-300 prose-strong:text-gray-200 prose-li:text-gray-300">
            <ReactMarkdown>{section}</ReactMarkdown>
          </div>
        </div>
      ))}
    </div>
  );
}
