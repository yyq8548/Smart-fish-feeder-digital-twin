# Fish Feeder software engineering interview summary design

## Goal

Create one English interview-preparation file that helps the project owner answer "Tell me about your fish feeder project" and reuse the same evidence in later behavioral interviews.

The writing must sound natural when spoken. It should explain engineering decisions without reading like a README, marketing page, or memorized script.

## Audience

The primary audience is a software engineer interviewer. Assume the interviewer understands APIs, databases, messaging, tests, and deployment but may not know aquarium hardware or embedded systems.

## Deliverable

Create `docs/software_engineer_interview_summary.md` with three sections.

### 1. Brief answer

A first-person answer that takes about 60 to 90 seconds to say aloud. It will cover:

- the unattended feeding problem;
- the physical feeder and cloud control system;
- the project owner's end-to-end responsibility;
- one or two hard engineering problems;
- evidence that the system was used and tested; and
- what the work demonstrates about the owner as a software engineer.

### 2. Complete project summary

A detailed first-person narrative organized under these headings:

1. Why I built it
2. Who used it and what problem it solved
3. What I owned
4. How the system works
5. How commands and telemetry move through the system
6. Security and physical safety decisions
7. The SQLite concurrency problem
8. Testing and CI
9. Production deployment and operations
10. Results, limitations, and lessons
11. What I would build next

The complete summary should remain readable aloud. Paragraphs should be short, and technical terms should appear only when they explain a decision or result.

### 3. Behavioral interview map

Map project evidence to common interview prompts:

- Tell me about something you built.
- Tell me about a difficult technical problem.
- Tell me about a time you worked through ambiguity.
- Tell me about a failure or risk you prevented.
- Tell me about a security trade-off.
- Tell me about a time you improved reliability.
- Tell me about user feedback or impact.
- Tell me about something you would do differently.

Each entry will identify the strongest example and the main point to emphasize. It will not duplicate the full answer or manufacture a separate story.

## Evidence rules

Use only facts supported by the repository or already confirmed by the project owner:

- the original physical feeder remains in service;
- 10 additional units were built and delivered to hobbyists;
- the dashboard is deployed on a public VPS;
- the system uses an ESP32, FastAPI, SQLite, MQTT/TLS, and Docker;
- the current automated suite includes 91 Python tests and 34 dashboard tests;
- GitHub Actions runs six jobs and includes browser-to-Wokwi validation;
- the platform has account verification, device claims, signed device messages, replay protection, monitoring, and tested backup recovery; and
- production verification found no database lock or HTTP 5xx errors during the recorded post-deployment observation.

Do not claim revenue, customer growth, measured time savings, artificial intelligence, independent safety certification, broad commercial scale, or completed physical acceptance work that has not been documented.

## Voice

- English only.
- First person where the speaker describes ownership or decisions.
- Plain technical language.
- Mixed sentence length so the answer sounds spoken rather than generated.
- No promotional claims, generic conclusions, emojis, em dashes, or en dashes.
- No dense inventory of tools when a shorter explanation carries the same meaning.

## Validation

Before completion:

1. Verify every number and feature against current repository files.
2. Confirm that the brief answer can be read aloud in 60 to 90 seconds.
3. Scan for unsupported claims and planned work stated as complete.
4. Run the Humanizer draft, audit, and final pass.
5. Scan the final file for em dashes, en dashes, placeholders, and encoding artifacts.
6. Confirm that the behavioral map points to evidence already explained in the complete summary.
