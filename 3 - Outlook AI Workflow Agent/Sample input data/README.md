# Sample Email Data for AI Email Workflow Agent

This directory contains 15 realistic construction industry emails in `.eml` format, representing the types of emails that would flow through an Outlook inbox in an AEC (Architecture, Engineering, Construction) environment.

## Email Classification Guide

The AI agent should be able to classify these emails into the following categories:

| Email | Subject | Expected Classification | Project |
|-------|---------|------------------------|---------|
| email-001 | RFI #003 - Bearing Pad Material Substitution | **RFI** | Harbor Bridge |
| email-002 | Submittal - Curtain Wall System Kawneer 1600 | **Submittal** | Downtown Tower |
| email-003 | RE: Duct Conflicts Floors 15-20 | **Correspondence** (coordination) | Downtown Tower |
| email-004 | Night Work Permit Extension Request | **Correspondence** (permit/approval) | Harbor Bridge |
| email-005 | Monthly Progress Report April 2024 | **Correspondence** (report) | Downtown Tower |
| email-006 | Revised Imaging Suite Shielding Specs | **RFI Response / ASI** | Eastside Medical |
| email-007 | RE: Conduit Installation Phase 2 Schedule | **Correspondence** (schedule) + **Submittal** | Harbor Bridge |
| email-008 | Warranty Item: Pool Heater Malfunction | **Correspondence** (warranty) | Riverside Community |
| email-009 | RFI #020 - Jet Bridge Connection Elevation | **RFI** | Airport Terminal C |
| email-010 | Residential Unit STC Testing Results | **RFI Response** (test results) | Waterfront Mixed-Use |
| email-011 | Phase 2 Abatement Plan Submittal | **Submittal** | Lincoln High School |
| email-012 | Membrane System Chemical Feed Coordination | **RFI** (coordination) | Cedar Hills WTP |
| email-013 | Order Confirmation - W24x76 Grade A992 | **Correspondence** (procurement) | Harbor Bridge |
| email-014 | RE: Pool Heater Warranty Service | **Correspondence** (warranty resolution) | Riverside Community |
| email-015 | ASI-016 - Revised Rebar Splice Locations | **ASI / Design Change** | Harbor Bridge |

## Classification Categories

- **RFI** — Request for Information: questions requiring design team response
- **Submittal** — Material/equipment submittals for review and approval
- **ASI** — Architect's Supplemental Instruction: design changes/clarifications
- **Correspondence** — General project communication (schedules, reports, coordination, permits, procurement)

## Projects Referenced

| Project | Emails |
|---------|--------|
| Harbor Bridge Reconstruction | 001, 004, 007, 013, 015 |
| Downtown Tower Office Complex | 002, 003, 005 |
| Eastside Medical Pavilion | 006 |
| Riverside Community Center | 008, 014 |
| Airport Terminal C Expansion | 009 |
| Waterfront Mixed-Use Development | 010 |
| Lincoln High School Renovation | 011 |
| Cedar Hills Water Treatment Plant | 012 |

## Sample Agent Commands

These emails support testing the following natural language commands:

1. "File email-001 as an RFI to the Harbor Bridge project"
2. "Classify all today's emails and show me what you found"
3. "File all submittal-related emails to their respective projects"
4. "Show me which emails are RFIs that need responses"
5. "Tag email-005 as a monthly report for Downtown Tower"
6. "Move all Harbor Bridge emails to the Harbor Bridge project folder"
7. "Which emails have action items with deadlines this week?"
8. "File email-013 as procurement correspondence for Harbor Bridge"
9. "Classify email-007 — it has both schedule info and a submittal"
10. "Show me all emails that reference open RFIs"

## Email Characteristics

- **Format:** Standard .eml (RFC 5322 compliant)
- **Date range:** April 15-17, 2024
- **Senders:** Mix of contractors, architects, engineers, owners, and vendors
- **Complexity:** Some emails contain multiple topics (e.g., email-007 has schedule + submittal)
- **Cross-references:** Emails reference RFI numbers, submittal specs, ASIs, and meeting action items
- **Attachments:** Referenced but not included (the AI should recognize attachment references)
