# Sample Data for AI Code Compliance Analyzer

This directory contains realistic sample data for testing an AI-powered code compliance assistant that analyzes project documents against building codes and regulations.

## Directory Structure

```
sample-data/
├── codes/                                    # Code and regulation excerpts
│   ├── ibc-2021-excerpts.json               # International Building Code (14 sections)
│   ├── ifc-2021-excerpts.json               # International Fire Code (10 sections)
│   ├── ada-2010-excerpts.json               # ADA Accessibility Standards (13 sections)
│   └── energy-code-excerpts.json            # ASHRAE 90.1-2019 Energy Code (8 sections)
├── project-documents/                        # Project documents to analyze
│   ├── downtown-tower-code-analysis.json    # 25-story office tower (7 known issues)
│   ├── eastside-medical-code-analysis.json  # 3-story medical building (7 known issues)
│   └── waterfront-residential-code-analysis.json  # 12-story mixed-use (9 known issues)
└── README.md
```

## Codes & Regulations Included

| Code | Sections | Key Topics |
|------|----------|------------|
| IBC 2021 | 14 | Occupancy separation, egress, corridors, sprinklers, building height, door sizes |
| IFC 2021 | 10 | Fuel storage limits, fire alarm, sprinklers, generator rooms, fire command center |
| ADA 2010 | 13 | Door clearances, ramp slopes, restrooms, parking, elevators, signage |
| ASHRAE 90.1-2019 | 8 | Roof/wall insulation, fenestration, lighting power density, HVAC efficiency |

## Project Documents (with Intentional Compliance Issues)

### Downtown Tower Office Complex (PROJ-002)
- 25-story Type IIA office tower with retail and parking
- **7 known issues** including height/construction type limits, egress width, parking accessibility
- Tests: IBC height tables, egress calculations, ADA parking, fire command center requirement

### Eastside Medical Pavilion (PROJ-004)
- 3-story medical building with surgery suite and imaging
- **7 known issues** including fuel storage code violation, I-2 occupancy requirements
- Tests: IFC fuel storage limits, healthcare occupancy requirements, ADA medical facility compliance

### Waterfront Mixed-Use Development (PROJ-005)
- 12-story residential with retail, parking, and community room
- **9 known issues** including STC non-compliance, parking count, window-to-wall ratio
- Tests: Sound transmission, ADA unit requirements, energy code, assembly occupancy

## Compliance Issue Severity Levels

The known issues span different severity levels for testing risk scoring:

| Severity | Example Issues |
|----------|---------------|
| **Critical** | Generator fuel exceeds IFC limit (PROJ-004), STC non-compliant (PROJ-005) |
| **High** | Accessible parking count wrong (PROJ-005), window-to-wall ratio exceeds prescriptive (PROJ-002, 005) |
| **Medium** | Fire command center needed (PROJ-002), single stair to basement (PROJ-004) |
| **Low** | Signage not yet verified, corridor width exceeds minimum |

## Test Scenarios

### 1. Single-Code Analysis
- Run IBC analysis on Downtown Tower → should flag height/type, egress width, occupancy separation
- Run ADA analysis on Waterfront → should flag parking count, unit door clearance
- Run IFC analysis on Eastside Medical → should flag fuel storage violation

### 2. Multi-Code Analysis
- Run all codes against Waterfront → should produce 9+ findings across IBC, ADA, energy, and sound
- Run IBC + IFC against Eastside Medical → should flag both occupancy separation and fuel storage

### 3. Severity Scoring
- Generator fuel violation should score Critical (permit risk, code violation)
- STC non-compliance should score Critical (requires rework of 200 units)
- Signage verification should score Low (documentation gap, not a violation)

### 4. Actionable Outputs
- Fuel storage finding → should recommend generating an RFI with options (reduce tank, relocate, H-3 classification)
- STC finding → should recommend generating an RFI for wall assembly modification
- Parking count → should recommend updating site plan (simple fix)

### 5. Cross-Reference Detection
- Downtown Tower stair width → AI should calculate: 155 occupants × 0.3 in/occupant = 46.5 inches required. 56 inches provided. PASS.
- Waterfront retail exits → AI should calculate: 1000 occupants requires 4 exits per Table 1006.2.1. Only 3 stairs serve retail. POTENTIAL ISSUE.
- Eastside Medical parking → AI should verify: 120 spaces requires 5 accessible per Table 208.2. 5 provided. PASS.

## Data Design Principles

1. **Mix of pass/fail** — not everything is non-compliant; the AI should correctly identify both
2. **Varying complexity** — from simple lookups (parking count) to multi-step calculations (egress width)
3. **Cross-code interactions** — some issues involve multiple codes (e.g., fuel storage is both IFC and IBC)
4. **Real-world ambiguity** — some items are "not yet verified" rather than clearly pass/fail
5. **Actionable findings** — each issue has a clear path to resolution (RFI, design change, documentation)
6. **Multiple disciplines** — structural, architectural, mechanical, electrical, fire protection, accessibility
