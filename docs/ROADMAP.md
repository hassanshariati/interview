# Delivery Roadmap

- **Milestone 0 — starter (this ZIP):** job creation, CV parsing, keyword evidence, manual report JSON, optional unsaved voice demo.
- **Milestone 1 — production foundations:** OAuth/OIDC, RBAC, tenants, encrypted object storage, audit, migration tooling, validation and scanning.
- **Milestone 2 — stronger CV intelligence:** multilingual structured extraction, OCR, versioned ontology and human-reviewed matching. Never auto-reject.
- **Milestone 3 — scheduling:** email and calendar OAuth, invitations, timezone-aware slot bookings, reminders and rescheduling.
- **Milestone 4 — full voice interviews:** candidate-specific links, approved question plans, consent, adaptive conversation, transcript and reconnection.
- **Milestone 5 — evidence-grounded report:** rubric-based scoring with timestamps and reviewer override, PDF report; assess fairness and accuracy.
- **Milestone 6 — deployment and validation:** load, privacy, accessibility, availability, data protection, monitoring, backups and Kubernetes.

Acceptance tests for production must include: candidate accent and disability fairness, microphone failure, API outage, email replay, calendar race, ambiguous CV entries, contradictory answers, and partial transcript coverage.
