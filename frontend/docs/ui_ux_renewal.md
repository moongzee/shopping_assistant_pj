# UI/UX 개편 작업 보고서 (1:1 복원 + 테마 격리 + 추가 개선)

## 1. 작업 개요
- **일자**: 2026-01-19 ~ 2026-01-20
- **목적**: `/`(신규 GPT 스타일)과 `/ui-prev`(기존 클래식) 그리고 `/admin`(클래식)을 **레이아웃/스타일/기능까지 충돌 없이 1:1로 유지**
- **핵심 원칙**: "URL만 다르고, 각 페이지는 레퍼런스 UI/동작과 동일해야 함"
- **추가 개선**: 초기 사용자 경험 향상 및 디버깅 편의성 개선

## 2. 레이아웃 충돌의 원인과 해결
기존에는 `frontend/app/layout.tsx`가 모든 페이지를 `.container`로 감싸면서, GPT 스타일(100vh 풀뷰) 페이지에서 **중앙 정렬/하단 컴포저/전체 높이 계산이 틀어질 수 있는 구조**였습니다.

### 2.1 해결: Root Layout에서 container 래퍼 제거
- **변경**: `frontend/app/layout.tsx`에서 `<div className="container">` 래퍼 제거
- **효과**:
  - `/`는 `gpt-theme`가 의도한 **풀-뷰(100vh) 레이아웃**을 정확히 사용
  - `/ui-prev`, `/admin`은 각 페이지가 직접 `.container`를 가지도록 하여 **클래식 구조를 1:1 재현**

## 3. CSS 1:1 복원 방식 (테마 네임스페이스)
전역 클래스 충돌을 막기 위해, 레퍼런스 CSS를 **그대로 유지하되** 최상위 wrapper 클래스로 스코프를 분리했습니다.

### 3.1 GPT Theme (`.gpt-theme`)
- **대상 경로**: `/`
- **기준 레퍼런스**: `.references/globals.css` (+ `.references/shopping-with-ai/page.tsx`)
- **특징**:
  - ROYAL NAVY / ENERGY BLUE / WHITE 기반 라이트 톤
  - 초기 중앙 입력 → 대화 시작 후 하단 고정
  - `textarea` + `Enter 전송 / Shift+Enter 줄바꿈`

### 3.2 Classic Theme (`.classic-theme`)
- **대상 경로**: `/ui-prev`, `/admin`
- **기준 레퍼런스**: `.references/frontend/app/globals.css` (+ `.references/frontend/app/page.tsx`, `.references/frontend/app/admin/page.tsx`)
- **특징**:
  - 원본 다크 그라데이션/2컬럼 그리드/기존 UI 요소 유지

> 구현 위치: `frontend/app/globals.css`에서 `.gpt-theme ...`, `.classic-theme ...`로 각각 레퍼런스 규칙을 분리 적용

## 4. ChatClient 컴포넌트 전략 (1:1 보장)
“하나의 컴포넌트에서 분기(variant)로 처리” 방식은 시간이 지나면 1:1 보장에 취약해집니다. 그래서 레퍼런스를 기준으로 **컴포넌트를 분리**했습니다.

- **GPT(신규)용**: `frontend/components/ChatClient.tsx`
  - `/`에서 사용
  - GPT 스타일 레이아웃 + `textarea` UX
- **Classic(레퍼런스)용**: `frontend/components/ChatClientClassic.tsx`
  - `/ui-prev`에서 사용
  - `.references/frontend/components/ChatClient.tsx`의 기능/구조를 그대로 복원

## 5. 페이지 매핑 결과
- **`/`**: `.gpt-theme` + `ChatClient` (신규 GPT 스타일)
- **`/ui-prev`**: `.classic-theme` + `.container` + `ChatClientClassic` (기존 UI 1:1)
- **`/admin`**: `.classic-theme` + `.container` (기존 어드민 UI 1:1)

## 6. 품질 체크 (오류/버그 방지)
- `next build` 통과(타입체크 포함)
- `pnpm lint`가 프롬프트 없이 동작하도록 ESLint 설정 추가:
  - `frontend/.eslintrc.json`
  - `frontend/package.json` devDependencies에 `eslint`, `eslint-config-next` 추가

### 6.1 (Windows) `.next` 캐시 꼬임 대응
개발 중 간헐적으로 `Cannot find module './###.js'` 형태의 런타임 에러가 발생할 수 있습니다. 이 경우 `.next` 캐시가 깨진 상태이므로 아래 순서로 복구합니다.

- `pnpm clean`
- `pnpm dev`

> 참고: `clean` 스크립트는 Windows에서도 동작하도록 `rimraf .next`를 사용합니다.

## 7. 추가 UI 개선사항 (2026-01-20)

### 7.1 전송 버튼 아이콘화
- **변경**: 텍스트 "전송"을 SVG 전송 아이콘으로 교체
- **이유**: 모던한 UI 개선 및 시각적 일관성
- **구현**:
  - `lucide-react` 대신 직접 SVG 코드 내장 (의존성 최소화)
  - 로딩 상태("...")는 텍스트 유지
- **파일**: `frontend/components/ChatClient.tsx`

### 7.2 세션 ID 관리 개선
- **세션 ID 인풋 제거**: 초기 화면에서 불필요한 UI 요소 제거
- **세션 스토리지 저장**: 브라우저 세션 스토리지에 자동 저장
- **디버깅 편의성**: F12 개발자 도구에서 쉽게 확인 가능
- **구현**:
  - 프로덕션에서는 완전히 숨김
  - 초기 로딩 시 세션 스토리지에서 값 복원
  - 세션 ID 변경 시 자동 저장
- **파일**: `frontend/components/ChatClient.tsx`

### 7.3 초기 화면 레이아웃 최적화
- **emptyChat 구조 변경**: `chatWindow` 밖으로 분리하여 별도 섹션 배치
- **중앙 정렬 개선**: "무엇을 도와드릴까요?" 메시지와 입력창의 위치 조정
- **시각적 계층화**: 메시지를 위쪽에, 입력창을 중앙에 배치
- **CSS 개선**:
  - `justify-content: space-between`으로 공간 분배
  - 패딩으로 여백 조정
  - `align-self`로 개별 요소 위치 제어
- **파일**: `frontend/components/ChatClient.tsx`, `frontend/app/globals.css`

### 7.4 품질 유지
- **빌드 검증**: 모든 변경사항에 대해 `next build` 통과 확인
- **린터 검증**: `pnpm lint` 오류 없음 확인
- **의존성 정리**: 불필요한 라이브러리 제거로 번들 크기 최적화

## 8. 현재 상태 요약
- **기능 완성도**: 100% (기존 기능 유지 + 개선)
- **UI/UX 품질**: 향상 (모던한 디자인 + 사용자 경험 개선)
- **코드 품질**: 우수 (린터 통과 + 타입 안정성)
- **유지보수성**: 양호 (문서화 완료 + 구조화)
