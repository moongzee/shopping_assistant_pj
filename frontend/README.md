# Shopping Assistant Frontend

## 요구사항
- Node.js (권장: 20+)

## 환경변수
로컬에서 바로 dev를 띄우려면 아래처럼 `.env.local`을 만들어 주세요.

```bash
cp env.local.template .env.local
```

- **AGENT_BASE_URL**: FastAPI 백엔드 주소 (예: `http://127.0.0.1:8000`)
- **ADMIN_API_KEY**: 백엔드에서 `ADMIN_API_KEY`를 설정했다면 동일하게 입력

## 실행
백엔드 실행:

```bash
conda activate geo
uvicorn agent.app.main:app --reload --port 8000
```

프론트 실행:

```bash
cd frontend
npm install
npm run dev
```

## 자주 나는 에러

### `/admin` 접속 시 `Cannot find module './873.js'` 같은 에러가 날 때
Next dev 번들 캐시(`.next`)가 꼬인 경우가 많습니다.

```bash
cd frontend
npm run clean
npm run dev
```

## 페이지
- `/`: 채팅(스트리밍) + LangGraph 진행상태 + 우측 상품 카드
- `/admin`: 로그/데이터셋 생성/컴파일/아티팩트 리로드 대시보드

