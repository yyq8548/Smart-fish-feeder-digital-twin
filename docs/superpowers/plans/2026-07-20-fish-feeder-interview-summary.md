# Fish Feeder Interview Summary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create one English file that gives a spoken 60 to 90-second Fish Feeder introduction, a complete software engineering project narrative, and a behavioral interview evidence map.

**Architecture:** The deliverable is a standalone Markdown document grounded in current repository evidence. It has three parts: a brief spoken answer, a detailed first-person project summary, and a map from common behavioral questions to examples already explained in the summary.

**Tech Stack:** Markdown, PowerShell validation, Git

## Global Constraints

- Write in English only.
- Use first person for ownership and decisions.
- Keep language plain, specific, and comfortable to say aloud.
- Use only facts supported by the repository or confirmed by the project owner.
- Do not claim artificial intelligence, revenue, broad commercial scale, independent safety certification, or undocumented physical acceptance work.
- Use 91 Python tests and 34 dashboard tests when citing the current test suite.
- Do not use em dashes, en dashes, emojis, generic promotional claims, or placeholders.
- Run the Humanizer draft, audit, and final pass before completion.

---

### Task 1: Write and verify the interview summary

**Files:**
- Create: `docs/software_engineer_interview_summary.md`
- Reference: `README.md`
- Reference: `.github/workflows/ci.yml`
- Reference: `docs/architecture_v2.md`
- Reference: `docs/production_monitoring.md`
- Reference: `docs/backup_restore_drill.md`
- Reference: `docs/no_hardware_acceptance_drill.md`
- Reference: `docs/superpowers/specs/2026-07-20-fish-feeder-interview-summary-design.md`

**Interfaces:**
- Consumes: repository facts, owner-confirmed adoption facts, and the approved design specification
- Produces: `docs/software_engineer_interview_summary.md`, a standalone interview preparation document

- [ ] **Step 1: Build an evidence checklist from current files**

Run:

```powershell
rg -n "91 Python|34 dashboard|public VPS|WAL|busy timeout|five-minute|backup restore|HMAC|NVS|10 additional|remains in service" README.md docs .github
```

Expected: repository evidence for test counts, deployment, security, concurrency, monitoring, and recovery. Adoption facts about the original unit and 10 delivered units come from the project owner and must be labeled as owner-confirmed evidence.

- [ ] **Step 2: Draft the brief answer**

Create `docs/software_engineer_interview_summary.md` with a section named `## Brief answer`.

Content contract:

```text
Paragraph 1: personal problem and intended users
Paragraph 2: physical feeder plus cloud control architecture and personal ownership
Paragraph 3: hardest reliability or security decisions, test evidence, deployment, and result
```

Target 150 to 210 words. At a normal interview pace, this should take 60 to 90 seconds.

- [ ] **Step 3: Draft the complete project summary**

Add `## Complete project summary` with these exact subsections:

```text
### Why I built it
### Who used it and what problem it solved
### What I owned
### How the system works
### Command and telemetry flow
### Security and physical safety
### The SQLite concurrency problem
### Testing and CI
### Production deployment and operations
### Results, limitations, and lessons
### What I would build next
```

Explain decisions and consequences, not only tools. Include these verified facts where relevant:

```text
ESP32 feeder with DS18B20 temperature sensing, pump control, reverse cleaning, and cooling
FastAPI, SQLAlchemy, Alembic, SQLite, MQTT/TLS, Mosquitto, Docker Compose, Traefik
HMAC signatures, idempotency, expiration, event ordering, result retries, NVS replay protection
SQLite WAL, 10-second busy timeout, short write transactions, bounded lock retries
91 Python tests, 34 dashboard tests, six GitHub Actions jobs, browser-to-Wokwi validation
public VPS deployment, five-minute monitoring, Resend checks, isolated backup recovery drill
original unit in service and 10 additional units built and delivered
```

State current limits plainly: no AI feature, SQLite suits current scale but not large multi-tenant growth, and final physical acceptance depends on documented hardware testing.

- [ ] **Step 4: Add the behavioral interview map**

Add `## Behavioral interview map`. Use one compact table with columns `Question`, `Best example`, and `Point to emphasize`.

Include these prompts:

```text
Tell me about something you built.
Tell me about a difficult technical problem.
Tell me about a time you worked through ambiguity.
Tell me about a failure or risk you prevented.
Tell me about a security trade-off.
Tell me about a time you improved reliability.
Tell me about user feedback or impact.
Tell me about something you would do differently.
```

Each answer must point to evidence already covered in the complete summary. Do not create a new event or metric for the table.

- [ ] **Step 5: Run the Humanizer draft audit**

Review the draft for:

```text
generic significance claims
promotional language
tool inventories without decisions
repeated groups of three
uniform sentence rhythm
passive voice that hides ownership
generic upbeat conclusions
```

Rewrite flagged passages without removing facts. Keep technical documentation neutral and make spoken answers sound like one engineer explaining real work.

- [ ] **Step 6: Verify structure, timing, and forbidden patterns**

Run:

```powershell
$path = 'docs\software_engineer_interview_summary.md'
$content = Get-Content -Raw -Encoding utf8 -LiteralPath $path
$brief = [regex]::Match($content, '(?s)## Brief answer\s+(.*?)\s+## Complete project summary').Groups[1].Value
$words = ([regex]::Matches($brief, "\b[\w'-]+\b")).Count
Write-Output "BriefWords=$words"
if ($words -lt 150 -or $words -gt 210) { throw 'Brief answer must contain 150 to 210 words.' }
if ($content -match '\bTBD\b|\bTODO\b|<placeholder>|\[insert') { throw 'Placeholder found.' }
if ($content.Contains([char]0x2014) -or $content.Contains([char]0x2013) -or $content.Contains('Â')) { throw 'Forbidden dash or encoding artifact found.' }
```

Expected: `BriefWords` between 150 and 210, with no exception.

Run:

```powershell
rg -n "^## Brief answer$|^## Complete project summary$|^## Behavioral interview map$|^### " docs\software_engineer_interview_summary.md
git diff --check -- docs\software_engineer_interview_summary.md
```

Expected: all required headings found and no whitespace errors.

- [ ] **Step 7: Verify factual claims**

Read the final file beside the reference files. Confirm every number, deployed feature, and completed test has evidence. Confirm planned work is described as planned.

Run:

```powershell
rg -n -i "AI|revenue|customers|accuracy|latency|certified|production scale|100%" docs\software_engineer_interview_summary.md
```

Expected: no unsupported claim. Mentions of AI may appear only to state that the project does not use AI.

- [ ] **Step 8: Commit the finished document**

Run:

```bash
git add docs/software_engineer_interview_summary.md
git commit -m "Add Fish Feeder interview summary"
```

Expected: one commit containing only the finished interview summary.
