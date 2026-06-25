import os, json, uuid, shutil, re, httpx
from datetime import datetime
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

BASE_DIR = Path(__file__).resolve().parent.parent
BOOKS_DIR = BASE_DIR / 'books'
SAVES_DIR = BASE_DIR / 'saves'

app = FastAPI(title='StoryDive API', version='1.0.0')
app.add_middleware(CORSMiddleware, allow_origins=['*'], allow_methods=['*'], allow_headers=['*'])

class BookBrief(BaseModel):
    id: str; title: str; original_author: str; script_author: str
    genre: list; protagonist: str; save_count: int

class BookDetail(BaseModel):
    id: str; title: str; original_author: str; script_author: str
    upload_date: str; description: str; cover_image: str
    protagonist: str; genre: list; version: str

class SaveBrief(BaseModel):
    id: str; book_id: str; book_title: str
    last_modified: str; preview: list

class SaveDetail(BaseModel):
    id: str; book_id: str; book_title: str; book_author: str
    last_modified: str; story_preview: list; memo: str

class ActionRequest(BaseModel):
    save_id: str; action: str
    mode: str = 'normal'
    target_paragraph_index: Optional[int] = None

class SettingsData(BaseModel):
    llm_base_url: str = ''; llm_api_key: str = ''; llm_model: str = ''
    image_base_url: str = ''; image_api_key: str = ''; image_model: str = ''
    tts_endpoint: str = ''; llm_timeout: int = 60; llm_debug: bool = False

def load_json(p): 
    with open(p,'r',encoding='utf-8') as f: return json.load(f)
def load_md(p): 
    return open(p,'r',encoding='utf-8').read() if p.exists() else ''
def save_md(p, c):
    p.parent.mkdir(parents=True,exist_ok=True); open(p,'w',encoding='utf-8').write(c)

def load_settings():
    sp = BASE_DIR / 'settings.json'
    return load_json(sp) if sp.exists() else SettingsData().model_dump()

def parse_story_to_paragraphs(text):
    pars = []
    for line in text.strip().split('\n'):
        line = line.strip()
        if not line: continue
        if ': ' in line and not line.startswith('#') and not line.startswith('-'):
            parts = line.split(': ',1)
            sp = parts[0].strip()
            if sp and len(sp)<20 and not sp.startswith('http'):
                pars.append({'type':'dialogue','speaker':sp,'text':parts[1].strip()})
                continue
        pars.append({'type':'narration','text':line})
    return pars

def get_save_count(bid):
    n=0
    if SAVES_DIR.exists():
        for sd in SAVES_DIR.iterdir():
            if sd.is_dir() and (sd/'config.json').exists():
                try:
                    if load_json(sd/'config.json').get('book_id')==bid: n+=1
                except: pass
    return n

def get_saves_for_book(bid):
    r=[]
    if SAVES_DIR.exists():
        for sd in SAVES_DIR.iterdir():
            if sd.is_dir() and (sd/'config.json').exists():
                try:
                    if load_json(sd/'config.json').get('book_id')==bid: r.append(sd.name)
                except: pass
    return r


# ── LLM CLIENT ──
async def call_llm(messages, settings):
    url = (settings.get("llm_base_url","") or "https://api.openai.com/v1").rstrip("/") + "/chat/completions"
    key = settings.get("llm_api_key","")
    model = settings.get("llm_model","") or "gpt-4o"
    payload = {"model":model,"messages":messages,"temperature":0.8,"max_tokens":2048}
    debug = settings.get("llm_debug", False)
    if debug:
        print(f"\n=== LLM REQUEST ===\nURL: {url}\nModel: {model}\nPayload:\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n=== END REQUEST ===")
    headers = {"Authorization":f"Bearer {key}","Content-Type":"application/json"}
    import httpx
    to = settings.get('llm_timeout', 60) or 60
    async with httpx.AsyncClient(timeout=httpx.Timeout(float(to), connect=10.0)) as client:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        if debug:
            print(f"\n=== LLM RESPONSE ===\nStatus: {resp.status_code}\nBody:\n{json.dumps(resp.json(), ensure_ascii=False, indent=2)}\n=== END RESPONSE ===")
        return resp.json()["choices"][0]["message"]["content"]

def build_system_prompt(book_id):
    setting = load_md(BOOKS_DIR/book_id/"setting.md")
    cfg = load_json(BOOKS_DIR/book_id/"config.json")
    return f'''You are StoryDive's narrative engine for "{cfg["title"]}".

## Core Rules
1. Return ONLY a JSON array. Each element is a narrative paragraph.
2. Fields: "type" ("narration" or "dialogue"), "text".
   For dialogue also include: "speaker", "expression" (neutral/happy/sad/angry/surprised/determined/nervous/scared/calm/confused/shocked/weary/laughing/embarrassed/smug/worried/grinning/suspicious).
3. Use third-person limited POV following the protagonist.
4. Generate 4-8 paragraphs. Last paragraph must be a natural break point for player input.
5. Maintain the original work's language style.

## Setting
{setting}

Return ONLY the JSON array. No other text.'''

async def generate_narrative(book_id, save_id, action=None, mode="normal"):
    settings = load_settings()
    if not settings.get("llm_api_key") or settings["llm_api_key"] == "sk-placeholder":
        return mock_queue(book_id, action, mode)
    try:
        cfg = load_json(BOOKS_DIR/book_id/"config.json")
        story = load_md(SAVES_DIR/save_id/"story.md")
        memo = load_md(SAVES_DIR/save_id/"memo.md")
        protagonist = cfg.get("protagonist","protagonist")
        sp = build_system_prompt(book_id)
        parts = [f'# Script: {cfg["title"]}', f'# Protagonist: {protagonist}']
        if mode == "speak":
            parts.append(f'\n## Player Action\n[{protagonist}] said: "{action}"\nGenerate story based on this dialogue.')
        elif mode == "accelerate":
            idx = load_md(BOOKS_DIR/book_id/"index.md")
            parts.append(f'\n## Accelerate\nFast-forward. Summarize transition under 200 words, jump to next key scene.\n\nIndex:\n{idx}')
        elif action:
            parts.append(f'\n## Player Action\n{action}\nGenerate story based on this.')
        else:
            parts.append('\n## Begin\nStart the story from the beginning.')
        story_snip = story[-2000:] if len(story)>2000 else story
        memo_snip = memo[-1000:] if len(memo)>1000 else memo
        parts.append(f'\n## Current Story\n{story_snip}')
        parts.append(f'\n## Memo\n{memo_snip}')
        msgs = [{"role":"system","content":sp},{"role":"user","content":"\n".join(parts)}]
        resp = await call_llm(msgs, settings)
        import re
        m = re.search(r'\[[\s\S]*\]', resp)
        if m:
            raw = json.loads(m.group())
            result = []
            for p in raw:
                item = {"type":p.get("type","narration"),"text":p.get("text","")}
                if item["type"]=="dialogue":
                    item["speaker"]=p.get("speaker","")
                    item["expression"]=p.get("expression","neutral")
                result.append(item)
            return result
    except Exception as e:
        import traceback; traceback.print_exc()
    return mock_queue(book_id, action, mode)
def mock_queue(book_id, action=None, mode='normal'):
    cfg = load_json(BOOKS_DIR/book_id/'config.json')
    p = cfg.get('protagonist','protagonist')
    if mode=='speak':
        return [{'type':'dialogue','speaker':p,'expression':'determined','text':action},
                {'type':'narration','text':f'{p}的话语在空气中回荡。'},
                {'type':'dialogue','speaker':'旁白','expression':'neutral','text':'（你说出了心中的话。接下来会怎样？）'}]
    elif mode=='regret':
        return [{'type':'narration','text':f'时间仿佛倒流了。{p}感到一阵晕眩。'},
                {'type':'narration','text':'世界线重新编织。这一次，一切将会不同。'},
                {'type':'dialogue','speaker':'旁白','expression':'neutral','text':'（你改变了历史的走向。）'}]
    elif mode=='accelerate':
        return [{'type':'narration','text':'时光如白驹过隙。命运的齿轮加速转动。'},
                {'type':'narration','text':f'当{p}再次意识到身在何处时，一切都已经不同了。'},
                {'type':'dialogue','speaker':'旁白','expression':'neutral','text':'（剧情已加速推进到下一个关键节点。）'}]
    elif action:
        return [{'type':'narration','text':f'你决定：{action}。这个选择让故事掀开了新的篇章。'},
                {'type':'narration','text':'周围的氛围随之改变。'},
                {'type':'dialogue','speaker':'旁白','text':f'{p}，你的旅程还在继续。'}]
    return [{'type':'narration','text':f'欢迎，{p}。你的故事即将开始。'},
            {'type':'narration','text':'在这个世界里，每一个选择都可能改变命运。'},
            {'type':'dialogue','speaker':'旁白','text':'准备好了吗？让我们开始吧。'}]

def pars_to_story(pars):
    lines=[]
    for p in pars:
        if p['type']=='dialogue': lines.append(f"{p.get('speaker','')}: {p['text']}")
        else: lines.append(p['text'])
    return '\n'.join(lines)

def append_to_story(sid, pars):
    sp = SAVES_DIR/sid/'story.md'
    save_md(sp, load_md(sp).rstrip()+'\n'+pars_to_story(pars)+'\n')

def prune_story(sid, idx):
    sp = SAVES_DIR/sid/'story.md'
    lines = load_md(sp).strip().split('\n')
    if idx < len(lines): lines = lines[:idx]
    save_md(sp, '\n'.join(lines)+('\n' if lines else ''))

# ── API ──
@app.get('/api/books')
def list_books():
    books=[]
    if BOOKS_DIR.exists():
        for bd in BOOKS_DIR.iterdir():
            if bd.is_dir() and (bd/'config.json').exists():
                d=load_json(bd/'config.json')
                books.append(BookBrief(id=d['id'],title=d['title'],original_author=d['original_author'],
                    script_author=d['script_author'],genre=d.get('genre',[]),
                    protagonist=d.get('protagonist',''),save_count=get_save_count(d['id'])))
    return {'books':[b.model_dump() for b in books]}

@app.get('/api/books/{book_id}')
def get_book(book_id:str):
    c=BOOKS_DIR/book_id/'config.json'
    if not c.exists(): raise HTTPException(404)
    return BookDetail(**load_json(c)).model_dump()

@app.get('/api/saves')
def list_saves():
    saves=[]
    if SAVES_DIR.exists():
        for sd in SAVES_DIR.iterdir():
            if sd.is_dir() and (sd/'config.json').exists() and (sd/'story.md').exists():
                d=load_json(sd/'config.json')
                st=load_md(sd/'story.md')
                pars=parse_story_to_paragraphs(st)
                preview=pars[-3:] if len(pars)>3 else pars
                saves.append(SaveBrief(id=sd.name,book_id=d.get('book_id',''),
                    book_title=d.get('book_title',''),
                    last_modified=datetime.fromtimestamp((sd/'story.md').stat().st_mtime).isoformat(),
                    preview=[p['text'][:80] for p in preview]))
    return {'saves':[s.model_dump() for s in saves]}

@app.get('/api/saves/{save_id}')
def get_save(save_id:str):
    sd=SAVES_DIR/save_id
    if not sd.exists(): raise HTTPException(404)
    d=load_json(sd/'config.json') if (sd/'config.json').exists() else {}
    st=load_md(sd/'story.md'); mem=load_md(sd/'memo.md')
    pars=parse_story_to_paragraphs(st)
    preview=pars[-6:] if len(pars)>6 else pars
    return SaveDetail(id=save_id,book_id=d.get('book_id',''),book_title=d.get('book_title',''),
        book_author=d.get('book_author',''),
        last_modified=datetime.fromtimestamp((sd/'story.md').stat().st_mtime).isoformat() if (sd/'story.md').exists() else '',
        story_preview=[{'type':p['type'],'speaker':p.get('speaker'),'text':p['text'][:100]} for p in preview],
        memo=mem).model_dump()

@app.post('/api/books/{book_id}/start')
async def start_book(book_id:str):
    c=BOOKS_DIR/book_id/'config.json'
    if not c.exists(): raise HTTPException(404)
    d=load_json(c)
    sid=f"save_{uuid.uuid4().hex[:12]}"
    sd=SAVES_DIR/sid; sd.mkdir(parents=True,exist_ok=True)
    scfg={'book_id':book_id,'book_title':d['title'],'book_author':d.get('original_author',''),
          'protagonist':d.get('protagonist',''),'created':datetime.now().isoformat()}
    with open(sd/'config.json','w',encoding='utf-8') as f: json.dump(scfg,f,ensure_ascii=False,indent=2)
    save_md(sd/'story.md',f"# {d['title']}\n\n")
    save_md(sd/'memo.md',f"# 备忘录\n\n游戏刚开始。\n")
    queue = await generate_narrative(book_id, sid)
    append_to_story(sid, queue)
    return {'save_id':sid,'book_title':d['title'],'paragraph_queue':queue,'existing_saves':get_saves_for_book(book_id)}

@app.post('/api/saves/{save_id}/continue')
async def continue_save(save_id:str):
    sd=SAVES_DIR/save_id
    if not sd.exists(): raise HTTPException(404)
    cfg=load_json(sd/'config.json')
    full_history=parse_story_to_paragraphs(load_md(sd/'story.md'))
    # Just load the story, don't generate new content. Wait for player action.
    # Show only the last paragraph so player can continue from where they left off.
    if len(full_history)==0:
        full_history=[{'type':'narration','text':'[Empty story]'}]
    return {'save_id':save_id,'book_title':cfg['book_title'],'full_history':full_history}

@app.post('/api/game/action')
async def submit_action(req: ActionRequest):
    try:
        sd=SAVES_DIR/req.save_id
        if not sd.exists(): raise HTTPException(404)
        cfg=load_json(sd/'config.json')
        bid=cfg['book_id']
        if req.mode=='regret':
            prune_story(req.save_id, req.target_paragraph_index or 0)
        queue=await generate_narrative(bid, req.save_id, req.action, req.mode)
        if req.mode!='regret':
            append_to_story(req.save_id, queue)
        settings = load_settings(); is_mock = not settings.get('llm_api_key') or settings['llm_api_key'] == 'sk-placeholder'; return {'paragraph_queue':queue,'mode':req.mode,'mock':is_mock}
    except Exception as e:
        import traceback; traceback.print_exc()
        return {'error':str(e),'paragraph_queue':mock_queue('harry_potter','fallback','normal'),'mock':True}

@app.get('/api/settings')
def get_settings():
    return load_settings()

@app.post('/api/settings')
def save_settings(data: SettingsData):
    sp=BASE_DIR/'settings.json'
    with open(sp,'w',encoding='utf-8') as f: json.dump(data.model_dump(),f,ensure_ascii=False,indent=2)
    return {'status':'ok'}

@app.delete('/api/saves/{save_id}')
def delete_save(save_id:str):
    sd=SAVES_DIR/save_id
    if not sd.exists(): raise HTTPException(404)
    shutil.rmtree(sd)
    return {'status':'deleted'}

@app.get('/api/books/{book_id}/index')
def get_book_index(book_id:str):
    idx=BOOKS_DIR/book_id/'index.md'
    if not idx.exists(): raise HTTPException(404)
    return {'content':load_md(idx)}

if __name__=='__main__':
    import uvicorn, logging
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s', datefmt='%H:%M:%S')
    log_config = {
        "version": 1, "disable_existing_loggers": False,
        "formatters": {"plain": {"format": "%(asctime)s [%(levelname)s] %(message)s", "datefmt": "%H:%M:%S"}},
        "handlers": {"plain": {"class": "logging.StreamHandler", "formatter": "plain"}},
        "loggers": {"uvicorn": {"handlers": ["plain"], "level": "INFO"}, "uvicorn.access": {"handlers": ["plain"], "level": "INFO"}},
    }
    uvicorn.run(app, host='0.0.0.0', port=8800, log_config=log_config)
