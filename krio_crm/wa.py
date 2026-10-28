"""WhatsApp Cloud API adapter (LAVAALL voice-order v3).

Simulator by default. Real Graph calls happen ONLY when WA_LIVE=1 *and* WA_TOKEN + WA_PHONE_NUMBER_ID are set
(going live needs Osman's OK). Plain-text replies only, no templates.
Env: WA_TOKEN, WA_PHONE_NUMBER_ID, WA_VERIFY_TOKEN, WA_APP_SECRET, WA_GRAPH_VERSION (default v26.0), WA_LIVE, WA_DEFAULT_CLIENT.
"""
import os, json, hmac, hashlib, time, uuid, threading, shutil, urllib.request
HERE=os.path.dirname(os.path.abspath(__file__)); STATE=os.environ.get("WA_STATE_DIR") or os.path.join(os.path.dirname(HERE),"data","wa"); os.makedirs(STATE,exist_ok=True)
GRAPH="https://graph.facebook.com"
SIM_SECRET="sim-app-secret-TESTONLY"          # simulator signs its own posts with this; never a real secret
SIM_VERIFY="lavaall-sim-verify"
WINDOW=24*3600                                # customer-service window: free-form replies allowed for 24h after the customer's last message
ENV=("WA_TOKEN","WA_PHONE_NUMBER_ID","WA_VERIFY_TOKEN","WA_APP_SECRET")
_lock=threading.Lock()
def cfg():
    e=os.environ; return {"token":e.get("WA_TOKEN",""),"pnid":e.get("WA_PHONE_NUMBER_ID",""),"verify":e.get("WA_VERIFY_TOKEN") or SIM_VERIFY,
        "secret":e.get("WA_APP_SECRET",""),"ver":e.get("WA_GRAPH_VERSION","v26.0"),"live":e.get("WA_LIVE")=="1","client":e.get("WA_DEFAULT_CLIENT","")}
def mode():
    c=cfg(); return "live" if (c["live"] and c["token"] and c["pnid"]) else "simulator"
def env_status(): return {k:bool(os.environ.get(k)) for k in ENV+("WA_LIVE",)}   # booleans only, never values
# ---------- webhook security
def verify(args):
    c=cfg()
    if args.get("hub.mode")=="subscribe" and args.get("hub.verify_token") and hmac.compare_digest(args.get("hub.verify_token",""),c["verify"]): return args.get("hub.challenge","")
    return None
def sign(raw,secret): return "sha256="+hmac.new(secret.encode(),raw,hashlib.sha256).hexdigest()
def check_signature(raw,header):
    """Meta signs each POST with the App Secret (X-Hub-Signature-256). Live: real secret required. Simulator: the sim secret."""
    c=cfg(); secret=c["secret"] or (SIM_SECRET if mode()=="simulator" else "")
    if not secret or not header: return False
    return hmac.compare_digest(sign(raw,secret),header)
# ---------- inbound payload
def parse(p):
    out=[]
    if p.get("object")!="whatsapp_business_account": return out
    for e in p.get("entry",[]):
        for ch in e.get("changes",[]):
            v=ch.get("value",{}); names={c.get("wa_id"):c.get("profile",{}).get("name","") for c in v.get("contacts",[])}
            pn=v.get("metadata",{}).get("phone_number_id","")
            for m in v.get("messages",[]):
                t=m.get("type"); d={"id":m.get("id"),"from":m.get("from"),"ts":int(m.get("timestamp","0") or 0),"type":t,"name":names.get(m.get("from"),""),"pnid":pn,"media_id":None,"mime":None,"text":None}
                if t in ("audio","voice"): d["type"]="audio"; d["media_id"]=m[t].get("id"); d["mime"]=m[t].get("mime_type")
                elif t=="text": d["text"]=m["text"].get("body","")
                out.append(d)
    return out
# ---------- Graph calls (live only)
def _http(method,url,token,body=None):
    if mode()!="live": raise RuntimeError("Graph call blocked: simulator mode")
    req=urllib.request.Request(url,method=method,data=json.dumps(body).encode() if body is not None else None,headers={"Authorization":"Bearer "+token,**({"Content-Type":"application/json"} if body is not None else {})})
    with urllib.request.urlopen(req,timeout=30) as r: return r.read()
def fetch_media(media_id,dest_dir):
    """Media id -> (GET /{media-id} -> short-lived url) -> download with the same bearer token. Returns local path."""
    os.makedirs(dest_dir,exist_ok=True)
    if mode()!="live":
        src=_sim_media().get(media_id)
        if not src: raise KeyError("unknown simulated media id")
        dst=os.path.join(dest_dir,"wa-"+media_id+os.path.splitext(src["path"])[1]); shutil.copy(src["path"],dst); return dst
    c=cfg(); meta=json.loads(_http("GET",f"{GRAPH}/{c['ver']}/{media_id}?phone_number_id={c['pnid']}",c["token"]))
    ext={"audio/ogg":".ogg","audio/mpeg":".mp3","audio/mp4":".m4a","audio/aac":".aac","audio/amr":".amr"}.get((meta.get("mime_type") or "").split(";")[0],".bin")
    dst=os.path.join(dest_dir,"wa-"+media_id+ext); open(dst,"wb").write(_http("GET",meta["url"],c["token"])); return dst
def text_message(to,body): return {"messaging_product":"whatsapp","recipient_type":"individual","to":to,"type":"text","text":{"preview_url":False,"body":body[:4096]}}
def send_text(to,body,last_inbound_ts):
    """Plain-text reply inside the 24h service window. Returns a reply record (status sent / sent-simulated / blocked-window-closed / error)."""
    c=cfg(); url=f"{GRAPH}/{c['ver']}/{c['pnid'] or 'SIM_PHONE_NUMBER_ID'}/messages"; msg=text_message(to,body)
    rec={"to":to,"body":msg["text"]["body"],"at":int(time.time()),"mode":mode()}
    if time.time()-last_inbound_ts>WINDOW: rec["status"]="blocked-window-closed"; return rec   # would need a paid template; not built
    if mode()!="live":
        rec.update(status="sent-simulated",wamid="wamid.SIM"+uuid.uuid4().hex[:20])
        with _lock, open(os.path.join(STATE,"outbox.jsonl"),"a") as f: f.write(json.dumps({"url":url,"request":msg,"response":{"messages":[{"id":rec["wamid"]}]},"at":rec["at"]})+"\n")
        return rec
    try: r=json.loads(_http("POST",url,c["token"],msg)); rec.update(status="sent",wamid=r["messages"][0]["id"])
    except Exception as e: rec.update(status="error",error=type(e).__name__)
    return rec
# ---------- dedupe (Meta retries deliveries)
def seen(msg_id):
    p=os.path.join(STATE,"seen.json")
    with _lock:
        s=json.load(open(p)) if os.path.exists(p) else {}
        if msg_id in s: return True
        s[msg_id]=int(time.time()); json.dump(s,open(p,"w")); return False
# ---------- simulator
def _sim_media():
    p=os.path.join(STATE,"sim_media.json"); return json.load(open(p)) if os.path.exists(p) else {}
def sim_register_media(path,mime):
    m=_sim_media(); mid=str(uuid.uuid4().int)[:16]; m[mid]={"path":os.path.abspath(path),"mime":mime}
    json.dump(m,open(os.path.join(STATE,"sim_media.json"),"w")); return mid
def sim_payload(frm,media_id=None,mime="audio/ogg; codecs=opus",name="Test Customer",text=None,ts=None,pnid=None):
    """Same JSON shape Meta POSTs for a messages webhook (voice note or text)."""
    mid="wamid.HBgM"+uuid.uuid4().hex.upper()[:32]
    m={"from":frm,"id":mid,"timestamp":str(int(ts or time.time()))}
    if text is not None: m.update(type="text",text={"body":text})
    else: m.update(type="audio",audio={"mime_type":mime,"sha256":"SIMULATED","id":media_id,"voice":True})
    return {"object":"whatsapp_business_account","entry":[{"id":"SIM_WABA_ID","changes":[{"field":"messages","value":{"messaging_product":"whatsapp",
        "metadata":{"display_phone_number":"15550000000","phone_number_id":pnid or cfg()["pnid"] or "SIM_PHONE_NUMBER_ID"},
        "contacts":[{"profile":{"name":name},"wa_id":frm}],"messages":[m]}}]}]}
def sim_outbox():
    p=os.path.join(STATE,"outbox.jsonl"); return [json.loads(l) for l in open(p)] if os.path.exists(p) else []
def reset_sim_state():
    for f in ("outbox.jsonl","seen.json"):
        p=os.path.join(STATE,f)
        if os.path.exists(p): os.remove(p)
