# Sample Input Data for AI Project Data Assistant

This directory contains realistic sample data representing what would be indexed from Newforma Project Center (NPC). The data covers 8 construction projects across multiple record types.

## Files

| File | Records | Description |
|------|---------|-------------|
| `projects.csv` | 8 | Project metadata (name, location, type, value, dates, key parties) |
| `contacts.csv` | 22 | Project team contacts (name, company, role, project assignment) |
| `rfis.csv` | 21 | Requests for Information (questions, responses, status tracking) |
| `submittals.csv` | 16 | Material/equipment submittals (specs, review status, vendors) |
| `transmittals.csv` | 12 | Document transmittals (drawing packages, reports, correspondence) |
| `meeting_minutes.csv` | 8 | OAC and progress meeting records (topics, action items, attendees) |

## Projects Included

1. **Harbor Bridge Reconstruction** (PROJ-001) — Infrastructure, $12.5M, Active
2. **Downtown Tower Office Complex** (PROJ-002) — Commercial, $45M, Active
3. **Riverside Community Center** (PROJ-003) — Civic, $8.5M, Completed
4. **Eastside Medical Pavilion** (PROJ-004) — Healthcare, $22M, Active
5. **Waterfront Mixed-Use Development** (PROJ-005) — Mixed-Use, $67M, Active
6. **Lincoln High School Renovation** (PROJ-006) — Education, $18.5M, Active
7. **Airport Terminal C Expansion** (PROJ-007) — Aviation, $95M, Active
8. **Cedar Hills Water Treatment Plant** (PROJ-008) — Utilities, $31M, Active

## Key Contractors (Cross-Project)

| Contractor | Projects | Role |
|---|---|---|
| Acme Construction | PROJ-001, 002, 003, 006 | General Contractor |
| Pacific Builders Inc | PROJ-004, 008 | General Contractor |
| Pacific Mechanical | PROJ-002, 003 | Mechanical Subcontractor |
| Structural Engineering Inc. | PROJ-001 | Structural Engineer |
| Turner-Pacific JV | PROJ-005 | General Contractor |
| Kiewit-Hoffman JV | PROJ-007 | General Contractor |

## Data Characteristics

- **Total records:** 87 across all types
- **Date range:** 2021–2026
- **Location:** Portland, OR metro area
- **Project types:** Infrastructure, Commercial, Civic, Healthcare, Mixed-Use, Education, Aviation, Utilities
- **Contract values:** $8.5M – $95M
- **RFI categories:** Structural, Electrical, Mechanical, Architectural, Fire Protection, Environmental, Specialty, Process
- **Submittal statuses:** Approved, Approved with Comments, Under Review, Pending

## Sample Questions This Data Supports

- "Which contractors have we used in the last 5 years?"
- "Show me all open RFIs for the Harbor Bridge project"
- "What are the most common RFI categories across all projects?"
- "Give me a summary of the Downtown Tower project"
- "Which vendors have we used for structural steel?"
- "What projects has Acme Construction worked on?"
- "Show me all pending submittals"
- "What were the action items from the last Harbor Bridge meeting?"
- "How many projects are in Portland?"
- "What's the total contract value of all active projects?"
