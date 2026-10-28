"""Krio order CRM: webhook (ported from v3), API, CRM screens, DB, seed. Simulator only: any network call fails the test."""
import os, sys, json, time, tempfile, unittest, urllib.request
H = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, H)
T = tempfile.mkdtemp()
os.environ.update({"KRIO_DB": os.path.join(T, "t.sqlite3"), "KRIO_DATA": os.path.join(T, "data"), "WA_STATE_DIR": os.path.join(T, "wa"), "WA_VERIFY_TOKEN": "unit-verify"})
for k in ("WA_TOKEN", "WA_PHONE_NUMBER_ID", "WA_APP_SECRET", "WA_LIVE", "KRIO_ASR"): os.environ.pop(k, None)
def _no_net(*a, **k): raise AssertionError("network call attempted in simulator mode")
urllib.request.urlopen = _no_net
from krio_crm import wa, db, service, matcher
from krio_crm.server import app
from seed import seed
app.config["SYNC"] = True
CLIP = os.path.join(H, "tests", "clip_k1_synthetic.wav")
PN = "SIM_PHONE_NUMBER_ID"
class Base(unittest.TestCase):
    def setUp(self):
        import io, contextlib
        with contextlib.redirect_stdout(io.StringIO()): seed.main()
        self.c = app.test_client(); self.n0 = len(db.orders())
    def post(self, payload, secret=wa.SIM_SECRET, sig=None):
        raw = json.dumps(payload).encode()
        return self.c.post("/webhook", data=raw, headers={"Content-Type": "application/json", "X-Hub-Signature-256": sig or wa.sign(raw, secret)})
    def newest(self): return db.order(db.orders()[0]["id"])
class Webhook(Base):
    def test_verify_ok(self):
        r = self.c.get("/webhook?hub.mode=subscribe&hub.verify_token=unit-verify&hub.challenge=12345"); self.assertEqual((r.status_code, r.get_data(as_text=True)), (200, "12345"))
    def test_verify_bad_token(self): self.assertEqual(self.c.get("/webhook?hub.mode=subscribe&hub.verify_token=nope&hub.challenge=1").status_code, 403)
    def test_bad_signature_rejected(self):
        self.assertEqual(self.post(wa.sim_payload("23299000050", text="wan strip cipro", pnid=PN), sig="sha256=" + "0" * 64).status_code, 403); self.assertEqual(len(db.orders()), self.n0)
    def test_missing_signature_rejected(self): self.assertEqual(self.c.post("/webhook", data=b"{}", headers={"Content-Type": "application/json"}).status_code, 403)
    def test_status_only_payload_ignored(self):
        p = {"object": "whatsapp_business_account", "entry": [{"id": "W", "changes": [{"field": "messages", "value": {"messaging_product": "whatsapp", "metadata": {"display_phone_number": "1", "phone_number_id": "P"}, "statuses": [{"id": "wamid.x", "status": "delivered", "timestamp": "1", "recipient_id": "2"}]}}]}]}
        self.assertEqual(wa.parse(p), []); self.assertEqual(self.post(p).status_code, 200); self.assertEqual(len(db.orders()), self.n0)
    def test_text_order_matches_and_creates_customer(self):
        self.post(wa.sim_payload("23299000050", text="tu strip panadol en wan botul kof medsin", name="TEST New", pnid=PN))
        o = self.newest(); self.assertEqual([l["item"] for l in o["lines"]], ["Paracetamol 500mg", "Cough Syrup (Benylin)"])
        self.assertEqual(o["customer_wa"], "23299000050"); self.assertTrue(db.one("SELECT 1 FROM customers WHERE wa_id='23299000050'"))
    def test_routes_by_phone_number_id(self):
        self.post(wa.sim_payload("23299000051", text="wan strip cipro", pnid="SIM_PN_BO")); self.assertEqual(self.newest()["pharmacy"], "TEST Chemist Bo")
    def test_duplicate_delivery_ignored(self):
        p = wa.sim_payload("23299000052", text="wan strip cipro", pnid=PN); self.post(p); self.post(p); self.assertEqual(len(db.orders()), self.n0 + 1)
    def test_audio_without_asr_is_draft_for_owner(self):
        self.post(wa.sim_payload("23299000053", media_id=wa.sim_register_media(CLIP, "audio/wav"), pnid=PN)); o = self.newest()
        self.assertEqual((o["kind"], o["status"]), ("audio", "draft")); self.assertIn("asr-off", o["engines"]); self.assertTrue(os.path.exists(os.path.join(service.data_dir("audio"), o["audio"])))
    def test_audio_with_stub_asr(self):
        os.environ["KRIO_ASR"] = "1"; import types; fake = types.ModuleType("krio_crm.asr")
        fake.run_all = lambda p, e=None: {"mms-kri": {"text": "tu strip panadol en wan botul kof medsin", "sec": .1}, "whisper-krio": {"text": "", "sec": .1}}
        sys.modules["krio_crm.asr"] = fake; import krio_crm; real = getattr(krio_crm, "asr", None); krio_crm.asr = fake
        try:
            self.post(wa.sim_payload("23299000054", media_id=wa.sim_register_media(CLIP, "audio/wav"), pnid=PN)); o = self.newest()
            self.assertEqual(o["engine"], "mms-kri"); self.assertEqual([l["item"] for l in o["lines"]], ["Paracetamol 500mg", "Cough Syrup (Benylin)"])
        finally:
            os.environ.pop("KRIO_ASR"); sys.modules.pop("krio_crm.asr", None)
            if real: krio_crm.asr = real
            else: delattr(krio_crm, "asr")
    def test_confirm_sends_plain_text_reply_and_pdf(self):
        self.post(wa.sim_payload("23299000055", text="tu strip panadol en wan botul kof medsin", pnid=PN)); o = self.newest(); out0 = len(wa.sim_outbox())
        form = {f"item{i}": l["item"] for i, l in enumerate(o["lines"])}; form.update({f"qty{i}": str(l["qty"]) for i, l in enumerate(o["lines"])})
        self.assertEqual(self.c.post(f"/o/{o['id']}/confirm", data=form).status_code, 302)
        out = wa.sim_outbox(); self.assertEqual(len(out), out0 + 1); m = out[-1]["request"]
        self.assertEqual((m["type"], m["to"]), ("text", "23299000055")); self.assertNotIn("template", m)
        self.assertTrue(m["text"]["body"].startswith("Got your order:")); self.assertIn("2 x Paracetamol 500mg", m["text"]["body"])
        o = db.order(o["id"]); self.assertEqual((o["status"], o["reply"]["status"]), ("final", "sent-simulated")); self.assertTrue(os.path.exists(service.pdf_path(o["id"])))
    def test_window_closed_blocks_reply(self):
        self.post(wa.sim_payload("23299000056", text="wan strip cipro", ts=int(time.time()) - 25 * 3600, pnid=PN)); o = self.newest(); out0 = len(wa.sim_outbox())
        self.c.post(f"/o/{o['id']}/confirm", data={"item0": o["lines"][0]["item"], "qty0": "1"})
        self.assertEqual(len(wa.sim_outbox()), out0); self.assertEqual(db.order(o["id"])["reply"]["status"], "blocked-window-closed")
    def test_live_mode_needs_explicit_flag(self):
        os.environ.update({"WA_TOKEN": "x" * 20, "WA_PHONE_NUMBER_ID": "123"})
        try: self.assertEqual(wa.mode(), "simulator")
        finally: os.environ.pop("WA_TOKEN"); os.environ.pop("WA_PHONE_NUMBER_ID")
    def test_send_payload_shape(self):
        self.assertEqual(wa.text_message("232", "hi"), {"messaging_product": "whatsapp", "recipient_type": "individual", "to": "232", "type": "text", "text": {"preview_url": False, "body": "hi"}})
class Api(Base):
    def test_health(self): j = self.c.get("/api/health").get_json(); self.assertEqual((j["ok"], j["mode"], j["asr"]), (True, "simulator", False))
    def test_orders_list_and_filter(self):
        a = self.c.get("/api/orders").get_json(); self.assertEqual(len(a), self.n0)
        for o in self.c.get("/api/orders?chip=Replied").get_json(): self.assertEqual(o["chip"], "Replied")
    def test_match(self):
        j = self.c.post("/api/match", json={"text": "wan strip cipro"}).get_json(); self.assertEqual(j["lines"][0]["item"], "Ciprofloxacin 500mg")
    def test_confirm_api_unknown_and_drop(self):
        self.post(wa.sim_payload("23299000057", text="tu strip panadol en wan botul kof medsin", pnid=PN)); o = self.newest()
        j = self.c.post(f"/api/orders/{o['id']}/confirm", json={"lines": [{"pos": 0, "item": "Not In List"}, {"pos": 1, "item": "__DROP__"}]}).get_json()
        self.assertEqual(len(j["final"]), 1); self.assertTrue(j["final"][0]["item"].startswith("UNKNOWN"))
    def test_retype(self):
        self.post(wa.sim_payload("23299000058", text="zzz", pnid=PN)); o = self.newest()
        j = self.c.post(f"/api/orders/{o['id']}/retype", json={"text": "wan strip cipro"}).get_json(); self.assertEqual(j["lines"][0]["item"], "Ciprofloxacin 500mg")
    def test_pharmacy_crud_and_catalogue(self):
        r = self.c.post("/api/pharmacies", json={"name": "TEST Unit Shop", "town": "X"}); self.assertEqual(r.status_code, 201); pid = r.get_json()["id"]
        self.assertEqual(self.c.patch(f"/api/pharmacies/{pid}", json={"status": "trial"}).get_json()["status"], "trial")
        self.c.put(f"/api/pharmacies/{pid}/catalogue", json={"items": [{"item": "Zinc Tablets", "unit": "strip", "aliases": "zink"}]})
        self.assertEqual([x["item"] for x in self.c.get(f"/api/pharmacies/{pid}/catalogue").get_json()["items"]], ["Zinc Tablets"])
    def test_customer_patch(self):
        cid = self.c.get("/api/customers").get_json()[0]["id"]
        self.assertEqual(self.c.patch(f"/api/customers/{cid}", json={"status": "vip", "notes": "TEST"}).get_json()["status"], "vip")
    def test_404(self): self.assertEqual(self.c.get("/api/orders/nope").status_code, 404)
class Screens(Base):
    def test_all_screens_offline_and_clean(self):
        o = db.orders()[0]["id"]; f = [x for x in db.orders() if x["status"] == "final"][0]["id"]
        for u in ["/", "/?f=Needs%20check", f"/o/{o}", f"/o/{f}/receipt", "/customers", "/customers/1", "/pharmacies", "/pharmacies/1", "/catalogue", "/summary", "/settings", "/simulate"]:
            r = self.c.get(u); self.assertEqual(r.status_code, 200, u); h = r.get_data(as_text=True)
            self.assertNotRegex(h, r"(src|href)=[\"']?https?://", u); self.assertNotIn("Starlink", h); self.assertNotIn("Guinea", h)
    def test_pdf_and_png(self):
        f = [x for x in db.orders() if x["status"] == "final"][0]["id"]
        self.assertEqual(self.c.get(f"/o/{f}/pdf").data[:4], b"%PDF")
    def test_settings_never_prints_secrets(self):
        os.environ["WA_APP_SECRET"] = "supersecretvalue123"
        try: self.assertNotIn("supersecretvalue123", self.c.get("/settings").get_data(as_text=True))
        finally: os.environ.pop("WA_APP_SECRET")
    def test_simulator_form_creates_order(self):
        self.c.post("/simulate", data={"kind": "text", "text": "wan strip cipro", "from": "23299000059", "pharmacy": "1"}); self.assertEqual(len(db.orders()), self.n0 + 1)
class Data(Base):
    def test_seed_is_all_test(self):
        self.assertTrue(all(p["is_test"] and p["name"].startswith("TEST") for p in db.pharmacies()))
        self.assertTrue(all(c["name"].startswith("TEST") and c["wa_id"].startswith("232990000") for c in db.customers()))
    def test_customer_unique_per_pharmacy(self):
        a = db.upsert_customer(1, "23299000001", "x", 1); b = db.upsert_customer(1, "23299000001", "y", 1); self.assertEqual(a, b)
    def test_matcher_unchanged_thresholds(self): self.assertEqual(matcher.AUTO, 85)
if __name__ == "__main__": unittest.main()
