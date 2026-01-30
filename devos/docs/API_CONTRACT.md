# API Contract (REST) — SSOT

> Update this file first when API behavior changes.

## Conventions
- Base URL: /api
- Content-Type: application/json; charset=utf-8
- IDs: string (uuid recommended)
- Date/time: ISO-8601 string

## Error Format (mandatory)
```json
{
  "error": {
    "code": "STRING_CODE",
    "message": "Human readable message",
    "details": { "optional": "object" }
  }
}
```

## Auth (Default until decided)
- Mode: none

## Endpoints (placeholder)
| Name | Method | Path | Request | Response | Notes |
|---|---|---|---|---|---|
| Health | GET | /api/health | - | `{ "ok": true }` | baseline |

## Schemas (placeholder)
### Item
```json
{ "id": "string", "title": "string", "createdAt": "2026-01-01T00:00:00Z" }
```
