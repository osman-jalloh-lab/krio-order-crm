# WhatsApp go-live

> **Stop: needs Osman's OK first.** Making the free Meta developer account and app is a signup. Nothing here has been done.

1. Osman approves, then creates a Meta developer account and a Business app (free) with the WhatsApp product added.
2. In WhatsApp > API Setup, use the free test number first and add up to 5 TEST recipient phones.
3. Copy the **phone number id**, a **temporary token** and the **app secret** into environment variables on the server only (`WA_PHONE_NUMBER_ID`, `WA_TOKEN`, `WA_APP_SECRET`). Never put them in git.
4. Choose your own `WA_VERIFY_TOKEN` string.
5. Expose the webhook over HTTPS: deploy (see roadmap) or, for a test, use a tunnel.
6. In Meta, set Webhook URL = `https://<host>/webhook`, use the same verify token, and subscribe to `messages`.
7. Put the phone number id on the pharmacy's page (Pharmacies > pharmacy > WhatsApp number id).
8. Start with `WA_LIVE=1`. Settings will show **Live**. Send a test voice note from an allowed phone.
9. For production: verify the business, add a real number (a new SIM per pharmacy, because Coexistence with the existing WhatsApp Business app needs a Solution Partner), and create a permanent system-user token.

Rules built in: replies are plain text only, inside 24 hours of the customer's last message. Outside that window the send is blocked and shown as "Window closed". Templates are not implemented.
