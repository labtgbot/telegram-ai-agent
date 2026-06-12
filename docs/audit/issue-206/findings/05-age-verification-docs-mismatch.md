# Документация age verification описывает несуществующий контракт

Родительский контекст: #206

| Поле | Значение |
| --- | --- |
| Критичность | Low |
| Stage | Stage 3 - Low priority |
| Labels | `bug`, `documentation`, `stage-3-low`, `complexity-low` |
| Status | Confirmed |
| GitHub issue | https://github.com/labtgbot/telegram-ai-agent/issues/212 |

## Кратко

Текущий код открывает feature-flagged age-verification stub на
`/api/v1/user/me/age-verification`. Часть public docs все еще описывает старый
endpoint `POST /compliance/age-verify` и утверждает, что он выставляет
`users.age_verified`, что больше не совпадает с текущим кодом и schema
behavior.

## Доказательства

- `backend/app/api/v1/compliance.py:117-199` реализует
  `GET/POST /user/me/age-verification`.
- `backend/app/api/v1/compliance.py:184-188` явно говорит, что stub не
  persist-ит `age_verified_at` до подключения real provider.
- `docs/API_REFERENCE.md:274-277` документирует
  `POST /compliance/age-verify` и говорит, что он выставляет
  `users.age_verified`.
- `docs/USER_GUIDE.md:188` ссылается на тот же старый
  `POST /compliance/age-verify` flow.
- `docs/legal/AGE_VERIFICATION.md` частично отражает новый path, но все еще
  описывает future persistence semantics, из-за чего guidance противоречивый.

## Влияние

Frontend, QA и external integrators могут вызывать несуществующий endpoint или
писать tests против persistence, которого намеренно пока нет. Operational
severity низкая, потому что текущий production code блокирует provider-less
verification, но это повышает риск ошибок в следующей age-gate работе.

## Предлагаемое исправление

- Обновить `docs/API_REFERENCE.md` и `docs/USER_GUIDE.md`, чтобы они
  использовали
  `/api/v1/user/me/age-verification`.
- Явно пометить текущее поведение как non-persisting, feature-flagged stub.
- Перенести future provider persistence requirements в roadmap/follow-up
  section, не выдавая их за current API behavior.

## Критерии приемки

- [ ] Документация больше не упоминает `POST /compliance/age-verify` как
      текущий endpoint.
- [ ] Текущая документация говорит, что stub возвращает response, но не persist-ит
      `age_verified_at`.
- [ ] Future-provider persistence requirements задокументированы отдельно от
      текущего behavior.
