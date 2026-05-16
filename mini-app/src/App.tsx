import { RouterProvider } from "react-router-dom";

import { router } from "@/router";
import { useTelegramBootstrap } from "@/hooks/useTelegram";

export function App(): JSX.Element {
  useTelegramBootstrap();
  return <RouterProvider router={router} />;
}
