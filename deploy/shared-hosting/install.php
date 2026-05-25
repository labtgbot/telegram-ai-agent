<?php
declare(strict_types=1);

const TGAI_INSTALLER_VERSION = '1.0';
const TGAI_DEFAULT_APP_VERSION = '0.1.0';

function tgai_installer_fields(): array
{
    return [
        'public' => [
            'title' => 'Public URLs',
            'description' => 'Domains and public URLs used by Telegram, the Mini App, and the admin panel.',
            'fields' => [
                [
                    'name' => 'domain',
                    'label' => 'Bot / Mini App domain',
                    'type' => 'text',
                    'required' => true,
                    'placeholder' => 'bot.example.com',
                    'help' => 'Main HTTPS domain. The webhook will use https://domain/api/v1/bot/webhook.',
                ],
                [
                    'name' => 'admin_domain',
                    'label' => 'Admin dashboard domain',
                    'type' => 'text',
                    'required' => true,
                    'placeholder' => 'admin.example.com',
                ],
                [
                    'name' => 'telegram_mini_app_url',
                    'label' => 'Telegram Mini App URL',
                    'type' => 'url',
                    'required' => true,
                    'placeholder' => 'https://bot.example.com/',
                    'help' => 'HTTPS URL configured in BotFather as the Web App URL.',
                ],
                [
                    'name' => 'vite_api_base_url',
                    'label' => 'Mini App API URL',
                    'type' => 'text',
                    'required' => true,
                    'placeholder' => 'https://bot.example.com/api/v1',
                ],
                [
                    'name' => 'next_public_api_base_url',
                    'label' => 'Admin browser API URL',
                    'type' => 'text',
                    'required' => true,
                    'placeholder' => 'https://bot.example.com/api/v1',
                ],
                [
                    'name' => 'api_base_url',
                    'label' => 'Admin server API URL',
                    'type' => 'text',
                    'required' => true,
                    'placeholder' => 'http://backend:8000/api/v1',
                ],
                [
                    'name' => 'acme_email',
                    'label' => 'ACME email',
                    'type' => 'email',
                    'required' => true,
                    'placeholder' => 'ops@example.com',
                    'help' => 'Used by Caddy / Let us Encrypt in the single-host Docker deployment.',
                ],
            ],
        ],
        'hosting' => [
            'title' => 'Shared hosting and MySQL',
            'description' => 'Checks the PHP/MySQL hosting account and stores installer metadata when requested.',
            'fields' => [
                [
                    'name' => 'mysql_host',
                    'label' => 'MySQL host',
                    'type' => 'text',
                    'required' => false,
                    'placeholder' => 'localhost',
                ],
                [
                    'name' => 'mysql_port',
                    'label' => 'MySQL port',
                    'type' => 'number',
                    'required' => false,
                    'placeholder' => '3306',
                ],
                [
                    'name' => 'mysql_database',
                    'label' => 'MySQL database',
                    'type' => 'text',
                    'required' => false,
                    'placeholder' => 'telegram_ai_agent_installer',
                ],
                [
                    'name' => 'mysql_user',
                    'label' => 'MySQL user',
                    'type' => 'text',
                    'required' => false,
                ],
                [
                    'name' => 'mysql_password',
                    'label' => 'MySQL password',
                    'type' => 'password',
                    'required' => false,
                ],
                [
                    'name' => 'mysql_table_prefix',
                    'label' => 'Installer table prefix',
                    'type' => 'text',
                    'required' => false,
                    'placeholder' => 'tgai_',
                    'help' => 'Only letters, digits, and underscores are used.',
                ],
                [
                    'name' => 'store_installation_metadata',
                    'label' => 'Store redacted installer metadata in MySQL',
                    'type' => 'checkbox',
                    'required' => false,
                ],
            ],
        ],
        'runtime' => [
            'title' => 'Application runtime',
            'description' => 'The current application backend runs on Python/FastAPI with PostgreSQL and Redis.',
            'fields' => [
                [
                    'name' => 'app_version',
                    'label' => 'Application version / image tag',
                    'type' => 'text',
                    'required' => true,
                    'placeholder' => TGAI_DEFAULT_APP_VERSION,
                ],
                [
                    'name' => 'database_url',
                    'label' => 'PostgreSQL DATABASE_URL',
                    'type' => 'text',
                    'required' => true,
                    'placeholder' => 'postgresql+asyncpg://postgres:password@postgres:5432/telegram_ai_agent',
                    'help' => 'MySQL is not a backend database for this app yet. Use PostgreSQL for the FastAPI runtime.',
                ],
                [
                    'name' => 'postgres_password',
                    'label' => 'Bundled PostgreSQL password',
                    'type' => 'password',
                    'required' => false,
                    'help' => 'Used by docker/compose.prod.yml when PostgreSQL runs in Compose.',
                ],
                [
                    'name' => 'redis_url',
                    'label' => 'REDIS_URL',
                    'type' => 'text',
                    'required' => true,
                    'placeholder' => 'redis://redis:6379/0',
                ],
                [
                    'name' => 'backend_image',
                    'label' => 'Backend image',
                    'type' => 'text',
                    'required' => true,
                ],
                [
                    'name' => 'mini_app_image',
                    'label' => 'Mini App image',
                    'type' => 'text',
                    'required' => true,
                ],
                [
                    'name' => 'admin_image',
                    'label' => 'Admin image',
                    'type' => 'text',
                    'required' => true,
                ],
            ],
        ],
        'telegram' => [
            'title' => 'Telegram and BotFather',
            'description' => 'Bot token, webhook secret, and Mini App settings.',
            'fields' => [
                [
                    'name' => 'telegram_bot_token',
                    'label' => 'TELEGRAM_BOT_TOKEN',
                    'type' => 'password',
                    'required' => true,
                    'placeholder' => '123456:ABCDEF',
                ],
                [
                    'name' => 'telegram_bot_username',
                    'label' => 'Bot username without @',
                    'type' => 'text',
                    'required' => true,
                    'placeholder' => 'telegram_ai_agent_bot',
                ],
                [
                    'name' => 'telegram_webhook_secret',
                    'label' => 'TELEGRAM_WEBHOOK_SECRET',
                    'type' => 'password',
                    'required' => true,
                    'help' => 'Generated value is fine. Telegram sends it as X-Telegram-Bot-Api-Secret-Token.',
                ],
                [
                    'name' => 'telegram_api_base_url',
                    'label' => 'Telegram API base URL',
                    'type' => 'url',
                    'required' => true,
                    'placeholder' => 'https://api.telegram.org',
                ],
                [
                    'name' => 'telegram_set_commands_on_startup',
                    'label' => 'Backend sets bot commands on startup',
                    'type' => 'checkbox',
                    'required' => false,
                ],
                [
                    'name' => 'set_webhook_now',
                    'label' => 'Call setWebhook from this installer after generation',
                    'type' => 'checkbox',
                    'required' => false,
                    'help' => 'Requires outbound HTTPS from the hosting account.',
                ],
            ],
        ],
        'secrets' => [
            'title' => 'Admin, AI providers, payments',
            'description' => 'Secrets and optional service keys. Empty provider keys disable real calls where supported.',
            'fields' => [
                [
                    'name' => 'app_secret',
                    'label' => 'APP_SECRET',
                    'type' => 'password',
                    'required' => true,
                ],
                [
                    'name' => 'admin_jwt_secret',
                    'label' => 'ADMIN_JWT_SECRET',
                    'type' => 'password',
                    'required' => true,
                ],
                [
                    'name' => 'admin_super_telegram_ids',
                    'label' => 'Initial super-admin Telegram IDs',
                    'type' => 'text',
                    'required' => false,
                    'placeholder' => '123456789,987654321',
                ],
                [
                    'name' => 'gemini_api_key',
                    'label' => 'GEMINI_API_KEY',
                    'type' => 'password',
                    'required' => false,
                ],
                [
                    'name' => 'anthropic_api_key',
                    'label' => 'ANTHROPIC_API_KEY',
                    'type' => 'password',
                    'required' => false,
                ],
                [
                    'name' => 'openai_api_key',
                    'label' => 'OPENAI_API_KEY',
                    'type' => 'password',
                    'required' => false,
                ],
                [
                    'name' => 'composio_api_key',
                    'label' => 'COMPOSIO_API_KEY',
                    'type' => 'password',
                    'required' => false,
                ],
                [
                    'name' => 'payment_currency',
                    'label' => 'PAYMENT_CURRENCY',
                    'type' => 'text',
                    'required' => true,
                    'placeholder' => 'XTR',
                ],
                [
                    'name' => 'payment_provider_token',
                    'label' => 'PAYMENT_PROVIDER_TOKEN',
                    'type' => 'password',
                    'required' => false,
                    'help' => 'Usually empty for Telegram Stars-only XTR payments.',
                ],
                [
                    'name' => 'sentry_dsn',
                    'label' => 'SENTRY_DSN',
                    'type' => 'password',
                    'required' => false,
                ],
                [
                    'name' => 'sentry_environment',
                    'label' => 'SENTRY_ENVIRONMENT',
                    'type' => 'text',
                    'required' => false,
                    'placeholder' => 'production',
                ],
            ],
        ],
    ];
}

function tgai_default_values(): array
{
    $secret = static fn (): string => bin2hex(random_bytes(32));
    $postgresPassword = bin2hex(random_bytes(16));

    return [
        'domain' => 'bot.example.com',
        'admin_domain' => 'admin.example.com',
        'telegram_mini_app_url' => 'https://bot.example.com/',
        'vite_api_base_url' => 'https://bot.example.com/api/v1',
        'next_public_api_base_url' => 'https://bot.example.com/api/v1',
        'api_base_url' => 'http://backend:8000/api/v1',
        'acme_email' => 'ops@example.com',
        'mysql_host' => 'localhost',
        'mysql_port' => '3306',
        'mysql_database' => '',
        'mysql_user' => '',
        'mysql_password' => '',
        'mysql_table_prefix' => 'tgai_',
        'store_installation_metadata' => '0',
        'app_version' => TGAI_DEFAULT_APP_VERSION,
        'database_url' => 'postgresql+asyncpg://postgres:' . $postgresPassword . '@postgres:5432/telegram_ai_agent',
        'postgres_password' => $postgresPassword,
        'redis_url' => 'redis://redis:6379/0',
        'backend_image' => 'ghcr.io/labtgbot/telegram-ai-agent/backend:' . TGAI_DEFAULT_APP_VERSION,
        'mini_app_image' => 'ghcr.io/labtgbot/telegram-ai-agent/mini-app:' . TGAI_DEFAULT_APP_VERSION,
        'admin_image' => 'ghcr.io/labtgbot/telegram-ai-agent/admin:' . TGAI_DEFAULT_APP_VERSION,
        'telegram_bot_token' => '',
        'telegram_bot_username' => '',
        'telegram_webhook_secret' => $secret(),
        'telegram_api_base_url' => 'https://api.telegram.org',
        'telegram_set_commands_on_startup' => '1',
        'set_webhook_now' => '0',
        'app_secret' => $secret(),
        'admin_jwt_secret' => $secret(),
        'admin_super_telegram_ids' => '',
        'gemini_api_key' => '',
        'anthropic_api_key' => '',
        'openai_api_key' => '',
        'composio_api_key' => '',
        'payment_currency' => 'XTR',
        'payment_provider_token' => '',
        'sentry_dsn' => '',
        'sentry_environment' => 'production',
    ];
}

function tgai_all_field_names(): array
{
    $names = [];
    foreach (tgai_installer_fields() as $step) {
        foreach (($step['fields'] ?? []) as $field) {
            $names[] = $field['name'];
        }
    }

    return $names;
}

function tgai_checkbox_fields(): array
{
    $names = [];
    foreach (tgai_installer_fields() as $step) {
        foreach (($step['fields'] ?? []) as $field) {
            if (($field['type'] ?? '') === 'checkbox') {
                $names[] = $field['name'];
            }
        }
    }

    return $names;
}

function tgai_normalize_domain(string $domain): string
{
    $domain = trim($domain);
    $domain = preg_replace('#^https?://#i', '', $domain) ?? $domain;
    $domain = trim($domain, "/ \t\n\r\0\x0B");

    return strtolower($domain);
}

function tgai_normalize_url(string $url): string
{
    $url = trim($url);
    if ($url !== '' && !preg_match('#^https?://#i', $url)) {
        $url = 'https://' . $url;
    }

    return $url;
}

function tgai_bool_value(mixed $value): string
{
    if (is_bool($value)) {
        return $value ? 'true' : 'false';
    }

    $normal = strtolower(trim((string) $value));
    return in_array($normal, ['1', 'true', 'yes', 'on'], true) ? 'true' : 'false';
}

function tgai_normalize_installer_input(array $input): array
{
    $data = array_merge(tgai_default_values(), $input);

    foreach (tgai_all_field_names() as $name) {
        if (in_array($name, tgai_checkbox_fields(), true)) {
            $data[$name] = tgai_bool_value($data[$name] ?? '0');
            continue;
        }

        $data[$name] = trim((string) ($data[$name] ?? ''));
    }

    $data['domain'] = tgai_normalize_domain($data['domain']);
    $data['admin_domain'] = tgai_normalize_domain($data['admin_domain']);
    $data['telegram_api_base_url'] = rtrim(tgai_normalize_url($data['telegram_api_base_url']), '/');

    if ($data['telegram_mini_app_url'] === '' && $data['domain'] !== '') {
        $data['telegram_mini_app_url'] = 'https://' . $data['domain'] . '/';
    }
    $data['telegram_mini_app_url'] = tgai_normalize_url($data['telegram_mini_app_url']);

    if ($data['vite_api_base_url'] === '' && $data['domain'] !== '') {
        $data['vite_api_base_url'] = 'https://' . $data['domain'] . '/api/v1';
    }
    if ($data['next_public_api_base_url'] === '' && $data['domain'] !== '') {
        $data['next_public_api_base_url'] = 'https://' . $data['domain'] . '/api/v1';
    }
    if ($data['api_base_url'] === '') {
        $data['api_base_url'] = 'http://backend:8000/api/v1';
    }

    $data['mysql_port'] = preg_replace('/[^0-9]/', '', $data['mysql_port']) ?: '3306';
    $data['mysql_table_prefix'] = preg_replace('/[^A-Za-z0-9_]/', '', $data['mysql_table_prefix']) ?: 'tgai_';
    $data['payment_currency'] = strtoupper($data['payment_currency'] ?: 'XTR');
    $data['sentry_environment'] = $data['sentry_environment'] ?: 'production';

    $version = $data['app_version'] ?: TGAI_DEFAULT_APP_VERSION;
    foreach (['backend_image' => 'backend', 'mini_app_image' => 'mini-app', 'admin_image' => 'admin'] as $field => $imageName) {
        if ($data[$field] === '') {
            $data[$field] = 'ghcr.io/labtgbot/telegram-ai-agent/' . $imageName . ':' . $version;
        }
    }

    return $data;
}

function tgai_validate_installer_data(array $data, ?string $stepKey = null): array
{
    $errors = [];
    $steps = tgai_installer_fields();
    $stepsToCheck = $stepKey === null ? $steps : [$stepKey => $steps[$stepKey] ?? []];

    foreach ($stepsToCheck as $step) {
        foreach (($step['fields'] ?? []) as $field) {
            $name = $field['name'];
            $required = (bool) ($field['required'] ?? false);
            $value = trim((string) ($data[$name] ?? ''));
            if ($required && $value === '') {
                $errors[] = ($field['label'] ?? $name) . ' is required.';
            }
            if (($field['type'] ?? '') === 'url' && $value !== '' && !filter_var($value, FILTER_VALIDATE_URL)) {
                $errors[] = ($field['label'] ?? $name) . ' must be a valid URL.';
            }
            if (($field['type'] ?? '') === 'email' && $value !== '' && !filter_var($value, FILTER_VALIDATE_EMAIL)) {
                $errors[] = ($field['label'] ?? $name) . ' must be a valid email address.';
            }
        }
    }

    if (($stepKey === null || $stepKey === 'runtime') && !str_starts_with($data['database_url'], 'postgresql+asyncpg://')) {
        $errors[] = 'DATABASE_URL must use postgresql+asyncpg://. MySQL is only used by this installer metadata.';
    }

    return $errors;
}

function tgai_env_escape(string $value): string
{
    if ($value === '') {
        return '';
    }

    if (!preg_match('/[\s#"\'\\\\]/', $value)) {
        return $value;
    }

    return '"' . strtr($value, [
        "\\" => "\\\\",
        '"' => '\\"',
        "\n" => "\\n",
        "\r" => "\\r",
    ]) . '"';
}

function tgai_env_line(string $key, mixed $value): string
{
    return $key . '=' . tgai_env_escape((string) $value) . "\n";
}

function tgai_build_env_content(array $data): string
{
    $data = tgai_normalize_installer_input($data);
    $lines = [
        '# Generated by deploy/shared-hosting/install.php',
        '# Do not commit this file. Store it as .env.prod on the deployment host.',
        '',
    ];

    $groups = [
        'Telegram' => [
            'TELEGRAM_BOT_TOKEN' => $data['telegram_bot_token'],
            'TELEGRAM_BOT_USERNAME' => $data['telegram_bot_username'],
            'TELEGRAM_WEBHOOK_SECRET' => $data['telegram_webhook_secret'],
            'TELEGRAM_MINI_APP_URL' => $data['telegram_mini_app_url'],
            'TELEGRAM_API_BASE_URL' => $data['telegram_api_base_url'],
            'TELEGRAM_SIGNUP_BONUS_TOKENS' => '50',
            'TELEGRAM_SET_COMMANDS_ON_STARTUP' => $data['telegram_set_commands_on_startup'],
        ],
        'Backend' => [
            'APP_ENV' => 'production',
            'APP_SECRET' => $data['app_secret'],
            'APP_DEBUG' => 'false',
            'LOG_LEVEL' => 'INFO',
            'LOG_FORMAT' => 'json',
            'API_V1_PREFIX' => '/api/v1',
            'HEALTH_CHECK_TIMEOUT' => '2.0',
        ],
        'Production Docker Compose routing / images' => [
            'DOMAIN' => $data['domain'],
            'ADMIN_DOMAIN' => $data['admin_domain'],
            'ACME_EMAIL' => $data['acme_email'],
            'POSTGRES_PASSWORD' => $data['postgres_password'],
            'BACKEND_IMAGE' => $data['backend_image'],
            'MINI_APP_IMAGE' => $data['mini_app_image'],
            'ADMIN_IMAGE' => $data['admin_image'],
        ],
        'Frontend/API URLs' => [
            'VITE_API_BASE_URL' => $data['vite_api_base_url'],
            'NEXT_PUBLIC_API_BASE_URL' => $data['next_public_api_base_url'],
            'API_BASE_URL' => $data['api_base_url'],
        ],
        'Database' => [
            'DATABASE_URL' => $data['database_url'],
        ],
        'Redis' => [
            'REDIS_URL' => $data['redis_url'],
        ],
        'Composio MCP' => [
            'COMPOSIO_API_KEY' => $data['composio_api_key'],
            'COMPOSIO_DEFAULT_USER_ID' => '',
            'COMPOSIO_BASE_URL' => 'https://backend.composio.dev',
            'COMPOSIO_TIMEOUT_SECONDS' => '30.0',
            'COMPOSIO_MAX_RETRIES' => '3',
            'COMPOSIO_BACKOFF_BASE_SECONDS' => '0.5',
            'COMPOSIO_BACKOFF_MAX_SECONDS' => '8.0',
            'COMPOSIO_DEFAULT_TOOLKITS' => 'gemini,composio_search,image_gen,video_gen',
        ],
        'AI Providers' => [
            'GEMINI_API_KEY' => $data['gemini_api_key'],
            'ANTHROPIC_API_KEY' => $data['anthropic_api_key'],
            'OPENAI_API_KEY' => $data['openai_api_key'],
        ],
        'Admin' => [
            'ADMIN_JWT_SECRET' => $data['admin_jwt_secret'],
            'ADMIN_JWT_ALGORITHM' => 'HS256',
            'ADMIN_ACCESS_TOKEN_TTL' => '900',
            'ADMIN_REFRESH_TOKEN_TTL' => '604800',
            'ADMIN_LOGIN_CODE_TTL' => '300',
            'ADMIN_LOGIN_CODE_LENGTH' => '6',
            'ADMIN_LOGIN_MAX_ATTEMPTS' => '5',
            'ADMIN_SUPER_TELEGRAM_IDS' => $data['admin_super_telegram_ids'],
            'TOTP_ISSUER' => 'Telegram AI Agent',
            'TELEGRAM_INIT_DATA_MAX_AGE' => '86400',
        ],
        'Payments' => [
            'PAYMENT_PROVIDER_TOKEN' => $data['payment_provider_token'],
            'PAYMENT_CURRENCY' => $data['payment_currency'],
        ],
        'Monitoring' => [
            'METRICS_ENABLED' => 'true',
            'METRICS_PATH' => '/metrics',
            'METRICS_ACTIVE_USER_WINDOW_SECONDS' => '300',
            'SENTRY_DSN' => $data['sentry_dsn'],
            'SENTRY_ENVIRONMENT' => $data['sentry_environment'],
            'SENTRY_RELEASE' => $data['app_version'],
            'SENTRY_TRACES_SAMPLE_RATE' => '0.1',
            'SENTRY_PROFILES_SAMPLE_RATE' => '0.0',
        ],
    ];

    foreach ($groups as $title => $vars) {
        $lines[] = '# ' . $title;
        foreach ($vars as $key => $value) {
            $lines[] = rtrim(tgai_env_line($key, $value), "\n");
        }
        $lines[] = '';
    }

    return implode("\n", $lines);
}

function tgai_build_mini_app_env(array $data): string
{
    $data = tgai_normalize_installer_input($data);

    return implode('', [
        tgai_env_line('VITE_API_BASE_URL', $data['vite_api_base_url']),
        tgai_env_line('VITE_SENTRY_DSN', $data['sentry_dsn']),
        tgai_env_line('VITE_SENTRY_ENVIRONMENT', $data['sentry_environment']),
        tgai_env_line('VITE_SENTRY_RELEASE', $data['app_version']),
        tgai_env_line('VITE_SENTRY_TRACES_SAMPLE_RATE', '0.1'),
        tgai_env_line('VITE_SENTRY_REPLAYS_SESSION_SAMPLE_RATE', '0'),
        tgai_env_line('VITE_SENTRY_REPLAYS_ON_ERROR_SAMPLE_RATE', '0'),
    ]);
}

function tgai_build_admin_env(array $data): string
{
    $data = tgai_normalize_installer_input($data);

    return implode('', [
        tgai_env_line('NEXT_PUBLIC_API_BASE_URL', $data['next_public_api_base_url']),
        tgai_env_line('ADMIN_JWT_SECRET', $data['admin_jwt_secret']),
        tgai_env_line('ADMIN_JWT_ALGORITHM', 'HS256'),
        tgai_env_line('API_BASE_URL', $data['api_base_url']),
        tgai_env_line('NEXT_PUBLIC_SENTRY_DSN', $data['sentry_dsn']),
        tgai_env_line('SENTRY_DSN', $data['sentry_dsn']),
        tgai_env_line('NEXT_PUBLIC_SENTRY_ENVIRONMENT', $data['sentry_environment']),
        tgai_env_line('SENTRY_ENVIRONMENT', $data['sentry_environment']),
        tgai_env_line('NEXT_PUBLIC_SENTRY_RELEASE', $data['app_version']),
        tgai_env_line('SENTRY_RELEASE', $data['app_version']),
        tgai_env_line('NEXT_PUBLIC_SENTRY_TRACES_SAMPLE_RATE', '0.1'),
        tgai_env_line('SENTRY_TRACES_SAMPLE_RATE', '0.1'),
        tgai_env_line('NEXT_PUBLIC_SENTRY_REPLAYS_SESSION_SAMPLE_RATE', '0'),
        tgai_env_line('NEXT_PUBLIC_SENTRY_REPLAYS_ON_ERROR_SAMPLE_RATE', '0'),
    ]);
}

function tgai_shell_quote(string $value): string
{
    return "'" . str_replace("'", "'\"'\"'", $value) . "'";
}

function tgai_webhook_url(array $data): string
{
    $data = tgai_normalize_installer_input($data);

    return 'https://' . $data['domain'] . '/api/v1/bot/webhook';
}

function tgai_build_webhook_script(array $data): string
{
    $data = tgai_normalize_installer_input($data);
    $webhookUrl = tgai_webhook_url($data);

    return implode("\n", [
        '#!/usr/bin/env sh',
        'set -eu',
        '',
        'TELEGRAM_API_BASE_URL=' . tgai_shell_quote($data['telegram_api_base_url']),
        'TELEGRAM_BOT_TOKEN=' . tgai_shell_quote($data['telegram_bot_token']),
        'TELEGRAM_WEBHOOK_URL=' . tgai_shell_quote($webhookUrl),
        'TELEGRAM_WEBHOOK_SECRET=' . tgai_shell_quote($data['telegram_webhook_secret']),
        '',
        'curl -fsS -X POST "${TELEGRAM_API_BASE_URL}/bot${TELEGRAM_BOT_TOKEN}/setWebhook" \\',
        '  -d "url=${TELEGRAM_WEBHOOK_URL}" \\',
        '  -d "secret_token=${TELEGRAM_WEBHOOK_SECRET}"',
        '',
        'curl -fsS "${TELEGRAM_API_BASE_URL}/bot${TELEGRAM_BOT_TOKEN}/getWebhookInfo"',
        '',
    ]);
}

function tgai_build_botfather_checklist(array $data): string
{
    $data = tgai_normalize_installer_input($data);

    return implode("\n", [
        '# BotFather checklist',
        '',
        'Bot: @' . ltrim($data['telegram_bot_username'], '@'),
        '',
        '1. Open @BotFather.',
        '2. Run /setdomain and set:',
        '   https://' . $data['domain'],
        '3. Run /setmenubutton and set the Web App URL:',
        '   ' . $data['telegram_mini_app_url'],
        '4. Publish bot commands if automatic startup command sync is disabled.',
        '5. Verify the webhook URL after deploy:',
        '   ' . tgai_webhook_url($data),
        '',
    ]);
}

function tgai_redacted_value(string $name, mixed $value): mixed
{
    $secretMarkers = ['token', 'secret', 'password', 'key', 'dsn'];
    $lower = strtolower($name);
    foreach ($secretMarkers as $marker) {
        if (str_contains($lower, $marker) && trim((string) $value) !== '') {
            return '***redacted***';
        }
    }

    return $value;
}

function tgai_redacted_config(array $data): array
{
    $redacted = [];
    foreach ($data as $key => $value) {
        $redacted[$key] = tgai_redacted_value((string) $key, $value);
    }

    return $redacted;
}

function tgai_build_summary(array $data): string
{
    $data = tgai_normalize_installer_input($data);
    $redacted = tgai_redacted_config($data);
    $json = json_encode($redacted, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES);

    return implode("\n", [
        '# Telegram AI Agent shared hosting install summary',
        '',
        'Generated at: ' . gmdate('c'),
        '',
        '## Public endpoints',
        '',
        '- Mini App: ' . $data['telegram_mini_app_url'],
        '- API: ' . $data['vite_api_base_url'],
        '- Admin: https://' . $data['admin_domain'] . '/',
        '- Webhook: ' . tgai_webhook_url($data),
        '',
        '## Runtime note',
        '',
        'The shared-hosting PHP/MySQL installer prepares configuration and can store redacted installation metadata.',
        'It does not convert the current FastAPI backend to PHP or MySQL. The application runtime still requires Python/FastAPI, PostgreSQL, and Redis as described in docs/DEPLOYMENT.md.',
        '',
        '## Generated files',
        '',
        '- .env.prod: production env file for docker/compose.prod.yml or an equivalent managed runtime.',
        '- mini-app.env: build-time variables for mini-app/.env.',
        '- admin-dashboard.env: variables for admin-dashboard/.env.',
        '- telegram-webhook.sh: repeatable webhook registration command.',
        '- botfather-checklist.md: manual BotFather checklist.',
        '',
        '## Redacted configuration',
        '',
        '```json',
        is_string($json) ? $json : '{}',
        '```',
        '',
    ]);
}

function tgai_write_file(string $path, string $content, int $mode): void
{
    if (file_put_contents($path, $content) === false) {
        throw new RuntimeException('Could not write ' . $path);
    }
    chmod($path, $mode);
}

function tgai_write_generated_files(string $baseDir, array $data): array
{
    $data = tgai_normalize_installer_input($data);
    if (!is_dir($baseDir) && !mkdir($baseDir, 0700, true)) {
        throw new RuntimeException('Could not create ' . $baseDir);
    }

    $files = [
        '.env.prod' => [tgai_build_env_content($data), 0600],
        'mini-app.env' => [tgai_build_mini_app_env($data), 0600],
        'admin-dashboard.env' => [tgai_build_admin_env($data), 0600],
        'telegram-webhook.sh' => [tgai_build_webhook_script($data), 0700],
        'botfather-checklist.md' => [tgai_build_botfather_checklist($data), 0644],
        'install-summary.md' => [tgai_build_summary($data), 0644],
    ];

    $written = [];
    foreach ($files as $name => [$content, $mode]) {
        $path = rtrim($baseDir, DIRECTORY_SEPARATOR) . DIRECTORY_SEPARATOR . $name;
        tgai_write_file($path, $content, $mode);
        $written[$name] = $path;
    }

    return $written;
}

function tgai_check_requirements(): array
{
    $checks = [
        [
            'label' => 'PHP 8.1+',
            'ok' => version_compare(PHP_VERSION, '8.1.0', '>='),
            'detail' => PHP_VERSION,
        ],
    ];

    foreach (['json', 'curl', 'mbstring', 'openssl', 'pdo', 'pdo_mysql', 'session'] as $extension) {
        $checks[] = [
            'label' => 'PHP extension: ' . $extension,
            'ok' => extension_loaded($extension),
            'detail' => extension_loaded($extension) ? 'loaded' : 'missing',
        ];
    }

    $checks[] = [
        'label' => 'Writable installer directory',
        'ok' => is_writable(__DIR__),
        'detail' => __DIR__,
    ];

    $https = (!empty($_SERVER['HTTPS']) && $_SERVER['HTTPS'] !== 'off')
        || (($_SERVER['HTTP_X_FORWARDED_PROTO'] ?? '') === 'https');
    $checks[] = [
        'label' => 'HTTPS request',
        'ok' => $https || PHP_SAPI === 'cli',
        'detail' => $https ? 'yes' : 'not detected',
        'warning' => true,
    ];

    return $checks;
}

function tgai_mysql_dsn(array $data): string
{
    $host = $data['mysql_host'] ?: 'localhost';
    $port = $data['mysql_port'] ?: '3306';
    $db = $data['mysql_database'];

    return 'mysql:host=' . $host . ';port=' . $port . ';dbname=' . $db . ';charset=utf8mb4';
}

function tgai_has_mysql_credentials(array $data): bool
{
    return trim((string) ($data['mysql_host'] ?? '')) !== ''
        && trim((string) ($data['mysql_database'] ?? '')) !== ''
        && trim((string) ($data['mysql_user'] ?? '')) !== '';
}

function tgai_test_mysql_connection(array $data): array
{
    $data = tgai_normalize_installer_input($data);
    if (!tgai_has_mysql_credentials($data)) {
        return ['ok' => false, 'message' => 'MySQL credentials are incomplete.'];
    }

    try {
        $pdo = new PDO(tgai_mysql_dsn($data), $data['mysql_user'], $data['mysql_password'], [
            PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
            PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
        ]);
        $pdo->query('SELECT 1');

        return ['ok' => true, 'message' => 'MySQL connection succeeded.'];
    } catch (Throwable $error) {
        return ['ok' => false, 'message' => 'MySQL connection failed: ' . $error->getMessage()];
    }
}

function tgai_record_installation_metadata(array $data): array
{
    $data = tgai_normalize_installer_input($data);
    if ($data['store_installation_metadata'] !== 'true') {
        return ['ok' => true, 'message' => 'MySQL metadata storage skipped.'];
    }

    $connection = tgai_test_mysql_connection($data);
    if (!$connection['ok']) {
        return $connection;
    }

    try {
        $pdo = new PDO(tgai_mysql_dsn($data), $data['mysql_user'], $data['mysql_password'], [
            PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
        ]);
        $table = '`' . $data['mysql_table_prefix'] . 'installations`';
        $pdo->exec(
            "CREATE TABLE IF NOT EXISTS {$table} ("
            . "id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,"
            . "created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,"
            . "app_version VARCHAR(64) NOT NULL,"
            . "domain VARCHAR(255) NOT NULL,"
            . "admin_domain VARCHAR(255) NOT NULL,"
            . "redacted_config JSON NOT NULL"
            . ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"
        );
        $payload = json_encode(tgai_redacted_config($data), JSON_UNESCAPED_SLASHES);
        $stmt = $pdo->prepare(
            "INSERT INTO {$table} (app_version, domain, admin_domain, redacted_config) "
            . 'VALUES (:app_version, :domain, :admin_domain, :redacted_config)'
        );
        $stmt->execute([
            ':app_version' => $data['app_version'],
            ':domain' => $data['domain'],
            ':admin_domain' => $data['admin_domain'],
            ':redacted_config' => is_string($payload) ? $payload : '{}',
        ]);

        return ['ok' => true, 'message' => 'Redacted metadata was written to MySQL.'];
    } catch (Throwable $error) {
        return ['ok' => false, 'message' => 'Could not store metadata: ' . $error->getMessage()];
    }
}

function tgai_call_telegram_api(string $method, array $data): array
{
    $data = tgai_normalize_installer_input($data);
    $url = $data['telegram_api_base_url'] . '/bot' . $data['telegram_bot_token'] . '/' . $method;
    $ch = curl_init($url);
    if ($ch === false) {
        return ['ok' => false, 'message' => 'Could not initialize curl.'];
    }

    curl_setopt_array($ch, [
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_POST => true,
        CURLOPT_POSTFIELDS => [
            'url' => tgai_webhook_url($data),
            'secret_token' => $data['telegram_webhook_secret'],
        ],
        CURLOPT_TIMEOUT => 20,
    ]);

    $body = curl_exec($ch);
    $error = curl_error($ch);
    $status = (int) curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
    curl_close($ch);

    if ($body === false) {
        return ['ok' => false, 'message' => 'Telegram API request failed: ' . $error];
    }

    $decoded = json_decode((string) $body, true);
    if (!is_array($decoded) || ($decoded['ok'] ?? false) !== true) {
        return [
            'ok' => false,
            'message' => 'Telegram API returned HTTP ' . $status . ': ' . substr((string) $body, 0, 500),
        ];
    }

    return ['ok' => true, 'message' => 'Telegram ' . $method . ' succeeded.'];
}

function tgai_html(string $value): string
{
    return htmlspecialchars($value, ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8');
}

function tgai_current_step_keys(): array
{
    return array_keys(tgai_installer_fields());
}

function tgai_render_header(string $title): void
{
    echo '<!doctype html><html lang="en"><head><meta charset="utf-8">';
    echo '<meta name="viewport" content="width=device-width, initial-scale=1">';
    echo '<link rel="icon" href="data:,">';
    echo '<title>' . tgai_html($title) . '</title>';
    echo '<style>';
    echo 'body{margin:0;font-family:Inter,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:#f7f7f8;color:#1f2937}';
    echo 'main{max-width:980px;margin:0 auto;padding:32px 20px 56px}.shell{background:#fff;border:1px solid #e5e7eb;border-radius:8px;box-shadow:0 12px 40px rgba(15,23,42,.08);overflow:hidden}';
    echo 'header{padding:28px 32px;border-bottom:1px solid #e5e7eb;background:#111827;color:white}h1{font-size:28px;margin:0 0 8px}h2{font-size:22px;margin:0 0 8px}.muted{color:#6b7280}.panel{padding:28px 32px}.notice{padding:14px 16px;border-radius:8px;margin:16px 0;background:#eff6ff;border:1px solid #bfdbfe;color:#1e3a8a}.warn{background:#fff7ed;border-color:#fed7aa;color:#9a3412}.error{background:#fef2f2;border-color:#fecaca;color:#991b1b}.ok{background:#ecfdf5;border-color:#a7f3d0;color:#065f46}';
    echo '.steps{display:flex;gap:8px;flex-wrap:wrap;margin:0 0 24px}.step{padding:8px 11px;border:1px solid #d1d5db;border-radius:999px;text-decoration:none;color:#374151;font-size:14px}.step.active{background:#111827;color:#fff;border-color:#111827}';
    echo '.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px}.field{display:flex;flex-direction:column;gap:6px}.field.full{grid-column:1/-1}label{font-weight:650}input,textarea,select{font:inherit;border:1px solid #d1d5db;border-radius:6px;padding:10px 12px;background:white}textarea{min-height:96px}.help{font-size:13px;color:#6b7280}.actions{display:flex;justify-content:space-between;gap:12px;margin-top:28px}.button{border:0;background:#111827;color:white;border-radius:6px;padding:11px 16px;text-decoration:none;font-weight:700;cursor:pointer}.button.secondary{background:#e5e7eb;color:#111827}.button.danger{background:#991b1b}table{display:block;width:100%;border-collapse:collapse;overflow-x:auto;white-space:nowrap}td,th{padding:10px;border-bottom:1px solid #e5e7eb;text-align:left}code,pre{background:#f3f4f6;border-radius:6px}pre{padding:14px;overflow:auto}.check{display:flex;align-items:center;gap:10px}.check input{width:auto}';
    echo '@media(max-width:720px){main{padding:16px 10px}.panel,header{padding:22px 18px}.grid{grid-template-columns:1fr}.actions{flex-direction:column}.button{text-align:center}}';
    echo '</style></head><body><main><div class="shell">';
    echo '<header><h1>Telegram AI Agent installer</h1><div>Shared hosting PHP/MySQL configuration wizard</div></header>';
}

function tgai_render_footer(): void
{
    echo '</div></main></body></html>';
}

function tgai_render_steps(string $active): void
{
    $labels = ['requirements' => 'Requirements'] + array_map(
        static fn (array $step): string => $step['title'],
        tgai_installer_fields()
    ) + ['review' => 'Review'];

    echo '<nav class="steps">';
    foreach ($labels as $key => $label) {
        $class = $key === $active ? 'step active' : 'step';
        echo '<a class="' . $class . '" href="?step=' . tgai_html((string) $key) . '">' . tgai_html((string) $label) . '</a>';
    }
    echo '</nav>';
}

function tgai_render_messages(array $messages): void
{
    foreach ($messages as $message) {
        $kind = $message['kind'] ?? 'notice';
        echo '<div class="notice ' . tgai_html((string) $kind) . '">' . tgai_html((string) ($message['text'] ?? '')) . '</div>';
    }
}

function tgai_render_requirements(array $messages): void
{
    tgai_render_header('Telegram AI Agent installer');
    echo '<section class="panel">';
    tgai_render_steps('requirements');
    tgai_render_messages($messages);
    echo '<h2>Requirements check</h2>';
    echo '<p class="muted">This page validates the hosting account for the installer itself. The application runtime still needs Python/FastAPI, PostgreSQL, and Redis.</p>';
    echo '<table><thead><tr><th>Check</th><th>Status</th><th>Details</th></tr></thead><tbody>';
    foreach (tgai_check_requirements() as $check) {
        $class = $check['ok'] ? 'ok' : (($check['warning'] ?? false) ? 'warn' : 'error');
        $status = $check['ok'] ? 'OK' : (($check['warning'] ?? false) ? 'Warning' : 'Failed');
        echo '<tr><td>' . tgai_html((string) $check['label']) . '</td><td><span class="notice ' . $class . '">' . $status . '</span></td><td>' . tgai_html((string) $check['detail']) . '</td></tr>';
    }
    echo '</tbody></table>';
    echo '<div class="notice warn">MySQL support in this installer is for the hosting wizard metadata only. The current backend schema uses PostgreSQL-specific migrations and JSONB/partitioning.</div>';
    echo '<div class="actions"><span></span><a class="button" href="?step=public">Start configuration</a></div>';
    echo '</section>';
    tgai_render_footer();
}

function tgai_render_field(array $field, array $data): void
{
    $name = $field['name'];
    $type = $field['type'] ?? 'text';
    $value = (string) ($data[$name] ?? '');
    $required = !empty($field['required']);
    $class = in_array($type, ['textarea'], true) ? 'field full' : 'field';

    if ($type === 'checkbox') {
        echo '<div class="field full"><label class="check">';
        echo '<input type="checkbox" name="' . tgai_html($name) . '" value="1" ' . ($value === 'true' || $value === '1' ? 'checked' : '') . '>';
        echo '<span>' . tgai_html((string) $field['label']) . '</span></label>';
        if (!empty($field['help'])) {
            echo '<div class="help">' . tgai_html((string) $field['help']) . '</div>';
        }
        echo '</div>';
        return;
    }

    echo '<div class="' . $class . '">';
    echo '<label for="' . tgai_html($name) . '">' . tgai_html((string) $field['label']) . ($required ? ' *' : '') . '</label>';
    if ($type === 'textarea') {
        echo '<textarea id="' . tgai_html($name) . '" name="' . tgai_html($name) . '"' . ($required ? ' required' : '') . '>' . tgai_html($value) . '</textarea>';
    } else {
        $inputType = in_array($type, ['email', 'number', 'password', 'url'], true) ? $type : 'text';
        echo '<input id="' . tgai_html($name) . '" name="' . tgai_html($name) . '" type="' . $inputType . '" value="' . tgai_html($value) . '"';
        if (!empty($field['placeholder'])) {
            echo ' placeholder="' . tgai_html((string) $field['placeholder']) . '"';
        }
        if ($required) {
            echo ' required';
        }
        echo '>';
    }
    if (!empty($field['help'])) {
        echo '<div class="help">' . tgai_html((string) $field['help']) . '</div>';
    }
    echo '</div>';
}

function tgai_render_step_form(string $stepKey, array $data, array $messages): void
{
    $steps = tgai_installer_fields();
    $step = $steps[$stepKey] ?? null;
    if ($step === null) {
        tgai_render_requirements($messages);
        return;
    }

    $keys = tgai_current_step_keys();
    $index = array_search($stepKey, $keys, true);
    $prev = $index === 0 ? 'requirements' : $keys[$index - 1];
    $next = $index === count($keys) - 1 ? 'review' : $keys[$index + 1];

    tgai_render_header('Telegram AI Agent installer');
    echo '<section class="panel">';
    tgai_render_steps($stepKey);
    tgai_render_messages($messages);
    echo '<h2>' . tgai_html((string) $step['title']) . '</h2>';
    echo '<p class="muted">' . tgai_html((string) $step['description']) . '</p>';
    echo '<form method="post" action="?step=' . tgai_html($stepKey) . '">';
    echo '<input type="hidden" name="action" value="save_step">';
    echo '<input type="hidden" name="csrf" value="' . tgai_html($_SESSION['tgai_csrf'] ?? '') . '">';
    echo '<div class="grid">';
    foreach ($step['fields'] as $field) {
        tgai_render_field($field, $data);
    }
    echo '</div>';
    echo '<div class="actions"><a class="button secondary" href="?step=' . tgai_html((string) $prev) . '">Back</a><button class="button" type="submit" name="next" value="' . tgai_html((string) $next) . '">Save and continue</button></div>';
    echo '</form></section>';
    tgai_render_footer();
}

function tgai_render_review(array $data, array $messages): void
{
    $data = tgai_normalize_installer_input($data);
    $errors = tgai_validate_installer_data($data);

    tgai_render_header('Telegram AI Agent installer');
    echo '<section class="panel">';
    tgai_render_steps('review');
    tgai_render_messages($messages);
    echo '<h2>Review and generate files</h2>';
    echo '<p class="muted">Review public values. Secrets are not displayed here.</p>';
    foreach ($errors as $error) {
        echo '<div class="notice error">' . tgai_html($error) . '</div>';
    }
    echo '<table><tbody>';
    foreach ([
        'Domain' => $data['domain'],
        'Admin domain' => $data['admin_domain'],
        'Mini App URL' => $data['telegram_mini_app_url'],
        'Webhook URL' => tgai_webhook_url($data),
        'PostgreSQL URL' => preg_replace('#://([^:]+):([^@]+)@#', '://$1:***@', $data['database_url']) ?? $data['database_url'],
        'Redis URL' => preg_replace('#://:([^@]+)@#', '://:***@', $data['redis_url']) ?? $data['redis_url'],
        'Backend image' => $data['backend_image'],
        'Mini App image' => $data['mini_app_image'],
        'Admin image' => $data['admin_image'],
        'MySQL metadata' => $data['store_installation_metadata'] === 'true' ? 'enabled' : 'disabled',
    ] as $key => $value) {
        echo '<tr><th>' . tgai_html((string) $key) . '</th><td><code>' . tgai_html((string) $value) . '</code></td></tr>';
    }
    echo '</tbody></table>';
    echo '<div class="notice warn">After generation, move the generated files to the matching deployment target and remove or password-protect this installer.</div>';
    echo '<form method="post" action="?step=review"><input type="hidden" name="action" value="generate"><input type="hidden" name="csrf" value="' . tgai_html($_SESSION['tgai_csrf'] ?? '') . '">';
    echo '<div class="actions"><a class="button secondary" href="?step=secrets">Back</a><button class="button" type="submit"' . ($errors ? ' disabled' : '') . '>Generate files</button></div></form>';
    echo '</section>';
    tgai_render_footer();
}

function tgai_render_complete(array $messages, array $files): void
{
    tgai_render_header('Telegram AI Agent installer');
    echo '<section class="panel">';
    tgai_render_messages($messages);
    echo '<h2>Generated files</h2>';
    echo '<p class="muted">Files are stored under <code>' . tgai_html(__DIR__ . DIRECTORY_SEPARATOR . 'generated') . '</code>.</p>';
    echo '<table><thead><tr><th>File</th><th>Path</th></tr></thead><tbody>';
    foreach ($files as $name => $path) {
        echo '<tr><th>' . tgai_html((string) $name) . '</th><td><code>' . tgai_html((string) $path) . '</code></td></tr>';
    }
    echo '</tbody></table>';
    echo '<div class="notice warn">Security: delete install.php or protect this directory immediately after downloading the generated files.</div>';
    echo '<div class="actions"><a class="button secondary" href="?step=review">Back to review</a><a class="button danger" href="?reset=1">Reset installer session</a></div>';
    echo '</section>';
    tgai_render_footer();
}

function tgai_require_csrf(): bool
{
    return hash_equals((string) ($_SESSION['tgai_csrf'] ?? ''), (string) ($_POST['csrf'] ?? ''));
}

function tgai_run_installer(): void
{
    session_start();
    if (!isset($_SESSION['tgai_csrf'])) {
        $_SESSION['tgai_csrf'] = bin2hex(random_bytes(16));
    }
    if (!isset($_SESSION['tgai_installer'])) {
        $_SESSION['tgai_installer'] = tgai_default_values();
    }
    if (isset($_GET['reset'])) {
        $_SESSION['tgai_installer'] = tgai_default_values();
        header('Location: ?step=requirements');
        return;
    }

    $messages = [];
    $files = [];
    $step = (string) ($_GET['step'] ?? 'requirements');
    $validSteps = array_merge(['requirements'], tgai_current_step_keys(), ['review']);
    if (!in_array($step, $validSteps, true)) {
        $step = 'requirements';
    }

    if ($_SERVER['REQUEST_METHOD'] === 'POST') {
        if (!tgai_require_csrf()) {
            $messages[] = ['kind' => 'error', 'text' => 'CSRF validation failed. Reload the page and try again.'];
        } else {
            $action = (string) ($_POST['action'] ?? '');
            if ($action === 'save_step' && isset(tgai_installer_fields()[$step])) {
                $incoming = [];
                foreach ((tgai_installer_fields()[$step]['fields'] ?? []) as $field) {
                    $name = $field['name'];
                    $incoming[$name] = ($field['type'] ?? '') === 'checkbox'
                        ? (isset($_POST[$name]) ? 'true' : 'false')
                        : (string) ($_POST[$name] ?? '');
                }
                $_SESSION['tgai_installer'] = tgai_normalize_installer_input(array_merge($_SESSION['tgai_installer'], $incoming));
                $errors = tgai_validate_installer_data($_SESSION['tgai_installer'], $step);
                if ($step === 'hosting' && $_SESSION['tgai_installer']['store_installation_metadata'] === 'true') {
                    $mysql = tgai_test_mysql_connection($_SESSION['tgai_installer']);
                    $messages[] = ['kind' => $mysql['ok'] ? 'ok' : 'error', 'text' => $mysql['message']];
                    if (!$mysql['ok']) {
                        $errors[] = $mysql['message'];
                    }
                }
                if ($errors) {
                    foreach ($errors as $error) {
                        $messages[] = ['kind' => 'error', 'text' => $error];
                    }
                } else {
                    header('Location: ?step=' . rawurlencode((string) ($_POST['next'] ?? 'review')));
                    return;
                }
            }

            if ($action === 'generate') {
                $_SESSION['tgai_installer'] = tgai_normalize_installer_input($_SESSION['tgai_installer']);
                $errors = tgai_validate_installer_data($_SESSION['tgai_installer']);
                if ($errors) {
                    foreach ($errors as $error) {
                        $messages[] = ['kind' => 'error', 'text' => $error];
                    }
                } else {
                    try {
                        $files = tgai_write_generated_files(__DIR__ . DIRECTORY_SEPARATOR . 'generated', $_SESSION['tgai_installer']);
                        $messages[] = ['kind' => 'ok', 'text' => 'Configuration files were generated.'];
                        $metadata = tgai_record_installation_metadata($_SESSION['tgai_installer']);
                        $messages[] = ['kind' => $metadata['ok'] ? 'ok' : 'warn', 'text' => $metadata['message']];
                        if ($_SESSION['tgai_installer']['set_webhook_now'] === 'true') {
                            $webhook = tgai_call_telegram_api('setWebhook', $_SESSION['tgai_installer']);
                            $messages[] = ['kind' => $webhook['ok'] ? 'ok' : 'warn', 'text' => $webhook['message']];
                        }
                        tgai_render_complete($messages, $files);
                        return;
                    } catch (Throwable $error) {
                        $messages[] = ['kind' => 'error', 'text' => $error->getMessage()];
                    }
                }
            }
        }
    }

    $data = tgai_normalize_installer_input($_SESSION['tgai_installer']);
    if ($step === 'requirements') {
        tgai_render_requirements($messages);
    } elseif ($step === 'review') {
        tgai_render_review($data, $messages);
    } else {
        tgai_render_step_form($step, $data, $messages);
    }
}

if (!defined('TGAI_INSTALLER_TEST_MODE') || TGAI_INSTALLER_TEST_MODE !== true) {
    tgai_run_installer();
}
