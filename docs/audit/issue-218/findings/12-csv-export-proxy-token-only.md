# CSV-export proxy-routes проверяют только наличие токена; middleware по умолчанию analyst

Родительский контекст: #218

| Поле | Значение |
| --- | --- |
| Критичность | Low |
| Stage | Stage 3 - Low priority |
| Labels | `security`, `admin-crm`, `stage-3-low`, `complexity-low` |
| Status | Confirmed |
| GitHub issue | _pending_ |

## Кратко

Next.js proxy-routes для CSV-экспорта проверяют лишь наличие admin-токена, не
минимальную роль. В сочетании с тем, что middleware по умолчанию назначает
`analyst` нелистованным путям, это снижает порог доступа к экспортам PII на
уровне dashboard-прокси.

## Доказательства

- `admin-dashboard/app/api/admin/users/export.csv/route.ts:13-23` — проверка
  только присутствия токена.
- Аналогичный analytics export route.
- `admin-dashboard/middleware.ts:26-33` — дефолтная роль `analyst` для
  нелистованных путей.

## Влияние

Усиливает находку 218-05: даже на уровне dashboard-прокси экспорт CSV доступен
недостаточно привилегированной роли. Дублирующая защита отсутствует.

## Предлагаемое исправление

- В proxy-routes экспорта проверять минимальную роль (как минимум
  `support_admin`) и согласовать с backend-проверкой из 218-05.

## Критерии приёмки

- [ ] CSV-export proxy отвергает запросы ниже требуемой роли.
- [ ] Тест на доступ по ролям к export route.
