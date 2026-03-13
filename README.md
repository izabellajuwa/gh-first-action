# gh-first-action

## Salesforce record update process

This repository now includes an automated process that updates a Salesforce
record whenever an event is received.

### Workflow

- File: `.github/workflows/salesforce-record-update.yml`
- Triggers:
  - `repository_dispatch` with event type `salesforce-record-update`
  - Manual `workflow_dispatch` (for testing)

### Required GitHub secrets

Configure these repository secrets:

- `SF_CLIENT_ID`
- `SF_CLIENT_SECRET` (optional if your connected app does not require it)
- `SF_USERNAME`
- `SF_PASSWORD`
- `SF_SECURITY_TOKEN` (optional if not required by your org)
- `SF_LOGIN_URL` (optional; defaults to `https://login.salesforce.com`)

Optional repository variable:

- `SF_API_VERSION` (defaults to `v61.0`)

### Expected event payload

For `repository_dispatch` with `event_type` set to `salesforce-record-update`,
send this in `client_payload`:

```json
{
  "object_api_name": "Account",
  "record_id": "001000000000001AAA",
  "fields": {
    "Name": "Updated by event process",
    "Phone": "+1-555-0100"
  }
}
```

Supported aliases:

- `objectApiName` for `object_api_name`
- `recordId` for `record_id`
- `updates` or `data` for `fields`

### Manual run

Use **Actions → Update Salesforce Record From Event → Run workflow** and provide:

- `object_api_name`
- `record_id`
- `fields_json` (JSON object string, e.g. `{"Name":"Updated manually"}`)
