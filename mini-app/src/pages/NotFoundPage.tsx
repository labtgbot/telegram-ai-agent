import { Link } from "react-router-dom";

import { Card } from "@/components/Card";

export function NotFoundPage(): JSX.Element {
  return (
    <Card title="404">
      <p className="mb-3 text-sm">Page not found.</p>
      <Link to="/" className="text-sm text-tg-link underline">
        Go home
      </Link>
    </Card>
  );
}
