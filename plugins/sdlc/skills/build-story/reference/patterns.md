# Reusable coding patterns

The starting catalogue for every project, in any stack. The project's own
`PATTERNS.md` says how each one is done there (which module, which
component, which helper); it wins over this file. `build-story` reads both
before planning and adds to `PATTERNS.md` whenever a story creates
something reusable.

## 0. Reuse before you write

- Ask the graph first: `graphify query "<what you need>"`. If a function,
  component, hook or helper already does it, use it, or extend it with an
  option, instead of writing a second one.
- The rule of three: the second copy of something is a warning, the third
  is a pattern. Extract it, name it for what it does, and add it to
  `PATTERNS.md`.
- Never copy code from another feature to change one line. Give the shared
  piece a parameter instead.

## 1. Structure

- **Feature folders.** Code that changes together lives together
  (`src/<feature>/`), with its tests next to the features in `tests/`.
  Shared code lives in one place (`src/shared/`, `src/lib/`) and never
  imports from a feature.
- **Pure core, thin edges.** Business rules are pure functions (data in,
  data out, no I/O, no clock, no randomness), so they are easy to test and
  reuse. Files, network, storage, time and the UI sit at the edges and call
  the core.
- **One entry point per module.** Other code imports from the module's
  public file (`index.ts`, `__init__.py`, the package), not its internals.
- **Names say what, not how.** `parseQuarterFile`, not `processData2`.
  One name per idea across the codebase.

## 2. Errors and validation

- **Validate at the boundary.** Every input from outside (files, forms,
  URLs, APIs, environment) is checked once, where it enters, against an
  explicit schema or validator, and turned into typed data. Inner code
  trusts it.
- **Errors are data where callers must handle them.** Return a result
  (`{ ok: true, value } | { ok: false, errors }`, `Result<T, E>`, a typed
  error) for expected failures such as invalid input or not found. Throw
  only for bugs and broken invariants.
- **One error shape** per kind (validation, not found, forbidden,
  unavailable), with a stable code and a message for people. Never put
  personal data or secrets in a message or a log.
- **Fail closed.** Unknown, missing or malformed input is rejected, never
  guessed.

## 3. Data access and external calls

- **One gateway per external thing.** Each store, file format, API or
  service is wrapped in one module (repository, client, adapter). Nothing
  else talks to it, so it can be faked in tests and changed in one place.
- **Inject what varies.** Pass the gateway, the clock and configuration in
  (constructor or function parameters), rather than importing a global, so
  tests can replace them.
- **Timeouts, retries with backoff, and a clear error** on every network
  call. Never retry an action that is not safe to repeat.
- **Lookups by key use maps or sets**, never plain objects keyed by user
  input (`__proto__`, `constructor`).

## 4. UI components

- **Use the project's UI library** (`ui_library` in `.sdlc/build.yaml`) for
  every standard element: buttons, inputs, selects, checkboxes, dialogs,
  menus, tabs, tables, toasts, tooltips. Do not hand-build one the library
  has; accessibility, keyboard handling and focus come with it.
- **Theme, don't override.** Colours, type, spacing and radius come from
  the design's Tokens, set once in the library's theme. No one-off colours
  or pixel values in components.
- **Presentational and container components.** Presentational components
  take props and render, with no data fetching or global state. Containers
  (pages, routes) load data and pass it down. Shared presentational
  components live in one folder and go into `PATTERNS.md`.
- **Every state is designed.** Loading, empty, error and success states for
  each screen, as the design shows them.
- **Accessible by default.** Real labels, landmarks, headings in order,
  visible focus, text alternatives, and no information by colour alone.
  The end-to-end tests run an accessibility check.
- **User text is text.** Render it as text, never as HTML.

## 5. State and configuration

- **One source of truth** per piece of state. Derive the rest (counts,
  filters, totals) instead of storing copies.
- **Configuration from the environment**, read and validated once at
  start-up into a typed object. No secrets in code, config files or tests.
- **Feature flags** for behaviour that is not finished or not yet released:
  read through one helper, default off, and removed once the feature is on
  for everyone.
- **Constants have a name and one home.** No magic numbers or repeated
  strings.

## 6. Testing

- **Arrange, act, assert**, one behaviour per test, named for the story
  (`S<n> AC-<k>: ...`).
- **Builders and fixtures** for test data (`aRating({ level: 5 })`), shared
  in one test helper folder, so a change to the data shape is made once.
- **Fakes at the gateways**, never mocks of the code under test. Fake the
  clock and randomness.
- **Test through the public interface** of a module, not its internals.
- **Deterministic and offline.** No real network, no sleeps, no order
  dependence.

## 7. Logging and observability

- **Structured logs** (event name plus fields) at the edges, with a
  correlation id where the stack has one. No personal data, secrets or
  full request bodies.
- **Log once,** where the error is handled, not at every layer it passes.
