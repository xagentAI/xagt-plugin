# Verification evidence

## Prerequisites

- Review commit: `a4b5d3d`
- API base URL: `https://code-review-agent-ashy-six.vercel.app/v1`
- Authentication: none

## 1. Health check

```bash
curl --fail --silent --show-error https://code-review-agent-ashy-six.vercel.app/health
```

Expected response:

```json
{"status":"ok","commit":"a4b5d3d"}
```

## 2. Deployment proof

```bash
curl --fail --silent --show-error https://code-review-agent-ashy-six.vercel.app/.well-known/xagent-verification.json
```

Expected response:

```json
{"schemaVersion":1,"slug":"kestarsheng-code-review-agent","commit":"a4b5d3d"}
```

## 3. Capability call

```bash
curl --fail --silent --show-error \
  --request POST https://code-review-agent-ashy-six.vercel.app/v1/review \
  --header "content-type: application/json" \
  --data '{"code":"def f(x):\n    return x / 0","language":"python"}'
```

Expected success response (abridged):

```json
{
  "ok": true,
  "language": "python",
  "model": "deepseek-chat",
  "report": {
    "summary": "...",
    "score": 30,
    "grade": "D",
    "issues": [
      {
        "severity": "critical",
        "category": "correctness",
        "line": 2,
        "title": "除零错误",
        "description": "...",
        "suggestion": "..."
      }
    ],
    "strengths": ["..."],
    "improvements": ["..."]
  }
}
```

## 4. Safe error behavior

Empty body:

```bash
curl --fail --silent --show-error \
  --request POST https://code-review-agent-ashy-six.vercel.app/v1/review \
  --header "content-type: application/json" \
  --data '{}'
```

Expected: HTTP 422 with `{"ok":false,"error":...}`.

Oversized code (> 60 000 chars): HTTP 413.
LLM provider failure: HTTP 502 with `{"ok":false,"error":"LLM 调用失败: ..."}`.