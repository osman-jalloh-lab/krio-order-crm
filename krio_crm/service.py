"""Order intake, matching, confirmation, PDF. Matching and speech-to-text are the v2/v3 modules, unchanged."""
import os, uuid, datetime, shutil, threading, json
from . import db, matcher, wa
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def data_dir(*p):
    d = os.path.join(os.environ.get("KRIO_DATA") or os.path.join(ROOT, "data"), *p); os.makedirs(d, exist_ok=True); return d
def asr_enabled(): return os.environ.get("KRIO_ASR") == "1"
def asr_engines(): return tuple(e for e in os.environ.get("KRIO_ASR_ENGINES", "whisper-krio,mms-kri,vosk-en").split(",") if e)
def catalogue(pid): return matcher.build_catalogue(db.catalogue_rows(pid))
def new_id(): return datetime.datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4]
def match(pid, text):
    lines = matcher.match_lines(text or "", catalogue(pid)); return lines, matcher.match_score(lines)
# ---- status chip used by inbox, CRM and API
def chip(o):
    r = (o.get("reply") or {}).get("status", "")
    if o["status"] == "transcribing": return ("Transcribing", "info")
    if r.startswith("sent"): return ("Replied", "ok")
    if r == "blocked-window-closed": return ("Window closed", "bad")
    if o["status"] == "final": return ("Confirmed", "ok")
    if not o["lines"] or any(l["status"] != "auto" or l.get("watch") or l.get("repeat_of") is not None for l in o["lines"]): return ("Needs check", "warn")
    return ("Ready", "info")
# ---- intake (webhook, simulator, API)
def intake_message(m, sync=False):
    """m = one parsed WhatsApp message (wa.parse). Creates customer + order. Audio is transcribed in the background."""
    ph = db.pharmacy_for_phone_number_id(m.get("pnid")) or db.default_pharmacy()
    if not ph: raise RuntimeError("no pharmacy configured")
    cid = db.upsert_customer(ph["id"], m["from"], m.get("name", ""), ph["is_test"])
    o = {"id": new_id(), "pharmacy_id": ph["id"], "customer_id": cid, "channel": "whatsapp", "kind": m["type"], "wa_msg_id": m["id"],
         "wa_ts": m.get("ts") or 0, "is_test": ph["is_test"]}
    if m["type"] == "text":
        lines, sc = match(ph["id"], m["text"])
        o.update(transcript=m["text"], engine="whatsapp-text", engines={"whatsapp-text": {"text": m["text"], "score": sc}}, lines=lines)
        db.insert_order(o); return o["id"]
    path = wa.fetch_media(m["media_id"], data_dir("audio")); ext = os.path.splitext(path)[1]
    dst = os.path.join(data_dir("audio"), o["id"] + ext); shutil.move(path, dst)
    o.update(audio=os.path.basename(dst), status="transcribing" if asr_enabled() else "draft",
             engines={} if asr_enabled() else {"asr-off": {"text": "", "note": "Speech-to-text is switched off on this machine (KRIO_ASR!=1). Listen and type what you hear."}})
    db.insert_order(o)
    if asr_enabled():
        job = lambda: transcribe(o["id"], dst, ph["id"])
        job() if sync else threading.Thread(target=job, daemon=True).start()
    return o["id"]
def transcribe(oid, path, pid):
    from . import asr     # heavy (torch); imported only when switched on
    res = asr.run_all(path, asr_engines()); cat = catalogue(pid)
    for r in res.values(): r["lines"] = matcher.match_lines(r["text"], cat); r["score"] = matcher.match_score(r["lines"])
    krio = [k for k in ("mms-kri", "whisper-krio") if k in res and res[k]["text"]]
    pool = krio if any(res[k]["score"] > 0 for k in krio) else [k for k in res if res[k]["text"]]   # English Vosk = fallback only
    best = max(pool, key=lambda k: res[k]["score"]) if pool else None
    db.set_lines(oid, "draft", res[best]["lines"] if best else [])
    db.update_order(oid, engines={k: {kk: vv for kk, vv in v.items() if kk != "lines"} for k, v in res.items()}, engine=best or "",
                    transcript=res[best]["text"] if best else "", status="draft")
def retype(oid, text):
    """Owner types (or corrects) what the customer said; re-run the matcher on it."""
    o = db.order(oid); lines, sc = match(o["pharmacy_id"], text)
    eng = dict(o["engines"]); eng["owner-typed"] = {"text": text, "score": sc}
    db.set_lines(oid, "draft", lines); db.update_order(oid, transcript=text, engine="owner-typed", engines=eng, status="draft")
# ---- confirm + reply
def reply_text(o, lines):
    items = ", ".join(f'{l["qty"]} x {l["item"]}' for l in lines if not str(l["item"]).startswith("UNKNOWN")) or "your items"
    unk = [l for l in lines if str(l["item"]).startswith("UNKNOWN")]
    return f"Got your order: {items}." + (f" We'll check {len(unk)} item(s) with you." if unk else "") + f" We will have it ready soon. – {o['pharmacy']}"
def preview_lines(o):
    return [{"qty": l["qty"], "item": l["item"] or (l["top3"][0]["item"] if l["top3"] else "UNKNOWN")} for l in o["lines"] if l.get("repeat_of") is None]
def confirm(oid, choices):
    """choices: list of {pos, item, qty, keep('one'|'both')}; item '__DROP__' removes the line. Items not in the catalogue become UNKNOWN."""
    o = db.order(oid); cat = {x["item"]: x for x in db.catalogue_rows(o["pharmacy_id"])}; by = {int(c["pos"]): c for c in choices}; fin = []
    for i, l in enumerate(o["lines"]):
        c = by.get(i, {}); v = c.get("item") or l["item"] or ""; qn = str(c.get("qty") or l["qty"])
        if v == "__DROP__": continue
        if l.get("repeat_of") is not None and c.get("keep", "one") != "both" and v == l["item"]: continue
        if v in cat: fin.append({"qty": qn, "item": v, "unit": cat[v]["unit"], "raw": l["raw"], "match": "auto" if (l["status"] == "auto" and v == l["item"]) else "owner-confirmed"})
        else: fin.append({"qty": qn, "item": f'UNKNOWN: "{l["raw"]}"', "unit": "", "raw": l["raw"], "match": "unknown"})
    db.set_lines(oid, "final", fin); db.update_order(oid, status="final", confirmed=db.now()); o = db.order(oid)
    make_pdf(o)
    if o["channel"] == "whatsapp" and o["customer_wa"]:
        db.update_order(oid, reply=wa.send_text(o["customer_wa"], reply_text(o, fin), o["wa_ts"] or 0))
    return db.order(oid)
def pdf_path(oid): return os.path.join(data_dir("pdf"), oid + ".pdf")
def make_pdf(o):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    ss = getSampleStyleSheet(); ink = colors.HexColor("#0A0A14"); sun = colors.HexColor("#FFE03D")
    doc = SimpleDocTemplate(pdf_path(o["id"]), pagesize=A4, title="LAVAALL order record (TEST)")
    meta = Table([["Pharmacy", o["pharmacy"]], ["Customer", (o["customer_name"] or "") + (" +" + o["customer_wa"] if o["customer_wa"] else "")],
                  ["Order", o["id"]], ["Confirmed", (o["confirmed"] or "").replace("T", " ")], ["Channel", f'{o["channel"]} ({o["kind"]})'], ["Source of text", o["engine"] or "-"]], colWidths=[130, 330])
    meta.setStyle(TableStyle([("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#F4F9FF")), ("GRID", (0, 0), (-1, -1), .5, colors.HexColor("#DDE6F0")), ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold")]))
    rows = [["#", "Qty", "Item", "Unit", "Match", "Heard"]] + [[i + 1, l["qty"], Paragraph(l["item"], ss["BodyText"]), l["unit"], l["match"], Paragraph(l["raw"], ss["BodyText"])] for i, l in enumerate(o["final"])]
    it = Table(rows, colWidths=[22, 35, 170, 50, 90, 120]); it.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), ink), ("TEXTCOLOR", (0, 0), (-1, 0), sun), ("GRID", (0, 0), (-1, -1), .5, colors.HexColor("#DDE6F0")), ("FONTSIZE", (0, 0), (-1, -1), 8), ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
    doc.build([Paragraph("LAVAALL", ParagraphStyle("h", parent=ss["Title"], textColor=ink, alignment=0)), Paragraph("Voice order record — TEST DATA ONLY", ss["Heading2"]), Spacer(1, 6), meta, Spacer(1, 12), it, Spacer(1, 12),
               Paragraph("What the customer said (machine or owner-typed)", ss["Heading3"]), Paragraph(o["transcript"] or "(none)", ss["BodyText"]), Spacer(1, 14),
               Paragraph("Lines confirmed by the pharmacy on the review screen. No prices. Not a prescription or patient record.", ss["Italic"])])
# ---- summary
def summary(day, pid=None):
    os_ = db.orders(pid=pid, day=day); tot = {}; units = {}; auto = n = 0
    for o in os_:
        for l in (o["final"] or o["lines"]):
            if not l.get("item") or str(l["item"]).startswith("UNKNOWN"): continue
            try: qn = float(l["qty"])
            except ValueError: qn = 1
            tot[l["item"]] = tot.get(l["item"], 0) + qn; units[l["item"]] = l.get("unit", "")
        for l in o["lines"]: n += 1; auto += l["status"] == "auto"
    top = sorted(((k, int(v) if v == int(v) else v) for k, v in tot.items()), key=lambda x: -x[1])[:10]
    st = {"orders": len(os_), "confirmed": sum(o["status"] == "final" for o in os_), "replied": sum((o["reply"] or {}).get("status", "").startswith("sent") for o in os_),
          "needs_check": sum(chip(o)[0] == "Needs check" for o in os_), "auto_pct": round(100 * auto / n) if n else 0, "whatsapp": sum(o["channel"] == "whatsapp" for o in os_),
          "customers": len({o["customer_id"] for o in os_ if o["customer_id"]})}
    return st, top, units
