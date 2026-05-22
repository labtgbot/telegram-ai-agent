import { Card } from "@/components/Card";

interface BonusListProps {
  dailyAvailable: boolean | undefined;
  hasReferral: boolean;
}

interface BonusRow {
  id: string;
  title: string;
  description: string;
  status: string;
  state: "available" | "claimed" | "locked";
}

function buildRows(dailyAvailable: boolean, hasReferral: boolean): BonusRow[] {
  return [
    {
      id: "daily",
      title: "Ежедневный бонус",
      description: "Заходите каждый день, чтобы получать бесплатные токены.",
      status: dailyAvailable ? "Доступен" : "Уже получен сегодня",
      state: dailyAvailable ? "available" : "claimed",
    },
    {
      id: "referral",
      title: "Реферальная программа",
      description: "Получайте токены за каждого приглашённого друга.",
      status: hasReferral ? "Активна" : "Скопируйте свою ссылку",
      state: hasReferral ? "available" : "locked",
    },
    {
      id: "first-purchase",
      title: "Бонус за первую покупку",
      description: "Начисляется автоматически при первой оплате любого пакета.",
      status: "Авто",
      state: "available",
    },
  ];
}

const STATE_STYLES: Record<BonusRow["state"], string> = {
  available: "bg-tg-button/15 text-tg-button",
  claimed: "bg-tg-separator/40 text-tg-hint",
  locked: "bg-tg-secondary-bg text-tg-hint",
};

export function BonusList({ dailyAvailable, hasReferral }: BonusListProps): JSX.Element {
  const rows = buildRows(Boolean(dailyAvailable), hasReferral);
  return (
    <Card title="Бонусы">
      <ul className="flex flex-col gap-3" data-testid="bonuses">
        {rows.map((row) => (
          <li
            key={row.id}
            className="flex items-start justify-between gap-3"
            data-testid={`bonus-${row.id}`}
          >
            <div className="min-w-0">
              <p className="text-sm font-medium text-tg-text">{row.title}</p>
              <p className="text-xs text-tg-hint">{row.description}</p>
            </div>
            <span
              className={`shrink-0 rounded-full px-2 py-0.5 text-xs font-medium ${STATE_STYLES[row.state]}`}
            >
              {row.status}
            </span>
          </li>
        ))}
      </ul>
    </Card>
  );
}
