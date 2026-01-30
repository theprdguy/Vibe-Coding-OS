# UI Contract — SSOT

> Update this file first when UI behavior changes.

## Global UI States (mandatory)
Every screen must handle:
- loading
- empty
- error (with retry)
- success

## Screens (placeholder)
| Screen | Route | Primary action | Empty copy | Error copy |
|---|---|---|---|---|
| Home | / | (TBD) | "Nothing here yet." | "Something went wrong." |

## Accessibility baseline
- Buttons have accessible names
- Errors are announced (aria-live)
- Keyboard navigation supports primary flows
