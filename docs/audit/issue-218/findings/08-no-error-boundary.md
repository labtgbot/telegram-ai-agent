# Mini-app: нет React error boundary / router errorElement → падение обнуляет весь экран

Родительский контекст: #218

| Поле | Значение |
| --- | --- |
| Критичность | Medium |
| Stage | Stage 2 - Medium priority |
| Labels | `bug`, `frontend`, `stage-2-medium`, `complexity-low` |
| Status | Confirmed |
| GitHub issue | _pending_ |

## Кратко

В mini-app нет ни одного React error boundary и ни одного router `errorElement`.
Любая ошибка рендера или сбой загрузки lazy-chunk (типично на мобильных при
плохой сети) приводит к полностью белому экрану без возможности восстановления.

## Доказательства

- Поиск по `mini-app/src` не находит `ErrorBoundary`, `componentDidCatch`, ни
  `errorElement` (grep пуст).
- `mini-app/src/App.tsx`, `main.tsx`, `router.tsx`, `routePages.tsx:3-21` —
  lazy-загрузка страниц без error fallback.

## Влияние

Единичная ошибка рендера/загрузки чанка обрушивает всё приложение в белый экран
без диагностики и без кнопки повтора — особенно болезненно для Telegram Mini App
на нестабильной мобильной сети.

## Предлагаемое исправление

- Добавить корневой error boundary с fallback-UI и кнопкой «перезагрузить».
- Задать `errorElement` на route-уровне (react-router) для перехвата ошибок
  загрузки/рендера страниц.
- Логировать ошибки (Sentry/console) для диагностики.

## Критерии приёмки

- [ ] Брошенная в дочернем компоненте ошибка показывает fallback, а не белый
      экран.
- [ ] Сбой загрузки lazy-chunk обрабатывается с возможностью повтора.
- [ ] Тест на error boundary/`errorElement`.
