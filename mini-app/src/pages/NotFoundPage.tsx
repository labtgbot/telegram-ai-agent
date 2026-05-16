import { Link } from "react-router-dom";

import { Card } from "@/components/Card";
import { useTranslation } from "@/i18n/useTranslation";

export function NotFoundPage(): JSX.Element {
  const { t } = useTranslation();
  return (
    <Card title={t("notFound.title")}>
      <p className="mb-3 text-sm">{t("notFound.body")}</p>
      <Link to="/" className="text-sm text-tg-link underline">
        {t("notFound.cta")}
      </Link>
    </Card>
  );
}
