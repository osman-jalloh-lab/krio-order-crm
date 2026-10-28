"""SQLite storage for pharmacies, customers, orders, order lines and catalogues. One file, WAL mode, no ORM."""
import os, sqlite3, json, datetime, threading, re
SCHEMA = """
CREATE TABLE IF NOT EXISTS pharmacies(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, slug TEXT UNIQUE NOT NULL, town TEXT DEFAULT '', owner_name TEXT DEFAULT '',
  phone TEXT DEFAULT '', wa_phone_number_id TEXT DEFAULT '', status TEXT DEFAULT 'lead',   -- lead | trial | active | paused
  plan TEXT DEFAULT 'free', notes TEXT DEFAULT '', is_test INTEGER DEFAULT 1, created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS customers(
  id INTEGER PRIMARY KEY, pharmacy_id INTEGER NOT NULL REFERENCES pharmacies(id) ON DELETE CASCADE,
  wa_id TEXT NOT NULL, name TEXT DEFAULT '', notes TEXT DEFAULT '', tags TEXT DEFAULT '', status TEXT DEFAULT 'new',  -- new | regular | vip | blocked
  is_test INTEGER DEFAULT 1, created TEXT NOT NULL, last_seen TEXT, UNIQUE(pharmacy_id, wa_id));
CREATE TABLE IF NOT EXISTS catalogue_items(
  id INTEGER PRIMARY KEY, pharmacy_id INTEGER NOT NULL REFERENCES pharmacies(id) ON DELETE CASCADE,
  item TEXT NOT NULL, unit TEXT DEFAULT '', aliases TEXT DEFAULT '', pos INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS orders(
  id TEXT PRIMARY KEY, pharmacy_id INTEGER NOT NULL REFERENCES pharmacies(id) ON DELETE CASCADE,
  customer_id INTEGER REFERENCES customers(id) ON DELETE SET NULL, channel TEXT DEFAULT 'whatsapp', kind TEXT DEFAULT 'text', -- text | audio
  wa_msg_id TEXT UNIQUE, wa_ts INTEGER, transcript TEXT DEFAULT '', engine TEXT DEFAULT '', engines_json TEXT DEFAULT '{}',
  audio TEXT DEFAULT '', status TEXT DEFAULT 'draft',   -- transcribing | draft | final | cancelled
  reply_json TEXT DEFAULT '{}', created TEXT NOT NULL, confirmed TEXT, is_test INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS order_lines(
  id INTEGER PRIMARY KEY, order_id TEXT NOT NULL REFERENCES orders(id) ON DELETE CASCADE, kind TEXT NOT NULL, -- draft | final
  pos INTEGER, qty TEXT, item TEXT, unit TEXT DEFAULT '', raw TEXT DEFAULT '', status TEXT DEFAULT '', score REAL DEFAULT 0,
  top3_json TEXT DEFAULT '[]', watch TEXT DEFAULT '', repeat_of INTEGER, match TEXT DEFAULT '');
CREATE INDEX IF NOT EXISTS ix_orders_ph ON orders(pharmacy_id, created);
CREATE INDEX IF NOT EXISTS ix_lines ON order_lines(order_id, kind, pos);
"""
_local = threading.local()
def path(): return os.environ.get("KRIO_DB") or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "krio_crm.sqlite3")
def conn():
    p = path(); c = getattr(_local, "c", None)
    if c is None or getattr(_local, "p", None) != p:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        c = sqlite3.connect(p, check_same_thread=False); c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys=ON"); c.execute("PRAGMA journal_mode=WAL"); c.executescript(SCHEMA)
        _local.c, _local.p = c, p
    return c
def now(): return datetime.datetime.now().isoformat(timespec="seconds")
def slug(s): return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "pharmacy"
def q(sql, *a): return [dict(r) for r in conn().execute(sql, a).fetchall()]
def one(sql, *a):
    r = conn().execute(sql, a).fetchone(); return dict(r) if r else None
def run(sql, *a):
    c = conn(); cur = c.execute(sql, a); c.commit(); return cur.lastrowid
# ---- pharmacies
PH_FIELDS = ("name", "town", "owner_name", "phone", "wa_phone_number_id", "status", "plan", "notes")
def create_pharmacy(name, **kw):
    kw = {k: v for k, v in kw.items() if k in PH_FIELDS + ("is_test",)}
    base = slug(name); s = base; i = 2
    while one("SELECT 1 FROM pharmacies WHERE slug=?", s): s = f"{base}-{i}"; i += 1
    cols = ["name", "slug", "created"] + list(kw); vals = [name, s, now()] + list(kw.values())
    return run(f"INSERT INTO pharmacies({','.join(cols)}) VALUES({','.join('?'*len(cols))})", *vals)
def update(table, id_, fields, allowed):
    f = {k: v for k, v in fields.items() if k in allowed}
    if f: run(f"UPDATE {table} SET {','.join(k+'=?' for k in f)} WHERE id=?", *f.values(), id_)
def pharmacy(pid): return one("SELECT * FROM pharmacies WHERE id=?", pid)
def pharmacies():
    return q("""SELECT p.*, (SELECT COUNT(*) FROM orders o WHERE o.pharmacy_id=p.id) n_orders,
      (SELECT COUNT(*) FROM customers c WHERE c.pharmacy_id=p.id) n_customers,
      (SELECT COUNT(*) FROM catalogue_items c WHERE c.pharmacy_id=p.id) n_items,
      (SELECT MAX(created) FROM orders o WHERE o.pharmacy_id=p.id) last_order FROM pharmacies p ORDER BY p.name""")
def pharmacy_for_phone_number_id(pnid):
    return one("SELECT * FROM pharmacies WHERE wa_phone_number_id=? AND wa_phone_number_id!=''", pnid) if pnid else None
def default_pharmacy():
    name = os.environ.get("WA_DEFAULT_CLIENT", "")
    return (one("SELECT * FROM pharmacies WHERE name=?", name) if name else None) or one("SELECT * FROM pharmacies ORDER BY id LIMIT 1")
# ---- customers
CU_FIELDS = ("name", "notes", "tags", "status")
def upsert_customer(pid, wa_id, name="", is_test=1):
    c = one("SELECT * FROM customers WHERE pharmacy_id=? AND wa_id=?", pid, wa_id)
    if c:
        run("UPDATE customers SET last_seen=?, name=CASE WHEN name='' THEN ? ELSE name END WHERE id=?", now(), name or "", c["id"]); return c["id"]
    return run("INSERT INTO customers(pharmacy_id,wa_id,name,is_test,created,last_seen) VALUES(?,?,?,?,?,?)", pid, wa_id, name or "", is_test, now(), now())
def customer(cid): return one("SELECT c.*, p.name pharmacy FROM customers c JOIN pharmacies p ON p.id=c.pharmacy_id WHERE c.id=?", cid)
def customers(pid=None, search=""):
    sql = """SELECT c.*, p.name pharmacy, (SELECT COUNT(*) FROM orders o WHERE o.customer_id=c.id) n_orders,
      (SELECT MAX(created) FROM orders o WHERE o.customer_id=c.id) last_order FROM customers c JOIN pharmacies p ON p.id=c.pharmacy_id WHERE 1=1"""
    a = []
    if pid: sql += " AND c.pharmacy_id=?"; a.append(pid)
    if search: sql += " AND (c.name LIKE ? OR c.wa_id LIKE ?)"; a += [f"%{search}%"] * 2
    return q(sql + " ORDER BY COALESCE(last_order,c.created) DESC", *a)
# ---- catalogue
def catalogue_rows(pid): return q("SELECT item, unit, aliases FROM catalogue_items WHERE pharmacy_id=? ORDER BY pos, id", pid)
def set_catalogue(pid, rows):
    c = conn(); c.execute("DELETE FROM catalogue_items WHERE pharmacy_id=?", (pid,))
    c.executemany("INSERT INTO catalogue_items(pharmacy_id,item,unit,aliases,pos) VALUES(?,?,?,?,?)",
                  [(pid, r["item"].strip(), (r.get("unit") or "").strip(), (r.get("aliases") or "").strip(), i) for i, r in enumerate(rows) if r.get("item", "").strip()])
    c.commit()
# ---- orders
def _lines(oid, kind):
    out = []
    for l in q("SELECT * FROM order_lines WHERE order_id=? AND kind=? ORDER BY pos", oid, kind):
        l["top3"] = json.loads(l.pop("top3_json") or "[]"); out.append(l)
    return out
def order(oid):
    o = one("""SELECT o.*, p.name pharmacy, p.slug pharmacy_slug, c.name customer_name, c.wa_id customer_wa FROM orders o
      JOIN pharmacies p ON p.id=o.pharmacy_id LEFT JOIN customers c ON c.id=o.customer_id WHERE o.id=?""", oid)
    if not o: return None
    o["engines"] = json.loads(o.pop("engines_json") or "{}"); o["reply"] = json.loads(o.pop("reply_json") or "{}")
    o["lines"] = _lines(oid, "draft"); o["final"] = _lines(oid, "final"); return o
def orders(pid=None, customer_id=None, day=None, limit=500):
    sql = "SELECT id FROM orders WHERE 1=1"; a = []
    if pid: sql += " AND pharmacy_id=?"; a.append(pid)
    if customer_id: sql += " AND customer_id=?"; a.append(customer_id)
    if day: sql += " AND substr(created,1,10)=?"; a.append(day)
    return [order(r["id"]) for r in q(sql + " ORDER BY created DESC LIMIT ?", *a, limit)]
def insert_order(o):
    run("""INSERT INTO orders(id,pharmacy_id,customer_id,channel,kind,wa_msg_id,wa_ts,transcript,engine,engines_json,audio,status,created,is_test)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", o["id"], o["pharmacy_id"], o.get("customer_id"), o.get("channel", "whatsapp"), o.get("kind", "text"),
        o.get("wa_msg_id"), o.get("wa_ts"), o.get("transcript", ""), o.get("engine", ""), json.dumps(o.get("engines", {})), o.get("audio", ""),
        o.get("status", "draft"), o.get("created") or now(), o.get("is_test", 1))
    set_lines(o["id"], "draft", o.get("lines", []))
def set_lines(oid, kind, lines):
    c = conn(); c.execute("DELETE FROM order_lines WHERE order_id=? AND kind=?", (oid, kind))
    c.executemany("""INSERT INTO order_lines(order_id,kind,pos,qty,item,unit,raw,status,score,top3_json,watch,repeat_of,match) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        [(oid, kind, i, str(l.get("qty", 1)), l.get("item"), l.get("unit", ""), l.get("raw", ""), l.get("status", ""), l.get("score", 0),
          json.dumps(l.get("top3", [])), l.get("watch") or "", l.get("repeat_of"), l.get("match", "")) for i, l in enumerate(lines)])
    c.commit()
def update_order(oid, **f):
    for k in ("engines", "reply"):
        if k in f: f[k + "_json"] = json.dumps(f.pop(k))
    if f: run(f"UPDATE orders SET {','.join(k+'=?' for k in f)} WHERE id=?", *f.values(), oid)
