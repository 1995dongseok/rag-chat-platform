# check_db.py
import chromadb
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
import json

CHROMA_DIR = "./chroma_store"
COLLECTION_NAME = "docs_rag_v22"
EMBED_MODEL_NAME = "intfloat/multilingual-e5-base"

def test_database():
    print("🔄 DB 연결 중...")
    embed_fn = SentenceTransformerEmbeddingFunction(model_name=EMBED_MODEL_NAME)
    client = chromadb.PersistentClient(path=CHROMA_DIR)
    
    try:
        col = client.get_collection(name=COLLECTION_NAME, embedding_function=embed_fn)
        print(f"✅ DB 연결 성공! 총 데이터 개수: {col.count()}개\n")
    except Exception as e:
        print("❌ 컬렉션을 찾을 수 없습니다. DB 생성이 안 된 것 같습니다.")
        return

    # 테스트해볼 질문 목록
    test_queries = [
        {"query": "파이썬에서 제곱근을 구하는 방법", "platform": "PYTHON"},
        {"query": "자바에서 클래스의 정의", "platform": "JAVA"},
        {"query": "자바스크립트 Promise then 예시", "platform": "JAVASCRIPT"},
        {"query": "C#에서 콘솔창에 'Hello World'라는 문구를 출력하기 위해 사용하는 올바른 메서드는?", "platform": "CSHARP"}
    ]

    for tq in test_queries:
        print(f"==================================================")
        print(f"❓ 질문: {tq['query']} (언어: {tq['platform']})")
        print(f"==================================================")
        
        results = col.query(
            query_texts=[tq['query']],
            n_results=2, # 상위 2개만 확인
            where={"platform": tq['platform']},
            include=["documents", "metadatas", "distances"]
        )

        docs = results["documents"][0]
        metas = results["metadatas"][0]
        dists = results["distances"][0]

        if not docs:
            print("  -> ⚠️ 검색 결과가 없습니다.")
            continue

        for i, (doc, meta, dist) in enumerate(zip(docs, metas, dists)):
            print(f"\n[순위 {i+1} | 유사도(거리): {dist:.4f}]")
            print(f"🏷️ 타입: {meta.get('type')} | 📂 경로: {meta.get('section_path')}")
            print(f"🌐 URL: {meta.get('url')}")
            print(f"📄 내용 요약: {doc[:100]}...\n")

if __name__ == "__main__":
    test_database()