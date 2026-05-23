# Meridian Phase 2 and 3 Implementation Notes

## Phase 2 — Intelligent Layer

Implemented:

- LLM tool-planner hook in `backend/core/tools.py`
- Router integration with safe keyword fallback
- Response artifact contract:
  - table artifacts
  - chart artifacts
  - document artifacts
  - follow-up suggestion pills
- Chat UI rendering for artifacts
- Session-scoped uploaded-file retrieval for follow-up questions

Runtime notes:

- `PERSONAL_OS_LLM_ROUTER=auto` uses the LLM planner when Groq is configured.
- `PERSONAL_OS_LLM_ROUTER=false` forces deterministic routing.
- If the model planner fails, the old keyword router is used.

## Phase 3 — Proactive Intelligence

Implemented:

- Proactive notification table
- Pattern detection engine:
  - low job response rate
  - stale job applications
  - budget spikes
  - upcoming deadlines
  - learning gaps from saved jobs
- Morning briefing endpoint
- Dashboard notification cards
- Dismissable notification backend
- Scheduled task CRUD
- Natural-language schedule requests create persisted scheduled tasks

Endpoints:

- `GET /api/proactive/notifications`
- `POST /api/proactive/notifications/{id}/dismiss`
- `POST /api/proactive/run`
- `GET /api/proactive/briefing`
- `GET /api/scheduled-tasks`
- `POST /api/scheduled-tasks`
- `PUT /api/scheduled-tasks/{id}`
- `DELETE /api/scheduled-tasks/{id}`

Still future work:

- Actual background cron runner for scheduled tasks
- Email delivery through SendGrid
- Email-agent auto status update from inbox replies
- Push notifications/mobile delivery
