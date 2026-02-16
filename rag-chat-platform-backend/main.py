import os
import json
import asyncio
from fastapi import FastAPI, Request, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
import chromadb
from openai import OpenAI
from typing import List, Dict
from sentence_transformers import CrossEncoder
from dotenv import load_dotenv
from pydantic import BaseModel
from ingestion import IngestionService
from crawler import fetch_url_content

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
DB_PATH = os.getenv("CHROMA_DB_PATH")
COLLECTION_NAME = os.getenv("CHROMA_COLLECTION_NAME")
RERANK_MODEL_NAME = os.getenv("RERANK_MODEL_NAME")

if not OPENAI_API_KEY:
    raise ValueError("API Key가 없습니다. .env 파일을 확인해주세요.")

SELF_VERIFICATION_PROMPT = """당신은 엄격한 품질 검증자입니다.
생성된 답변을 아래 기준으로 평가하고 JSON 형식으로 응답하세요.

**평가 기준:**
1. 근거성(Groundedness): 답변이 제공된 컨텍스트에만 기반하는가? (0-10)
2. 관련성(Relevance): 답변이 질문과 직접 관련이 있는가? (0-10)
3. 인용 정확성: '출처:' 섹션에 URL이 정확히 명시되었는가? (0-10)

**출력 형식 (JSON):**
{
    "groundedness": 8,
    "relevance": 9,
    "citation_accuracy": 7,
    "reason": "URL은 포함되었으나 설명이 다소 부족함",
    "issues": ["설명 부족"]
}
"""

class RAGService:
    def __init__(self):
        self.client = chromadb.PersistentClient(path=DB_PATH)
        self.collection = self.client.get_collection(name=COLLECTION_NAME)
        self.llm = OpenAI()

        print("[RAG] Loading Cross-Encoder model...")
        self.cross_encoder = CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')
        print("[RAG] Model loaded.")

        self.ingestor = IngestionService(self.collection)

    def get_system_prompt(self, language: str, style: str):
        base_personas = {
            "Python": "당신은 Python 전문가입니다. PEP 8 스타일 가이드를 준수합니다.",
            "Java": "당신은 Java 시니어 개발자입니다. 객체 지향 원칙(SOLID)을 중시합니다.",
            "C++": "당신은 C++ 시스템 프로그래머입니다. 성능 최적화와 메모리 안전성을 우선합니다.",
            "JavaScript": "당신은 모던 JavaScript 전문가입니다. ES6+ 표준에 능숙합니다.",
            "JSP": "당신은 Java 웹 개발 전문가입니다. 레거시 시스템과 현대적 패턴을 모두 이해합니다.",
            "React": "당신은 React 프론트엔드 전문가입니다. 렌더링 최적화와 Hook 활용에 능숙합니다."
        }
        
        target_persona = base_personas.get(language, base_personas["Python"])

        style_instructions = {
            "Expert": """
            [답변 스타일: 수석 개발자]
            - 군더더기 없는 전문적인 어조를 사용하세요. (해요체 지양, 하십시오체 또는 간결한 문체 권장)
            - 단순한 해결책보다는 성능, 메모리 효율, 보안 이슈를 고려한 'Best Practice'를 제시하세요.
            - 사용자의 코드가 비효율적이라면 따끔하게 지적하고 개선안을 주세요.
            """,
            "Friendly": """
            [답변 스타일: 친절한 튜터]
            - 초보자가 이해하기 쉽도록 비유를 사용하여 상세하게 설명하세요.
            - 용어가 어렵다면 풀어서 설명하고, 격려하는 어조를 사용하세요.
            - 코드 예제에는 주석을 꼼꼼하게 다세요.
            """,
            "Strict": """
            [답변 스타일: 코드 리뷰어]
            - 서론과 결론을 최소화하고, 즉시 실행 가능한 코드 위주로 답변하세요.
            - 코드는 바로 복사/붙여넣기 할 수 있는 형태여야 합니다.
            - 설명은 코드 내 주석이나 코드 아래 짧은 글머리 기호로만 남기세요.
            """
        }

        selected_style = style_instructions.get(style, style_instructions["Expert"])

        return f"""
        {target_persona}
        {selected_style}

        제공된 Context를 바탕으로 답변하되, 다음 규칙을 엄격히 지키세요:
        1. 답변 내용에 반드시 참고한 문서의 URL을 포함하세요.
        2. 답변 끝에 '출처:' 섹션을 만들고 모든 관련 URL을 나열하세요.
        3. 사용자가 '{language}'에 대해 질문했다면 해당 언어 문법으로 예시를 작성하세요.
        """

    def search(self, query, language="Python", k=10):
        print(f"[Search] Query: {query}, Filter: {language.upper()}")
        
        try:
            return self.collection.query(
                query_texts=[query],
                n_results=k,
                where={"platform": language.upper()}, 
                include=['documents', 'metadatas']
            )
        except Exception as e:
            print(f"[Search Error] {e}")
            return {"documents": [[]], "metadatas": [[]]}

    def rerank(self, query, initial_results, threshold=-2.0):
        docs = initial_results['documents'][0]
        metas = initial_results['metadatas'][0]
        
        if not docs: return []

        content_to_original_rank = {doc: i for i, doc in enumerate(docs)}

        pairs = [[query, doc] for doc in docs]
        scores = self.cross_encoder.predict(pairs)

        reranked = sorted(zip(docs, metas, scores), key=lambda x: x[2], reverse=True)

        final_results = []
        for new_rank, (doc, meta, score) in enumerate(reranked[:5]):
            if float(score) < threshold:
                print(f"[Rerank] Drop document (Low Score: {score})")
                continue

            meta_with_score = meta.copy()
            meta_with_score['score'] = float(score)

            original_rank = content_to_original_rank.get(doc, 99)
            rank_change = original_rank - new_rank
            meta_with_score['rank_change'] = rank_change

            final_results.append({
                "id": f"rank_{new_rank+1}",
                "content": doc,
                "metadata": meta_with_score,
                "score": float(score)
            })

        return final_results

    async def verify(self, question, context, answer):
        try:
            response = self.llm.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": SELF_VERIFICATION_PROMPT},
                    {"role": "user", "content": f"[Question]\n{question}\n\n[Context]\n{context}\n\n[Answer]\n{answer}"}
                ],
                response_format={"type": "json_object"}
            )
            return json.loads(response.choices[0].message.content)
        except Exception as e:
            print(f"Verification Error: {e}")
            return {"groundedness": 0, "reason": "검증 실패"}

    async def optimize_prompt(self, query, issue_reason, language="Python"):
        OPTIMIZER_PROMPT = f"""당신은 {language} RAG 시스템 튜닝 전문가입니다.
        이전 답변이 다음 이유로 품질 검증에 실패했습니다: '{{reason}}'
        사용자 질문: '{{query}}'
        
        이 문제를 해결하기 위해 LLM에게 전달할 '개선된 시스템 프롬프트'를 새로 작성해주세요.
        '{language} 언어의 특성', '출처 표기', '상세 설명'을 더 강력하게 지시해야 합니다.
        """
        try:
            response = self.llm.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "system", "content": OPTIMIZER_PROMPT.format(reason=issue_reason, query=query)}],
            )
            return response.choices[0].message.content
        except:
            return f"당신은 {language} 전문가입니다. 반드시 출처 URL을 명시하고 내용을 상세히 설명하세요."
    
    async def generate_title(self, query):
        try:
            prompt = f"다음 사용자 질문을 바탕으로 2~3단어 이내의 짧은 대화 제목을 생성해줘. 따옴표 없이 제목만 출력해. 질문: {query}"
            response = self.llm.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}]
            )
            return response.choices[0].message.content.strip()
        except:
            return query[:15] + "..."

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
        body = await request.json()
        user_query = body.get("message", "")
        language = body.get("language", "Python")
        style = body.get("style", "Expert")

        if not user_query and body.get("messages"):
            user_query = body["messages"][-1].get("content", "")
        
        return StreamingResponse(stream_generator(user_query, language, style), media_type="text/event-stream")
    except Exception as e:
        return StreamingResponse(iter([sse_msg("error", {"message": str(e)})]), media_type="text/event-stream")

@app.post("/api/upload")
async def upload_document(
    file: UploadFile = File(...),
    language: str = Form(...)
):
    try:
        content = await file.read()
        print(f"[Upload] Received {file.filename} for {language}")
        
        count = await rag.ingestor.process_file(content, file.filename, language)
        
        return {"status": "success", "chunks_added": count, "message": f"{count}개의 지식 청크가 추가되었습니다."}
    except Exception as e:
        print(f"[Upload Error] {e}")
        return {"status": "error", "message": str(e)}

async def stream_generator(user_query, language, style):
    full_answer = ""
    full_answer_v2 = ""
    is_pass = False
    actual_fail_reason = "검증 데이터 부족" 
    
    print(f"\n[질문 수신] {user_query} (Language: {language}, Style: {style})")
    
    search_res = rag.search(user_query, language=language, k=10)
    
    retrieval_payload = []
    if search_res['documents']:
        for i, (doc, meta) in enumerate(zip(search_res['documents'][0], search_res['metadatas'][0])):
            retrieval_payload.append({"id": f"retr_{i}", "content": doc[:200], "metadata": meta})
    
    yield sse_msg("retrieval", {"round": 1, "payload": retrieval_payload})
    
    reranked_results = rag.rerank(user_query, search_res)
    yield sse_msg("rerank", {"round": 1, "payload": reranked_results})

    if not reranked_results:
        print("[System] 문서 범위 밖 질문(OOS) 감지 -> 답변 거부")
        no_result_msg = " 죄송합니다. 제공된 문서들 중에서 해당 질문에 대한 답변을 찾을 수 없습니다. (근거 부족)"
        yield sse_msg("final", {"content": no_result_msg})
        yield sse_msg("title", {"title": "문서 범위 밖 질문"})
        return

    context_text = ""
    for item in reranked_results:
        meta = item['metadata']
        context_text += f"[URL: {meta.get('url', 'N/A')}] {item['content']}\n\n"

    print("[Round 1] 답변 생성 중...")
    
    system_prompt_v1 = rag.get_system_prompt(language, style)
    
    stream = rag.llm.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": system_prompt_v1},
            {"role": "user", "content": f"[Context]\n{context_text}\n\nQuestion: {user_query}"}
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
        
        score = v_res.get('groundedness', 0)
        actual_fail_reason = v_res.get("reason", "품질 기준 미달")
        print(f"[Round 1 결과] 점수: {score}점 / 사유: {actual_fail_reason}")

        is_pass = score >= 7
        
        print(f"판정 결과: {'PASS (종료)' if is_pass else 'FAIL (Round 2 진입)'}")

        yield sse_msg("verification", {
            "type": "verification",
            "round": 1,
            "payload": {
                "pass": is_pass,
                "reason": actual_fail_reason,
                "ragas": {
                    "faithfulness": score / 10,
                    "relevance": v_res.get("relevance", 0) / 10,
                    "citation_accuracy": v_res.get("citation_accuracy", 0) / 10
                }
            }
        })

    if not is_pass:
        print(f"[Round 2] 자가 수정 프로세스 시작...")
        
        yield sse_msg("retrieval", {"round": 2, "payload": retrieval_payload})
        yield sse_msg("rerank", {"round": 2, "payload": reranked_results})
        
        refined_prompt = await rag.optimize_prompt(user_query, actual_fail_reason, language)
        print(f"[Round 2] 최적화된 프롬프트 생성 완료")

        yield sse_msg("token", {"delta": "\n\n---\n[System] 답변 품질 개선을 위해 재생성합니다...\n---\n\n"})
        
        stream_v2 = rag.llm.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": refined_prompt},
                {"role": "user", "content": f"[Context]\n{context_text}\n\nQuestion: {user_query}"}
            ],
            stream=True
        )
        
        for chunk in stream_v2:
            if chunk.choices[0].delta.content:
                text = chunk.choices[0].delta.content
                full_answer_v2 += text
                yield sse_msg("token", {"delta": text})

        print("[Round 2] 2차 검증 수행 중...")
        if full_answer_v2:
            v_res_v2 = await rag.verify(user_query, context_text, full_answer_v2)
            score_v2 = v_res_v2.get('groundedness', 0)
            
            is_pass_v2 = score_v2 >= 5
            
            yield sse_msg("verification", {
                "type": "verification",
                "round": 2,
                "payload": {
                    "pass": is_pass_v2,
                    "reason": "재생성 후 검증 통과" if is_pass_v2 else v_res_v2.get("reason"),
                    "ragas": {
                        "faithfulness": score_v2 / 10,
                        "relevance": v_res_v2.get("relevance", 0) / 10,
                        "citation_accuracy": v_res_v2.get("citation_accuracy", 0) / 10
                    }
                }
            })

    final_content = full_answer if is_pass else full_answer_v2
    yield sse_msg("final", {"content": final_content})

    title = await rag.generate_title(user_query)
    yield sse_msg("title", {"title": title})
    
    print("처리 완료\n")

class TestRequest(BaseModel):
    question: str
    language: str = "Python"
    style: str = "Expert"

@app.post("/api/test/run")
async def run_test_case(req: TestRequest):
    print(f"[Test] Processing: {req.question} ({req.language})")
    
    search_res = rag.search(req.question, language=req.language, k=10)
    reranked = rag.rerank(req.question, search_res)
    
    if not reranked:
        return {
            "question": req.question,
            "round1_ans": "OOS (문서 범위 밖)",
            "round1_pass": False,
            "round1_score": 0.0,
            "round1_reason": "Low Relevance Score (Filtered)",
            "round2_ans": "-",
            "round2_pass": False,
            "round2_score": 0.0,
            "final_ans": "문서 범위 밖입니다."
        }

    context_text = ""
    for item in reranked:
        meta = item['metadata']
        context_text += f"[URL: {meta.get('url', 'N/A')}] {item['content']}\n\n"

    system_prompt = rag.get_system_prompt(req.language, req.style)
    resp1 = rag.llm.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"[Context]\n{context_text}\n\nQuestion: {req.question}"}
        ]
    )
    ans1 = resp1.choices[0].message.content

    v_res1 = await rag.verify(req.question, context_text, ans1)
    score1 = v_res1.get('groundedness', 0)
    is_pass1 = score1 >= 7

    if is_pass1:
        return {
            "question": req.question,
            "round1_ans": ans1,
            "round1_pass": True,
            "round1_score": score1,
            "round1_reason": "Pass",
            "round2_ans": "-",
            "round2_pass": None,
            "round2_score": 0.0,
            "final_ans": ans1
        }

    refined_prompt = await rag.optimize_prompt(req.question, v_res1.get("reason"), req.language)
    
    resp2 = rag.llm.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": refined_prompt},
            {"role": "user", "content": f"[Context]\n{context_text}\n\nQuestion: {req.question}"}
        ]
    )
    ans2 = resp2.choices[0].message.content

    v_res2 = await rag.verify(req.question, context_text, ans2)
    score2 = v_res2.get('groundedness', 0)
    is_pass2 = score2 >= 5

    return {
        "question": req.question,
        "round1_ans": ans1,
        "round1_pass": False,
        "round1_score": score1,
        "round1_reason": v_res1.get("reason"),
        "round2_ans": ans2,
        "round2_pass": is_pass2,
        "round2_score": score2,
        "final_ans": ans2
    }

class UrlRequest(BaseModel):
    url: str

@app.post("/api/fetch-url")
async def get_url_content(req: UrlRequest):
    print(f"[Crawler] Fetching: {req.url}")
    content = fetch_url_content(req.url)
    
    if content.startswith("Error"):
        return {"status": "error", "message": content}
    
    return {"status": "success", "content": content}