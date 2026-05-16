import { Card } from "@/components/Card";
import { useThemeStore } from "@/store/useThemeStore";

export function SettingsPage(): JSX.Element {
  const scheme = useThemeStore((s) => s.scheme);

  return (
    <Card title="Settings">
      <dl className="text-sm">
        <div className="flex items-center justify-between py-2">
          <dt className="text-tg-hint">Theme</dt>
          <dd className="font-medium capitalize">{scheme}</dd>
        </div>
        <div className="flex items-center justify-between py-2">
          <dt className="text-tg-hint">Language</dt>
          <dd className="font-medium">Auto (Telegram)</dd>
        </div>
      </dl>
    </Card>
  );
}
