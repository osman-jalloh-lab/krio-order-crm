# LAVAALL Krio order CRM

A pharmacy customer sends a WhatsApp voice note or text in Krio, like "tu strip panadol en wan botul kof medsin". The pharmacy owner checks the matched items on one phone screen, taps **Confirm & send reply**, and gets a PDF order record. The customer gets back a plain-text "Got your order" message.

This is a standalone build: a Flask dashboard, a JSON API and the WhatsApp webhook, all on SQLite. It runs in **simulator mode** (it never calls Meta) unless `WA_LIVE=1` is set and the credentials are present. All seed data is invented and marked **TEST**.

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m seed.seed         # TEST data (wipes data/krio_crm.sqlite3)
scripts/run.sh 5090                   # http://127.0.0.1:5090
.venv/bin/python -m unittest tests.test_crm
```

Screens: Inbox, order review (auto-added / did-you-mean / blanks), receipt and PDF, Customers, Pharmacies pipeline, Catalogue editor, Today summary, Settings (Connect WhatsApp), Test-message simulator.

Docs: [architecture](docs/architecture.md) · [API](docs/api.md) · [data model](docs/data-model.md) · [setup & run](docs/setup-run.md) · [WhatsApp go-live](docs/whatsapp-go-live.md) · [costs](docs/costs.md) · [roadmap](docs/roadmap.md)

Not for commercial use yet: the MMS Krio speech model is licensed CC-BY-NC. See the roadmap.
