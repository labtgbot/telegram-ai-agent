import type { ReactElement } from "react";
import { useState } from "react";

import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { Select } from "@/components/Select";
import { Switch } from "@/components/Switch";
import { useTranslation } from "@/i18n/useTranslation";
import { userApi } from "@/services/userApi";
import type { AiResponseSize } from "@/store/useSettingsStore";
import { useSettingsStore } from "@/store/useSettingsStore";
import { useThemeStore } from "@/store/useThemeStore";
import { useUserStore } from "@/store/useUserStore";
import type { LanguagePreference } from "@/i18n";

type Status =
  | { kind: "idle" }
  | { kind: "ok"; message: string }
  | { kind: "error"; message: string };

const idle: Status = { kind: "idle" };

function isEmail(value: string): boolean {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value);
}

export function SettingsPage(): ReactElement {
  const { t } = useTranslation();
  const scheme = useThemeStore((s) => s.scheme);
  const user = useUserStore((s) => s.user);
  const resetUser = useUserStore((s) => s.reset);

  const language = useSettingsStore((s) => s.language);
  const notificationsEnabled = useSettingsStore((s) => s.notificationsEnabled);
  const aiResponseSize = useSettingsStore((s) => s.aiResponseSize);
  const setLanguage = useSettingsStore((s) => s.setLanguage);
  const setNotifications = useSettingsStore((s) => s.setNotificationsEnabled);
  const setAiResponseSize = useSettingsStore((s) => s.setAiResponseSize);

  const [exportEmail, setExportEmail] = useState("");
  const [exportStatus, setExportStatus] = useState<Status>(idle);
  const [exportSubmitting, setExportSubmitting] = useState(false);

  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [deleteStatus, setDeleteStatus] = useState<Status>(idle);
  const [deleteSubmitting, setDeleteSubmitting] = useState(false);

  const languageOptions: ReadonlyArray<{ value: LanguagePreference; label: string }> = [
    { value: "auto", label: t("settings.languageAuto") },
    { value: "en", label: t("settings.languageEn") },
    { value: "ru", label: t("settings.languageRu") },
  ];

  const aiSizeOptions: ReadonlyArray<{ value: AiResponseSize; label: string }> = [
    { value: "short", label: t("settings.aiResponseShort") },
    { value: "medium", label: t("settings.aiResponseMedium") },
    { value: "long", label: t("settings.aiResponseLong") },
  ];

  const requestExport = async (): Promise<void> => {
    setExportStatus(idle);
    if (!isEmail(exportEmail)) {
      setExportStatus({ kind: "error", message: t("common.requiredEmail") });
      return;
    }
    setExportSubmitting(true);
    try {
      await userApi.requestDataExport({ email: exportEmail });
      setExportStatus({ kind: "ok", message: t("settings.dataExportSuccess") });
      setExportEmail("");
    } catch {
      setExportStatus({ kind: "error", message: t("settings.dataExportError") });
    } finally {
      setExportSubmitting(false);
    }
  };

  const confirmDelete = async (): Promise<void> => {
    setDeleteSubmitting(true);
    setDeleteStatus(idle);
    try {
      await userApi.deleteAccount();
      setDeleteStatus({ kind: "ok", message: t("settings.deleteAccountSuccess") });
      setDeleteDialogOpen(false);
      resetUser();
    } catch {
      setDeleteStatus({ kind: "error", message: t("settings.deleteAccountError") });
    } finally {
      setDeleteSubmitting(false);
    }
  };

  return (
    <div className="space-y-4">
      <Card title={t("settings.appearance")}>
        <dl className="text-sm">
          <div className="flex items-center justify-between py-2">
            <dt className="text-tg-hint">{t("settings.theme")}</dt>
            <dd className="font-medium capitalize" data-testid="settings-scheme">
              {scheme}
            </dd>
          </div>
        </dl>
        <Select
          label={t("settings.language")}
          value={language}
          onChange={(next) => setLanguage(next)}
          options={languageOptions}
          id="settings-language"
        />
      </Card>

      <Card title={t("settings.notifications")}>
        <Switch
          label={t("settings.notifications")}
          description={t("settings.notificationsBody")}
          checked={notificationsEnabled}
          onChange={setNotifications}
          id="settings-notifications"
        />
      </Card>

      <Card title={t("settings.aiResponseSize")}>
        <Select
          label={t("settings.aiResponseSize")}
          description={t("settings.aiResponseSizeBody")}
          value={aiResponseSize}
          onChange={(next) => setAiResponseSize(next)}
          options={aiSizeOptions}
          id="settings-ai-response-size"
        />
      </Card>

      <Card title={t("settings.security")}>
        <dl className="text-sm">
          <div className="flex items-center justify-between py-2">
            <dt className="text-tg-hint">{t("settings.twoFactor")}</dt>
            <dd className="font-medium" data-testid="settings-2fa">
              {user?.totp_enabled
                ? t("settings.twoFactorEnabled")
                : t("settings.twoFactorDisabled")}
            </dd>
          </div>
        </dl>

        <div className="mt-4 border-t border-tg-separator pt-4">
          <h3 className="text-sm font-semibold">{t("settings.dataExport")}</h3>
          <p className="mt-1 text-xs text-tg-hint">{t("settings.dataExportBody")}</p>
          <label htmlFor="settings-export-email" className="mt-3 block text-xs text-tg-hint">
            {t("settings.dataExportEmail")}
          </label>
          <input
            id="settings-export-email"
            type="email"
            value={exportEmail}
            onChange={(event) => setExportEmail(event.target.value)}
            placeholder="you@example.com"
            className="mt-1 w-full rounded-tg border border-tg-separator bg-tg-bg px-3 py-2 text-sm text-tg-text focus:outline-none focus:ring-2 focus:ring-tg-accent"
          />
          <div className="mt-3 flex items-center justify-between gap-3">
            {exportStatus.kind !== "idle" ? (
              <p
                className={`text-xs ${exportStatus.kind === "ok" ? "text-tg-accent" : "text-tg-destructive"}`}
                role={exportStatus.kind === "error" ? "alert" : "status"}
                data-testid="export-status"
              >
                {exportStatus.message}
              </p>
            ) : (
              <span />
            )}
            <Button onClick={() => void requestExport()} disabled={exportSubmitting}>
              {t("settings.dataExportSubmit")}
            </Button>
          </div>
        </div>

        <div className="mt-4 border-t border-tg-separator pt-4">
          <h3 className="text-sm font-semibold">{t("settings.deleteAccount")}</h3>
          <p className="mt-1 text-xs text-tg-hint">{t("settings.deleteAccountBody")}</p>
          {deleteStatus.kind !== "idle" ? (
            <p
              className={`mt-2 text-xs ${deleteStatus.kind === "ok" ? "text-tg-accent" : "text-tg-destructive"}`}
              role={deleteStatus.kind === "error" ? "alert" : "status"}
              data-testid="delete-status"
            >
              {deleteStatus.message}
            </p>
          ) : null}
          <div className="mt-3 flex justify-end">
            <Button variant="destructive" onClick={() => setDeleteDialogOpen(true)}>
              {t("settings.deleteAccountCta")}
            </Button>
          </div>
        </div>
      </Card>

      <ConfirmDialog
        open={deleteDialogOpen}
        title={t("settings.deleteAccountConfirmTitle")}
        body={t("settings.deleteAccountConfirmBody")}
        confirmLabel={t("settings.deleteAccountCta")}
        cancelLabel={t("common.cancel")}
        requireText={t("settings.deleteAccountConfirmInput")}
        onConfirm={() => void confirmDelete()}
        onCancel={() => setDeleteDialogOpen(false)}
        confirming={deleteSubmitting}
      />
    </div>
  );
}
