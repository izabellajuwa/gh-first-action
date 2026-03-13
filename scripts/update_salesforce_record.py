#!/usr/bin/env python3
"""Update a Salesforce record based on a received GitHub event."""

from __future__ import annotations

import json
import os
import sys
from typing import Any
from urllib import error, parse, request


def fail(message: str) -> None:
    """Exit with a clear error message."""
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def get_required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        fail(f"Missing required environment variable: {name}")
    return value


def load_json_file(path: str) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as file_obj:
            return json.load(file_obj)
    except FileNotFoundError as exc:
        fail(f"GitHub event file does not exist: {path} ({exc})")
    except json.JSONDecodeError as exc:
        fail(f"GitHub event file is not valid JSON: {path} ({exc})")


def first_non_empty(payload: dict[str, Any], keys: list[str]) -> str:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def first_present(payload: dict[str, Any], keys: list[str]) -> Any:
    for key in keys:
        if key in payload:
            return payload[key]
    return None


def parse_fields(fields_raw: Any) -> dict[str, Any]:
    if isinstance(fields_raw, dict):
        return fields_raw

    if isinstance(fields_raw, str):
        if not fields_raw.strip():
            fail("fields_json/fields was provided but empty")
        try:
            parsed_fields = json.loads(fields_raw)
        except json.JSONDecodeError as exc:
            fail(f"fields_json/fields is not valid JSON: {exc}")
        if not isinstance(parsed_fields, dict):
            fail("fields_json/fields must decode to a JSON object")
        return parsed_fields

    fail("Missing fields to update. Provide fields as a JSON object.")


def payload_from_event() -> dict[str, Any]:
    event_name = os.getenv("GITHUB_EVENT_NAME", "").strip()
    event_path = os.getenv("GITHUB_EVENT_PATH", "").strip()

    if event_path:
        event = load_json_file(event_path)
        if not isinstance(event, dict):
            fail("GitHub event content must be a JSON object")

        if event_name == "repository_dispatch":
            payload = event.get("client_payload", {})
        elif event_name == "workflow_dispatch":
            inputs = event.get("inputs", {})
            if not isinstance(inputs, dict):
                fail("workflow_dispatch inputs must be a JSON object")
            payload = {
                "object_api_name": inputs.get("object_api_name"),
                "record_id": inputs.get("record_id"),
                "fields": inputs.get("fields_json"),
            }
        else:
            payload = event.get("client_payload") or event.get("payload") or {}

        if not isinstance(payload, dict):
            fail("Event payload must be a JSON object")
        if payload:
            return payload

    env_payload = os.getenv("EVENT_PAYLOAD", "").strip()
    if env_payload:
        try:
            payload = json.loads(env_payload)
        except json.JSONDecodeError as exc:
            fail(f"EVENT_PAYLOAD is not valid JSON: {exc}")
        if not isinstance(payload, dict):
            fail("EVENT_PAYLOAD must decode to a JSON object")
        return payload

    fail(
        "No event payload found. Use repository_dispatch client_payload, "
        "workflow_dispatch inputs, or EVENT_PAYLOAD."
    )


def normalize_payload(payload: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    object_api_name = first_non_empty(
        payload, ["object_api_name", "objectApiName", "sobject", "object"]
    )
    if not object_api_name:
        fail("Missing object API name (object_api_name or objectApiName)")

    record_id = first_non_empty(payload, ["record_id", "recordId", "id"])
    if not record_id:
        fail("Missing Salesforce record id (record_id or recordId)")

    fields_raw = first_present(payload, ["fields", "updates", "data", "fields_json"])
    fields = parse_fields(fields_raw)
    if not fields:
        fail("No fields supplied for Salesforce update")

    return object_api_name, record_id, fields


def request_access_token() -> tuple[str, str, str]:
    login_url = (
        os.getenv("SF_LOGIN_URL", "").strip() or "https://login.salesforce.com"
    ).rstrip("/")
    api_version = os.getenv("SF_API_VERSION", "").strip() or "v61.0"

    auth_payload = {
        "grant_type": "password",
        "client_id": get_required_env("SF_CLIENT_ID"),
        "username": get_required_env("SF_USERNAME"),
        "password": get_required_env("SF_PASSWORD") + os.getenv("SF_SECURITY_TOKEN", ""),
    }
    client_secret = os.getenv("SF_CLIENT_SECRET", "").strip()
    if client_secret:
        auth_payload["client_secret"] = client_secret

    token_url = f"{login_url}/services/oauth2/token"
    token_data = parse.urlencode(auth_payload).encode("utf-8")

    token_request = request.Request(token_url, data=token_data, method="POST")
    token_request.add_header("Content-Type", "application/x-www-form-urlencoded")

    try:
        with request.urlopen(token_request, timeout=60) as response:
            body = response.read().decode("utf-8")
    except error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        fail(f"Failed to authenticate with Salesforce ({exc.code}): {details}")
    except error.URLError as exc:
        fail(f"Unable to connect to Salesforce auth endpoint: {exc}")

    try:
        token_response = json.loads(body)
    except json.JSONDecodeError as exc:
        fail(f"Salesforce auth response is not valid JSON: {exc}")

    access_token = token_response.get("access_token", "")
    instance_url = token_response.get("instance_url", "").rstrip("/")
    if not access_token or not instance_url:
        fail("Salesforce auth response did not include access_token and instance_url")

    return access_token, instance_url, api_version


def update_salesforce_record(
    access_token: str,
    instance_url: str,
    api_version: str,
    object_api_name: str,
    record_id: str,
    fields: dict[str, Any],
) -> None:
    update_url = (
        f"{instance_url}/services/data/{api_version}/sobjects/"
        f"{parse.quote(object_api_name, safe='')}/{parse.quote(record_id, safe='')}"
    )
    payload = json.dumps(fields).encode("utf-8")

    update_request = request.Request(update_url, data=payload, method="PATCH")
    update_request.add_header("Authorization", f"Bearer {access_token}")
    update_request.add_header("Content-Type", "application/json")

    try:
        with request.urlopen(update_request, timeout=60):
            pass
    except error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        fail(f"Failed to update Salesforce record ({exc.code}): {details}")
    except error.URLError as exc:
        fail(f"Unable to connect to Salesforce update endpoint: {exc}")

    updated_fields = ", ".join(sorted(fields.keys()))
    print(
        f"Updated {object_api_name} record {record_id}. "
        f"Fields changed: {updated_fields}"
    )


def main() -> None:
    payload = payload_from_event()
    object_api_name, record_id, fields = normalize_payload(payload)
    access_token, instance_url, api_version = request_access_token()
    update_salesforce_record(
        access_token=access_token,
        instance_url=instance_url,
        api_version=api_version,
        object_api_name=object_api_name,
        record_id=record_id,
        fields=fields,
    )


if __name__ == "__main__":
    main()
