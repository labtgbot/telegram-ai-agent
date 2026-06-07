"""Unit tests for the rate-limit configuration loader."""
from __future__ import annotations

import pytest

from app.services.rate_limit_config import (
    ACTION_ADMIN_LOGIN_REQUEST,
    ACTION_ADMIN_LOGIN_VERIFY,
    ACTION_DEFAULT,
    ACTION_IMAGE,
    ACTION_VIDEO,
    ACTION_VOICE,
    DEFAULT_RATE_LIMITS,
    PLAN_ADMIN_LOGIN,
    PLAN_ANONYMOUS,
    PLAN_FREE,
    PLAN_PREMIUM,
    PLAN_PRO,
    RateLimitConfig,
    RateLimitRule,
    _coerce_rule,
    merge_overrides,
)


def test_default_catalog_covers_every_plan() -> None:
    assert PLAN_ANONYMOUS in DEFAULT_RATE_LIMITS
    assert PLAN_FREE in DEFAULT_RATE_LIMITS
    assert PLAN_PREMIUM in DEFAULT_RATE_LIMITS
    assert PLAN_PRO in DEFAULT_RATE_LIMITS
    assert PLAN_ADMIN_LOGIN in DEFAULT_RATE_LIMITS


def test_default_free_plan_matches_adr_table() -> None:
    free = DEFAULT_RATE_LIMITS[PLAN_FREE]
    assert free["per_hour"].limit == 10
    assert free["image_per_day"].limit == 5
    assert free["video_per_day"].limit == 2


def test_default_premium_plan_matches_adr_table() -> None:
    premium = DEFAULT_RATE_LIMITS[PLAN_PREMIUM]
    assert premium["per_hour"].limit == 100
    assert premium["image_per_day"].limit == 50
    assert premium["video_per_day"].limit == 20


def test_pro_plan_is_strictly_above_premium() -> None:
    premium = DEFAULT_RATE_LIMITS[PLAN_PREMIUM]
    pro = DEFAULT_RATE_LIMITS[PLAN_PRO]
    for key, rule in premium.items():
        assert pro[key].limit > rule.limit, f"pro must exceed premium for {key}"


def test_anonymous_has_only_hourly() -> None:
    anon = DEFAULT_RATE_LIMITS[PLAN_ANONYMOUS]
    assert "per_hour" in anon
    assert "per_day" not in anon


def test_admin_login_defaults_match_adr() -> None:
    admin_login = DEFAULT_RATE_LIMITS[PLAN_ADMIN_LOGIN]
    assert admin_login["request_per_15m"].limit == 5
    assert admin_login["request_per_15m"].window_seconds == 15 * 60
    assert admin_login["verify_per_15m"].limit == 5
    assert admin_login["verify_per_15m"].window_seconds == 15 * 60


# -------------------------------------------------------------- RateLimitRule


@pytest.mark.parametrize("limit, window", [(0, 60), (-1, 60), (10, 0), (10, -3)])
def test_rate_limit_rule_rejects_non_positive(limit: int, window: int) -> None:
    with pytest.raises(ValueError):
        RateLimitRule(limit=limit, window_seconds=window)


# ----------------------------------------------------------------- _coerce_rule


def test_coerce_rule_full_form() -> None:
    rule = _coerce_rule({"limit": 50, "window_seconds": 3600})
    assert rule is not None
    assert rule.limit == 50
    assert rule.window_seconds == 3600


def test_coerce_rule_per_hour_shorthand() -> None:
    rule = _coerce_rule({"per_hour": 25})
    assert rule is not None
    assert rule.limit == 25
    assert rule.window_seconds == 3600


def test_coerce_rule_per_day_shorthand() -> None:
    rule = _coerce_rule({"per_day": 1000})
    assert rule is not None
    assert rule.limit == 1000
    assert rule.window_seconds == 86400


def test_coerce_rule_int_means_per_hour() -> None:
    rule = _coerce_rule(7)
    assert rule is not None
    assert rule.limit == 7
    assert rule.window_seconds == 3600


@pytest.mark.parametrize(
    "value",
    [None, True, False, "10", -1, 0, [], {"limit": "x"}, {"window_seconds": 60}],
)
def test_coerce_rule_rejects_garbage(value: object) -> None:
    assert _coerce_rule(value) is None


# ----------------------------------------------------------------- merge_overrides


def test_merge_with_no_overrides_returns_copy_of_base() -> None:
    merged = merge_overrides(DEFAULT_RATE_LIMITS, None)
    assert merged == DEFAULT_RATE_LIMITS
    # Verify it's a deep-enough copy that callers can't mutate the source.
    merged[PLAN_FREE]["per_hour"] = RateLimitRule(limit=999, window_seconds=60)
    assert DEFAULT_RATE_LIMITS[PLAN_FREE]["per_hour"].limit == 10


def test_merge_replaces_only_specified_keys() -> None:
    overrides = {"free": {"per_hour": {"per_hour": 25}}}
    merged = merge_overrides(DEFAULT_RATE_LIMITS, overrides)
    assert merged[PLAN_FREE]["per_hour"].limit == 25
    # Other keys for free plan must remain untouched.
    assert (
        merged[PLAN_FREE]["per_day"].limit
        == DEFAULT_RATE_LIMITS[PLAN_FREE]["per_day"].limit
    )
    # Other plans must remain untouched.
    assert merged[PLAN_PRO] == DEFAULT_RATE_LIMITS[PLAN_PRO]


def test_merge_adds_new_buckets() -> None:
    overrides = {"free": {"custom_per_day": {"per_day": 7}}}
    merged = merge_overrides(DEFAULT_RATE_LIMITS, overrides)
    assert merged[PLAN_FREE]["custom_per_day"].limit == 7
    assert merged[PLAN_FREE]["custom_per_day"].window_seconds == 86400


def test_merge_silently_skips_bad_rules() -> None:
    overrides = {"free": {"per_hour": "garbage"}}
    merged = merge_overrides(DEFAULT_RATE_LIMITS, overrides)
    # original survives the skip
    assert (
        merged[PLAN_FREE]["per_hour"].limit
        == DEFAULT_RATE_LIMITS[PLAN_FREE]["per_hour"].limit
    )


def test_merge_silently_skips_non_mapping_plan_overrides() -> None:
    overrides = {"free": "not-a-mapping"}
    merged = merge_overrides(DEFAULT_RATE_LIMITS, overrides)
    assert merged[PLAN_FREE] == DEFAULT_RATE_LIMITS[PLAN_FREE]


# ----------------------------------------------------------- RateLimitConfig.rules_for


def test_rules_for_default_action_picks_hour_and_day() -> None:
    cfg = RateLimitConfig(plans=dict(DEFAULT_RATE_LIMITS))
    rules = cfg.rules_for(PLAN_FREE, ACTION_DEFAULT)
    keys = [k for k, _ in rules]
    assert keys == ["per_hour", "per_day"]


def test_rules_for_image_includes_image_per_day() -> None:
    cfg = RateLimitConfig(plans=dict(DEFAULT_RATE_LIMITS))
    rules = cfg.rules_for(PLAN_FREE, ACTION_IMAGE)
    keys = [k for k, _ in rules]
    assert keys == ["per_hour", "per_day", "image_per_day"]


def test_rules_for_video_includes_video_per_day() -> None:
    cfg = RateLimitConfig(plans=dict(DEFAULT_RATE_LIMITS))
    rules = cfg.rules_for(PLAN_FREE, ACTION_VIDEO)
    keys = [k for k, _ in rules]
    assert keys == ["per_hour", "per_day", "video_per_day"]


def test_rules_for_voice_includes_voice_per_day() -> None:
    cfg = RateLimitConfig(plans=dict(DEFAULT_RATE_LIMITS))
    rules = cfg.rules_for(PLAN_FREE, ACTION_VOICE)
    keys = [k for k, _ in rules]
    assert keys == ["per_hour", "per_day", "voice_per_day"]


def test_rules_for_admin_login_request_uses_request_window() -> None:
    cfg = RateLimitConfig(plans=dict(DEFAULT_RATE_LIMITS))
    rules = cfg.rules_for(PLAN_ADMIN_LOGIN, ACTION_ADMIN_LOGIN_REQUEST)
    keys = [k for k, _ in rules]
    assert keys == ["request_per_15m"]


def test_rules_for_admin_login_verify_uses_verify_window() -> None:
    cfg = RateLimitConfig(plans=dict(DEFAULT_RATE_LIMITS))
    rules = cfg.rules_for(PLAN_ADMIN_LOGIN, ACTION_ADMIN_LOGIN_VERIFY)
    keys = [k for k, _ in rules]
    assert keys == ["verify_per_15m"]


def test_rules_for_skips_missing_buckets() -> None:
    cfg = RateLimitConfig(plans=dict(DEFAULT_RATE_LIMITS))
    rules = cfg.rules_for(PLAN_ANONYMOUS, ACTION_DEFAULT)
    keys = [k for k, _ in rules]
    assert keys == ["per_hour"]  # anonymous has no per_day


def test_rules_for_unknown_action_falls_back_to_default() -> None:
    cfg = RateLimitConfig(plans=dict(DEFAULT_RATE_LIMITS))
    rules = cfg.rules_for(PLAN_FREE, "totally-unknown-action")
    keys = [k for k, _ in rules]
    assert keys == ["per_hour", "per_day"]


def test_rules_for_unknown_plan_returns_empty() -> None:
    cfg = RateLimitConfig(plans=dict(DEFAULT_RATE_LIMITS))
    rules = cfg.rules_for("phantom-plan", ACTION_DEFAULT)
    assert rules == []
