import { RouterProvider } from "react-router-dom";

import { router } from "@/router";
import { useTelegramBootstrap } from "@/hooks/useTelegram";
import { ConsentBanner } from "@/components/ConsentBanner";

export function App(): JSX.Element {
  useTelegramBootstrap();
  return (
    <>
      <RouterProvider router={router} />
      <ConsentBanner />
    </>
  );
}
