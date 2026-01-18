# Agent API 정의서 (FastAPI + LangGraph + DSPy)

본 문서는 `agent/` 백엔드의 HTTP API를 사람이 읽기 좋게 정리한 **API 정의서**입니다.  
실제 OpenAPI 스펙/Swagger UI는 서버 실행 후 `GET /docs` 에서 확인할 수 있습니다.

---

## 공통

- **Base URL (local)**: `http://127.0.0.1:8000`
- **Content-Type**: JSON 요청은 `application/json`
- **응답 인코딩**: UTF-8

### 스트리밍 관련 환경변수(요약)
- `STREAM_CHUNK_CHARS` (기본 24): `token.delta`를 몇 글자 단위로 쪼개서 보낼지
- `STREAM_DELAY_MS` (기본 15): `token` 이벤트 사이에 인위적으로 딜레이를 줄지(“타이핑처럼” 보이게)

### 인증(관리자 API)

관리자 API는 선택적으로 헤더 키로 보호됩니다.

- **Header**: `x-admin-key: <ADMIN_API_KEY>`
- 백엔드 환경변수 `ADMIN_API_KEY`가 **비어있지 않으면** 위 헤더가 없거나 값이 틀릴 때 `401`을 반환합니다.

---

## 1) Health / Debug

### 1.1 Health Check

- **GET** `/health`
- **Response 200**

```json
{ "ok": true }
```

### 1.2 Debug Env (마스킹)

- **GET** `/debug/env`
- **Response 200**
- `.env` 로드 결과와 일부 환경변수를 **마스킹**해서 보여줍니다.

```json
{
  "loaded_dotenv_files": [".../agent/.env", ".../.env"],
  "settings": {
    "dspy_model": "...",
    "mcp_snowflake_url": "...",
    "mcp_cortex_analyst_url": "...",
    "mcp_cortex_search_service_name": "...",
    "memory_max_turns": 6,
    "stream_chunk_chars": 24,
    "stream_delay_ms": 15,
    "dspy_artifacts_dir": "agent/artifacts"
  },
  "aws_env_present": {
    "AWS_REGION": "ap-northeast-2",
    "AWS_ACCESS_KEY_ID": "AKIA************ABCD",
    "AWS_SECRET_ACCESS_KEY": true,
    "AWS_SESSION_TOKEN": false
  }
}
```

---

## 2) Chat (SSE Streaming)

### 2.1 채팅 스트리밍

- **POST** `/v1/chat/stream`
- **Response 200**: `text/event-stream`
- LangGraph 노드 진행(`state`) + LLM 텍스트 델타(`token`) + 최종 메타(`final`)를 **SSE**로 전달합니다.

#### Response Headers (중요)
스트리밍/프록시 버퍼링을 줄이기 위해 아래 헤더를 포함합니다.

- `Cache-Control: no-cache, no-transform`
- `Connection: keep-alive`
- `X-Accel-Buffering: no`

#### Request Body

```json
{
  "session_id": "demo-session",
  "user_query": "로엠 따뜻하고 편한 기모 긴팔 추천해줘",
  "client_message_id": "optional-client-id"
}
```

- **session_id**: 멀티턴 메모리 분리 키 (LangGraph `thread_id`)
- **user_query**: 사용자 입력
- **client_message_id**: 옵션. 없으면 서버가 UUID 생성

#### SSE Event 종류

아래 이벤트들이 순서대로(또는 중간에 `error`) 스트리밍됩니다.

##### (1) `start`

```json
{ "session_id": "demo-session", "message_id": "uuid" }
```

##### (2) `state`

LangGraph 노드 실행 단계 표시.

```json
{
  "session_id": "demo-session",
  "message_id": "uuid",
  "node": "intent_agent",
  "update_keys": ["messages", "sql_constraints", "rag_keywords"]
}
```

##### (3) `token`

LLM 텍스트를 chunk 단위로 전달합니다.
클라이언트는 `delta`를 **도착 순서대로 그대로 이어붙이면** 최종 응답이 됩니다.

> 참고: 서버는 UI에서 “스트리밍처럼” 보이도록 `STREAM_CHUNK_CHARS`/`STREAM_DELAY_MS` 설정에 따라
> Bedrock에서 받은 델타를 더 작은 조각으로 나눠서 보낼 수 있습니다.

```json
{
  "session_id": "demo-session",
  "message_id": "uuid",
  "delta": "부분 문자열..."
}
```

##### (4) `final`

UI 카드 렌더링용 메타 포함(중요).

```json
{
  "session_id": "demo-session",
  "message_id": "uuid",
  "elapsed_ms": 12345,
  "recommended_products": [{ "...": "..." }],
  "grouped_recommended_products": { "상의": [{ "...": "..." }] },
  "recommended_style_codes": ["STYLE_CODE_1", "STYLE_CODE_2"]
}
```

#### `recommended_products` / `grouped_recommended_products` 상세 정의 (중요)

프론트의 “오른쪽 카드 UI”는 아래 2개 필드를 사용합니다.

- **`recommended_products`**: 카드 렌더링을 위한 “평탄화(flat) 리스트”
  - 타입: `Array<Product>`
  - 의미: 최종 추천 상품 목록(최대 30개 권장). **표시 순서 = 추천 순서**입니다.
  - 주의: 데이터 소스(정형 DB) 컬럼 스키마에 따라 추가 키가 포함될 수 있습니다.

- **`grouped_recommended_products`**: 카테고리별 그룹핑 된 “딕셔너리”
  - 타입: `Record<string, Array<Product>>`
  - 의미: `category`(또는 `subcategory`) 기준으로 묶은 추천 상품들.
  - **각 그룹 내부의 순서**는 `recommended_products`에서의 순서를 보존합니다.
  - 프론트는 이 값이 비어있을 때 `recommended_products`를 기준으로 클라이언트에서 그룹핑 fallback이 가능합니다.

##### Product 스키마(최소 필드)

`Product`는 최소한 아래 필드들을 포함하는 것을 목표로 합니다(일부는 null/빈값일 수 있음).

| 필드 | 타입 | 설명 |
|---|---|---|
| `style_code` | `string` | 상품 식별 스타일코드(피드백/학습 라벨 키) |
| `product_name` | `string` | 상품명 |
| `brand` | `string` | 브랜드 |
| `category` | `string` | 대분류(예: 상의/아우터/바지/원피스 등) |
| `subcategory` | `string` | 소분류(예: 긴소매 티셔츠 등) |
| `price` | `string \| number` | 가격(원본 스키마 유지) |
| `material` | `string` | 소재/특징 |
| `image_url` | `string` | 이미지 URL(있으면 카드 썸네일 렌더링) |
| `url` | `string` | 상품 상세 링크 |

> 참고: 데이터 소스에 따라 `STYLE_CODE`, `PRODUCT_NAME`, `IMAGE_URL`, `URL` 등 대문자 키가 포함될 수도 있습니다.  
> 현재 프론트는 `style_code/STYLE_CODE`, `product_name/PRODUCT_NAME`, `image_url/IMAGE_URL`, `url/URL` 등을 fallback으로 읽습니다.

##### `final` 예시(카드 렌더링용)

```json
{
  "session_id": "demo-session",
  "message_id": "uuid",
  "elapsed_ms": 12345,
  "recommended_style_codes": ["RMLWF4TR14", "RMCKF49R98"],
  "recommended_products": [
    {
      "style_code": "RMLWF4TR14",
      "brand": "로엠",
      "category": "상의",
      "subcategory": "긴소매 티셔츠",
      "product_name": "올데이티셔츠 터틀넥 티셔츠_RMLWF4TR14",
      "material": "면48%,리오셀48%,스판덱스4%",
      "price": "19900",
      "image_url": "https://.../image.jpg",
      "url": "https://www.musinsa.com/products/5493539"
    }
  ],
  "grouped_recommended_products": {
    "상의": [
      {
        "style_code": "RMLWF4TR14",
        "brand": "로엠",
        "category": "상의",
        "subcategory": "긴소매 티셔츠",
        "product_name": "올데이티셔츠 터틀넥 티셔츠_RMLWF4TR14",
        "material": "면48%,리오셀48%,스판덱스4%",
        "price": "19900",
        "image_url": "https://.../image.jpg",
        "url": "https://www.musinsa.com/products/5493539"
      }
    ]
  }
}
```

#### (옵션) 디버그 메타
학습/디버깅을 위한 메타는 서버 내부 로그(`agent/data/logs/chat.jsonl`)에만 저장됩니다.

##### (5) `done`

```json
{ "session_id": "demo-session", "message_id": "uuid" }
```

##### (예외) `error`

그래프 실행 중 예외 발생 시, 스트림이 끊기지 않도록 error 이벤트를 보냅니다.

```json
{
  "session_id": "demo-session",
  "message_id": "uuid",
  "error": "error message",
  "error_type": "ExceptionName"
}
```

#### cURL 예시

```bash
curl -N -X POST "http://127.0.0.1:8000/v1/chat/stream" \
  -H "Content-Type: application/json" \
  -d '{"session_id":"demo-session","user_query":"로엠 따뜻하고 편한 기모 긴팔 추천해줘"}'
```

---

## 3) Feedback (학습 데이터)

### 3.1 피드백 저장

- **POST** `/v1/feedback`
- **Response 200**

#### Request Body

```json
{
  "session_id": "demo-session",
  "message_id": "uuid-from-start-event",
  "rating": 5,
  "selected_style_codes": ["RMKAF4TR02"],
  "notes": "optional"
}
```

#### Response 200

```json
{ "ok": true }
```

---

## 4) Admin: Artifacts / Logs / Training Jobs

> 아래 엔드포인트들은 `ADMIN_API_KEY` 설정 시 `x-admin-key` 헤더가 필요합니다.

### 4.1 Artifacts Reload (무중단)

- **POST** `/admin/reload_artifacts`
- **Response 200**

```json
{
  "ok": true,
  "result": {
    "artifacts_dir": "agent/artifacts",
    "files": {
      "relaxed_constraints": ".../relaxed_constraints.json",
      "product_ranker": ".../product_ranker.json",
      "fusion_decision": ".../fusion_decision.json"
    }
  }
}
```

### 4.2 Logs (tail)

#### 4.2.1 Chat Logs
- **GET** `/admin/logs/chat?limit=200`

#### 4.2.2 Feedback Logs
- **GET** `/admin/logs/feedback?limit=200`

응답 포맷:

```json
{ "ok": true, "path": "agent/data/logs/chat.jsonl", "rows": [ { "...": "..." } ] }
```

### 4.3 Dataset Build (로그/피드백 → 학습용 jsonl)

- **POST** `/admin/datasets/build`

#### Request Body

```json
{
  "chat_log": "agent/data/logs/chat.jsonl",
  "feedback_log": "agent/data/logs/feedback.jsonl",
  "out_ranker": "agent/data/datasets/ranker.jsonl",
  "out_relax": "agent/data/datasets/relaxed_constraints.jsonl",
  "out_fusion": "agent/data/datasets/fusion.jsonl",
  "async_run": true
}
```

#### Response (async_run=true)

```json
{ "ok": true, "job_id": "uuid" }
```

#### Response (async_run=false)

```json
{
  "ok": true,
  "result": {
    "ranker_examples": 10,
    "relax_examples": 20,
    "fusion_examples": 8,
    "out_ranker": "agent/data/datasets/ranker.jsonl",
    "out_relax": "agent/data/datasets/relaxed_constraints.jsonl",
    "out_fusion": "agent/data/datasets/fusion.jsonl"
  }
}
```

### 4.4 DSPy Compile (학습/최적화) + (옵션) reload

- **POST** `/admin/compile`

#### Request Body

```json
{
  "module": "product_ranker",
  "dataset": "agent/data/datasets/ranker.jsonl",
  "out": "agent/artifacts/product_ranker.json",
  "reload_artifacts": true,
  "async_run": true
}
```

- **module**: `relaxed_constraints | product_ranker | fusion_decision`
- **reload_artifacts**: 컴파일 성공 후 서버에 즉시 반영할지 여부

#### Response (async_run=true)

```json
{ "ok": true, "job_id": "uuid" }
```

### 4.5 Job Status

- **GET** `/admin/jobs/{job_id}`

#### Response 200

```json
{
  "ok": true,
  "job_id": "uuid",
  "status": "queued|running|done|error",
  "result": { "...": "..." },
  "error": "optional"
}
```

---

## 5) 주요 데이터 모델(요약)

### recommended_products 아이템(예시)

`recommended_products`의 각 아이템은 DB/수집원에 따라 키가 더 있을 수 있으며, 최소한 아래 키들을 기대합니다.

```json
{
  "style_code": "RMKAF4TR02",
  "brand": "로엠",
  "category": "상의",
  "subcategory": "긴소매 티셔츠",
  "product_name": "상품명",
  "material": "면...",
  "price": "19900",
  "url": "https://..."
}
```

