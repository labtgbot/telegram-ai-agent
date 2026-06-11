"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

type Step = "request" | "verify";

interface RequestCodeResponse {
  delivery: "bot" | "response";
  ttl_seconds: number;
  code: string | null;
}

function postLoginTarget(from: string | null): string {
  if (!from || !from.startsWith("/") || from.startsWith("//") || from.includes("\\")) {
    return "/dashboard";
  }
  return from;
}

export function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const [step, setStep] = useState<Step>("request");
  const [telegramId, setTelegramId] = useState("");
  const [code, setCode] = useState("");
  const [totpCode, setTotpCode] = useState("");
  const [delivery, setDelivery] = useState<RequestCodeResponse | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reasonNotice = useMemo(() => {
    const reason = params.get("reason");
    if (reason === "expired") return "Session expired. Sign in again to continue.";
    if (reason === "invalid") return "Invalid session. Please sign in.";
    if (reason === "forbidden") return "You do not have permission to view that page.";
    return null;
  }, [params]);

  async function requestCode(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setPending(true);
    try {
      const id = Number(telegramId.trim());
      if (!Number.isFinite(id) || id <= 0) {
        throw new Error("Telegram ID must be a positive number.");
      }
      const response = await fetch("/api/auth/login/request", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ telegram_id: id }),
      });
      const payload = (await response.json().catch(() => ({}))) as Partial<RequestCodeResponse> & {
        detail?: string;
      };
      if (!response.ok) {
        throw new Error(payload.detail ?? `Request failed (${response.status}).`);
      }
      setDelivery({
        delivery: payload.delivery ?? "bot",
        ttl_seconds: payload.ttl_seconds ?? 0,
        code: payload.code ?? null,
      });
      setStep("verify");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error.");
    } finally {
      setPending(false);
    }
  }

  async function verifyCode(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setPending(true);
    try {
      const id = Number(telegramId.trim());
      const body: Record<string, unknown> = { telegram_id: id, code: code.trim() };
      if (totpCode.trim()) body.totp_code = totpCode.trim();
      const response = await fetch("/api/auth/login/verify", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const payload = (await response.json().catch(() => ({}))) as { detail?: string };
      if (!response.ok) {
        throw new Error(payload.detail ?? `Verification failed (${response.status}).`);
      }
      router.replace(postLoginTarget(params.get("from")));
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error.");
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="w-full max-w-md space-y-6">
      <header className="space-y-1">
        <h1 className="text-2xl font-semibold text-slate-900 dark:text-slate-100">Admin sign-in</h1>
        <p className="text-sm text-slate-500 dark:text-slate-400">
          Authenticate with your Telegram ID. The bot delivers a one-time code; super-admins also
          enter a TOTP from their authenticator app.
        </p>
      </header>

      {reasonNotice && (
        <div
          role="alert"
          className="rounded-md border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-800"
        >
          {reasonNotice}
        </div>
      )}

      {step === "request" && (
        <form onSubmit={requestCode} className="space-y-4" aria-label="Request login code">
          <label className="block space-y-1 text-sm">
            <span className="font-medium text-slate-700 dark:text-slate-200">Telegram ID</span>
            <Input
              name="telegram_id"
              inputMode="numeric"
              autoComplete="off"
              required
              value={telegramId}
              onChange={(event) => setTelegramId(event.target.value)}
              placeholder="123456789"
            />
          </label>
          <Button type="submit" disabled={pending} className="w-full">
            {pending ? "Sending..." : "Send code"}
          </Button>
        </form>
      )}

      {step === "verify" && (
        <form onSubmit={verifyCode} className="space-y-4" aria-label="Verify login code">
          {delivery?.delivery === "response" && delivery.code && (
            <div className="rounded-md border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-700 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200">
              Dev code: <code className="font-mono">{delivery.code}</code>
            </div>
          )}
          {delivery?.delivery === "bot" && (
            <p className="text-sm text-slate-500 dark:text-slate-400">
              We sent a one-time code to your Telegram. It expires in{" "}
              {Math.max(60, delivery.ttl_seconds)} seconds.
            </p>
          )}
          <label className="block space-y-1 text-sm">
            <span className="font-medium text-slate-700 dark:text-slate-200">One-time code</span>
            <Input
              name="code"
              inputMode="numeric"
              autoComplete="one-time-code"
              required
              value={code}
              onChange={(event) => setCode(event.target.value)}
              placeholder="123456"
            />
          </label>
          <label className="block space-y-1 text-sm">
            <span className="font-medium text-slate-700 dark:text-slate-200">
              TOTP code <span className="text-slate-400">(super-admin only)</span>
            </span>
            <Input
              name="totp_code"
              inputMode="numeric"
              autoComplete="one-time-code"
              value={totpCode}
              onChange={(event) => setTotpCode(event.target.value)}
              placeholder="Optional"
            />
          </label>
          <div className="flex gap-3">
            <Button type="submit" disabled={pending} className="flex-1">
              {pending ? "Verifying..." : "Sign in"}
            </Button>
            <Button
              type="button"
              variant="secondary"
              onClick={() => {
                setStep("request");
                setCode("");
                setTotpCode("");
                setError(null);
              }}
            >
              Back
            </Button>
          </div>
        </form>
      )}

      {error && (
        <p role="alert" className="text-sm text-red-600 dark:text-red-400">
          {error}
        </p>
      )}
    </div>
  );
}
