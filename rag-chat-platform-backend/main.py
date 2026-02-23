import os
import json
import asyncio
import re
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
import chromadb
from chromadb.utils import embedding_functions
from openai import OpenAI
from typing import List, Dict, Tuple, Optional
from sentence_transformers import CrossEncoder
from dotenv import load_dotenv
import math

load_dotenv()

OPENAI_API_KEY   = os.getenv("OPENAI_API_KEY")
DB_PATH          = os.getenv("CHROMA_DB_PATH")
COLLECTION_NAME  = os.getenv("CHROMA_COLLECTION_NAME")
EMBED_MODEL_NAME = os.getenv("EMBED_MODEL_NAME")

# 노트북과 동일한 3개 리랭커 모델명 (환경변수로 덮어쓰기 가능)
CE1_MODEL = os.getenv("CE1_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2")   # 영어 최적화, 경량
CE2_MODEL = os.getenv("CE2_MODEL", "cross-encoder/nli-distilroberta-base")   # 다국어, 한국어 강점 (예시)
CE3_MODEL = os.getenv("CE3_MODEL", "BAAI/bge-reranker-base")                 # 범용

if not OPENAI_API_KEY:
    raise ValueError("API Key가 없습니다. .env 파일을 확인해주세요.")

# ────────────────────────────────────────────────────────────
# 프롬프트 상수
# ────────────────────────────────────────────────────────────
SELF_VERIFICATION_PROMPT = """당신은 엄격한 품질 검증자입니다.
생성된 답변을 아래 기준으로 평가하고 JSON 형식으로 응답하세요.

**평가 기준:**
1. 근거성(Groundedness): 답변이 제공된 컨텍스트에만 기반하는가? (0-10)
2. 관련성(Relevance): 답변이 질문과 직접 관련이 있는가? (0-10)
3. 인용 정확성: '출처:' 섹션에 URL과 경로(Path)가 정확히 명시되었는가? (0-10)

**출력 형식 (JSON):**
{
    "groundedness": 8,
    "relevance": 9,
    "citation_accuracy": 7,
    "reason": "출처는 명시되었으나 설명이 다소 부족함"
}
"""

# ────────────────────────────────────────────────────────────
# 멀티 리랭커 (노트북 Cell 64~65 통합)
# ────────────────────────────────────────────────────────────
class MultiReranker:
    """
    Cross-Encoder x3 + BM25 앙상블 리랭커.
    노트북의 ensemble_rerank() 로직을 클래스로 캡슐화.
    """

    # 기본 앙상블 가중치 (한국어 문서 최적화)
    DEFAULT_WEIGHTS = {
        "ce1":  0.25,   # ms-marco-MiniLM   (영어 최적화)
        "ce2":  0.45,   # TinyBERT          (다국어·한국어 강점)
        "ce3":  0.15,   # bge-reranker-base (범용)
        "bm25": 0.15,   # BM25              (어휘 매칭)
    }

    def __init__(
        self,
        ce1_model: str = CE1_MODEL,
        ce2_model: str = CE2_MODEL,
        ce3_model: str = CE3_MODEL,
        weights: Optional[Dict[str, float]] = None,
    ):
        print(f"[Reranker] Loading CE1: {ce1_model}")
        self.ce1 = CrossEncoder(ce1_model, max_length=512)

        print(f"[Reranker] Loading CE2: {ce2_model}")
        self.ce2 = CrossEncoder(ce2_model, max_length=512)

        print(f"[Reranker] Loading CE3: {ce3_model}")
        self.ce3 = CrossEncoder(ce3_model, max_length=512)

        self.weights = weights or self.DEFAULT_WEIGHTS
        print("[Reranker] All models loaded.")

    def _score_ce(self, query: str, docs: List[str], model: CrossEncoder) -> List[float]:
        pairs = [[query, d] for d in docs]
        return [float(s) for s in model.predict(pairs)]

    def _score_bm25(self, query: str, docs: List[str], k1: float = 1.5, b: float = 0.75) -> List[float]:
        tokenized = [d.lower().split() for d in docs]
        query_tokens = query.lower().split()
        n = len(tokenized)
        avgdl = sum(len(d) for d in tokenized) / n if n else 1

        idf: Dict[str, float] = {}
        for term in query_tokens:
            df = sum(1 for d in tokenized if term in d)
            idf[term] = math.log((n - df + 0.5) / (df + 0.5) + 1)

        scores = []
        for doc_tokens in tokenized:
            score = 0.0
            dl = len(doc_tokens)
            tf_map: Dict[str, int] = {}
            for t in doc_tokens:
                tf_map[t] = tf_map.get(t, 0) + 1
            for term in query_tokens:
                tf = tf_map.get(term, 0)
                numerator   = tf * (k1 + 1)
                denominator = tf + k1 * (1 - b + b * dl / avgdl)
                score += idf.get(term, 0) * numerator / denominator
            scores.append(score)
        return scores

    @staticmethod
    def _normalize(scores: List[float]) -> List[float]:
        mn, mx = min(scores), max(scores)
        if mx == mn:
            return [0.5] * len(scores)
        return [(s - mn) / (mx - mn) for s in scores]

    def rerank(
        self,
        query: str,
        initial_results: List[Dict],
        top_k: int = 5,
        weights: Optional[Dict[str, float]] = None,
        verbose: bool = True,
    ) -> List[Dict]:
        
        if not initial_results:
            return []

        w    = weights or self.weights
        docs = [item["content"] for item in initial_results]

        if verbose:
            print(f"[Reranker] 앙상블 리랭킹 시작 (문서 {len(docs)}개)...")

        raw: Dict[str, List[float]] = {}
        if w.get("ce1", 0) > 0:
            raw["ce1"] = self._score_ce(query, docs, self.ce1)
            if verbose: print("[Reranker] CE1 완료 (영어)")
        if w.get("ce2", 0) > 0:
            raw["ce2"] = self._score_ce(query, docs, self.ce2)
            if verbose: print("[Reranker] CE2 완료 (다국어)")
        if w.get("ce3", 0) > 0:
            raw["ce3"] = self._score_ce(query, docs, self.ce3)
            if verbose: print("[Reranker] CE3 완료 (범용)")
        if w.get("bm25", 0) > 0:
            raw["bm25"] = self._score_bm25(query, docs)
            if verbose: print("[Reranker] BM25 완료")

        norm: Dict[str, List[float]] = {m: self._normalize(s) for m, s in raw.items()}

        n = len(initial_results)
        final_scores = []
        for i in range(n):
            ws = sum(norm[m][i] * w.get(m, 0) for m in norm)
            wt = sum(w.get(m, 0) for m in norm)
            final_scores.append(ws / wt if wt > 0 else 0.0)

        order = sorted(range(n), key=lambda i: final_scores[i], reverse=True)

        results = []
        for new_rank, orig_idx in enumerate(order[:top_k]):
            item        = initial_results[orig_idx]
            score       = final_scores[orig_idx]
            rank_change = orig_idx - new_rank

            meta_with_score               = item["metadata"].copy()
            meta_with_score["score"]       = score
            meta_with_score["rank_change"] = rank_change

            results.append({
                "id":           item.get("id", f"rank_{new_rank}"),
                "content":      item["content"],
                "metadata":     meta_with_score,
                "score":        score,
                "model_scores": {m: norm[m][orig_idx] for m in norm},
            })

        if verbose:
            print(f"[Reranker] 앙상블 완료: 상위 {len(results)}개 선택")
        return results

# ────────────────────────────────────────────────────────────
# RAGService
# ────────────────────────────────────────────────────────────
class RAGService:
    def __init__(self):
        self.client = chromadb.PersistentClient(path=DB_PATH)
        self.llm    = OpenAI()

        print(f"[RAG] Loading Embedding model ({EMBED_MODEL_NAME})...")
        self.embed_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=EMBED_MODEL_NAME,
            device="cpu"
        )

        self.collection = self.client.get_collection(name=COLLECTION_NAME)

        print("[RAG] Loading Multi-Reranker models...")
        self.reranker = MultiReranker()
        print("[RAG] All models loaded.")

    def route_intent(self, query: str):
        intent = "Concept"
        if re.search(r"코드|예제|작성|구현|만들어|짜줘", query, re.IGNORECASE):
            intent = "Code"
        if re.search(r"에러|오류|fail|exception|bug|안돼", query, re.IGNORECASE):
            intent = "Error"
        return intent
        
    def detect_language(self, query: str, fallback_lang: str) -> str:
        """[V2 반영] 질문 텍스트를 분석하여 프론트엔드의 언어 설정을 덮어쓸지 결정"""
        q = (query or "")
        ql = q.lower()
        
        if ("자바스크립트" in q) or re.search(r"\bjavascript\b", ql) or re.search(r"\bjs\b", ql):
            return "JAVASCRIPT"
        if ("자바" in q) or re.search(r"\bjava\b", ql):
            return "JAVA"
        if ("파이썬" in q) or re.search(r"\bpython\b", ql):
            return "PYTHON"
        if ("c#" in ql) or ("csharp" in ql) or ("씨샵" in q):
            return "CSHARP"
            
        return fallback_lang.upper()

    def retrieve_hybrid(self, query, language="Python", intent="Concept"):
        # V2: 지능형 언어 라우팅
        target_lang = self.detect_language(query, language)
        print(f"[Search] Query: {query} | Filter: {target_lang} | Intent: {intent}")

        query_vec = self.embed_fn([query])

        # V2: 소문자 메타데이터 타입 반영
        quota = {"code": 1, "text": 4, "comment": 1}
        if intent == "Code":
            quota = {"code": 4, "text": 1, "comment": 1}
        elif intent == "Error":
            quota = {"code": 2, "text": 2, "comment": 2}

        combined_results = []
        seen_ids = set()

        try:
            for ctype, count in quota.items():
                if count == 0:
                    continue

                res = self.collection.query(
                    query_embeddings=query_vec,
                    n_results=count * 2,
                    where={
                        "$and": [
                            {"platform": target_lang},
                            {"type": ctype}
                        ]
                    },
                    include=["documents", "metadatas"]
                )

                if res["documents"] and res["documents"][0]:
                    for i, (doc, meta) in enumerate(zip(res["documents"][0], res["metadatas"][0])):
                        doc_id = res["ids"][0][i]
                        if doc_id not in seen_ids:
                            combined_results.append({
                                "content":  doc,
                                "metadata": meta,
                                "id":       doc_id
                            })
                            seen_ids.add(doc_id)

            return combined_results

        except Exception as e:
            print(f"[Search Error] {e}")
            return []

    def rerank(self, query, initial_results, top_k=5):
        return self.reranker.rerank(query, initial_results, top_k=top_k)

    def get_system_prompt(self, language: str, style: str, intent: str):
        intent_persona = {
            "Code":    f"당신은 실용적인 {language} 코딩 튜터입니다. 설명보다 잘 작동하는 코드를 우선시합니다.",
            "Concept": f"당신은 친절한 {language} 선생님입니다. 개념을 쉽게 풀어서 설명합니다.",
            "Error":   f"당신은 {language} 디버깅 전문가입니다. 원인을 분석하고 해결책을 제시합니다."
        }
        target_persona = intent_persona.get(intent, intent_persona["Concept"])

        style_instructions = {
            "Expert":   "전문 용어를 정확히 사용하고, 간결하고 명확하게 답변하세요 (하십시오체 권장).",
            "Friendly": "초보자도 이해하기 쉽게 비유를 사용하고 격려하는 어조를 사용하세요 (해요체 권장).",
            "Strict":   "서론/결론을 생략하고 핵심과 코드만 답변하세요."
        }
        selected_style = style_instructions.get(style, style_instructions["Expert"])

        return f"""
        {target_persona}
        {selected_style}

        [필수 규칙]
        1. 답변 내용에 반드시 참고한 문서의 URL을 본문 중에 자연스럽게 언급하거나, 답변 끝에 '출처:' 섹션을 만들어 나열하세요.
        2. 제공된 [Context]에 없는 내용은 지어내지 말고 "문서에 내용이 없습니다"라고 하세요.
        3. 코드를 작성할 때는 {language}의 표준 스타일 가이드를 따르세요.
        """

    async def verify(self, question, context, answer):
        try:
            response = self.llm.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": SELF_VERIFICATION_PROMPT},
                    {"role": "user",   "content": f"[Question]\n{question}\n\n[Context]\n{context}\n\n[Answer]\n{answer}"}
                ],
                response_format={"type": "json_object"}
            )
            return json.loads(response.choices[0].message.content)
        except Exception as e:
            print(f"Verification Error: {e}")
            return {"groundedness": 0, "reason": "검증 실패"}

    async def optimize_prompt(self, query, issue_reason, language="Python"):
        OPTIMIZER_PROMPT = f"""당신은 RAG 시스템 튜닝 전문가입니다.
        이전 답변이 다음 이유로 품질 검증에 실패했습니다: '{issue_reason}'
        사용자 질문: '{query}'

        이 문제를 해결하기 위해 LLM에게 전달할 '개선된 지시사항(Advice)'을 한 문장으로 작성하세요.
        예: "출처 URL을 반드시 포함하세요", "코드에 주석을 더 추가하세요"
        """
        try:
            response = self.llm.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "system", "content": OPTIMIZER_PROMPT}],
            )
            return response.choices[0].message.content
        except:
            return "출처 URL을 명시하고 내용을 상세히 설명하세요."

    async def generate_title(self, query):
        try:
            prompt = f"질문을 3단어 이내의 제목으로 요약해줘: {query}"
            response = self.llm.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}]
            )
            return response.choices[0].message.content.strip().replace('"', '')
        except:
            return "New Chat"

# ────────────────────────────────────────────────────────────
# FastAPI 앱
# ────────────────────────────────────────────────────────────
rag = RAGService()
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def sse_msg(event, data):
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

@app.post("/api/chat/stream")
async def chat_endpoint(request: Request):
    try:
        body       = await request.json()
        user_query = body.get("message", "")
        language   = body.get("language", "Python")
        style      = body.get("style", "Expert")

        if not user_query and body.get("messages"):
            user_query = body["messages"][-1].get("content", "")

        return StreamingResponse(stream_generator(user_query, language, style), media_type="text/event-stream")
    except Exception as e:
        print(f"Error: {e}")
        return StreamingResponse(iter([sse_msg("error", {"message": str(e)})]), media_type="text/event-stream")

async def stream_generator(user_query, language, style):
    full_answer        = ""
    full_answer_v2     = ""
    is_pass            = False
    actual_fail_reason = "검증 데이터 부족"

    intent = rag.route_intent(user_query)
    # V2: 언어 자동 감지로 language 변수 덮어쓰기
    detected_lang = rag.detect_language(user_query, language)
    
    print(f"\n[질문 수신] {user_query} (UI Lang: {language} -> Detected: {detected_lang}, Style: {style}) -> Intent: {intent}")

    yield sse_msg("token", {"delta": ""})

    search_results = rag.retrieve_hybrid(user_query, language=detected_lang, intent=intent)

    retrieval_payload = []
    for i, item in enumerate(search_results):
        retrieval_payload.append({
            "id":       f"retr_{i}",
            "content":  item["content"][:200],
            "metadata": item["metadata"]
        })

    yield sse_msg("retrieval", {"round": 1, "payload": retrieval_payload})

    reranked_results = rag.rerank(user_query, search_results)
    yield sse_msg("rerank", {"round": 1, "payload": reranked_results})

    if not reranked_results:
        print("[System] 문서 범위 밖 질문(OOS) 감지 -> 답변 거부")
        no_result_msg = f"죄송합니다. {detected_lang} 문서들 중에서 해당 질문에 대한 답변을 찾을 수 없습니다."
        yield sse_msg("final", {"content": no_result_msg})
        yield sse_msg("title", {"title": "문서 범위 밖 질문"})
        return

    # V2 반영: 강력한 메타데이터(section_path)를 Context에 주입
    context_text = ""
    for item in reranked_results:
        meta = item["metadata"]
        sec_path = meta.get('section_path', 'N/A')
        doc_type = meta.get('type', 'text').upper()
        url = meta.get('url', 'N/A')
        
        context_text += f"[경로(Path): {sec_path} | Type: {doc_type} | URL: {url}]\n{item['content']}\n\n"

    print("[Round 1] 답변 생성 중...")

    system_prompt_v1 = rag.get_system_prompt(detected_lang, style, intent)

    stream = rag.llm.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": system_prompt_v1},
            {"role": "user",   "content": f"[Context]\n{context_text}\n\nQuestion: {user_query}"}
        ],
        stream=True
    )

    for chunk in stream:
        if chunk.choices[0].delta.content:
            text = chunk.choices[0].delta.content
            full_answer += text
            yield sse_msg("token", {"delta": text})

    print("[Round 1] 품질 검증 수행 중...")
    if full_answer:
        v_res = await rag.verify(user_query, context_text, full_answer)

        s_faith = v_res.get("groundedness", 0)
        s_rel   = v_res.get("relevance", 0)
        s_cite  = v_res.get("citation_accuracy", 0)

        actual_fail_reason = v_res.get("reason", "품질 기준 미달")
        print(f"[Round 1 결과] Faith: {s_faith}, Rel: {s_rel}, Cite: {s_cite} / 사유: {actual_fail_reason}")

        is_pass = s_faith >= 7

        yield sse_msg("verification", {
            "type": "verification",
            "round": 1,
            "payload": {
                "pass":   is_pass,
                "reason": actual_fail_reason,
                "ragas": {
                    "faithfulness":      s_faith / 10,
                    "relevance":         s_rel   / 10,
                    "citation_accuracy": s_cite  / 10
                }
            }
        })

    if not is_pass:
        print("[Round 2] 자가 수정 프로세스 시작...")

        yield sse_msg("rerank", {"round": 2, "payload": reranked_results})

        advice = await rag.optimize_prompt(user_query, actual_fail_reason, detected_lang)
        print(f"[Round 2] Advice: {advice}")

        system_prompt_v2 = (
            system_prompt_v1
            + f"\n\n[수정 지시사항]\n이전 답변이 '{actual_fail_reason}' 이유로 반려되었습니다. "
            + f"다음 사항을 준수하세요: {advice}"
        )

        yield sse_msg("token", {"delta": "\n\n---\n[System] 답변 품질 개선을 위해 재생성합니다...\n---\n\n"})

        stream_v2 = rag.llm.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt_v2},
                {"role": "user",   "content": f"[Context]\n{context_text}\n\nQuestion: {user_query}"}
            ],
            stream=True
        )

        for chunk in stream_v2:
            if chunk.choices[0].delta.content:
                text = chunk.choices[0].delta.content
                full_answer_v2 += text
                yield sse_msg("token", {"delta": text})

        print("[Round 2] 품질 검증 수행 중...")
        v_res2 = await rag.verify(user_query, context_text, full_answer_v2)

        s_faith2 = v_res2.get("groundedness", 0)
        s_rel2   = v_res2.get("relevance", 0)
        s_cite2  = v_res2.get("citation_accuracy", 0)

        is_pass2            = s_faith2 >= 5
        actual_fail_reason2 = v_res2.get("reason", "최종 확인")

        yield sse_msg("verification", {
            "type": "verification",
            "round": 2,
            "payload": {
                "pass":   is_pass2,
                "reason": actual_fail_reason2,
                "ragas": {
                    "faithfulness":      s_faith2 / 10,
                    "relevance":         s_rel2   / 10,
                    "citation_accuracy": s_cite2  / 10
                }
            }
        })

    final_content = full_answer if is_pass else full_answer_v2
    yield sse_msg("final", {"content": final_content})

    title = await rag.generate_title(user_query)
    yield sse_msg("title", {"title": title})

    print("처리 완료\n")

# if __name__ == "__main__":
#     import uvicorn
#     uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)