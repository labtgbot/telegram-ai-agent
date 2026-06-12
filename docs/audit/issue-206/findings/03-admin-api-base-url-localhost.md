# Admin dashboard по умолчанию обращается к localhost API в production

Родительский контекст: #206

| Поле | Значение |
| --- | --- |
| Критичность | High |
| Stage | Stage 1 - High priority |
| Labels | `bug`, `admin-crm`, `devops`, `stage-1-high`, `complexity-medium` |
| Status | Confirmed |
| GitHub issue | https://github.com/labtgbot/telegram-ai-agent/issues/210 |

## Кратко

Next.js admin dashboard fallback-ится на `http://localhost:8000/api/v1` для
browser и server API calls. Helm и production compose не задают `API_BASE_URL`
или `NEXT_PUBLIC_API_BASE_URL`, поэтому production admin container может пройти
health checks, но login и API proxy calls будут обращаться к localhost внутри
admin pod/container.

## Доказательства

- `admin-dashboard/lib/env.ts:4-6` задает
  `NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1"`.
- `admin-dashboard/lib/env.ts:43-48` задает server-side
  `API_BASE_URL ?? publicEnv.apiBaseUrl`.
- `admin-dashboard/lib/api/server.ts` и
  `admin-dashboard/app/api/auth/refresh/route.ts` строят upstream admin API
  calls из `serverEnv().apiBaseUrl`.
- `deploy/helm/telegram-ai-agent/templates/admin-deployment.yaml:39-47` задает
  напрямую только `PORT` и `NODE_ENV`, затем импортирует shared secret. Он не
  рендерит `API_BASE_URL` или `NEXT_PUBLIC_API_BASE_URL`.
- `deploy/helm/telegram-ai-agent/values.yaml:208-225` и
  `deploy/helm/telegram-ai-agent/values-production.yaml:89-97` не имеют admin
  API base URL settings.
- `docker/compose.prod.yml:134-149` задает только `PORT` и `NODE_ENV` для
  admin service и не требует API base URL env vars.
- `.env.example:35-36` все еще содержит localhost defaults для admin dashboard.

## Влияние

Admin dashboard может быть развернут и помечен ready, но admin login, refresh,
data pages, CSV exports и browser-side API calls будут падать, потому что
dashboard пытается достучаться до backend на собственном localhost. Оператор
должен вручную знать про undocumented env vars вне chart/compose path, а ошибка
не ловится на startup.

## Предлагаемое исправление

- Добавить явные `admin.apiBaseUrl` / `admin.publicApiBaseUrl` values в Helm
  chart и рендерить их в `API_BASE_URL` и `NEXT_PUBLIC_API_BASE_URL`.
- Задать production defaults, соответствующие ingress/service topology, либо
  требовать значения на render time.
- Добавить production guard в `admin-dashboard/lib/env.ts`, который отклоняет
  localhost API URLs при `NODE_ENV=production`.
- Обновить compose production env validation и `.env.example`.

## Критерии приемки

- [ ] Production admin deployment рендерит non-localhost `API_BASE_URL` и
      `NEXT_PUBLIC_API_BASE_URL` либо падает на template validation, если они
      не заданы.
- [ ] Admin dashboard отказывается стартовать в production с localhost API
      defaults.
- [ ] Compose production требует те же env vars.
- [ ] Tests или render checks покрывают missing и valid production API URL config.
