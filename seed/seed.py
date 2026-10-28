"""Seed TEST data: invented pharmacies and customers, no real records. Run: python -m seed.seed  (wipes the DB first)."""
import os, sys, csv, time, datetime, random
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from krio_crm import db, service, wa
HERE = os.path.dirname(os.path.abspath(__file__))
PHARMS = [("TEST Pharmacy Freetown", "Freetown (test)", "active", "free", "SIM_PHONE_NUMBER_ID"),
          ("TEST Chemist Bo", "Bo (test)", "trial", "free", "SIM_PN_BO"),
          ("TEST Drug Store Makeni", "Makeni (test)", "lead", "free", "")]
CUST = [("TEST Aminata", "23299000001"), ("TEST Mohamed", "23299000002"), ("TEST Fatmata", "23299000003"), ("TEST Ibrahim", "23299000004"),
        ("TEST Mariama", "23299000005"), ("TEST Abu", "23299000006"), ("TEST Kadiatu", "23299000007"), ("TEST Sorie", "23299000008")]
ORDERS = ["tu strip panadol en wan botul kof medsin", "wan pak kotem en tri sachet ORS", "fayv strip amoxil en tu strip flagyl",
          "wan inhaler en siks pis siring", "tu pak malaria test", "gi mi wan botul kof medsin", "tri strip para en wan tube", "wan pak kotin",
          "tu strip panadol tu strip panadol", "wan bokis glav en tu rol kotin wul", "fo sachet ORS en wan botul vitamin C", "wan strip cipro"]
def main():
    p = db.path()
    for s in ("", "-wal", "-shm"):
        if os.path.exists(p + s): os.remove(p + s)
    db._local.__dict__.clear(); wa.reset_sim_state()
    rows = list(csv.DictReader(open(os.path.join(HERE, "test_catalogue_SL_pharmacy_TESTDATA.csv"), encoding="utf-8-sig")))
    pids = []
    for name, town, st, plan, pn in PHARMS:
        pid = db.create_pharmacy(name, town=town, status=st, plan=plan, wa_phone_number_id=pn, owner_name="TEST Owner", phone="", notes="Invented test pharmacy. Not a real business.", is_test=1)
        db.set_catalogue(pid, rows); pids.append((pid, pn))
    rnd = random.Random(7); now = time.time(); n = 0
    for k, text in enumerate(ORDERS * 2):
        pid, pn = pids[0] if k % 3 else pids[k % 2] ; name, num = CUST[rnd.randrange(len(CUST))]
        age = (len(ORDERS) * 2 - k) * 3600 * 2.5   # spread over ~2.5 days
        ts = int(now - age)
        m = {"id": f"wamid.SEED{k:04d}", "from": num, "ts": ts, "type": "text", "name": name, "pnid": pn, "text": text}
        oid = service.intake_message(m, sync=True); created = datetime.datetime.fromtimestamp(ts).isoformat(timespec="seconds")
        db.update_order(oid, created=created)
        if k < len(ORDERS) * 2 - 6 and k % 4 != 3:   # older orders: confirmed with the suggested items
            o = db.order(oid); service.confirm(oid, [{"pos": i, "item": l["item"] or (l["top3"][0]["item"] if l["top3"] else "__DROP__"), "qty": l["qty"]} for i, l in enumerate(o["lines"])])
            db.update_order(oid, confirmed=created)
        n += 1
    c = db.one("SELECT id FROM customers WHERE wa_id='23299000001'")
    if c: db.update("customers", c["id"], {"status": "regular", "notes": "TEST customer. Prefers pickup after 5pm.", "tags": "pickup"}, db.CU_FIELDS)
    print(f"seeded {len(PHARMS)} TEST pharmacies, {n} TEST orders, {len(db.customers())} TEST customers into {p}")
if __name__ == "__main__": main()
