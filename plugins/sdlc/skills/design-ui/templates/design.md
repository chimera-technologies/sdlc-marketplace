---
id: <spec-slug>
spec: specs/<spec-slug>.md
source: <mockup (HTML mockups in mockups/) or figma (frames in a Figma file)>
figma_file: <https://www.figma.com/design/<FILE_KEY>/<name>, or none for mockup>
figma_file_key: <FILE_KEY, or none for mockup>
owner: "<@github-handle or @org/team: the spec's owner>"
created: <YYYY-MM-DD>
---

# Design: <short title>

## Screens
| Screen | Source | Screenshot | Stories | Requirements |
|---|---|---|---|---|
| <screen-id, kebab-case> | <mockups/<screen-id>.html, or the Figma node id, e.g. 1:2> | screens/<screen-id>.png | <S1, S2> | <REQ-1, REQ-2> |

## States
<Empty, error, validation and warning states the screens show, one bullet
each, naming the screen and the requirement (for example REQ-9 validation).>

## Tokens
<The design's colours, type scale and spacing as named values, so Build
uses the same ones (for example `color.accent #1f6feb`).>

## No UI
<Stories from the spec that have no screen, one per line with the reason
(for example "S5: delivery and acceptance run, no new screen"). Write
"None." if every story has a screen.>
