"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";
import { putComposioState } from "@/lib/admin-system/browser";
import type { ComposioState } from "@/lib/admin-system/types";
import { formatDateTime } from "@/lib/dashboard/format";

import {
  ErrorBanner,
  Field,
  SuccessBanner,
  humanSystemError,
  textareaClass,
} from "./system-shared";

interface ComposioEditorProps {
  initial: ComposioState;
  canEdit: boolean;
}

function parseTools(raw: string): string[] {
  return raw
    .split(/[\s,;\n]+/)
    .map((t) => t.trim())
    .filter(Boolean);
}

function stringifyConfig(config: Record<string, unknown>): string {
  if (!config || Object.keys(config).length === 0) return "{}";
  return JSON.stringify(config, null, 2);
}

function parseConfig(raw: string): Record<string, unknown> | string {
  const trimmed = raw.trim();
  if (!trimmed) return {};
  let parsed: unknown;
  try {
    parsed = JSON.parse(trimmed);
  } catch (err) {
    return `Invalid JSON: ${(err as Error).message}`;
  }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    return "Config must be a JSON object.";
  }
  return parsed as Record<string, unknown>;
}

export function ComposioEditor({ initial, canEdit }: ComposioEditorProps) {
  const router = useRouter();
  const [tools, setTools] = useState(initial.enabled_tools.join("\n"));
  const [config, setConfig] = useState(() => stringifyConfig(initial.config));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | undefined>();
  const [success, setSuccess] = useState<string | undefined>();

  async function submit() {
    if (!canEdit) return;
    const enabledTools = parseTools(tools);
    const parsedConfig = parseConfig(config);
    if (typeof parsedConfig === "string") {
      setError(parsedConfig);
      return;
    }
    setBusy(true);
    setError(undefined);
    try {
      const response = await putComposioState({
        enabled_tools: enabledTools,
        config: parsedConfig,
      });
      setTools(response.enabled_tools.join("\n"));
      setConfig(stringifyConfig(response.config));
      setSuccess(`Composio config saved (${enabledTools.length} tool${enabledTools.length === 1 ? "" : "s"} enabled).`);
      router.refresh();
    } catch (err) {
      setError(humanSystemError(err, "Failed to save Composio config."));
    } finally {
      setBusy(false);
    }
  }

  const disabled = !canEdit || busy;

  return (
    <section
      aria-label="Composio config"
      className="space-y-4 rounded-card border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900"
    >
      <header>
        <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">
          Composio integrations
        </h2>
        <p className="text-sm text-slate-500 dark:text-slate-400">
          Toggle which Composio tools are exposed to the agent and tune connector-specific options.
        </p>
      </header>

      <ErrorBanner>{error}</ErrorBanner>
      <SuccessBanner>{success}</SuccessBanner>

      <Field
        label={`Enabled tools (${parseTools(tools).length})`}
        hint="One slug per line or comma-separated, e.g. gmail.send_email, github.create_issue."
      >
        <textarea
          rows={4}
          value={tools}
          onChange={(e) => {
            setTools(e.target.value);
            setSuccess(undefined);
            setError(undefined);
          }}
          disabled={disabled}
          className={textareaClass}
          spellCheck={false}
          placeholder={`gmail.send_email
github.create_issue`}
        />
      </Field>

      <Field
        label="Connector config (JSON)"
        hint="Optional per-tool options. Stored verbatim and exposed to the runtime."
      >
        <textarea
          rows={8}
          value={config}
          onChange={(e) => {
            setConfig(e.target.value);
            setSuccess(undefined);
            setError(undefined);
          }}
          disabled={disabled}
          className={textareaClass}
          spellCheck={false}
        />
      </Field>

      <div className="flex flex-wrap items-center justify-between gap-2 border-t border-slate-200 pt-3 dark:border-slate-800">
        <p className="text-xs text-slate-500 dark:text-slate-400">
          {initial.updated_at
            ? `Last changed ${formatDateTime(initial.updated_at)} by admin #${initial.updated_by ?? "?"}.`
            : "Never changed."}
        </p>
        <Button variant="primary" size="md" onClick={submit} disabled={disabled}>
          {busy ? "Saving…" : "Save Composio config"}
        </Button>
      </div>
    </section>
  );
}
