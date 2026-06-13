# Образы инфра-сервисов закреплены по version-only тегам

Родительский контекст: #218

| Поле | Значение |
| --- | --- |
| Критичность | Low |
| Stage | Stage 3 - Low priority |
| Labels | `devops`, `stage-3-low`, `complexity-low` |
| Status | Confirmed |
| GitHub issue | _pending_ |

## Кратко

В `docker/compose.prod.yml` сторонние инфра-образы закреплены по version-only
тегам (`caddy:2.8-alpine`, `postgres:15-alpine`, `redis:7-alpine`). Такие теги
мутабельны: при разных деплоях могут подтянуться разные patch-версии — деплой
недетерминирован (remediation #148 касался app-образов и `:latest`, но не
patch-level pinning инфра-сервисов).

## Доказательства

- `docker/compose.prod.yml:53` — `caddy:2.8-alpine`.
- `docker/compose.prod.yml:266` — `postgres:15-alpine`.
- `docker/compose.prod.yml:298` — `redis:7-alpine`.

## Влияние

Недетерминированные обновления базовых сервисов между деплоями: внезапные
изменения поведения/патчей без явного контроля версий.

## Предлагаемое исправление

- Пиновать образы по digest (`@sha256:...`) или фиксированному patch-тегу;
  обновлять контролируемо через dependabot/renovate.

## Критерии приёмки

- [ ] Инфра-образы закреплены детерминированно (digest/patch-tag).
- [ ] Обновления версий проходят через контролируемый процесс.
