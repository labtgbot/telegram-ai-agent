# CI: несогласованные pinned-версии actions/checkout (v4 vs v6)

Родительский контекст: #218

| Поле | Значение |
| --- | --- |
| Критичность | Low |
| Stage | Stage 3 - Low priority |
| Labels | `devops`, `stage-3-low`, `complexity-low` |
| Status | Confirmed |
| GitHub issue | https://github.com/labtgbot/telegram-ai-agent/issues/248 |

## Кратко

Большинство workflow'ов закрепляют `actions/checkout` на SHA версии v6, но
load-smoke-test и e2e job'ы используют SHA версии v4. Версии запинены (хорошо),
но рассинхронизованы — часть job'ов недополучает обновления/патчи.

## Доказательства

- `.github/workflows/backend.yml:288` — `actions/checkout@34e11...  # v4`.
- `.github/workflows/mini-app.yml:87` — `actions/checkout@34e11...  # v4`.
- Прочие workflow'ы — `actions/checkout@df4cb1...  # v6`.

## Влияние

Несогласованность supply-chain: одни job'ы используют устаревшую версию
checkout. Сам по себе не уязвимость, но гигиенический долг и риск расхождения
поведения.

## Предлагаемое исправление

- Привести все `actions/checkout` к единой запиненной версии (SHA), желательно
  через единый dependabot/renovate-конфиг.

## Критерии приёмки

- [ ] Все workflow'ы используют одну запиненную версию `actions/checkout`.
