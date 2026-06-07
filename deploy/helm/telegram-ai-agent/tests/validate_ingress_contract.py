#!/usr/bin/env python3
"""Validate the production ingress IP-allowlist contract."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import yaml

WHITELIST_ANNOTATION = "nginx.ingress.kubernetes.io/whitelist-source-range"
PUBLIC_ALLOWLISTS = {"0.0.0.0/0", "::/0"}


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as file:
        document = yaml.safe_load(file)
    if not isinstance(document, dict):
        raise AssertionError(f"{path}: expected a YAML mapping")
    return document


def _host_serves(host: dict[str, Any], service: str) -> bool:
    paths = host.get("paths", [])
    if not isinstance(paths, list):
        raise AssertionError(f"{host.get('host')}: expected paths to be a list")
    return any(path.get("service") == service for path in paths)


def _assert_restricted_allowlist(value: str | None, context: str) -> None:
    if not value:
        raise AssertionError(f"{context}: admin ingress must define an IP allowlist")
    cidrs = {item.strip() for item in value.split(",") if item.strip()}
    if not cidrs:
        raise AssertionError(f"{context}: allowlist must contain at least one CIDR")
    public = sorted(cidrs.intersection(PUBLIC_ALLOWLISTS))
    if public:
        raise AssertionError(f"{context}: public allowlist is not a restriction: {public}")


def _production_hosts(values_path: Path) -> tuple[list[str], list[str]]:
    values = _load_yaml(values_path)
    ingress = values["ingress"]
    hosts = ingress["hosts"]

    if WHITELIST_ANNOTATION in (ingress.get("annotations") or {}):
        raise AssertionError(
            "production ingress uses a global whitelist-source-range; "
            "admin restrictions must not apply to public bot/mini-app hosts"
        )

    admin_hosts = [host for host in hosts if _host_serves(host, "admin")]
    if len(admin_hosts) != 1:
        raise AssertionError(f"expected exactly one admin host, got {len(admin_hosts)}")

    admin_annotations = admin_hosts[0].get("annotations") or {}
    _assert_restricted_allowlist(
        admin_annotations.get(WHITELIST_ANNOTATION),
        f"{values_path}: host {admin_hosts[0]['host']}",
    )

    public_hosts = [host for host in hosts if not _host_serves(host, "admin")]
    if not public_hosts:
        raise AssertionError("expected at least one public bot/mini-app host")
    for host in public_hosts:
        if WHITELIST_ANNOTATION in (host.get("annotations") or {}):
            raise AssertionError(
                f"{values_path}: public host {host['host']} must not define "
                f"{WHITELIST_ANNOTATION}"
            )

    return [admin_hosts[0]["host"]], [host["host"] for host in public_hosts]


def _rendered_ingresses(rendered_path: Path) -> dict[str, dict[str, Any]]:
    with rendered_path.open(encoding="utf-8") as file:
        documents = yaml.safe_load_all(file)
        manifests = [
            document
            for document in documents
            if isinstance(document, dict) and document.get("kind") == "Ingress"
        ]

    ingress_by_host: dict[str, dict[str, Any]] = {}
    for manifest in manifests:
        rules = manifest.get("spec", {}).get("rules", [])
        for rule in rules:
            host = rule.get("host")
            if host:
                ingress_by_host[host] = manifest
    return ingress_by_host


def validate(values_path: Path, rendered_path: Path | None) -> None:
    admin_hosts, public_hosts = _production_hosts(values_path)
    if rendered_path is None:
        return

    ingress_by_host = _rendered_ingresses(rendered_path)
    for host in admin_hosts:
        manifest = ingress_by_host.get(host)
        if manifest is None:
            raise AssertionError(f"{rendered_path}: missing rendered admin ingress for {host}")
        annotations = manifest["metadata"].get("annotations", {})
        _assert_restricted_allowlist(
            annotations.get(WHITELIST_ANNOTATION),
            f"{rendered_path}: rendered host {host}",
        )

    for host in public_hosts:
        manifest = ingress_by_host.get(host)
        if manifest is None:
            raise AssertionError(f"{rendered_path}: missing rendered public ingress for {host}")
        annotations = manifest["metadata"].get("annotations", {})
        if WHITELIST_ANNOTATION in annotations:
            raise AssertionError(
                f"{rendered_path}: rendered public host {host} must not define "
                f"{WHITELIST_ANNOTATION}"
            )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--values", required=True, type=Path)
    parser.add_argument("--rendered", type=Path)
    args = parser.parse_args()
    validate(values_path=args.values, rendered_path=args.rendered)


if __name__ == "__main__":
    main()
