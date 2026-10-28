# Data model (SQLite, `data/krio_crm.sqlite3`, WAL)

- **pharmacies**: id, name, slug, town, status (lead/trial/active/paused), plan, wa_phone_number_id, owner_name, phone, notes, is_test, created
- **customers**: id, pharmacy_id → pharmacies, wa_id, name, status (new/regular/vip/blocked), notes, tags, first_seen, last_seen, is_test. UNIQUE(pharmacy_id, wa_id)
- **catalogue_items**: id, pharmacy_id, item, unit, aliases (`;`-separated), pos
- **orders**: id (`YYYYMMDD-HHMMSS-xxxx`), pharmacy_id, customer_id, channel, kind (text/audio), wa_msg_id UNIQUE, wa_ts, audio, transcript, engine, engines_json, status (transcribing/draft/final), reply_json, created, confirmed, is_test
- **order_lines**: order_id, kind (draft/final), pos, qty, item, unit, raw, status/match, score, top3_json, repeat_of, watch

Files live under `data/`: `audio/`, `pdf/`, `wa/` (simulator outbox, seen ids). The whole `data/` folder is git-ignored. Back it up by copying the folder (or use `sqlite3 .backup`).

Personal data: customer phone numbers and voice notes are personal data. Real deployments need a retention rule (suggested: audio deleted after 30 days) and a pharmacy-owner agreement. The seed only uses invented 23299000xxx numbers.
