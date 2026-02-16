🚀 RAG 플랫폼 프로젝트 구동 가이드 (팀원용)

________________________________________

📋 1. 프로젝트 스펙 (버전 정보) 
- Frontend: React 19 / Vite / Tailwind CSS / Zustand • Backend: Python 3.10+ / FastAPI 
- AI/DB: ChromaDB / OpenAI GPT-4o / Cross-Encoder
- 핵심 기능: 언어별 맞춤 답변(Python, Java, React 등), 2단계 품질 검증(Self-Correction)

________________________________________

🛠️ 2. 사전 준비물 (설치 필수)
- Node.js: 공식 홈페이지에서 v18 이상 버전을 설치하세요.
- Python: 공식 홈페이지에서 v3.10 이상 버전을 설치하세요. (설치 시 'Add Python to PATH' 체크 필수)
- Git: 코드를 내려받기 위해 설치하세요.

________________________________________

💻 3. 서버(Backend) 실행 방법 터미널(CMD)을 열고 백엔드 폴더에서 다음 명령어를 순서대로 입력하세요.
- 가상환경 생성: python -m venv venv
- 가상환경 접속: o (Windows): venv\Scripts\activate o (Mac/Linux): source venv/bin/activate
- 필수 라이브러리 설치: Bash pip install fastapi uvicorn chromadb openai sentence-transformers python-dotenv pypdf python-multipart
- 환경 설정: .env 파일을 생성하고 아래 내용을 입력합니다. 코드 스니펫 OPENAI_API_KEY=전달받은_키_입력 CHROMA_DB_PATH=./chroma_db CHROMA_COLLECTION_NAME=docs_rag_v22
- 서버 실행: uvicorn main:app --reload

________________________________________

🖥️ 4. 화면(Frontend) 실행 방법 새 터미널을 열고 프론트엔드 폴더에서 입력하세요.
- 의존성 설치: npm install
- 마크다운 관련 설치: npm install react-markdown rehype-highlight
- 클라이언트 사이드 라우팅 관련 설치: npm install react-router-dom
- 프로그램 실행: npm run dev
- 접속: 브라우저에서 http://localhost:5173 접속

________________________________________

⚠️ 5. 주의사항 (꼭 읽어주세요!)
- 스타일 선택: 화면 우측 상단 드롭다운 버튼을 눌러 수석 개발자, 친절한 사수 등 답변 스타일을 선택해주세요(default: 수석 개발자/Expert).
- 언어 선택: 화면 우측 상단 드롭다운 버튼을 눌러 Python, Java 등 타겟 언어를 선택해주세요(default: Python).
- DB 폴더: 프로젝트 폴더 안에 chroma_db 폴더가 반드시 있어야 AI가 지식을 찾아올 수 있습니다(default: 2026. 02. 13 기준 데이터).

________________________________________
