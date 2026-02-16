import hashlib
import io
from typing import List
from pypdf import PdfReader
from chromadb import Collection
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

# DE 노트북과 동일한 모델 사용
EMBED_MODEL_NAME = "intfloat/multilingual-e5-base"

class IngestionService:
    def __init__(self, collection: Collection):
        self.collection = collection
        self.embed_fn = SentenceTransformerEmbeddingFunction(model_name=EMBED_MODEL_NAME)

    def chunk_with_overlap(self, s: str, chunk_size: int = 800, overlap: int = 100) -> List[str]:
        s = (s or "").strip()
        if not s:
            return []
        if len(s) <= chunk_size:
            return [s]
        
        out = []
        start = 0
        while start < len(s):
            end = min(len(s), start + chunk_size)
            chunk = s[start:end].strip()
            if chunk:
                out.append(chunk)
            if end == len(s):
                break
            start = max(0, end - overlap)
        return out

    async def process_file(self, file_content: bytes, filename: str, platform: str) -> int:
        text = ""
        if filename.lower().endswith(".pdf"):
            reader = PdfReader(io.BytesIO(file_content))
            for page in reader.pages:
                extracted = page.extract_text()
                if extracted:
                    text += extracted + "\n"
        else:
            text = file_content.decode("utf-8", errors="ignore")

        chunks = self.chunk_with_overlap(text)
        
        if not chunks:
            return 0

        ids = []
        metadatas = []
        base_id = hashlib.sha1(filename.encode()).hexdigest()[:10]

        for i, chunk in enumerate(chunks):
            ids.append(f"hotfix_{base_id}_{i}")
            metadatas.append({
                "platform": platform.upper(),
                "type": "text",
                "url": f"uploaded:{filename}",
                "section_path": "HotFix Upload",
                "source": "WEB_TESTER"
            })

        print(f"[Ingestion] Adding {len(chunks)} chunks to DB (Platform: {platform})...")
        self.collection.add(
            ids=ids,
            documents=chunks,
            metadatas=metadatas
        )
        
        return len(chunks)