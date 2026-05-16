# Mini App

Telegram Mini App для **Telegram AI Agent**: React 18 + Vite + TypeScript
(strict) + Telegram WebApp SDK + Tailwind + Zustand + React Router v6.

## Стек

- **Сборка:** Vite 5, TypeScript strict (`tsconfig.app.json`).
- **UI:** React 18, Tailwind CSS с дизайн-токенами, привязанными к
  `WebApp.themeParams` через CSS-переменные.
- **Telegram:** [`@twa-dev/sdk`](https://github.com/twa-dev/SDK) + ленивая
  загрузка `telegram-web-app.js` в `index.html` для запуска внутри Telegram.
- **Маршрутизация:** React Router v6 (`createBrowserRouter`) с layout.
- **State:** Zustand (`store/useThemeStore`, `store/useUserStore`).
- **API клиент:** `services/apiClient.ts` — fetch-обёртка, автоматически
  пробрасывает `X-Telegram-Init-Data` (бэкенд проверяет его в
  `app.auth.dependencies.get_current_user_from_init_data`).
- **Качество:** ESLint + Prettier, Vitest (jsdom) + Testing Library.

## Структура

```
mini-app/
├── index.html
├── src/
│   ├── components/      # Button, Card — переиспользуемый UI
│   ├── hooks/           # useTelegramBootstrap
│   ├── layouts/         # AppLayout (header + outlet + bottom nav)
│   ├── pages/           # Home, Balance, Settings, NotFound
│   ├── services/        # apiClient, telegram (init / theme)
│   ├── store/           # Zustand-слайсы
│   ├── types/           # доменные типы (TelegramThemeParams и др.)
│   ├── App.tsx
│   ├── router.tsx
│   ├── index.css        # Tailwind + CSS-переменные темы
│   └── main.tsx
├── tests/               # Vitest: компоненты, store, apiClient, theme
└── public/
```

## Quickstart

```bash
cd mini-app
cp .env.example .env       # настроить VITE_API_BASE_URL
npm install
npm run dev                # vite на http://localhost:5173
```

Тестирование внутри Telegram: задеплойте dev-сервер (например, через
`ngrok`) и установите ссылку как Mini App в `@BotFather` (`/setmenubutton`
или `Menu Button -> Web App`).

## Скрипты

| Команда             | Что делает                                |
| ------------------- | ----------------------------------------- |
| `npm run dev`       | Vite dev-server                           |
| `npm run build`     | TypeScript build + Vite production bundle |
| `npm run preview`   | Локальный preview production-сборки       |
| `npm run lint`      | ESLint (strict, `--max-warnings 0`)       |
| `npm run typecheck` | `tsc -b --noEmit`                         |
| `npm run test`      | Vitest, jsdom                             |
| `npm run format`    | Prettier write                            |

## Telegram theme

`useTelegramBootstrap` вызывает `WebApp.ready()` / `.expand()`, читает
`WebApp.themeParams` и `WebApp.colorScheme` и записывает их в CSS-переменные
(`--tg-color-*`). При смене темы в Telegram срабатывает событие
`themeChanged` — переменные пересчитываются автоматически. Tailwind-классы
`bg-tg-bg`, `text-tg-text`, `border-tg-separator` и т. д. читают эти
переменные, так что UI всегда совпадает с темой клиента (light/dark/custom).

Вне Telegram (например, при локальной разработке в браузере) SDK работает в
no-op режиме, и используются значения по умолчанию из `index.css`.

## API клиент и initData

`ApiClient` (см. `src/services/apiClient.ts`) — единая точка для запросов к
бэкенду. На каждый запрос автоматически добавляется заголовок
`X-Telegram-Init-Data`, который backend проверяет (HMAC + TTL) в
`get_current_user_from_init_data`. Базовый URL берётся из
`VITE_API_BASE_URL` (см. `.env.example`).

Пример:

```ts
import { apiClient } from "@/services/apiClient";

const me = await apiClient.get<UserPublic>("/users/me");
const invoice = await apiClient.post<InvoiceLink>("/payments/invoice", {
  pack_id: "starter",
});
```

При ошибке (>=400) выбрасывается `ApiError` с `status` и распарсенным
телом ответа.

## Docs

- [Telegram Mini Apps](https://core.telegram.org/bots/webapps)
- `docs/API_REFERENCE.md`
- `docs/TOKEN_ECONOMY.md`
