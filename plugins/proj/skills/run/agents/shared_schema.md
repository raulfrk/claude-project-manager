# Shared Output Schema

All 6 preflight agents return the same JSON envelope:

```json
{
  "agent": "<agent_name>",
  "findings": [
    {
      "severity": "BLOCKING|WARNING|INFO",
      "title": "<short description>",
      "evidence": "<direct quote, file:line reference, or path list>",
      "suggested_fix": "<optional remediation>"
    }
  ]
}
```

Agents must emit valid JSON with no preamble or postamble. If no findings, return `{"agent": "<name>", "findings": []}`.
