---
id: claims-status-self-service
spec: specs/claims-status-self-service.md
source: mockup
figma_file: none
figma_file_key: none
owner: "@claims-po"
created: 2026-09-29
---

# Design: Let customers check claim status themselves

## Screens
| Screen | Source | Screenshot | Stories | Requirements |
|---|---|---|---|---|
| claim-status-list | mockups/claim-status-list.html | screens/claim-status-list.png | S3 | REQ-1, REQ-2 |
| claim-status-empty | mockups/claim-status-empty.html | screens/claim-status-empty.png | S3 | REQ-1 |

## States
- claim-status-empty: the signed-in customer has no open claims (REQ-1).
- claim-status-list: one row per open claim, newest first, each with its
  Legal-approved status and next step (REQ-2).

## Tokens
- `color.text #1d2522`, `color.muted #5d6a65`, `color.accent #17715f`
- `color.border #d9dfdc`, `color.surface #ffffff`, `color.page #f4f6f5`
- `type.body 16/24 IBM Plex Sans`, `type.label 13/18 IBM Plex Sans 600`
- `space.unit 8px`; page width 1280, content column 720

## No UI
- S1: server endpoint only, no screen.
- S2: mapping table in claims-core, no screen.
