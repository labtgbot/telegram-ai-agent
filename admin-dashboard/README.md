# Admin Dashboard

Next.js 14 + TypeScript. Профессиональная CRM для управления ботом.

## Layout

```
admin-dashboard/
├── app/                # App Router
│   ├── (auth)/login
│   ├── dashboard/
│   ├── users/
│   ├── transactions/
│   ├── pricing/
│   ├── analytics/
│   ├── broadcast/
│   └── settings/
├── components/
├── lib/                # API клиент, auth
├── styles/
└── package.json
```

## Quickstart

```bash
npm install
npm run dev
```

## Auth

JWT-based, с обязательной 2FA для super-admin. Подробнее — `docs/SECURITY.md`.

## Docs

- `docs/ADMIN_CRM_GUIDE.md`
- `docs/API_REFERENCE.md`
- `docs/ANALYTICS.md` (будет добавлен в Phase 3)
