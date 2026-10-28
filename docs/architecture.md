# Architecture

```
WhatsApp (Meta Cloud API) ──POST /webhook──▶ server.py ──▶ service.intake_message
   ▲   signature HMAC-SHA256, dedupe wamid        │            ├─ text  → matcher → draft lines
   │                                              │            └─ audio → fetch media → (ASR thread if KRIO_ASR=1) → matcher
   └──── wa.send_text (24h window check) ◀── service.confirm ◀── owner taps Confirm on /o/<id>
                                                   └─ reportlab PDF → data/pdf/<id>.pdf
SQLite (db.py, WAL) ◀── dashboard screens (Jinja) + JSON API (/api/*)
```

| Module | Role |
|---|---|
| `krio_crm/wa.py` | Webhook verify, signature check, payload parse, simulator media/outbox, send text with the 24h window. Copied from v3. Only the state path and default client changed. |
| `krio_crm/matcher.py` | Krio number words and units, alias plus fuzzy match (rapidfuzz/jellyfish). At 85 or above the item is added automatically; from 60 it becomes a suggestion; below that the line is blank. Logic unchanged from v3; `build_catalogue(rows)` lets it read DB rows. |
| `krio_crm/asr.py` | Whisper-Krio / MMS-kri / Vosk-en runners from v3, imported lazily only when `KRIO_ASR=1`. |
| `krio_crm/service.py` | Intake, transcribe, retype, confirm, PDF, daily summary. |
| `krio_crm/db.py` | Schema plus small helpers. One connection per thread. |
| `krio_crm/server.py` | Routes: screens, API, webhook. |
| `seed/seed.py` | Invented TEST pharmacies, customers and orders. |

Routing: each pharmacy has its own WhatsApp number. Inbound `metadata.phone_number_id` is matched to `pharmacies.wa_phone_number_id`, with a fallback to the first pharmacy.

Design: MAGNUM tokens (ink #0A0A14, sun #FFE03D, sky). The layout is phone-first with a five-tab bottom bar, and becomes a sidebar at 1024px or wider. Motion is under 200ms, ease-out, and turned off when the device asks for reduced motion (emil-design-eng rules). No external fonts or CDNs; everything is served locally.
