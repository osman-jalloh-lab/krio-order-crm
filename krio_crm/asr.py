"""Local CPU speech-to-text. Krio: MMS-1b-all + 'kri' adapter (CC-BY-NC 4.0, DEMO ONLY) and evanmazor/whisper-small-krio (Apache-2.0).
English fallback: Vosk small-en-us (v1). Models load lazily, one at a time guarded by a lock."""
import os, json, wave, subprocess, threading, time
import numpy as np
BASE=os.environ.get("KRIO_MODELS_BASE","/home/box/agent-data/projects/lavaall/prototypes/voice-to-pdf")  # models/hf + models/vosk live here (not in git)
os.environ.setdefault("HF_HOME",os.path.join(BASE,"models","hf")); os.environ.setdefault("HF_HUB_OFFLINE","1")
import torch; torch.set_num_threads(4)
L=threading.Lock(); M={}
def to16k(path):
    wav=path+".16k.wav"; subprocess.run(["ffmpeg","-y","-loglevel","error","-i",path,"-ac","1","-ar","16000",wav],check=True); return wav
def load_audio(wav):
    import soundfile as sf; a,sr=sf.read(wav,dtype="float32"); return a
def mms(a):
    if "mms" not in M:
        from transformers import Wav2Vec2ForCTC, AutoProcessor
        p=AutoProcessor.from_pretrained("facebook/mms-1b-all",target_lang="kri")
        m=Wav2Vec2ForCTC.from_pretrained("facebook/mms-1b-all",target_lang="kri",ignore_mismatched_sizes=True,torch_dtype=torch.bfloat16,low_cpu_mem_usage=True)
        m.eval(); M["mms"]=(p,m)
    p,m=M["mms"]; x=p(a,sampling_rate=16000,return_tensors="pt")
    with torch.inference_mode(): lg=m(x.input_values.to(torch.bfloat16)).logits
    return p.decode(lg[0].float().argmax(-1))
def whisper_krio(a):
    if "wk" not in M:
        from transformers import WhisperProcessor, WhisperForConditionalGeneration
        p=WhisperProcessor.from_pretrained("evanmazor/whisper-small-krio"); m=WhisperForConditionalGeneration.from_pretrained("evanmazor/whisper-small-krio"); m.eval(); M["wk"]=(p,m)
    p,m=M["wk"]; out=[]
    for i in range(0,len(a),30*16000):
        x=p(a[i:i+30*16000],sampling_rate=16000,return_tensors="pt").input_features
        with torch.inference_mode(): ids=m.generate(x,max_new_tokens=200)
        out.append(p.batch_decode(ids,skip_special_tokens=True)[0])
    return " ".join(out).strip()
def vosk_en(wav):
    from vosk import Model,KaldiRecognizer,SetLogLevel
    if "vosk" not in M: SetLogLevel(-1); M["vosk"]=Model(os.path.join(BASE,"models","vosk-model-small-en-us-0.15"))
    wf=wave.open(wav,"rb"); r=KaldiRecognizer(M["vosk"],16000); parts=[]
    while True:
        d=wf.readframes(4000)
        if not d: break
        if r.AcceptWaveform(d): parts.append(json.loads(r.Result())["text"])
    parts.append(json.loads(r.FinalResult())["text"]); return " ".join(p for p in parts if p).strip()
ENGINES={"mms-kri":("Meta MMS-1b-all + kri adapter (CC-BY-NC, demo only)",mms),
         "whisper-krio":("evanmazor/whisper-small-krio (Apache-2.0)",whisper_krio)}
def run_all(path, engines=("mms-kri","whisper-krio","vosk-en")):
    wav=to16k(path); a=load_audio(wav); res={}
    for k in engines:
        t=time.time()
        try:
            with L: txt=vosk_en(wav) if k=="vosk-en" else ENGINES[k][1](a)
            res[k]={"text":txt,"sec":round(time.time()-t,1)}
        except Exception as e: res[k]={"text":"","sec":round(time.time()-t,1),"error":f"{type(e).__name__}: {str(e)[:200]}"}
    return res
