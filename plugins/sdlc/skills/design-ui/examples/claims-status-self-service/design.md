---
id: claims-status-self-service
spec: specs/claims-status-self-service.md
source: figma
figma_file: https://www.figma.com/design/AbC123exampleKey/claims-status-self-service-UI
figma_file_key: AbC123exampleKey
owner: "@claims-po"
created: 2026-09-29
---

# Design: Let customers check claim status themselves

## Screens
| Screen | Source | Screenshot | Stories | Requirements |
|---|---|---|---|---|
| claim-status-list | 12:34 | screens/claim-status-list.png | S3 | REQ-1, REQ-2 |
| claim-status-empty | 12:58 | screens/claim-status-empty.png | S3 | REQ-1 |

## States
- claim-status-empty: the signed-in customer has no open claims (REQ-1).
- claim-status-list: one row per open claim, newest first, each with its
  Legal-approved status and next step (REQ-2).

## Tokens
- `color.text #1d2522`, `color.muted #5d6a65`, `color.accent #17715f`
- `type.body 16/24 IBM Plex Sans`, `type.label 13/18 IBM Plex Sans 600`
- `space.unit 8px`; page width 1280, content column 720

## No UI
- S1: server endpoint only, no screen.
- S2: mapping table in claims-core, no screen.
