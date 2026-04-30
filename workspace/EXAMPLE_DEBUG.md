# 버그 분석 출력 예제

아래는 JSON 응답의 `"파일"` 값(Slack에 첨부되는 result.md)의 예시이다.
실제 분석 내용에 맞게 구조와 항목 모두 자유롭게 변형한다.

---

# {기능명} {에러코드} 버그 분석

## 분석 기준
- **레포**: mesher-labs/viv-monorepo @ main (브랜치: main)
- **분석 파일**: `server/src/draft/application/icon-generation/generate-icon.use-case.ts` L47–63

## 1. 증상 요약

| 항목 | 값 |
|------|----|
| Status | 502 |
| Error Code | `ICON_GENERATION_FAILED` |
| Message | `Gemini did not return an image (finishReason=content-filter)` |
| Endpoint | `POST /api/v1/drafts/:id/icon-generations` |

## 2. 근본 원인

드래프트의 사용자 입력 텍스트가 Gemini 이미지 생성 프롬프트에 그대로 주입되어 Safety Filter를 트리거함.

- `generate-icon.use-case.ts` L52에서 `draft.title + draft.description`을 프롬프트에 직접 포함
- Gemini가 `finishReason=content-filter`로 응답 시 fallback 없이 즉시 502 throw
- content-filter는 특정 사용자 콘텐츠에서 언제든 발생 가능한 known case임에도 서버 에러로 처리

```typescript
// generate-icon.use-case.ts L47–63 (문제 코드)
const prompt = `Create an icon for: ${draft.title}. ${draft.description}`;
const response = await this.geminiAdapter.generateImage(prompt);

if (!response.image || response.finishReason === 'content-filter') {
  throw new IconGenerationFailedError(
    `Gemini did not return an image (finishReason=${response.finishReason})`
  );  // ← fallback 없이 바로 502
}
```

## 3. 해결 방향

**Fix 1 — content-filter 시 generic 프롬프트로 재시도**
```typescript
if (response.finishReason === 'content-filter') {
  const fallback = await this.geminiAdapter.generateImage(
    `Create a simple icon for a ${draft.category} item`
  );
  if (!fallback.image) throw new IconGenerationFailedError(...);
  return fallback.image;
}
```

**Fix 2 — 에러 코드 분리 (content-filter는 클라이언트 책임)**
```typescript
// 502 대신 422로 반환
throw new HttpException({ error_code: 'ICON_CONTENT_FILTERED' }, 422);
```

## 4. 컨피던스

| 항목 | 컨피던스 | 근거 |
|------|---------|------|
| 원인 분석 (content-filter 트리거 경로) | 92% | 코드 L47–63 직접 확인 |
| 해결책 (fallback 재시도) | 85% | Gemini API 동작 검증 필요 |
