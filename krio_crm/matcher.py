"""Fuzzy + sound-alike matching of transcript text to a client's catalogue. Never invents items."""
import csv, re, unicodedata
from rapidfuzz import fuzz
import jellyfish
AUTO=85
NUMS={"zero":0,"one":1,"two":2,"three":3,"four":4,"five":5,"six":6,"seven":7,"eight":8,"nine":9,"ten":10,"eleven":11,"twelve":12,
 "fifteen":15,"twenty":20,"thirty":30,"fifty":50,"hundred":100,
 # Krio
 "wan":1,"tu":2,"tri":3,"fo":4,"fayv":5,"faiv":5,"siks":6,"sevin":7,"sebin":7,"et":8,"nayn":9,"nain":9,"ten":10,"ilevin":11,"twelv":12,"twenti":20,"tray":3,"try":3,"wen":1,"fen":5,"fem":5,"to":2,"tou":2}
STOP={"and","en","plus","give","gi","me","mi","i","want","wan","de","di","a","of","pack","packs","strip","strips","bottle","bottles","box","boxes",
 "piece","pieces","pis","tablet","tablets","sachet","sachets","tube","tubes","roll","rolls","ampoule","ampoules","order","oda","customer","kostoma",
 "packet","packets","trip","please","plis","pak","bokis","botul","for","fo","bai","buy","sel","sell","total","na","dem","sɔm","som","the"}
def norm(s):
    s=s.lower().replace("ɛ","e").replace("ɔ","o")
    s=unicodedata.normalize("NFKD",s); s="".join(c for c in s if not unicodedata.combining(c))
    s=re.sub(r"[^a-z0-9 ]+"," ",s)
    s=re.sub(r"\bmed(?:i|e)? ?sin\b","medsin",s)  # ASR often splits 'medsin'
    s=re.sub(r"\bmalaya\b","malaria",s)  # Osman dictation 2026-10-27
    return s.split()
UNITS={"ml":"ml","milliliter":"ml","milliliters":"ml","millilitre":"ml","millilitres":"ml","mls":"ml","mg":"mg","milligram":"mg","milligrams":"mg",
 "g":"g","gram":"g","grams":"g","l":"l","liter":"l","litre":"l","liters":"l","litres":"l","cc":"ml","mcg":"mcg","microgram":"mcg"}
def _strip(a): return " ".join(w for w in a.split() if w not in STOP)
def load_catalogue(path):
    return build_catalogue(csv.DictReader(open(path,encoding="utf-8-sig")))
def build_catalogue(rows):
    """rows: dicts with item, unit, aliases ('a|b|c'). Same logic as the v2/v3 CSV loader."""
    out=[]
    for r in rows:
        name=r.get("item","").strip()
        if not name: continue
        al=[a.strip() for a in (r.get("aliases") or "").split("|") if a.strip()]+[name, re.sub(r"\(.*?\)|\d+\w*","",name).strip()]
        out.append({"item":name,"unit":r.get("unit","").strip(),"aliases":sorted({" ".join(norm(a)) for a in al if norm(a)}|{x for a in al if norm(a) for x in [_strip(" ".join(norm(a)))] if len(x)>3}),
                    # short alias left after dropping unit words (e.g. 'ion tablet' -> 'ion'): exact word match only
                    "exact":sorted({x for a in al if norm(a) for x in [_strip(" ".join(norm(a)))] if x and len(x)<=3 and x!=" ".join(norm(a))})})
    return out
def _phon(a,b):
    ma=" ".join(jellyfish.metaphone(w) for w in a.split()); mb=" ".join(jellyfish.metaphone(w) for w in b.split())
    return fuzz.ratio(ma,mb) if ma and mb else 0
def score(phrase,alias):
    f=max(fuzz.ratio(phrase,alias), fuzz.token_sort_ratio(phrase,alias))
    # sound-alike only for longer words (short codes like 'gv'/'kaf' collide phonetically)
    p=_phon(phrase,alias)*0.95 if min(len(phrase),len(alias))>=5 else 0
    return round(max(f,p),1)
def best(phrase,cat,k=3):
    res=[]
    for c in cat:
        s=max(score(phrase,a) for a in c["aliases"])
        if phrase in c.get("exact",()): s=100.0
        res.append((s,c["item"],c["unit"]))
    res.sort(reverse=True); return res[:k]
GENERIC={"syrup","syrups","tablet","tablets","cream","creams","drip","drips","injection","capsule","capsules","medsin","medicine","ointment","drops"}
GLUE=("strips","strip","bottles","bottle","tablets","tablet","sachets","sachet","tubes","tube","packets","packet","pack","boxes","box","rolls","roll","pieces","piece","ampoules","ampoule")
def unglue(ws,cat):
    """'stripmetronidazole' -> 'strip metronidazole' when the remainder matches the catalogue better than the glued word."""
    out=[]
    for w in ws:
        for g in GLUE:
            r=w[len(g):]
            if w.startswith(g) and len(r)>=4 and cat:
                br=best(r,cat,1); bw=best(w,cat,1)
                if br and br[0][0]>=AUTO and br[0][0]>(bw[0][0] if bw else 0): out+= [g,r]; break
        else: out.append(w)
    return out
CONFUSABLE=[("kotin","Artemether-Lumefantrine (Coartem)","cotin","Cotton Wool")]
def _watch(ws):
    from rapidfuzz import fuzz as _f
    for a,ia,b,ib in CONFUSABLE:
        for w in ws:
            if max(_f.ratio(w,a),_f.ratio(w,b))>=80:
                return f"Check: '{a}' = {ia} but '{b}' = {ib}. Heard '{w}'."
    return ""
def _seg_sentence(text,cat=None):
    """Split one sentence into chunks. A number starts a chunk; 'and/en/plus' end one; unit words become size."""
    ws=norm(text); ws=unglue(ws,cat) if cat else ws; chunks=[]; cur={"qty":None,"w":[],"size":None}
    for k,w in enumerate(ws):
        isnum=w.isdigit() or (w in NUMS and w!="fo")
        nxt=ws[k+1] if k+1<len(ws) else ""
        if isnum and nxt in UNITS:   # '5 ml' -> size of the current item, never a new item
            cur["size"]=f"{int(w) if w.isdigit() else NUMS[w]} {UNITS[nxt]}"; cur["_skip"]=True; continue
        if w in UNITS and cur.pop("_skip",False): continue
        if isnum:
            v=int(w) if w.isdigit() else NUMS[w]
            if cur["qty"] in (20,30,40,50,60,70,80,90) and not cur["w"] and not cur["size"] and 1<=v<=9 and ws[k-1] in NUMS:
                cur["qty"]+=v; continue   # 'twenty two' -> 22
            if cur["w"] or cur["qty"] is not None or cur["size"]: chunks.append(cur)
            cur={"qty":int(w) if w.isdigit() else NUMS[w],"w":[],"size":None}; continue
        if w in("and","en","plus"):
            if cur["w"]: chunks.append(cur); cur={"qty":None,"w":[],"size":None}
            continue
        if w in UNITS: continue
        if w not in STOP: cur["w"].append(w)
    cur.pop("_skip",None)
    if cur["w"] or cur["qty"] is not None or cur["size"]: chunks.append(cur)
    return chunks
def _attach_wordless(chunks,cat=None):
    """Chunks with no item words (e.g. '5 ml') give size/qty to the nearest item chunk."""
    out=[]; pend=None
    for c in chunks:
        if not c["w"]:
            tgt=out[-1] if out else None
            if tgt is not None and cat and c["qty"] is not None and not c["size"] and not tgt["size"]:
                nm=_top(tgt["w"],cat)[1] or ""; m=re.search(r"(\d+)\s*(G|ml|mg|mcg)\b",nm)
                if m and int(m.group(1))==c["qty"]: tgt["size"]=m.group(1)+m.group(2); continue   # 'Cannula. Twenty two.' -> 22G
            if tgt is not None and c["size"] and not tgt["size"] and c["qty"] is None: tgt["size"]=c["size"]
            else: pend=c   # qty/unit-only sentence ('Two strips.') carries to the next item
            continue
        if pend:
            c["size"]=c["size"] or pend["size"]; c["qty"]=c["qty"] if c["qty"] is not None else (None if pend["size"] else pend["qty"]); pend=None
        out.append(c)
    return out
def segment(text,cat=None):
    """Sentence ends are item boundaries. A qty-less fragment joins the previous chunk when that matches better
    (e.g. 'metered. Spigot.'). With a catalogue, chunks holding two items are split at the match boundary."""
    chunks=[]
    for sent in re.split(r"[.!?;\n]+",text):
        for c in _seg_sentence(sent,cat):
            chunks.append(c)
    chunks=_attach_wordless(chunks,cat)
    if cat:
        g=[]; carry=None   # generic-only chunks ('syrup', 'drip') join the next named item, else the one before
        for k,c in enumerate(chunks):
            if carry: c["w"]=carry["w"]+c["w"]; c["qty"]=carry["qty"] if carry["qty"] is not None else c["qty"]; c["size"]=c["size"] or carry["size"]; carry=None
            if c["w"] and all(w in GENERIC for w in c["w"]):
                nxt=chunks[k+1] if k+1<len(chunks) else None
                if nxt is not None and nxt["qty"] is None and not all(w in GENERIC for w in nxt["w"]): carry=c; continue
                if g: g[-1]["w"]+=c["w"]; continue
            g.append(c)
        if carry: g.append(carry)
        chunks=g
        merged=[]
        for c in chunks:
            if merged and c["qty"] is None:
                p=merged[-1]; prev_s=_top(p["w"],cat); own=_top(c["w"],cat); join=_top(p["w"]+c["w"],cat)
                if join[0]>max(prev_s[0],own[0]) or (own[0]<60 and join[0]>=prev_s[0] and prev_s[0]<AUTO):
                    p["w"]=p["w"]+c["w"]; p["size"]=p["size"] or c["size"]; continue
            merged.append(c)
        chunks=[]
        for c in merged: chunks.extend(_split_cat(c,cat))
        out=[]   # neighbours resolving to the same item merge when the second has no qty of its own
        for c in chunks:
            if out and c["qty"] is None and c["w"]:
                a=_top(out[-1]["w"],cat); b=_top(c["w"],cat)
                if a[0]>=AUTO and b[0]>=AUTO and a[1]==b[1]: out[-1]["w"]+=c["w"]; continue
            out.append(c)
        chunks=out
    return [c for c in chunks if c["w"]]
def _cands(ws,cat):
    cands={}
    for n in (1,2,3):  # best n-gram window inside the chunk
        for i in range(len(ws)-n+1):
            for s,it,u in best(" ".join(ws[i:i+n]),cat,5):
                if s>cands.get(it,(0,))[0]: cands[it]=(s,u)
    return sorted(((v[0],k,v[1]) for k,v in cands.items()),reverse=True)[:3]
def _top(ws,cat):
    t=_cands(ws,cat) if ws else []
    return (t[0][0],t[0][1]) if t else (0,None)
def _split_cat(c,cat):
    ws=c["w"]
    if len(ws)<2: return [c]
    w0=best(" ".join(ws),cat,1); whole=(w0[0][0],w0[0][1]) if w0 else (0,None)  # whole phrase as one item
    for i in range(1,len(ws)):
        a=_top(ws[:i],cat); b=_top(ws[i:],cat)
        if a[0]>=AUTO and b[0]>=AUTO and a[1]!=b[1] and not (whole[0]>=AUTO and whole[0]>=max(a[0],b[0])):
            first={"qty":c["qty"],"w":ws[:i],"size":c["size"]}; rest={"qty":None,"w":ws[i:],"size":None}
            return [first]+_split_cat(rest,cat)
    return [c]
def match_lines(text,cat):
    lines=[]
    for c in segment(text,cat):
        raw=" ".join(c["w"]); top=_cands(c["w"],cat)
        if top and top[0][0]>=AUTO: st="auto"; item=top[0][1]
        elif top and top[0][0]>=60: st="suggest"; item=None
        else: st="unknown"; item=None
        if c.get("size"): raw+=f" [{c['size']}]"
        lines.append({"watch":_watch(c["w"]),"raw":raw,"qty":c["qty"] or 1,"size":c.get("size") or "","status":st,"item":item,"unit":(top[0][2] if st=="auto" else ""),
                      "score":top[0][0] if top else 0,"top3":[{"item":t[1],"score":t[0],"unit":t[2]} for t in top]})
    seen={}   # repeated item = likely re-read; flag for owner, never auto-merge
    for i,l in enumerate(lines):
        if l["status"]=="auto":
            if l["item"] in seen: l["repeat_of"]=seen[l["item"]]
            else: seen[l["item"]]=i
    return lines
def match_score(lines):
    """Item-match score used to pick the better ASR transcript: auto lines count fully, suggestions partly."""
    if not lines: return 0.0
    return round(sum(1.0 if l["status"]=="auto" else (l["score"]/200 if l["status"]=="suggest" else 0) for l in lines),2)
