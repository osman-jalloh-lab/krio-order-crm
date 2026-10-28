# API (JSON, localhost, no auth yet: do not expose publicly)

| Method | Path | Body / query | Returns |
|---|---|---|---|
| GET | /api/health | | `{ok, mode, asr, db}` |
| GET | /api/pharmacies | | list |
| POST | /api/pharmacies | `{name, town?, status?, plan?, wa_phone_number_id?, owner_name?, phone?, notes?}` | 201 pharmacy |
| GET/PATCH | /api/pharmacies/:id | fields as above | pharmacy |
| GET/PUT | /api/pharmacies/:id/catalogue | PUT `{items:[{item, unit, aliases}]}` (replaces all) | `{pharmacy_id, items}` |
| GET | /api/customers | `?pharmacy=&q=` | list |
| GET/PATCH | /api/customers/:id | `{name, status(new/regular/vip/blocked), notes, tags}` | customer |
| GET | /api/orders | `?pharmacy=&chip=Needs check|Ready|Replied|Window closed|Transcribing` | list with `chip` |
| GET | /api/orders/:id | | order with `lines`, `final`, `engines`, `reply` |
| POST | /api/orders/:id/confirm | `{lines:[{pos, item, qty, keep}]}`; item `__DROP__` drops a line; unknown names become `UNKNOWN: "…"` | final order (PDF written, reply sent or simulated) |
| POST | /api/orders/:id/retype | `{text}` | order re-matched from the owner's typing |
| POST | /api/match | `{text, pharmacy?}` | `{lines, score}` |
| GET | /api/summary | `?pharmacy=` | today's counts and top items |
| GET/POST | /webhook | Meta verify / events (`X-Hub-Signature-256` required) | `EVENT_RECEIVED` |

Files: `/o/:id/pdf`, `/o/:id/pdf.png`, `/o/:id/audio`, `/catalogue.csv?pharmacy=`.

Example: `curl -s localhost:5090/api/match -H 'content-type: application/json' -d '{"text":"wan strip cipro"}'`
