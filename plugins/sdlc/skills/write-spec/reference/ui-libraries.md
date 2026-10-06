# Choosing a UI component library

Every spec with a user interface names one UI component library, and the
build uses it for every standard element (buttons, form controls, dialogs,
menus, tabs, tables, toasts). A library gives accessibility, keyboard
handling, focus management and consistent states for free; hand-built
components get these wrong in ways tests rarely catch.

If the repo already uses one, keep it. Otherwise compare two or three
against the criteria below, recommend one, and write "Decision needed from:
tech lead".

## Criteria

| Criterion | What to check |
|---|---|
| Accessibility | Follows WAI-ARIA patterns; keyboard and screen-reader support documented; passes axe on its own examples |
| Fit with the stack | Built for the chosen framework and version; works with its rendering mode (SPA, SSR, static export) |
| Theming | Colours, type, spacing and radius set from tokens in one theme, so the design's Tokens map onto it |
| Coverage | Has the components the screens need (data tables, date pickers, dialogs) without a second library |
| Health | Actively maintained, recent releases, wide use, clear upgrade path |
| Licence and cost | Open-source licence the organisation allows; no paid tier needed for what the spec uses |
| Size and runtime | Bundle cost acceptable for the app; no CDN, fonts or calls to other hosts at runtime (bundle everything) |
| Security | No unmaintained transitive dependencies; passes the project's audit |

## Common choices (examples, not an approved list)

Use the organisation's standards skill if there is one; it overrides this
list.

| Platform | Well-established options |
|---|---|
| React | shadcn/ui (Radix primitives, Tailwind), MUI, Mantine, Chakra UI, React Aria Components |
| Angular | Angular Material (CDK), PrimeNG |
| Vue | Vuetify, PrimeVue, Quasar |
| Svelte | Skeleton, shadcn-svelte (Bits UI) |
| Web components / any framework | Shoelace (Web Awesome), Lit-based design systems |
| Blazor (.NET) | MudBlazor, Fluent UI Blazor |
| Flutter | Material 3 (built in), Cupertino |
| Android | Jetpack Compose Material 3 |
| iOS | SwiftUI (system components) |

## In the spec

Under **Technology and architecture**, write:

```
UI component library: <name and version line>, because <the deciding criteria>.
Theme: the design's Tokens map to <the library's theme mechanism>.
```

Then:
- the design (`sdlc:design-ui`) draws the mockups with the library's
  components and default look, themed with the Tokens;
- `/sdlc:init stack=` records it as `ui_library` in `.sdlc/build.yaml`;
- the scaffold story installs it and sets up the theme once;
- every later story uses its components.
