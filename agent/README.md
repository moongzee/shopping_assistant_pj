## FastAPI 기반 패션 쇼핑 추천 Agent API

`test_agent.ipynb`의 LangGraph 워크플로우(의도분석 → 정형검색 → 비정형검색 → 융합 → 응답생성)를
**그대로 모듈화**해서 `FastAPI + SSE`로 노출합니다.

> 전체(백엔드+프론트+학습/배포) 가이드는 레포 루트의 `README.md`를 참고하세요.

### 핵심 기능

- **스트리밍 응답(SSE)**: `token` 이벤트로 LLM 답변을 chunk 단위로 스트리밍
- **진행상태 노출**: LangGraph 노드 실행 단계마다 `state` 이벤트로 현재 노드/업데이트 키를 전송
- **추천상품 메타 분리**: 마지막 `final` 이벤트에 `recommended_products` / `grouped_recommended_products` 제공
- **세션별 멀티턴 메모리**: `session_id`를 LangGraph `thread_id`로 사용 + `messages`를 체크포인터에 저장
- **로그/피드백 저장**: `chat.jsonl`/`feedback.jsonl`로 학습/평가 데이터 축적

### 실행

```bash
pip install -r agent/requirements.txt
uvicorn agent.app.main:app --reload --port 8000
```

### 호출 예시

```bash
curl -N -X POST "http://localhost:8000/v1/chat/stream" \
  -H "Content-Type: application/json" \
  -d '{"session_id":"demo-session","user_query":"로엠 따뜻하고 편한 기모 긴팔 추천해줘"}'
```

### SSE 이벤트 스펙(요약)

- `start`: 요청 시작
- `state`: LangGraph 노드 진행 이벤트
- `token`: LLM 답변 텍스트 델타 스트림
- `final`: 추천상품 메타(카드용) + 부가 메타
- `done`: 스트림 종료

### 피드백 저장 API

- `POST /v1/feedback`
- 예시:

```bash
curl -X POST "http://localhost:8000/v1/feedback" \
  -H "Content-Type: application/json" \
  -d '{"session_id":"demo-session","message_id":"<start 이벤트의 message_id>","rating":5,"selected_style_codes":["RMKAF4TR02"]}'
```

### DSPy 최적화(compile) 루프(스캐폴딩)

1) 로그/피드백으로 데이터셋 생성:

```bash
python -m agent.train.build_dataset
```

2) 모듈 compile(예: 정형 fallback 후보 생성기):

```bash
python -m agent.train.compile \
  --module relaxed_constraints \
  --dataset agent/data/datasets/relaxed_constraints.jsonl \
  --out agent/artifacts/relaxed_constraints.json
```

3) 서버 재시작 없이 artifact reload:

```bash
curl -X POST "http://localhost:8000/admin/reload_artifacts"
```

### 환경변수

- 이 API는 서버 시작 시 `.env`를 자동으로 로드합니다(기존 OS 환경변수는 덮어쓰지 않음).
- `.env` 위치는 아래 중 하나를 사용하세요.
  - `agent/.env`
  - 레포 루트의 `.env`

- `DSPY_MODEL`: DSPy가 사용할 모델 식별자(기본값: 노트북과 동일)
- `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` / `AWS_SESSION_TOKEN` / `AWS_REGION`: Bedrock 사용 시 필요(코드에 하드코딩 금지)
- `MCP_SNOWFLAKE_URL`, `MCP_CORTEX_ANALYST_URL` 등: MCP 엔드포인트/툴 설정

`agent/env.example`을 참고해서 실제 `.env`를 만들어 넣으면 됩니다(비밀키는 절대 git 커밋 금지).

