# Setup and run

Needs Python 3.11+. ASR is optional and heavy.

```bash
cd krio-order-crm
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m seed.seed           # wipes + seeds TEST data
scripts/run.sh 5090                     # or: PORT=5090 .venv/bin/python -m krio_crm.server
nohup scripts/run.sh 5090 > data/server.log 2>&1 &   # background
```

| Env | Default | Meaning |
|---|---|---|
| PORT / HOST | 5090 / 127.0.0.1 | listen address |
| KRIO_DB | data/krio_crm.sqlite3 | database |
| KRIO_DATA | data/ | audio, pdf, wa state |
| KRIO_ASR | off | `1` = transcribe voice notes (needs about 2.5GB RAM plus torch/transformers/vosk) |
| KRIO_ASR_ENGINES | whisper-krio,mms-kri,vosk-en | engines to run |
| KRIO_MODELS_BASE | prototype folder | where the model folders live |
| WA_VERIFY_TOKEN, WA_APP_SECRET, WA_TOKEN, WA_PHONE_NUMBER_ID | unset | Meta credentials, kept in the environment only and never committed |
| WA_LIVE | off | `1` plus credentials = real sends. Anything else = simulator |

With ASR off, voice notes still arrive. The owner plays the note, types what they hear into "Correct the text", and the matcher does the rest.

Tests: `.venv/bin/python -m unittest tests.test_crm` (29 tests, offline; any network call fails a test).
Screenshots: `pip install playwright` then `.venv/bin/python scripts/shots.py http://127.0.0.1:5090 /tmp/shots` (uses the system Chrome).
