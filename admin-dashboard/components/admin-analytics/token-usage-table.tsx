"use client";

import { formatInteger } from "@/lib/dashboard/format";
import type { TokenUsagePoint } from "@/lib/admin-analytics/types";

interface TokenUsageTableProps {
  services: TokenUsagePoint[];
  totalRequests: number;
  totalTokensSpent: number;
}

function formatPct(value: number): string {
  return `${(value * 100).toFixed(1)}%`;
}

const SERVICE_LABELS: Record<string, string> = {
  text_generation: "Text generation",
  image_generation: "Image generation",
  audio_generation: "Audio generation",
  video_generation: "Video generation",
  embedding: "Embedding",
  moderation: "Moderation",
};

function labelOf(service: string): string {
  return SERVICE_LABELS[service] ?? service.replaceAll("_", " ");
}

export function TokenUsageTable({
  services,
  totalRequests,
  totalTokensSpent,
}: TokenUsageTableProps) {
  if (services.length === 0) {
    return (
      <p className="text-sm text-slate-500 dark:text-slate-400">
        No token spend in the selected range.
      </p>
    );
  }
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full text-sm">
        <thead className="text-xs uppercase tracking-wide text-slate-500 dark:text-slate-400">
          <tr>
            <th scope="col" className="px-3 py-2 text-left font-medium">
              Service
            </th>
            <th scope="col" className="px-3 py-2 text-right font-medium">
              Requests
            </th>
            <th scope="col" className="px-3 py-2 text-right font-medium">
              Tokens
            </th>
            <th scope="col" className="px-3 py-2 text-left font-medium">
              Share
            </th>
          </tr>
        </thead>
        <tbody>
          {services.map((row) => {
            const widthPct = Math.max(2, Math.min(100, row.share * 100));
            return (
              <tr
                key={row.service_type}
                className="border-t border-slate-200 dark:border-slate-800"
              >
                <td className="px-3 py-2 font-medium text-slate-800 dark:text-slate-100">
                  {labelOf(row.service_type)}
                </td>
                <td className="px-3 py-2 text-right text-slate-700 dark:text-slate-200">
                  {formatInteger(row.requests)}
                </td>
                <td className="px-3 py-2 text-right text-slate-700 dark:text-slate-200">
                  {formatInteger(row.tokens_spent)}
                </td>
                <td className="px-3 py-2">
                  <div className="flex items-center gap-2">
                    <div className="h-2 w-32 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
                      <div
                        className="h-full rounded-full bg-indigo-500"
                        style={{ width: `${widthPct}%` }}
                        aria-hidden
                      />
                    </div>
                    <span className="w-12 text-right text-xs text-slate-500 dark:text-slate-400">
                      {formatPct(row.share)}
                    </span>
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
        <tfoot className="border-t-2 border-slate-300 text-sm font-medium dark:border-slate-700">
          <tr>
            <td className="px-3 py-2 text-slate-700 dark:text-slate-200">Total</td>
            <td className="px-3 py-2 text-right text-slate-900 dark:text-slate-100">
              {formatInteger(totalRequests)}
            </td>
            <td className="px-3 py-2 text-right text-slate-900 dark:text-slate-100">
              {formatInteger(totalTokensSpent)}
            </td>
            <td className="px-3 py-2" />
          </tr>
        </tfoot>
      </table>
    </div>
  );
}
