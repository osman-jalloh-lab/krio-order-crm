"""Flask app: dashboard screens + JSON API + Meta WhatsApp webhook (simulator unless WA_LIVE=1)."""
import os, json, time, datetime, csv, io, collections, subprocess, threading
from flask import Flask, request, redirect, render_template, abort, jsonify, send_file, url_for
from . import db, wa, service
from .service import chip
HERE = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, template_folder=os.path.join(HERE, "templates"), static_folder=os.path.join(HERE, "static"))
app.config.update(MAX_CONTENT_LENGTH=20 * 1024 * 1024, SYNC=False)
def conf(l):
    s = l.get("score", 0); return "hi" if l["status"] == "auto" and s >= 85 else ("mid" if s >= 60 else "lo")
def who(o): return o.get("customer_name") or (("+" + o["customer_wa"]) if o.get("customer_wa") else "Walk-in")
def initials(s): return "".join(w[0] for w in (s or "?").replace("+", "").split()[:2]).upper() or "?"
app.jinja_env.globals.update(chip=chip, conf=conf, who=who, initials=initials, mode=wa.mode)
app.jinja_env.filters["hm"] = lambda s: s.replace("T", " ")[11:16] if s else ""
app.jinja_env.filters["day"] = lambda s: s[:10] if s else ""
app.jinja_env.filters["when"] = lambda s: (s[11:16] if s and s[:10] == datetime.date.today().isoformat() else (s[:10] if s else "—"))
def get_order(oid):
    o = db.order(oid)
    if not o: abort(404)
    return o
def cur_pharmacy():
    pid = request.values.get("pharmacy", type=int)
    return db.pharmacy(pid) if pid else db.default_pharmacy()
# ================= WhatsApp webhook (unchanged contract from v3)
@app.get("/webhook")
def wh_verify():
    ch = wa.verify(request.args); return (ch, 200, {"Content-Type": "text/plain"}) if ch is not None else ("forbidden", 403)
@app.post("/webhook")
def wh_receive():
    raw = request.get_data()
    if not wa.check_signature(raw, request.headers.get("X-Hub-Signature-256", "")): return "bad signature", 403
    try: msgs = wa.parse(json.loads(raw or b"{}"))
    except ValueError: return "bad json", 400
    for m in msgs:
        if not m["id"] or m["type"] not in ("audio", "text"): continue
        if wa.seen(m["id"]) or db.one("SELECT 1 FROM orders WHERE wa_msg_id=?", m["id"]): continue
        job = lambda m=m: service.intake_message(m, sync=app.config["SYNC"])
        job() if app.config["SYNC"] else threading.Thread(target=job, daemon=True).start()
    return "EVENT_RECEIVED", 200
# ================= screens
@app.get("/")
def inbox():
    f = request.args.get("f", "all"); ph = request.args.get("pharmacy", type=int)
    os_ = db.orders(pid=ph); counts = collections.Counter(chip(o)[0] for o in os_)
    if f != "all": os_ = [o for o in os_ if chip(o)[0] == f]
    return render_template("inbox.html", orders=os_, f=f, counts=counts, tab="inbox", phs=db.pharmacies(), ph=ph)
@app.get("/o/<oid>")
def review(oid):
    o = get_order(oid); cat = db.catalogue_rows(o["pharmacy_id"])
    return render_template("review.html", o=o, cat=cat, tab="inbox", preview=service.reply_text(o, service.preview_lines(o)))
@app.post("/o/<oid>/confirm")
def confirm(oid):
    o = get_order(oid); ch = []
    for i in range(len(o["lines"])):
        ch.append({"pos": i, "item": request.form.get(f"alt{i}") or request.form.get(f"item{i}", ""), "qty": request.form.get(f"qty{i}", "1"), "keep": request.form.get(f"keep{i}", "one")})
    service.confirm(oid, ch); return redirect(url_for("receipt", oid=oid))
@app.post("/o/<oid>/retype")
def retype(oid):
    get_order(oid); service.retype(oid, request.form.get("text", "")); return redirect(url_for("review", oid=oid))
@app.get("/o/<oid>/receipt")
def receipt(oid): return render_template("receipt.html", o=get_order(oid), tab="inbox")
@app.get("/o/<oid>/pdf")
def pdf(oid):
    p = service.pdf_path(get_order(oid)["id"])
    if not os.path.exists(p): abort(404)
    return send_file(p, download_name=f"order-{oid}.pdf")
@app.get("/o/<oid>/pdf.png")
def pdfpng(oid):
    p = service.pdf_path(get_order(oid)["id"]); png = p[:-4] + "-p1"
    if not os.path.exists(p): abort(404)
    if not os.path.exists(png + ".png") or os.path.getmtime(png + ".png") < os.path.getmtime(p):
        subprocess.run(["pdftoppm", "-png", "-r", "80", "-f", "1", "-l", "1", "-singlefile", p, png], check=True)
    return send_file(png + ".png")
@app.get("/o/<oid>/audio")
def audio(oid):
    o = get_order(oid)
    if not o["audio"]: abort(404)
    return send_file(os.path.join(service.data_dir("audio"), os.path.basename(o["audio"])), conditional=True)
@app.get("/customers")
def customers_page():
    s = request.args.get("q", ""); ph = request.args.get("pharmacy", type=int)
    return render_template("customers.html", rows=db.customers(ph, s), s=s, tab="customers", phs=db.pharmacies(), ph=ph)
@app.route("/customers/<int:cid>", methods=["GET", "POST"])
def customer_page(cid):
    c = db.customer(cid) or abort(404)
    if request.method == "POST":
        db.update("customers", cid, request.form.to_dict(), db.CU_FIELDS); return redirect(url_for("customer_page", cid=cid, saved=1))
    os_ = db.orders(customer_id=cid); counts = collections.Counter()
    for o in os_:
        for l in (o["final"] or o["lines"]):
            if l.get("item") and not str(l["item"]).startswith("UNKNOWN"): counts[l["item"]] += 1
    return render_template("customer.html", c=c, orders=os_, usual=counts.most_common(5), tab="customers")
@app.get("/pharmacies")
def pharmacies_page(): return render_template("pharmacies.html", rows=db.pharmacies(), tab="pharmacies")
@app.route("/pharmacies/<int:pid>", methods=["GET", "POST"])
def pharmacy_page(pid):
    p = db.pharmacy(pid) or abort(404)
    if request.method == "POST":
        db.update("pharmacies", pid, request.form.to_dict(), db.PH_FIELDS); return redirect(url_for("pharmacy_page", pid=pid, saved=1))
    return render_template("pharmacy.html", p=p, orders=db.orders(pid=pid, limit=8), cust=db.customers(pid)[:8], n_items=len(db.catalogue_rows(pid)), tab="pharmacies")
@app.post("/pharmacies/new")
def pharmacy_new():
    name = request.form.get("name", "").strip() or abort(400)
    pid = db.create_pharmacy(name, town=request.form.get("town", ""), status="lead", is_test=1); return redirect(url_for("pharmacy_page", pid=pid))
@app.route("/catalogue", methods=["GET", "POST"])
def catalogue():
    p = cur_pharmacy() or abort(404)
    if request.method == "POST":
        rows = []; i = 0
        while f"item{i}" in request.form:
            it = request.form[f"item{i}"].strip()
            if it and not request.form.get(f"del{i}"):
                rows.append({"item": it, "unit": request.form.get(f"unit{i}", ""), "aliases": "|".join(a.strip() for a in request.form.get(f"aliases{i}", "").replace(",", "|").split("|") if a.strip())})
            i += 1
        db.set_catalogue(p["id"], rows); return redirect(url_for("catalogue", pharmacy=p["id"], saved=len(rows)))
    return render_template("catalogue.html", p=p, rows=db.catalogue_rows(p["id"]), phs=db.pharmacies(), tab="catalogue")
@app.get("/catalogue.csv")
def catalogue_csv():
    p = cur_pharmacy() or abort(404); b = io.StringIO(); w = csv.DictWriter(b, ["item", "unit", "aliases"]); w.writeheader(); w.writerows(db.catalogue_rows(p["id"]))
    return app.response_class(b.getvalue(), mimetype="text/csv", headers={"Content-Disposition": f'attachment; filename="{p["slug"]}-catalogue.csv"'})
@app.get("/summary")
def summary():
    days = [r["d"] for r in db.q("SELECT DISTINCT substr(created,1,10) d FROM orders ORDER BY d DESC LIMIT 30")]
    d = request.args.get("day") or (days[0] if days else datetime.date.today().isoformat()); ph = request.args.get("pharmacy", type=int)
    st, top, units = service.summary(d, ph)
    return render_template("summary.html", d=d, days=days, st=st, top=top, units=units, tab="summary", phs=db.pharmacies(), ph=ph)
@app.get("/settings")
def settings():
    c = wa.cfg(); return render_template("settings.html", m=wa.mode(), ver=c["ver"], env=wa.env_status(), outbox=wa.sim_outbox()[-6:][::-1],
        hook=request.host_url + "webhook", tab="settings", asr=service.asr_enabled(), engines=service.asr_engines(), phs=db.pharmacies())
@app.route("/simulate", methods=["GET", "POST"])
def simulate():
    if request.method == "POST":
        if wa.mode() == "live": abort(403)
        ph = db.pharmacy(request.form.get("pharmacy", type=int)) or db.default_pharmacy()
        frm = "".join(ch for ch in request.form.get("from", "") if ch.isdigit()) or "23299000000"
        ts = int(time.time()) - (25 * 3600 if request.form.get("old") else 0)
        if request.form.get("kind") == "audio":
            mid = wa.sim_register_media(os.path.join(os.path.dirname(HERE), "tests", "clip_k1_synthetic.wav"), "audio/wav")
            p = wa.sim_payload(frm, media_id=mid, name=request.form.get("name", ""), ts=ts, pnid=ph["wa_phone_number_id"] or None)
        else: p = wa.sim_payload(frm, text=request.form.get("text", ""), name=request.form.get("name", ""), ts=ts, pnid=ph["wa_phone_number_id"] or None)
        raw = json.dumps(p).encode()
        with app.test_client() as tc: r = tc.post("/webhook", data=raw, headers={"Content-Type": "application/json", "X-Hub-Signature-256": wa.sign(raw, wa.SIM_SECRET)})
        time.sleep(.3); return redirect(url_for("inbox", sim=r.status_code))
    return render_template("simulate.html", tab="inbox", phs=db.pharmacies())
# ================= JSON API  (/api/...)
def J(x, code=200): return jsonify(x), code
def body(): return request.get_json(silent=True) or {}
def order_json(o): return {**o, "chip": chip(o)[0]}
@app.get("/api/health")
def api_health(): return J({"ok": True, "mode": wa.mode(), "asr": service.asr_enabled(), "db": os.path.basename(db.path())})
@app.get("/api/pharmacies")
def api_pharmacies(): return J(db.pharmacies())
@app.post("/api/pharmacies")
def api_pharmacy_new():
    b = body()
    if not b.get("name"): return J({"error": "name required"}, 400)
    pid = db.create_pharmacy(b.pop("name"), **b); return J(db.pharmacy(pid), 201)
@app.route("/api/pharmacies/<int:pid>", methods=["GET", "PATCH"])
def api_pharmacy(pid):
    if not db.pharmacy(pid): return J({"error": "not found"}, 404)
    if request.method == "PATCH": db.update("pharmacies", pid, body(), db.PH_FIELDS)
    return J(db.pharmacy(pid))
@app.route("/api/pharmacies/<int:pid>/catalogue", methods=["GET", "PUT"])
def api_catalogue(pid):
    if not db.pharmacy(pid): return J({"error": "not found"}, 404)
    if request.method == "PUT":
        rows = body().get("items")
        if not isinstance(rows, list): return J({"error": "items: list required"}, 400)
        db.set_catalogue(pid, rows)
    return J({"pharmacy_id": pid, "items": db.catalogue_rows(pid)})
@app.get("/api/customers")
def api_customers(): return J(db.customers(request.args.get("pharmacy", type=int), request.args.get("q", "")))
@app.route("/api/customers/<int:cid>", methods=["GET", "PATCH"])
def api_customer(cid):
    if not db.customer(cid): return J({"error": "not found"}, 404)
    if request.method == "PATCH": db.update("customers", cid, body(), db.CU_FIELDS)
    return J({**db.customer(cid), "orders": [o["id"] for o in db.orders(customer_id=cid)]})
@app.get("/api/orders")
def api_orders():
    os_ = db.orders(pid=request.args.get("pharmacy", type=int), customer_id=request.args.get("customer", type=int), day=request.args.get("day"))
    st = request.args.get("chip"); return J([order_json(o) for o in os_ if not st or chip(o)[0] == st])
@app.get("/api/orders/<oid>")
def api_order(oid):
    o = db.order(oid); return J(order_json(o)) if o else J({"error": "not found"}, 404)
@app.post("/api/orders/<oid>/confirm")
def api_confirm(oid):
    if not db.order(oid): return J({"error": "not found"}, 404)
    return J(order_json(service.confirm(oid, body().get("lines", []))))
@app.post("/api/orders/<oid>/retype")
def api_retype(oid):
    if not db.order(oid): return J({"error": "not found"}, 404)
    service.retype(oid, body().get("text", "")); return J(order_json(db.order(oid)))
@app.post("/api/match")
def api_match():
    b = body(); pid = b.get("pharmacy_id") or (db.default_pharmacy() or {}).get("id")
    lines, sc = service.match(pid, b.get("text", "")); return J({"pharmacy_id": pid, "score": sc, "lines": lines})
@app.get("/api/summary")
def api_summary():
    d = request.args.get("day") or datetime.date.today().isoformat(); st, top, units = service.summary(d, request.args.get("pharmacy", type=int))
    return J({"day": d, "stats": st, "top_items": [{"item": k, "qty": v, "unit": units[k]} for k, v in top]})
def main():
    port = int(os.environ.get("PORT", "5090")); app.run(host=os.environ.get("HOST", "127.0.0.1"), port=port, debug=False, threaded=True)
if __name__ == "__main__": main()
