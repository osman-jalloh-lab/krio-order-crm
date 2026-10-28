# Roadmap

1. **Fine-tune Whisper on Krio before any commercial use.** The MMS Krio model is CC-BY-NC (non-commercial). Collect consented pharmacy voice notes, fine-tune whisper-small, and drop MMS.
2. **Hosting:** a Hetzner CX43 (€16.49 per month) running Flask with gunicorn, Caddy for HTTPS, and ASR on the same box. Vercel can host the dashboard only if ASR runs elsewhere.
3. Login for owners (one account per pharmacy) and API tokens. Today it is localhost only with no auth.
4. Go live on WhatsApp after Osman's OK (see whatsapp-go-live.md).
5. Prices and stock on catalogue items, so totals can go on the receipt.
6. Audio retention job (delete after 30 days) and export/delete per customer.
7. Postgres when there is more than one server.
8. Optional: send the PDF as a WhatsApp document.
