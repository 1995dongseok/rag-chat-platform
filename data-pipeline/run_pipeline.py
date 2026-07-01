import os
import re
import json
import time
import random
import hashlib
import shutil
from pathlib import Path
from typing import List, Dict, Tuple, Optional
from urllib.parse import urljoin, urlparse, urldefrag

import requests
from bs4 import BeautifulSoup, Tag
from tqdm import tqdm
import chromadb
from chromadb.config import Settings
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

# ==========================================
# 1. 설정 및 상수 (Configuration)
# ==========================================
LIVE_CRAWL = True

PLATFORM_URLS = {
    "PYTHON": [
        "https://docs.python.org/ko/3.14/tutorial/stdlib.html",
        "https://docs.python.org/ko/3.14/tutorial/controlflow.html",
    ],
    "JAVA": [
        "https://docs.oracle.com/javase/tutorial/",
    ],
    "JAVASCRIPT": [
        "https://ko.javascript.info/",
    ],
    "CSHARP": [
        "https://learn.microsoft.com/ko-kr/dotnet/csharp/tour-of-csharp/tutorials/",
    ],
}

PLATFORM_RULES = {
    "CSHARP": dict(
        allowed_hosts=("learn.microsoft.com",),
        allowed_prefixes=("/ko-kr/dotnet/csharp/tour-of-csharp/tutorials/",),
        strip_query=True,
        deny_prefixes=("/ko-kr/answers/", "/ko-kr/training/", "/ko-kr/shows/", "/ko-kr/events/", "/ko-kr/legal/", "/ko-kr/privacy/"),
        deny_substrings=("aka.ms", "go.microsoft.com", "github.com"),
    ),
    "JAVASCRIPT": dict(
        allowed_hosts=("ko.javascript.info",),
        allowed_prefixes=("/",),
        strip_query=True,
        deny_prefixes=("/img/", "/files/", "/fonts/", "/assets/"),
        deny_substrings=(".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".css", ".js", ".zip", ".pdf"),
    )
}

OUTPUT_DIR = "./rag_chunks"
CHROMA_DIR = "./chroma_db"
COLLECTION_NAME = "docs_rag_v22"
EMBED_MODEL_NAME = "intfloat/multilingual-e5-base"

MAX_PAGES_PER_PLATFORM = 120
MAX_DEPTH = 3
CRAWL_SLEEP_S = 0.2
REQUEST_TIMEOUT = 25
MIN_BLOCK_CHARS = 40
MIN_CHUNK_CHARS = 40
MAX_CHARS = 4200

WS = re.compile(r"\s+")
META_NOISE = re.compile(r"(Copy 버튼|upper-right corner|Copy|clipboard)", re.IGNORECASE)
DEFAULT_DENY_EXTS = (".png",".jpg",".jpeg",".gif",".svg",".webp",".mp4",".webm",".mov",".pdf",".zip",".tar",".gz",".tgz",".7z")

session = requests.Session()
HTML_CACHE: Dict[str, str] = {}

# ==========================================
# 2. 유틸리티 함수 (Utils)
# ==========================================
def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)

def stable_id(*parts: str) -> str:
    h = hashlib.sha1()
    h.update("||".join(parts).encode("utf-8"))
    return h.hexdigest()

def infer_source(url: str) -> str:
    return urlparse(url).netloc

def normalize_url(base: str, href: str, *, strip_query: bool = True) -> Optional[str]:
    if not href: return None
    href = href.strip()
    if href.startswith(("mailto:", "javascript:")): return None
    u = urljoin(base, href)
    u, _ = urldefrag(u)
    p = urlparse(u)
    if p.scheme not in ("http", "https"): return None
    if strip_query: p = p._replace(query="")
    path = re.sub(r"/{2,}", "/", p.path or "/")
    p = p._replace(path=path)
    return p.geturl()

def fast_reject(u: str, cfg: dict) -> bool:
    if not u: return True
    p = urlparse(u)
    path = (p.path or "").lower()
    deny_exts = tuple(cfg.get("deny_exts") or DEFAULT_DENY_EXTS)
    if any(path.endswith(ext) for ext in deny_exts): return True
    deny_prefixes = tuple(cfg.get("deny_prefixes") or ())
    if deny_prefixes and any((p.path or "/").startswith(px) for px in deny_prefixes): return True
    deny_substrings = tuple(cfg.get("deny_substrings") or ())
    if deny_substrings and any(s in u for s in deny_substrings): return True
    return False

def is_allowed(u: str, allowed_hosts: Tuple[str, ...], allowed_prefixes: Tuple[str, ...]) -> bool:
    p = urlparse(u)
    if p.netloc not in allowed_hosts: return False
    path = p.path or "/"
    return any(path.startswith(px) for px in allowed_prefixes)

def _default_allowed_prefixes(start_url: str) -> Tuple[str, ...]:
    p = urlparse(start_url)
    path = p.path or "/"
    if not path.endswith("/"):
        path = path.rsplit("/", 1)[0] + "/"
    return (path,)

def make_cfg(platform: str, start_url: str, *, allowed_hosts=None, allowed_prefixes=None, docset=None, doc_lang: str="", strip_query: bool=True, deny_prefixes: Tuple[str, ...]=(), deny_substrings: Tuple[str, ...]=(), deny_exts: Tuple[str, ...]=()):
    host = urlparse(start_url).netloc
    return {
        "platform": platform,
        "docset": docset or platform,
        "start_url": start_url,
        "allowed_hosts": tuple(allowed_hosts) if allowed_hosts else (host,),
        "allowed_prefixes": tuple(allowed_prefixes) if allowed_prefixes else _default_allowed_prefixes(start_url),
        "doc_lang": doc_lang,
        "strip_query": bool(strip_query),
        "deny_prefixes": tuple(deny_prefixes) if deny_prefixes else (),
        "deny_substrings": tuple(deny_substrings) if deny_substrings else (),
        "deny_exts": tuple(deny_exts) if deny_exts else (),
    }

def fetch_html(url: str, timeout: int = REQUEST_TIMEOUT, max_retries: int = 6, use_cache: bool = True) -> str:
    if use_cache and url in HTML_CACHE: return HTML_CACHE[url]
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.7,en;q=0.6",
    }
    last_err = None
    for i in range(max_retries):
        try:
            r = session.get(url, timeout=timeout, headers=headers)
            if r.status_code in (429, 503):
                time.sleep((2 ** i) + random.random())
                continue
            r.raise_for_status()
            enc = r.apparent_encoding or r.encoding or "utf-8"
            html = r.content.decode(enc, errors="replace")
            if use_cache: HTML_CACHE[url] = html
            time.sleep(CRAWL_SLEEP_S)
            return html
        except requests.RequestException as e:
            last_err = e
            time.sleep((2 ** i) + random.random())
    raise RuntimeError(f"fetch failed: {url} | last_err={repr(last_err)}")

# ==========================================
# 3. 크롤링 로직 (Crawling)
# ==========================================
def collect_site_pages(cfg: dict, max_pages: int = MAX_PAGES_PER_PLATFORM, max_depth: int = MAX_DEPTH) -> List[str]:
    start_url = cfg["start_url"]
    allowed_hosts = cfg["allowed_hosts"]
    allowed_prefixes = cfg["allowed_prefixes"]
    strip_query = bool(cfg.get("strip_query", True))

    seen = set([start_url])
    q: List[Tuple[str, int]] = [(start_url, 0)]
    out: List[str] = []

    with tqdm(total=max_pages, desc=f"collect {cfg['docset']}", leave=False) as pbar:
        while q and len(out) < max_pages:
            url, depth = q.pop(0)
            if depth > max_depth: continue
            out.append(url)
            pbar.update(1)
            try: html = fetch_html(url)
            except Exception: continue

            soup = BeautifulSoup(html, "lxml")
            for a in soup.select("a[href]"):
                u = normalize_url(url, a.get("href"), strip_query=strip_query)
                if not u or u in seen: continue
                if fast_reject(u, cfg): continue
                if is_allowed(u, allowed_hosts, allowed_prefixes):
                    seen.add(u)
                    q.append((u, depth + 1))
    return out

# ==========================================
# 4. 추출 및 파싱 로직 (Extraction)
# ==========================================
def detect_doc_lang(soup: BeautifulSoup, fallback: str = "") -> str:
    html_tag = soup.find("html")
    if html_tag and html_tag.get("lang"): return html_tag.get("lang").split("-")[0].lower()
    return fallback

def clean_text(s: str) -> str:
    if not s: return ""
    s = s.replace("¶", "").replace("Â¶", "")
    s = s.replace("\\n", " ").replace("\n", " ")
    s = re.sub(r"\s{2,}", " ", s).strip()
    return META_NOISE.sub("", s).strip()

def pick_main(soup: BeautifulSoup):
    return (soup.select_one('div[role="main"]') or soup.select_one('div.body') or soup.select_one('main') or soup.select_one('article') or soup.body)

def remove_noise(main: Tag):
    for sel in ["nav", "header", "footer", "script", "style", ".toc", ".toc-tree", ".breadcrumb", ".prev-next-area", ".sphinxsidebar", ".sphinxsidebarwrapper", ".related"]:
        for node in main.select(sel): node.decompose()

def classify_admonition(div: Tag) -> str:
    classes = set(div.get("class") or [])
    known = ["note","warning","tip","important","caution","attention","hint","seealso","versionadded","versionchanged","deprecated"]
    for k in known:
        if k in classes: return k
    return "note"

def detect_language_from_codeblock(node: Tag) -> str:
    code = node.get_text("\n", strip=False)
    if re.search(r"\bpublic\s+class\b|\bSystem\.out\.", code): return "java"
    if re.search(r"\bdef\b|\bimport\b|\bNone\b", code): return "python"
    return "text"

def normalize_python_repl(code: str) -> str:
    lines = code.splitlines()
    out = []
    for ln in lines:
        s = ln.rstrip()
        if s.startswith(">>> "): out.append(s[4:]); continue
        if s.startswith("... "): out.append(s[4:]); continue
        if s.strip() == "...": continue
        if re.fullmatch(r"[0-9 ]+", s.strip()): continue
        out.append(s)
    return "\n".join(out).strip()

def split_code_and_comments(code: str, lang: str = "python"):
    lines = code.splitlines()
    blocks, buf, cur = [], [], None

    def flush():
        nonlocal buf, cur
        if cur and any(ln.strip() for ln in buf):
            txt = "\n".join(buf).rstrip()
            if len(txt.strip()) >= 5: blocks.append((cur, txt))
        buf, cur = [], None

    lang = (lang or "").lower()
    if lang == "python":
        code = normalize_python_repl(code)
        for ln in code.splitlines():
            t = "comment" if ln.lstrip().startswith("#") else "code"
            if cur is None: cur, buf = t, [ln]
            elif t == cur: buf.append(ln)
            else: flush(); cur, buf = t, [ln]
        flush()
        return blocks

    in_block = False
    for ln in lines:
        i = 0
        while i < len(ln):
            if in_block:
                end = ln.find("*/", i)
                if end == -1:
                    piece = ln[i:]
                    if cur != "comment": flush(); cur = "comment"
                    buf.append(piece); i = len(ln)
                else:
                    piece = ln[i:end+2]
                    if cur != "comment": flush(); cur = "comment"
                    buf.append(piece); i = end+2; in_block = False
            else:
                sl, bl = ln.find("//", i), ln.find("/*", i)
                starts = [p for p in (sl, bl) if p != -1]
                nxt = min(starts) if starts else -1
                if nxt == -1:
                    piece = ln[i:]
                    if cur != "code": flush(); cur = "code"
                    buf.append(piece); i = len(ln)
                else:
                    if nxt > i:
                        piece = ln[i:nxt]
                        if cur != "code": flush(); cur = "code"
                        buf.append(piece)
                    if nxt == sl:
                        piece = ln[nxt:]
                        if cur != "comment": flush(); cur = "comment"
                        buf.append(piece); i = len(ln)
                    else:
                        end = ln.find("*/", nxt+2)
                        if end == -1:
                            piece = ln[nxt:]
                            if cur != "comment": flush(); cur = "comment"
                            buf.append(piece); in_block = True; i = len(ln)
                        else:
                            piece = ln[nxt:end+2]
                            if cur != "comment": flush(); cur = "comment"
                            buf.append(piece); i = end+2
        if buf: buf[-1] = buf[-1] + "\n"
    flush()
    return [(k, v.rstrip()) for k, v in blocks if len(v.strip()) >= 5]

def infer_vmffotvha_type(kind: str, note_type: Optional[str], content: str) -> str:
    if kind == "note": return f"vmffotvha/note/{note_type or 'note'}"
    if kind == "comment": return "vmffotvha/code/comment"
    if kind == "code": return "vmffotvha/code/example"
    if re.search(r"(처음|입문|가이드)", (content or "").lower()): return "vmffotvha/text/guide"
    return "vmffotvha/text/explanation"

def extract_blocks(html: str, url: str, cfg: dict):
    soup = BeautifulSoup(html, "lxml")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    doc_lang = detect_doc_lang(soup, cfg.get("doc_lang", ""))
    main = pick_main(soup)
    if not main: return title, doc_lang, []
    remove_noise(main)

    h = {1: None, 2: None, 3: None}
    def current_path(): return " > ".join([x for x in (h[1], h[2], h[3]) if x])

    recs = []
    block_index = 0

    for el in main.descendants:
        if not isinstance(el, Tag): continue
        if el.name in {"h1","h2","h3"}:
            level = int(el.name[1])
            txt = WS.sub(" ", el.get_text(" ", strip=True)).strip()
            if txt:
                h[level] = txt
                for deeper in range(level+1, 4): h[deeper] = None
            continue

        if el.name == "div" and "admonition" in (el.get("class") or []):
            nt = classify_admonition(el)
            txt = clean_text(el.get_text("\n", strip=True))
            if txt and len(txt) >= 30:
                recs.append({"url": url, "doc_title": title, "section_path": current_path(), "block_index": block_index, "content_type": infer_vmffotvha_type("note", nt, txt), "lang": "text", "content": txt, "platform": cfg["platform"], "docset": cfg["docset"], "doc_lang": doc_lang, "source": infer_source(url)})
                block_index += 1
            continue

        if el.name == "div" and "highlight" in (el.get("class") or []):
            pre = el.find("pre")
            if pre:
                code_txt = pre.get_text("\n", strip=False).rstrip("\n").strip("\n")
                if code_txt and len(code_txt) >= 10:
                    lang = detect_language_from_codeblock(pre)
                    for t, chunk in split_code_and_comments(code_txt, lang=lang):
                        recs.append({"url": url, "doc_title": title, "section_path": current_path(), "block_index": block_index, "content_type": infer_vmffotvha_type(t, None, chunk), "lang": lang, "content": chunk, "platform": cfg["platform"], "docset": cfg["docset"], "doc_lang": doc_lang, "source": infer_source(url)})
                        block_index += 1
            continue

        if el.name in {"p","blockquote"}:
            txt = clean_text(el.get_text("\n", strip=True))
            if txt and len(txt) >= 40:
                recs.append({"url": url, "doc_title": title, "section_path": current_path(), "block_index": block_index, "content_type": infer_vmffotvha_type("text", None, txt), "lang": "text", "content": txt, "platform": cfg["platform"], "docset": cfg["docset"], "doc_lang": doc_lang, "source": infer_source(url)})
                block_index += 1

    return title, doc_lang, recs

# ==========================================
# 5. 청킹 및 저장 (Chunking & File IO)
# ==========================================
from collections import defaultdict

def chunk_records(in_jsonl: str, out_jsonl: str) -> str:
    in_p, out_p = Path(in_jsonl).resolve(), Path(out_jsonl).resolve()
    if not in_p.exists(): return ""
    out_p.parent.mkdir(parents=True, exist_ok=True)
    
    grouped = defaultdict(list)
    with open(in_p, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip(): continue
            r = json.loads(line)
            content = (r.get("content") or "").strip()
            if len(content) < MIN_BLOCK_CHARS: continue
            key = (r.get("platform") or "unknown", r.get("docset") or "unknown", r.get("url") or "unknown", r.get("section_path") or "", r.get("content_type") or "unknown")
            grouped[key].append(r)

    wrote = 0
    with open(out_p, "w", encoding="utf-8") as out:
        for key, blocks in grouped.items():
            platform, docset, url, section_path, content_type = key
            blocks.sort(key=lambda x: x.get("block_index", 10**9))
            body = "\n".join([(b.get("content") or "").strip() for b in blocks if (b.get("content") or "").strip()]).strip()
            if not body: continue
            if len(body) > MAX_CHARS: body = body[:MAX_CHARS]
            if len(body) < MIN_CHUNK_CHARS: continue
            last_bi = str(blocks[-1].get("block_index", "na"))
            rid = stable_id(docset, platform, url, section_path, content_type, last_bi)

            rec = {
                "id": rid, "text": body, "url": url, "platform": platform, "docset": docset,
                "section_path": section_path, "content_type": content_type, "lang": blocks[0].get("lang"),
                "doc_lang": blocks[0].get("doc_lang"), "source": blocks[0].get("source"),
            }
            out.write(json.dumps(rec, ensure_ascii=False) + "\n")
            wrote += 1
    return str(out_p)

def map_type(content_type: str) -> str:
    ct = (content_type or "").lower()
    if "/code/comment" in ct: return "comment"
    if "/code/example" in ct: return "code"
    return "text"

def blocks_to_split_files(blocks: List[dict], platform: str, out_dir: str) -> Dict[str, str]:
    buckets = {"comment": [], "code": [], "text": []}
    for r in blocks: buckets[map_type(r.get("content_type"))].append(r)

    pdir = Path(out_dir) / platform
    pdir.mkdir(parents=True, exist_ok=True)
    out = {}
    for t in ("comment", "code", "text"):
        out_p = pdir / f"{platform}_{t}_blocks.jsonl"
        with open(out_p, "w", encoding="utf-8") as f:
            for r in buckets[t]: f.write(json.dumps(r, ensure_ascii=False) + "\n")
        out[t] = str(out_p)
    return out

# ==========================================
# 6. ChromaDB 적재 (Ingestion)
# ==========================================
def get_chroma_collection(persist_dir: str, name: str):
    ensure_dir(persist_dir)
    print(f"🔄 모델 로드 중: {EMBED_MODEL_NAME}")
    embed_fn = SentenceTransformerEmbeddingFunction(model_name=EMBED_MODEL_NAME)
    client = chromadb.PersistentClient(path=persist_dir, settings=Settings(anonymized_telemetry=False))
    return client.get_or_create_collection(name=name, embedding_function=embed_fn, metadata={"embed_model": EMBED_MODEL_NAME})

def add_jsonl_to_chroma(col, jsonl_path: str, *, extra_meta: dict):
    if not Path(jsonl_path).exists(): return
    ids, docs, metas = [], [], []
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip(): continue
            r = json.loads(line)
            ids.append(r["id"])
            docs.append(r["text"])
            metas.append({
                "platform": r.get("platform"),
                "type": extra_meta.get("type"),
                "url": r.get("url"),
                "section_path": r.get("section_path"),
                "content_type": r.get("content_type"),
                "source": r.get("source"),
                "doc_lang": r.get("doc_lang"),
            })

    bs = 128
    for i in range(0, len(ids), bs):
        col.add(ids=ids[i:i+bs], documents=docs[i:i+bs], metadatas=metas[i:i+bs])

# ==========================================
# 7. 메인 파이프라인 (Pipeline Workflow)
# ==========================================
def unified_ingest_pipeline(platform_urls: dict, *, reset: bool=False):
    if reset:
        print("🗑️ 기존 데이터 초기화 중...")
        if Path(OUTPUT_DIR).exists(): shutil.rmtree(OUTPUT_DIR, ignore_errors=True)
        if Path(CHROMA_DIR).exists(): shutil.rmtree(CHROMA_DIR, ignore_errors=True)
        Path(OUTPUT_DIR).mkdir(parents=True, exist_ok=True)
        Path(CHROMA_DIR).mkdir(parents=True, exist_ok=True)

    col = get_chroma_collection(CHROMA_DIR, COLLECTION_NAME)
    summary = {}

    for platform, urls in platform_urls.items():
        platform = (platform or "").strip().upper()
        print(f"\n🚀 [INGEST] platform={platform} 시작")

        rules = PLATFORM_RULES.get(platform, {})
        cfgs = [make_cfg(platform=platform, start_url=u, docset=platform, **rules) for u in urls]

        all_pages = []
        for cfg in cfgs:
            all_pages.extend(collect_site_pages(cfg))
        
        # Deduplication
        pages = list(dict.fromkeys(all_pages))
        blocks = []

        print(f"📦 크롤링 및 파싱 중 (총 {len(pages)} 페이지)")
        for u in tqdm(pages, desc=f"extract {platform}"):
            try:
                html = fetch_html(u)
                _, _, recs = extract_blocks(html, u, cfgs[0])
                blocks.extend(recs)
            except Exception as e:
                pass

        block_files = blocks_to_split_files(blocks, platform, OUTPUT_DIR)
        pdir = Path(OUTPUT_DIR) / platform

        out_paths = {}
        for t in ("comment", "code", "text"):
            out_p = str(pdir / f"{platform}_{t.capitalize()}.jsonl")
            chunk_records(block_files[t], out_p)
            add_jsonl_to_chroma(col, out_p, extra_meta={"type": t})
            out_paths[t] = out_p

        summary[platform] = {"pages_crawled": len(pages), "blocks_extracted": len(blocks), "files": out_paths}
        print(f"✅ {platform} 완료: {summary[platform]}")

    print("\n🎉 모든 파이프라인 작업이 완료되었습니다!")
    print(f"📁 생성된 DB 위치: {CHROMA_DIR}")

if __name__ == "__main__":
    print("==================================================")
    print("   RAG Data Ingestion Pipeline (V2) 시작")
    print("==================================================")
    # reset=True 이면 실행할 때마다 기존 DB를 지우고 새로 만듭니다.
    unified_ingest_pipeline(PLATFORM_URLS, reset=True)