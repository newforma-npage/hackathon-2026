# Sample Data for AI RFI Workflow Assistant

This directory contains realistic sample data for testing an AI-powered RFI assistant that handles the full RFI lifecycle: intake, analysis, coordination, and response drafting.

## Directory Structure

```
sample-data/
├── rfis/                    # 10 RFIs at various stages and complexity levels
│   ├── rfi-101.json         # Structural connection conflict (Downtown Tower)
│   ├── rfi-102.json         # PT tendon vs drainage conflict (Harbor Bridge) - CRITICAL
│   ├── rfi-103.json         # MRI door size and shielding (Eastside Medical)
│   ├── rfi-104.json         # Kitchen exhaust fire rating (Waterfront Mixed-Use)
│   ├── rfi-105.json         # Concealed structural damage (Lincoln HS) - UNFORESEEN
│   ├── rfi-106.json         # Valve actuator power discrepancy (Cedar Hills WTP)
│   ├── rfi-107.json         # TSA checkpoint vs columns (Airport Terminal C) - COMPLEX
│   ├── rfi-108.json         # Lobby tile pattern clarification (Downtown Tower) - SIMPLE/CLOSED
│   ├── rfi-109.json         # Ceiling plenum depth insufficient (Downtown Tower) - BIM CLASH
│   └── rfi-110.json         # Generator fuel code violation (Eastside Medical) - CODE COMPLIANCE
├── prior-rfis/              # Historical RFI responses for RAG context
│   └── prior-rfi-responses.json
├── specs/                   # Specification excerpts referenced by RFIs
│   └── spec-excerpts.json
└── README.md
```

## RFI Variety Matrix

The 10 RFIs are designed to test different aspects of the AI assistant:

| RFI | Complexity | Discipline | Test Focus |
|-----|-----------|-----------|------------|
| RFI-101 | Medium | Structural | Drawing conflict detection, connection design |
| RFI-102 | High | Structural/Civil | Multi-discipline conflict, critical path impact |
| RFI-103 | Medium | Specialty/Medical | Equipment coordination, temporary conditions |
| RFI-104 | High | Arch/Mechanical | Code interpretation, fire rating, 200-unit impact |
| RFI-105 | High | Arch/Historic | Unforeseen condition, change order justification |
| RFI-106 | Medium | Electrical/Process | Spec vs drawing discrepancy, system-wide impact |
| RFI-107 | Very High | Multi-discipline | TSA coordination, structural redesign, 3 options |
| RFI-108 | Low | Architectural | Simple clarification (already closed with response) |
| RFI-109 | High | MEP Coordination | BIM clash detection, 47 clashes, 4 options |
| RFI-110 | Critical | Code Compliance | Fire code violation, permit risk, 5 options |

## AI Assistant Test Scenarios

### 1. Automated Intake & Classification
- **Simple:** RFI-108 (tile pattern) — should classify as "clarification", low priority
- **Complex:** RFI-107 (TSA checkpoint) — should classify as "multi-discipline conflict", high priority, multiple stakeholders
- **Urgent:** RFI-110 (fuel code) — should flag as "code compliance violation", critical, permit risk

### 2. Document Intelligence & Conflict Detection
- **Drawing conflict:** RFI-101 (S-501 vs S-301 connection details)
- **Cross-discipline conflict:** RFI-102 (PT tendon profile vs drainage scuppers)
- **Spec vs drawing:** RFI-106 (electrical drawings vs valve spec)
- **BIM clash:** RFI-109 (Navisworks clash report, 47 hard clashes)

### 3. Workflow Guidance & Recommendations
- **Respond directly:** RFI-108 (simple clarification, precedent exists)
- **Escalate to structural:** RFI-101, RFI-102, RFI-105
- **Coordinate with owner:** RFI-107 (TSA), RFI-110 (Providence Health requirements)
- **Code research needed:** RFI-104 (IMC 506.3.2), RFI-110 (IFC 5704.3.3.4)
- **Change order potential:** RFI-105 (unforeseen condition), RFI-107 (structural redesign)

### 4. Draft Response Generation
- **RFI-108** has a complete response — use as a training example for tone/format
- **RFI-101** — AI should reference spec section 05 12 00 paragraph 1.5.A ("structural drawings govern")
- **RFI-106** — AI should identify the systemic issue (4 additional valves with same problem)
- **RFI-110** — AI should present options with pros/cons and recommend Option 4

### 5. Conversational Follow-ups
Test questions the AI should handle:
- "Is RFI-102 a design conflict or a coordination issue?"
- "Will RFI-107 require a change order?"
- "What's the cost impact of RFI-109 Option 2 (drop ceiling 6 inches)?"
- "Has this type of issue come up before on other projects?" (should find prior RFIs)
- "What's the code reference for the fuel storage limit in RFI-110?"
- "Can we use the same beam penetration approach from RFI-007 for RFI-109?"

## Data Characteristics

- **Projects covered:** 6 (Harbor Bridge, Downtown Tower, Eastside Medical, Waterfront, Lincoln HS, Airport Terminal C, Cedar Hills WTP)
- **Disciplines:** Structural, Architectural, Mechanical, Electrical, Process, Specialty/Medical, Code Compliance, Historic
- **Priorities:** Critical (2), High (5), Medium (2), Low (1)
- **Statuses:** Open (9), Closed (1 — with response for reference)
- **Complexity range:** Simple clarification to multi-discipline redesign
- **Cost impacts:** None to High (structural redesign)
- **Schedule impacts:** None to 6 weeks
- **Attachments referenced:** Drawings, specs, vendor docs, photos, code references, markups, calculations
- **Cross-references:** RFIs reference each other and prior responses

## Supporting Data

### Prior RFI Responses (`prior-rfis/`)
5 historical RFI responses that provide context for the AI:
- Establishes precedents (beam penetration criteria, change order approach)
- Shows response format and tone
- Enables "has this come up before?" queries

### Specification Excerpts (`specs/`)
6 spec sections with relevant paragraphs that the AI should reference when analyzing RFIs:
- Post-tensioning (03 38 00)
- Structural steel (05 12 00)
- RF shielding (13 49 00)
- HVAC ducts (23 31 00)
- Valve actuators (40 05 23.13)
- Generator assemblies (26 32 00)
