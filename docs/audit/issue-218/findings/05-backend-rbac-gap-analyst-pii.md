# Backend admin endpoints требуют только «is admin», dashboard гейтит /users до support_admin → analyst читает PII/CSV напрямую

Родительский контекст: #218

| Поле | Значение |
| --- | --- |
| Критичность | Medium |
| Stage | Stage 2 - Medium priority |
| Labels | `security`, `admin-crm`, `backend`, `stage-2-medium`, `complexity-medium` |
| Status | Confirmed |
| GitHub issue | https://github.com/labtgbot/telegram-ai-agent/issues/224 |

## Кратко

Dashboard middleware гейтит страницы `/users`, `/transactions`, `/content` и
т.д. до ролей `support_admin`/`super_admin`. Но это лишь page-gate: backend
endpoints, к которым браузер ходит напрямую, требуют только `get_current_admin`
(любой админ, включая `analyst`). Поэтому наименее привилегированный `analyst`
может, минуя UI, читать список пользователей с PII и выгружать CSV.

## Доказательства

- `admin-dashboard/middleware.ts:12-20` — `ROUTE_ROLES` гейтит `/users` →
  `support_admin`, `/transactions` → `support_admin`, и т.д.; прочее по
  умолчанию `analyst`.
- `backend/app/api/v1/admin_users.py` — `list_users_endpoint` и
  `export_users_csv_endpoint` зависят только от
  `Depends(get_current_admin)` без проверки минимальной роли.
- Браузерный клиент ходит на backend напрямую (`admin-dashboard/lib/api/browser.ts`),
  поэтому page-gate middleware не применяется к этим вызовам.

## Влияние

`analyst` (least-privileged) может получить персональные данные пользователей и
полный CSV-экспорт, хотя UI это скрывает. Нарушение принципа наименьших
привилегий и потенциально — требований к доступу к PII (GDPR).

## Предлагаемое исправление

- Ввести серверную проверку минимальной роли на backend (зависимость
  `require_role(Role.SUPPORT_ADMIN)` и т.п.) для user-list, экспортов,
  transactions, content — синхронно с `ROUTE_ROLES`.
- Зафиксировать единый источник правды для матрицы «endpoint → минимальная
  роль» и покрыть тестами авторизации по ролям.

## Критерии приёмки

- [ ] `analyst` получает 403 на backend user-list/CSV-export/transactions.
- [ ] Матрица ролей backend согласована с dashboard middleware.
- [ ] Тесты проверяют доступ по каждой роли для затронутых endpoints.
