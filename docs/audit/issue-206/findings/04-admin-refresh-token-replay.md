# Admin refresh tokens переиспользуются после rotation и logout

Родительский контекст: #206

| Поле | Значение |
| --- | --- |
| Критичность | Medium |
| Stage | Stage 2 - Medium priority |
| Labels | `bug`, `backend`, `admin-crm`, `security`, `stage-2-medium`, `complexity-medium` |
| Status | Confirmed |
| GitHub issue | https://github.com/labtgbot/telegram-ai-agent/issues/211 |

## Кратко

Admin refresh endpoint описан как token rotation, но refresh tokens являются
stateless JWT без server-side session, denylist или used-token record. Refresh
возвращает новую token pair, при этом старый refresh token остается валидным до
своего original expiry. Logout только удаляет local cookies в Next.js app.

## Доказательства

- `backend/app/auth/jwt.py:49-68` создает JWT с random `jti`.
- `backend/app/auth/jwt.py:111-152` валидирует signature, expiry, claims и
  token type, но не сверяет `jti` с persisted session state.
- `backend/app/api/v1/auth.py:368-417` декодирует refresh token, валидирует
  user/admin role и возвращает новую token pair.
- `backend/app/api/v1/auth.py:434-453` выпускает fresh access/refresh pair, но
  предыдущий refresh token не отзывается.
- `admin-dashboard/lib/auth/cookies.ts:19-35` хранит refresh token в HttpOnly
  cookie 14 дней.
- `admin-dashboard/app/api/auth/logout/route.ts:5-7` только очищает local
  cookies; backend logout/revoke call отсутствует.

## Влияние

Если admin refresh token украден, attacker может replay-ить его весь
refresh-token lifetime даже после того, как легитимный admin обновил session
или вышел. Система не может revoke-нуть один device/session, обнаружить
refresh-token reuse или принудительно разлогинить после suspicious activity без
rotation глобального JWT secret.

## Предлагаемое исправление

- Хранить refresh sessions server-side через hashed `jti` или session id с user
  id, role, issued-at, expiry, revoked-at и replaced-by metadata.
- На refresh atomically помечать текущий refresh token как used/revoked и
  создавать successor session.
- Отклонять unknown, revoked, expired или already-used refresh `jti`. Reuse
  считать suspicious и отзывать session chain.
- Добавить backend logout/revoke endpoint и вызывать его из admin dashboard до
  очистки cookies.

## Критерии приемки

- [ ] Повторное использование old refresh token после successful refresh
      возвращает 401.
- [ ] Logout отзывает active refresh session server-side.
- [ ] Concurrent refresh attempts не создают несколько valid successor
      sessions.
- [ ] Tests покрывают replay rejection, logout invalidation и
      banned/deactivated admin behavior.
