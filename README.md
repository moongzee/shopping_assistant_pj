## Shopping Assistant (Backend + Frontend + DSPy 학습/최적화)

이 프로젝트는 `test_agent.ipynb` 기반의 패션 쇼핑 추천 로직을 **FastAPI + LangGraph + DSPy**로 모듈화하고,
프론트는 **Next.js**로 “채팅 스트리밍 + LangGraph 진행상태 + 추천 상품 카드” UI와
“DSPy 학습/컴파일/배포(reload)”를 위한 **대시보드(/admin)** 를 제공합니다.

### 구성(폴더)
- **백엔드(Agent API)**: `agent/`
- **프론트(UI + 대시보드)**: `frontend/`
  - `/`: 채팅 스트리밍 + LangGraph 중간과정 + 추천 상품 카드
  - `/admin`: 로그/데이터셋 생성/컴파일/아티팩트 리로드 대시보드

---

## 로컬 환경 세팅(처음부터)

### 0) 전제
- **Python**: (현재 로컬에서는) `conda geo` 환경을 사용
- **Node.js**: 20+ 권장

---

## 1) 백엔드(Agent API) 설정/실행

### 1-1) 의존성 설치
레포 루트(= `shopping_assistant/`)에서:

```bash
conda activate geo
pip install -r agent/requirements.txt
```

### 1-2) 환경변수(.env)
백엔드는 시작 시 `.env`를 자동으로 로드합니다(기존 OS 환경변수는 덮어쓰지 않음).
아래 중 하나 위치에 `.env`를 두면 됩니다.

- `agent/.env`
- 레포 루트의 `.env`

템플릿은 `agent/env.example` 참고하세요(비밀키는 절대 git 커밋 금지).

#### 필수/핵심 환경변수(요약)
- **Bedrock/DSPy**
  - `DSPY_MODEL`
  - `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN`(선택), `AWS_REGION`
- **MCP**
  - `MCP_CORTEX_ANALYST_URL`, `MCP_SNOWFLAKE_URL` 등
- **운영**
  - `ADMIN_API_KEY` (설정 시 admin API 보호됨)
  - `FRONTEND_ORIGINS` (CORS 허용 origin 목록, 콤마 구분)
  - `AGENT_DATA_DIR` (로그/데이터셋 저장 경로)

### 1-3) 백엔드 실행

```bash
uvicorn agent.app.main:app --reload --port 8000
```

#### 헬스체크
- `GET http://localhost:8000/health`

---

## 2) 프론트(Next.js) 설정/실행

### 2-1) `.env.local` 만들기(커밋 제외)
`frontend/` 폴더로 이동한 뒤:

```bash
cd frontend
# env.example를 기반으로 로컬 env 파일을 만듭니다.
cp env.example .env.local
```

`AGENT_BASE_URL`은 보통 아래로 두면 됩니다.
- `AGENT_BASE_URL=http://127.0.0.1:8000`

#### (권장) 스트리밍이 “final과 함께 한 번에” 보일 때
일부 환경(특히 Next.js API Route 프록시/리버스프록시)에서는 `text/event-stream`이 **버퍼링**되어,
토큰이 실시간으로 보이지 않고 `final`처럼 한 번에 렌더링되는 것처럼 보일 수 있습니다.

이 경우 아래를 `.env.local`에 추가해 **브라우저가 백엔드 SSE를 직접 호출**하게 만들면 가장 확실합니다.

- `NEXT_PUBLIC_AGENT_BASE_URL=http://127.0.0.1:8000`

`ADMIN_API_KEY`는 백엔드에서 `ADMIN_API_KEY`를 설정했을 때만 동일하게 넣어주세요.

> `.env.local`은 `frontend/.gitignore`에 의해 **커밋되지 않습니다.**

### 2-2) 의존성 설치/실행

```bash
npm install
npm run dev
```

### 2-3) 접속
- 채팅 UI: `http://localhost:3000/`
- 학습/최적화 대시보드: `http://localhost:3000/admin`

---

## 3) 채팅 스트리밍 + LangGraph 진행상태 + 상품 카드(동작 방식)

### 3-1) 백엔드 SSE 이벤트
`POST /v1/chat/stream`는 `text/event-stream`으로 아래 이벤트를 보냅니다.

- `start`: 요청 시작( `message_id` 부여 )
- `state`: LangGraph 노드 진행( `node`, `update_keys` )
- `token`: LLM 응답 텍스트 델타(스트리밍)
- `final`: `recommended_products`, `grouped_recommended_products` 등 카드용 메타
- `done`: 스트림 종료

### 3-1-1) 스트리밍이 느리거나 “한 번에” 보이는 경우(튜닝/트러블슈팅)
- **(우선 권장)** 프론트 `.env.local`에 `NEXT_PUBLIC_AGENT_BASE_URL`을 설정해
  브라우저가 백엔드 SSE를 직접 호출하도록 구성합니다(프록시 버퍼링 회피).
- **백엔드 튜닝(선택)** 토큰이 너무 크게/빠르게 와서 UI가 “한 번에” 보인다면,
  백엔드 `.env`에 아래 값을 조절할 수 있습니다.
  - `STREAM_CHUNK_CHARS` (기본 24): 더 작게 하면 더 잘게 쪼개서 전송
  - `STREAM_DELAY_MS` (기본 15): 더 크게 하면 토큰 전송 간격을 늘려 “타이핑처럼” 보이게 함


### 3-2) 피드백(학습 데이터)
사용자가 카드에서 “이 상품 선택(피드백)”을 누르면:
- `POST /v1/feedback` 로 `selected_style_codes`가 저장됩니다.
- 이 데이터가 DSPy 학습/컴파일 데이터셋의 라벨로 사용됩니다.

---

## 4) DSPy 학습/최적화(learn → compile → deploy) 개념/방법

### 4-1) DSPy를 왜 쓰나?
DSPy는 “프롬프트를 문자열로만 관리”하기보다, **입출력이 명확한 모듈(프로그램)**로 LLM을 다루고,
로그/피드백으로 쌓인 데이터를 이용해 **optimizer(teleprompt)**로 모듈을 **compile(최적화)** 합니다.

이 프로젝트에서는 아래 모듈들을 “학습 대상”으로 둡니다.
- **RelaxedConstraintsGenerator**: 정형 검색(Analyst SQL)이 비거나 너무 빡빡할 때, LLM이 제약을 완화한 후보를 생성
- **ProductRanker**: 정형 후보(products)에서 사용자 의도에 맞는 style_code 우선순위 생성
- **FusionDecisionMaker**: 정형 결과 + 비정형 리뷰 시그널을 종합해 최종 추천 style_code 결정

> 결과물은 “학습된 프롬프트/데모(가중치)” 같은 형태로 **artifact 파일(json)** 로 저장됩니다.

### 4-2) 데이터는 어디에 쌓이나?
백엔드는 자동으로 아래에 로그를 쌓습니다.
- `agent/data/logs/chat.jsonl`
- `agent/data/logs/feedback.jsonl`

운영에서는 `AGENT_DATA_DIR`로 디렉터리를 분리/영속화하는 것을 권장합니다.

### 4-3) 데이터셋 생성(build_dataset)
로그/피드백을 DSPy 학습용 jsonl로 변환:
- `agent/data/datasets/ranker.jsonl`
- `agent/data/datasets/relaxed_constraints.jsonl`
- `agent/data/datasets/fusion.jsonl`

CLI:

```bash
python -m agent.train.build_dataset
```

또는 대시보드:
- `/admin` → `dataset 생성`

### 4-4) 컴파일(compile) + 서버 무중단 반영(reload)
CLI:

```bash
python -m agent.train.compile \
  --module product_ranker \
  --dataset agent/data/datasets/ranker.jsonl \
  --out agent/artifacts/product_ranker.json

curl -X POST "http://localhost:8000/admin/reload_artifacts"
```

대시보드:
- `/admin` → `compile 실행` (완료 시 reload 포함)

### 4-4-1) 대시보드(/admin) 버튼/기능 설명(개념)

대시보드는 “학습/최적화 루프”를 버튼으로 감싼 것입니다. 각 버튼의 역할은 아래와 같습니다.

- **로그 새로고침**
  - 하는 일: 서버가 저장한 로그 파일을 다시 읽어 화면을 갱신
    - `agent/data/logs/chat.jsonl`
    - `agent/data/logs/feedback.jsonl`
  - 의미: “학습 재료가 쌓였는지(피드백이 들어왔는지)” 확인용
  - 주의: 모델/아티팩트를 바꾸지 않습니다(화면만 갱신).

- **dataset 생성**
  - 하는 일: `chat.jsonl`/`feedback.jsonl`을 DSPy 학습용 **데이터셋(jsonl)** 로 변환/저장
  - 산출물:
    - `agent/data/datasets/ranker.jsonl` (ProductRanker 학습)
    - `agent/data/datasets/fusion.jsonl` (FusionDecisionMaker 학습)
    - `agent/data/datasets/relaxed_constraints.jsonl` (RelaxedConstraintsGenerator 학습)
  - 의미: “학습 재료를 모듈 입력/정답 라벨 형태로 가공”하는 단계(아직 최적화 전)

- **compile 실행**
  - 하는 일: 선택한 모듈(`product_ranker`/`fusion_decision`/`relaxed_constraints`)을
    데이터셋으로 DSPy optimizer가 **compile(최적화)** 해서 artifact 파일로 저장
  - 산출물(예):
    - `agent/artifacts/product_ranker.json`
    - `agent/artifacts/fusion_decision.json`
    - `agent/artifacts/relaxed_constraints.json`
  - 의미: “학습/최적화 결과물을 파일(artifact)로 생성”하는 단계
  - 주의: 데이터셋 예시가 너무 적으면(보통 2개 미만) compile이 실패합니다.

- **artifacts reload**
  - 하는 일: 서버가 메모리에 캐시하고 있던 DSPy 모듈을 버리고,
    디스크의 최신 artifact를 다시 로드
  - 의미: 서버 재시작 없이(무중단) “컴파일 결과를 즉시 반영”하는 단계

- **Job**
  - dataset 생성/compile은 오래 걸릴 수 있어 비동기 job으로 실행됩니다.
  - 상태: `queued → running → done | error`
  - `error`가 뜨면 대체로 “데이터셋 예시 부족”, “모델 인증/권한”, “네트워크(MCP/Bedrock)” 이슈입니다.

### 4-4-2) 대시보드에서 추천 품질을 올리는 최소 루틴(권장 순서)

1. 채팅 UI(`/`)에서 여러 질의를 수행하고, 카드에서 **선택(피드백)** 을 누른다.
2. 대시보드(`/admin`)에서 **로그 새로고침**으로 `feedback`이 쌓였는지 확인
3. **dataset 생성**
4. **compile 실행**(보통 `product_ranker`부터 추천)
5. 필요 시 **artifacts reload** (대시보드 compile이 reload 포함이면 생략 가능)
6. 채팅 UI에서 같은/유사 질의로 결과 비교

### 4-5) “학습을 어떻게 시킬지” 권장 운영 루프
- **(수집)** 실제 사용자 쿼리/클릭 피드백(선택한 style_code) 누적
- **(정제)** 품질이 낮은 세션/이상치 제거, 라벨 보강(예: 좋은/나쁜 추천 구분)
- **(생성)** `build_dataset`로 학습 데이터셋 생성
- **(컴파일)** 모듈별 optimizer로 compile
- **(평가)** 오프라인 평가(히트율/정확도/다양성) → 개선 확인
- **(배포)** artifact를 서버에 반영(무중단 reload)

> 주의: DSPy compile은 최소 예시 수가 필요합니다(예: 2개 이상). 운영에서는 더 많은 샘플을 권장합니다.

---

## 5) Docker 이미지(로컬/배포 공용) + EKS 배포 고려사항

### 5-1) Dockerfile 위치
- 백엔드: `agent/Dockerfile`
- 프론트: `frontend/Dockerfile` (Next.js `output: standalone` 사용)

### 5-2) 이미지 빌드(레포 루트에서)
레포 루트(= `shopping_assistant/`)에서:

```bash
docker build -f agent/Dockerfile -t shopping-assistant-backend:local .
docker build -f frontend/Dockerfile -t shopping-assistant-frontend:local .
```

### 5-3) docker-compose 로컬 실행
레포 루트에서:

```bash
docker compose -f docker-compose.yml up --build
```

- 프론트: `http://localhost:3000`
- 백엔드: `http://localhost:8000`

### 5-4) EKS(Pod) 배포 시 핵심 포인트
- **환경변수/시크릿 주입**
  - AWS 자격증명, MCP URL, ADMIN 키 등은 **Secret/IRSA**로 주입(이미지에 포함 금지)
- **로그/데이터/아티팩트 영속화**
  - `AGENT_DATA_DIR`를 PV(EBS/EFS)로 마운트해 `chat.jsonl/feedback.jsonl/datasets`가 유지되게 구성
  - DSPy artifact도
    - (A) **이미지에 bake** 하거나
    - (B) `DSPY_ARTIFACTS_DIR`를 PV/ConfigMap으로 마운트해서 롤링 업데이트 없이 갱신
- **헬스체크**
  - liveness/readiness에 `/health` 사용 권장
- **스케일링**
  - 멀티턴 메모리는 현재 LangGraph MemorySaver(프로세스 메모리) 기반이므로,
    운영에서 백엔드를 여러 Pod로 스케일아웃하면 **세션 고정(Sticky)** 또는 외부 체크포인터(예: Redis/DB)로 전환이 필요합니다.
    (현재는 “로컬/단일 인스턴스”에 최적화)
- **CORS**
  - 도메인 배포 시 `FRONTEND_ORIGINS`를 실제 프론트 도메인으로 설정

---

## 참고
- 데모 UI 컨셉 참고: [TheGreatBonnie/CrewAI-Shopping-Assistant](https://github.com/TheGreatBonnie/CrewAI-Shopping-Assistant)

