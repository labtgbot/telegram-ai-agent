<?php
declare(strict_types=1);

define('TGAI_INSTALLER_TEST_MODE', true);
require dirname(__DIR__) . '/install.php';

function assert_true(bool $condition, string $message): void
{
    if (!$condition) {
        fwrite(STDERR, "Assertion failed: {$message}\n");
        exit(1);
    }
}

function assert_contains(string $needle, string $haystack, string $message): void
{
    assert_true(str_contains($haystack, $needle), $message);
}

function assert_not_contains(string $needle, string $haystack, string $message): void
{
    assert_true(!str_contains($haystack, $needle), $message);
}

$fields = tgai_installer_fields();
$fieldNames = [];
foreach ($fields as $step) {
    foreach (($step['fields'] ?? []) as $field) {
        $fieldNames[] = $field['name'];
    }
}

foreach (
    [
        'domain',
        'admin_domain',
        'telegram_mini_app_url',
        'database_url',
        'redis_url',
        'mysql_host',
        'telegram_bot_token',
        'admin_jwt_secret',
        'vite_api_base_url',
        'next_public_api_base_url',
    ] as $requiredField
) {
    assert_true(in_array($requiredField, $fieldNames, true), "field {$requiredField} exists");
}

$input = [
    'domain' => 'bot.example.com',
    'admin_domain' => 'admin.example.com',
    'acme_email' => 'ops@example.com',
    'app_version' => '0.1.0',
    'database_url' => 'postgresql+asyncpg://postgres:secret@postgres:5432/telegram_ai_agent',
    'redis_url' => 'redis://redis:6379/0',
    'mysql_host' => 'localhost',
    'mysql_port' => '3306',
    'mysql_database' => 'hosting_installer',
    'mysql_user' => 'installer',
    'mysql_password' => 'mysql-secret',
    'mysql_table_prefix' => 'tgai_',
    'telegram_bot_token' => '123456:ABCDEF',
    'telegram_bot_username' => 'telegram_ai_agent_bot',
    'telegram_webhook_secret' => 'webhook-secret',
    'telegram_mini_app_url' => 'https://bot.example.com/',
    'app_secret' => 'app-secret',
    'admin_jwt_secret' => 'admin-secret',
    'admin_super_telegram_ids' => '123456789',
    'vite_api_base_url' => 'https://bot.example.com/api/v1',
    'next_public_api_base_url' => 'https://bot.example.com/api/v1',
    'api_base_url' => 'http://backend:8000/api/v1',
    'payment_currency' => 'XTR',
    'backend_image' => 'ghcr.io/labtgbot/telegram-ai-agent/backend:0.1.0',
    'mini_app_image' => 'ghcr.io/labtgbot/telegram-ai-agent/mini-app:0.1.0',
    'admin_image' => 'ghcr.io/labtgbot/telegram-ai-agent/admin:0.1.0',
];

$normalized = tgai_normalize_installer_input($input);
$env = tgai_build_env_content($normalized);
assert_contains("APP_ENV=production\n", $env, 'production env is generated');
assert_contains("DOMAIN=bot.example.com\n", $env, 'domain is generated');
assert_contains("DATABASE_URL=postgresql+asyncpg://postgres:secret@postgres:5432/telegram_ai_agent\n", $env, 'database url is generated');
assert_contains("TELEGRAM_MINI_APP_URL=https://bot.example.com/\n", $env, 'mini app url is generated');
assert_contains("ADMIN_JWT_SECRET=admin-secret\n", $env, 'admin secret is generated');

$tmpBase = sys_get_temp_dir() . '/tgai-installer-' . bin2hex(random_bytes(6));
$files = tgai_write_generated_files($tmpBase, $normalized);

foreach (['.env.prod', 'mini-app.env', 'admin-dashboard.env', 'telegram-webhook.sh', 'botfather-checklist.md', 'install-summary.md'] as $fileName) {
    assert_true(isset($files[$fileName]), "{$fileName} returned");
    assert_true(is_file($files[$fileName]), "{$fileName} written");
}

$summary = file_get_contents($files['install-summary.md']);
assert_true(is_string($summary), 'summary can be read');
assert_contains('Telegram AI Agent', $summary, 'summary names product');
assert_contains('bot.example.com', $summary, 'summary contains public domain');
assert_contains('PostgreSQL', $summary, 'summary explains runtime database');
assert_not_contains('admin-secret', $summary, 'summary redacts admin secret');
assert_not_contains('123456:ABCDEF', $summary, 'summary redacts bot token');
assert_not_contains('mysql-secret', $summary, 'summary redacts mysql password');

echo "Shared hosting installer smoke test passed\n";
