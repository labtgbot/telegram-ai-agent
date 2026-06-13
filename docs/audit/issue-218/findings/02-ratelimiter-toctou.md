# Rate limiter: неатомарный check-then-record (TOCTOU) допускает превышение квоты при конкуренции

Родительский контекст: #218

| Поле | Значение |
| --- | --- |
| Критичность | High |
| Stage | Stage 1 - High priority |
| Labels | `security`, `backend`, `stage-1-high`, `complexity-medium` |
| Status | Confirmed |
| GitHub issue | _pending_ |

## Кратко

`RateLimiter._evaluate` сначала отдельным pipeline «подсматривает» счётчики
(`zremrangebyscore`+`zcard`), затем отдельным pipeline записывает событие
(`zadd`). Между чтением и записью нет атомарности: N конкурентных запросов
одновременно проходят проверку «есть место» и затем все пишут запись, превышая
квоту. Эмпирически при `limit=1` пять параллельных вызовов получают 5/5 allowed.

## Доказательства

- `backend/app/services/rate_limiter.py:303-316` — «Round 1»: peek счётчиков
  отдельным `pipeline(transaction=False)`.
- `backend/app/services/rate_limiter.py:345-388` — проверка breach по
  результатам peek.
- `backend/app/services/rate_limiter.py:401-411` — «Round 2»: запись `zadd`
  отдельным pipeline; `transaction=True` делает атомарной только саму запись,
  но не пару check→record.
- Гонка: два запроса видят `count=0` (под лимитом), оба доходят до Round 2 и
  оба пишут, итог `count=2` при `limit=1`.

## Влияние

Любую квоту (per-user, admin-login, генерация) можно превысить всплеском
параллельных запросов: обход anti-bruteforce admin login, перерасход дорогих
генераций, обход анти-абуза. Это нивелирует значительную часть rate-limit
защиты.

## Предлагаемое исправление

- Сделать check-and-record атомарным: единый Lua-скрипт
  (`zremrangebyscore`→`zcard`→условный `zadd`+`expire`), возвращающий
  allowed/remaining/reset.
- Либо `WATCH`/`MULTI`-транзакция с повтором при изменении ключа.
- Покрыть тестом конкуренции (как минимум `limit=1`, 5 параллельных вызовов → 1
  allowed).

## Критерии приёмки

- [ ] При `limit=N` ни одна последовательность параллельных вызовов не
      пропускает больше N запросов в окне.
- [ ] Решение реализовано атомарной серверной операцией Redis.
- [ ] Добавлен тест конкуренции, падающий на текущей реализации.
