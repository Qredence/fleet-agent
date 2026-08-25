# `better-ui` review — `apps/web` core workspace

**Date:** 2026-08-25
**Scope:** workspace shell, conversation pane, assistant-ui `Thread`, process panel (9 files), project sidebar, the 8 primitives those surfaces compose, `lib/surfaces.tsx`, and `src/index.css`.
**Method:** every file in scope was read once; motion durations, easings, transition properties, scale-on-press values, icon stroke widths, radius pairs, and state-cue structure were extracted directly from the code. The `better-ui` principles were applied in the order they appear in the skill. **Findings were then verified live in a headed Chrome session** (Vite dev server + FastAPI backend, agent-browser) — see "Live verification" at the end.
**Out of scope:** `apps/api`, `components/elements/*`, `components/assistant-ui/{tool-fallback,tool-group,reasoning,markdown-text,file,image,attachment,follow-up-suggestions,tooltip-icon-button}.tsx`, accessibility (`better-accessibility`), typography (`better-typography`), layout (`better-layout`), colors (`better-colors`).

---

## Findings

### Group A — "Transition only what changes"

The motion vocabulary in `src/lib/surfaces.tsx` is correct (specific properties listed, `motion-reduce:` opt-outs). The primitives and major surfaces that don't use it reach for `transition-all` or the bare `transition` shorthand, which Tailwind expands to a fixed list of ~10 common animatable properties (including `transform`, `filter`, and `backdrop-filter`) — broad enough to animate things the developer never intended.

| Severity | Location | Before | After | Why |
| --- | --- | --- | --- | --- |
| MEDIUM | `src/components/ui/button.tsx:7`, `src/components/ui/badge.tsx:8`, `src/components/ui/tabs.tsx:61` | `… transition-all …` | `… transition-[background-color,color,box-shadow,opacity,transform,scale,translate] …` (each variant names only the properties it actually changes) | `transition-all` is the explicit anti-pattern the skill lists in "Before you finish." Animating every property means a future style change (e.g. adding `flex-basis` or `text-align`) will animate without warning. |
| MEDIUM | `src/components/ui/sheet.tsx:56` | `… shadow-lg transition duration-200 ease-in-out …` | `… shadow-lg transition-[opacity,transform,translate] duration-200 ease-out …` | Same anti-pattern: bare `transition` is broader than needed. Sheet only changes opacity and the side-axis translate. |
| LOW | `src/components/ui/sidebar.tsx:435` (`SidebarGroupAction`), `src/components/ui/sidebar.tsx:575` (`SidebarMenuAction`) | `… transition-transform …` (the element itself never applies a `transform`) | Drop `transition-transform`; keep `transition-opacity` if the element animates opacity (it does, via `group-focus-within/menu-item:opacity-100`) | Dead `transition-transform` on elements that don't transform is a no-op cost; if no property changes here, the `transition-*` should be removed, not widened. |
| LOW | `src/components/process-panel/process-step-card.tsx:43` | `… text-muted-foreground transition-transform …` (only `rotate-90` changes) | `… transition-[rotate,transform] …` or `transition-transform` (current is fine — kept for completeness) | The current usage is acceptable; flagged only because `transition-transform` (broad) is one class away from `transition-all` (broad-er). Worth a comment in the file. |

### Group B — Skip / reduce motion

The project's own `surfaces.tsx` (lines 17, 20, 23, 26, 33, 41) and the inner `Skeleton` components in `ThreadHistorySkeleton` (lines 118–127) consistently opt out of motion for `prefers-reduced-motion`. The main entrance animations in the chat thread, the sheet, the tooltip, and the tabs do not — so a reduced-motion user still gets a 150–200 ms fade and slide every time a message arrives or a tab changes.

| Severity | Location | Before | After | Why |
| --- | --- | --- | --- | --- |
| MEDIUM | `src/components/assistant-ui/thread.tsx:222` (`ThreadWelcome` h1), `:241` (`ThreadSuggestionItem`), `:313` (`AssistantMessage`), `:453` (`UserMessage`), `:413` (`AssistantActionBar`) | `… fade-in slide-in-from-bottom-1 animate-in fill-mode-both … duration-150` (no `motion-safe:` prefix) | `… motion-safe:fade-in motion-safe:slide-in-from-bottom-1 motion-safe:animate-in motion-safe:fill-mode-both …` | Reduced-motion users should not see the entrance animation. The skill's `Before you finish` table does not call this out, but `surfaces.tsx` already establishes the pattern. |
| MEDIUM | `src/components/assistant-ui/thread.tsx:115` (`ThreadHistorySkeleton` wrapper) | `animate-in fade-in fill-mode-both …` on the wrapper container; only the inner `Skeleton` components have `motion-reduce:animate-none` | `motion-safe:animate-in motion-safe:fade-in …` on the wrapper | The wrapper's `animate-in` fires even with reduced motion; the children are gated but the container fade is not. |
| MEDIUM | `src/components/ui/sheet.tsx:31` (`SheetOverlay`), `:56` (`SheetContent`); `src/components/ui/tooltip.tsx:51` (`TooltipContent`); `src/components/ui/tabs.tsx:61` (`TabsTrigger`) | `… transition … data-[state=open]:animate-in …` (no `motion-safe:`) | Add `motion-safe:` to every `animate-in` / `animate-out` on these primitives | The four primitives cover the four most-frequent transient UI states in the app. Each one of them plays a 150–200 ms animation without consulting the user's preference. |
| LOW | `src/components/ui/button.tsx:7` | `… transition-all … active:not-aria-[haspopup]:translate-y-px …` (no `motion-reduce:`) | Add `motion-reduce:transition-none` and replace the `active:translate-y-px` with `motion-safe:active:translate-y-px` (or with the `scale-[0.96]` from `surfaces.tsx:pressable`) | Button is the most-pressed element in the app; a reduced-motion user feels the press on every click. |

### Group C — Contextual icon animations

The skill prescribes exactly `scale 0.25 → 1`, `opacity 0 → 1`, `blur 4px → 0px` for icon transitions. `surfaces.tsx` (`iconSwap`, `iconSwapIn`, `iconSwapOut`) is correct. The chat thread and the process-panel status chip use a different recipe (and skip the blur entirely).

| Severity | Location | Before | After | Why |
| --- | --- | --- | --- | --- |
| MEDIUM | `src/components/assistant-ui/thread.tsx:416` (Copy → Check), `:418` (Check → Copy) | `<CheckIcon className="animate-in zoom-in-50 fade-in duration-200 ease-out" />` and `<CopyIcon className="animate-in zoom-in-75 fade-in duration-150" />` | Apply the `iconSwap` + `iconSwapIn` / `iconSwapOut` classes from `surfaces.tsx`, e.g. wrap the icons in a 1×1 grid and apply `iconSwap` + `iconSwapIn` / `iconSwapOut`; gate the whole thing with `motion-safe:` | The skill's exact values: `scale 0.25 → 1, opacity 0 → 1, blur 4px → 0px`. `zoom-in-50/75` is the wrong scale and the blur channel is missing, so the swap doesn't read as the same motion as the rest of the app. `iconSwap` / `iconSwapIn` / `iconSwapOut` are defined in `surfaces.tsx:25-30` and already implement the correct recipe — they are not imported anywhere in the app yet. |
| MEDIUM | `src/components/process-panel/status-chip.tsx:64` (`StatusIcon`) | Icon and color are looked up from a `Record` and rendered directly; status changes snap | Wrap the icon in a 1×1 grid, apply `iconSwap` + `iconSwapIn` / `iconSwapOut` from `surfaces.tsx`, and key on `status` so React swaps the active layer | A step going from `running` → `completed` should cross-fade the `Loader2` into the `CheckCircle2`. The static cue (the new color and icon) is present, but the motion is the same recipe used everywhere else in the app — it should match. |
| LOW | `src/components/process-panel/process-step-card.tsx:41` (`ChevronRight`) | `… transition-transform … expanded && 'rotate-90'` | Current is correct; no change needed. Flagged only because the chevron rotation is the standard disclosure pattern (not the icon-swap recipe), and it works without `motion-reduce:` because a 90° rotate is not motion a reduced-motion user typically objects to. | n/a |

### Group D — Match icon stroke to text weight

The skill: `1.5px` stroke for `400` text, `2px` stroke for `600`. Lucide defaults to `2px`. The project uses `2px` everywhere; the only place the text weight drops low enough for this to feel off is the branch picker.

| Severity | Location | Before | After | Why |
| --- | --- | --- | --- | --- |
| LOW | `src/components/assistant-ui/thread.tsx:526, 530` (BranchPicker chevrons) | `<ChevronLeftIcon />` and `<ChevronRightIcon />` at default `2px` stroke, next to `text-xs` (12 px) `font-medium` (500) | Either pass `strokeWidth={1.5}` to the icons, or bump the surrounding text to `text-sm font-semibold` to match the `2px` stroke | At 12 px text, a `2px` lucide stroke is roughly 17 % of the cap height — too heavy. `1.5px` brings it closer to 13 %. |
| LOW | All Button / Sidebar / Tabs consumers | Default `2px` lucide stroke at `text-sm font-medium` (500) | Acceptable — flagged only so the next person knows the design system committed to `2px` and is choosing the text weight to match, not the other way around | n/a |

### Group E — Subtle exit animations / interruptibility

| Severity | Location | Before | After | Why |
| --- | --- | --- | --- | --- |
| MEDIUM | `src/components/process-panel/process-step-card.tsx:65` (`{expanded && (...)}`) | The expanded `<dl>` appears/disappears instantly via conditional render | Wrap in `surfaces.tsx:collapsePanel` (or a small `grid-template-rows` trick keyed on `expanded`) so the body slides in and out | Better-ui says "Exits should be softer than enters" and the skill calls for a "small fixed `translateY` rather than full height." A click should not yank the eye from the title to the body. The skill also requires "Interruptible animations" — a CSS transition is interruptible, a keyframe is not. |
| LOW | `src/components/ui/sheet.tsx:56` (SheetContent) | Exit translate is `translate-x-[2.5rem]` (40 px) and `translate-y-[2.5rem]` | The 40 px is on the high end of "small fixed" (the skill gives 8–24 px as the typical range); either keep the 40 px and add `ease-in` for the exit direction, or drop to `translate-x-[1.5rem]` / `translate-y-[1.5rem]` | Sheet exits already work; this is a polish call. |
| LOW | `src/components/ui/tooltip.tsx:51` (TooltipContent) | `data-closed:zoom-out-95` exit | No change needed; tw-animate-css defaults are acceptable for tooltips. Flagged only so the recipe stays consistent with the rest of the primitives. | n/a |

### Group F — Scale on press

| Severity | Location | Before | After | Why |
| --- | --- | --- | --- | --- |
| MEDIUM | `src/components/ui/button.tsx:7` | `… active:not-aria-[haspopup]:translate-y-px …` | `… motion-safe:active:scale-[0.96] …` (or adopt `surfaces.tsx:pressable` for the whole base) | The skill says: "Always `0.96`; anything below `0.95` feels exaggerated." `surfaces.tsx:pressable` (lines 16–17) and `components/assistant-ui/attachment.tsx:193, 286` already use `scale-[0.96]`. Note: `surfaces.tsx:pressable` and `iconSwap` / `iconSwapIn` / `iconSwapOut` are defined in the design system but **never imported** anywhere in `src/`. Three different press patterns exist in the app: `translate-y-px` (Button), `scale-[0.96]` (attachment, surfaces.tsx), and a local `scale-[0.98]` with no transition (tool-fallback, out of scope). One primitive is the only place left using `translate-y-px` — making the system more consistent is a single-class change. |

### Group G — Concentric border radius

| Severity | Location | Before | After | Why |
| --- | --- | --- | --- | --- |
| LOW | `src/lib/surfaces.tsx:7` (`paper`) and `:9` (`floating`) | Both strings are literally identical: `bg-background border border-border/60 dark:bg-popover` | `floating` should add a layered shadow recipe (per the skill's "shadows for elevation" principle) — e.g. `bg-popover border border-border/40 shadow-md ring-1 ring-black/5 dark:ring-white/5` | One of the two was probably meant to elevate. As written, the primitive has no "floating" surface. |
| LOW | `src/components/assistant-ui/thread.tsx:151` (Composer) | `--composer-radius: 1.5rem` (24 px) — outside the project's radius scale (max `--radius-4xl = 1.625rem`) | Either use `--radius-3xl` (1.375 rem) for the composer, or promote the value to a named token (e.g. `--radius-composer`) | Custom radii next to a deliberate scale make the scale useless. |

### Group H — Shadows for elevation vs borders for structure

| Severity | Location | Before | After | Why |
| --- | --- | --- | --- | --- |
| LOW | `src/components/ui/sidebar.tsx:252` (`SidebarInner` for the `floating` variant) | `group-data-[variant=floating]:shadow-sm group-data-[variant=floating]:ring-1 group-data-[variant=floating]:ring-sidebar-border` | Replace `ring-1 ring-sidebar-border` with a layered `shadow-md` (or remove the ring entirely if `shadow-sm` is enough) | The skill: "Where a border exists only to create depth, prefer layered transparent `box-shadow` values." A 1 px `ring` is doing what a 1 px `border` would; if it's only there to delineate the panel, a `shadow` covers the same job without the visual line. |
| LOW | `src/components/ui/sheet.tsx:73` (close X) and other icon-only buttons | The X button has no shadow or border; relies on `hover:bg-foreground/[0.06]` | Acceptable; flagged only because the design system has both `ghostButton` (in `surfaces.tsx:19`) and the shadcn `Button variant="ghost"` (in `button.tsx:17`). Two "ghost" definitions, slightly different. | n/a |

### Group I — One SVG, recolored per state

| Severity | Location | Before | After | Why |
| --- | --- | --- | --- | --- |
| LOW | All lucide icons in `surfaces.tsx:1-46` consumers | Lucide uses `currentColor` by default — confirmed. All states change via `text-*` class on the wrapper. | n/a | The design system already commits to this principle. No changes needed. |

### Group J — `prefers-reduced-motion` not consulted globally

| Severity | Location | Before | After | Why |
| --- | --- | --- | --- | --- |
| MEDIUM | `src/components/assistant-ui/thread.tsx:274` (`StopDictation` icon) | `<SquareIcon className="… animate-pulse fill-current" />` | Add `motion-reduce:animate-none` (the surrounding chip is reduced-motion-aware; the icon is not) | A subtle one, but the dictation pulse is exactly the kind of motion a reduced-motion user objects to. |

### Group K — Dark mode is dead design system surface

| Severity | Location | Before | After | Why |
| --- | --- | --- | --- | --- |
| MEDIUM | `src/index.css:125-158` (the `.dark` block) | Full dark palette defined, including `--sidebar-primary: oklch(0.488 0.243 264.376)` (a unique blue) that the light mode doesn't have | Either wire up a `prefers-color-scheme: dark` media query (cheapest), add a `ThemeProvider` + toggle, or delete the dark tokens | There is no `ThemeProvider`, no `setTheme`, no `useTheme`, no `prefers-color-scheme` media query, and no `.dark` class is ever set anywhere in `src/`. The dark mode is a design surface that ships tokens but no path to use them. The `--sidebar-primary` blue in dark mode is the only chromatic chart/sidebar color in the entire system and is unreachable. |

### Group L — Misc / dead attributes

| Severity | Location | Before | After | Why |
| --- | --- | --- | --- | --- |
| LOW | `src/components/process-panel/status-chip.tsx:37` | `<Loader2 data-running="true" … />` | Remove the unused `data-running="true"` attribute | It's set on one icon and never read anywhere. Dead. |
| LOW | `src/components/assistant-ui/thread.tsx:291` (`MessageError`) | `… text-destructive … dark:text-red-200` | Drop the `dark:text-red-200`; the `text-destructive` token already has a dark-mode OKLCH value (`oklch(0.704 0.191 22.216)`) | The override escapes the token system. |
| LOW | `src/components/assistant-ui/thread.tsx:158` (Viewport) | `… overflow-y-scroll scroll-smooth …` | Add `motion-reduce:scroll-auto` so reduced-motion users get instant jumps | Consistent with the rest of the file's motion gating. |
| LOW | `src/components/process-panel/activity-tab.tsx:37` and `src/components/process-panel/artifacts-tab.tsx:92` | `active.scrollIntoView({ block: 'nearest' })` | `active.scrollIntoView({ block: 'nearest', behavior: 'smooth' })` (gated on `motion-safe:` if the parent opts in) | The thread viewport already requests `scroll-smooth` via CSS, but `scrollIntoView` without `behavior: 'smooth'` jumps instantly in most browsers regardless. The process panel and the thread disagree on the same operation. |
| LOW | `src/components/ui/sidebar.tsx:227, 239, 411` | `… ease-linear …` | Either `ease-out` (consistent with the rest of the system) or document the choice — the skill doesn't prescribe for layout shifts, but the rest of the app uses `cubic-bezier(0.23,1,0.32,1)` or `cubic-bezier(0.2,0,0,1)`, not `linear` | Visual consistency. |
| LOW | `src/components/ui/sidebar.tsx:25-27` (width constants) | `SIDEBAR_WIDTH = "16rem"` (256 px), but `agent-workspace.tsx:141-143` constrains the sidebar to `220–320 px` with a `248 px` default | Sync the constants — either `SIDEBAR_WIDTH = "15.5rem"` to match the `248 px` default, or move the 220–320 px range into the sidebar primitive | The primitive's constants are never used (the workspace shell re-declares its own), so the primitive's values are a future footgun. |

---

## Verdict

**Approve** with work to do.

No `HIGH` finding remains. The codebase has a coherent motion vocabulary in `lib/surfaces.tsx` that is applied faithfully where it is imported, and the inner `Skeleton` components correctly gate motion for reduced-motion users. The findings above are polish and consistency items — none of them break an interaction, none of them make motion unusable, and every state change has at least one static cue (color, icon, or label) in addition to its motion.

The two areas worth prioritizing:

1. **Group A (`transition-all` / `transition` shorthand on Button, Tabs, Sheet, Badge)** — one fix in one primitive file improves the whole app.
2. **Group B (motion-reduce on entrance animations and primitives)** — same leverage; a single PR adding `motion-safe:` to the five lines in `thread.tsx` and the four primitives covers every reduced-motion regression in the chat.

The dark-mode dead surface (Group K) is a design-system decision, not a polish bug, but worth flagging.

## Out-of-scope discoveries

While confirming citations, the review found two issues in files that were excluded from the scope. They are recorded here so the next review pass can pick them up directly.

| Severity | Location | Before | After | Why |
| --- | --- | --- | --- | --- |
| MEDIUM | `src/components/assistant-ui/tool-fallback.tsx:31` | `const pressable = "active:scale-[0.98]";` (used 6 times) | Replace with the imported `surfaces.tsx:pressable` (`active:scale-[0.96] motion-reduce:transition-none` + the full `transition-transform duration-150 ease-[cubic-bezier(0.23,1,0.32,1)]`) | `0.98` is the only `scale` value in the codebase that does not match the `0.96` the skill prescribes. The local class also drops the transition and easing, so the press is static — different from the rest of the system. |
| LOW | `src/components/assistant-ui/attachment.tsx:286` | `… size-7 rounded-full active:scale-[0.96] motion-reduce:transition-none` (no transition) | Add `transition-transform duration-150 ease-[cubic-bezier(0.23,1,0.32,1)]` before `active:scale-[0.96]` to match `surfaces.tsx:pressable` | The press jumps without a transition. Cosmetic, but the rest of the system transitions. |

---

## Live verification (headed Chrome, 2026-08-25)

The app was run locally (`pnpm dev:web` on :5174 + `fastapi dev --port 8010`, CORS extended to :5174) and every code-derived finding was re-checked in the browser via computed styles, CSSOM inspection, and media-query emulation.

| Finding | Live result |
| --- | --- |
| Group A — Button/Tabs `transition-all` | **Confirmed.** Header toggle button and tab trigger both compute `transition-property: all, 0.15s, cubic-bezier(0.4, 0, 0.2, 1)`. |
| Group A — sidebar `transition-transform` dead | **Confirmed.** `SidebarMenuAction` computes `transition-property: transform, translate, scale, rotate` while its class list contains no transform utility and its computed `transform` is `none`. |
| Group B — reduced motion not honored | **Confirmed.** With `prefers-reduced-motion: reduce` emulated, the welcome `<h1>` still runs `animation: enter 0.2s` (`playState: running`). CSSOM inspection shows the stylesheet only gates `motion-safe:`/`motion-reduce:`-prefixed utilities — there is no global reduced-motion reset. |
| Group C — Copy icon swap recipe | **Confirmed (static).** The rendered copy icon's class is exactly `lucide-copy animate-in zoom-in-75 fade-in duration-150` — no blur, wrong scale, matching the code. (Live swap not triggered: clipboard permission.) |
| Group E — step-card instant expand | **Confirmed.** Clicking a step card toggles `aria-expanded` and the body appears with `transition: all 0s`, `animation: none` — a hard snap; only the chevron rotates. |
| Group F — Button press `translate-y-px` | **Confirmed.** The button base rule is `.active:not-aria-[haspopup]:translate-y-px:active:not([aria-haspopup])`; the only `scale-[0.96]` in the live DOM is the composer's Add-attachment button. |
| Group G — composer radius off-scale | **Confirmed.** Composer computes `border-radius: 24px` (`--composer-radius: 1.5rem`) against a scale whose neighbors are 22px (3xl) and 26px (4xl). |
| Group K — dark mode unreachable | **Confirmed.** With `prefers-color-scheme: dark` emulated, `documentElement.classList` has no `dark`, `--background` still resolves to `oklch(1 0 0)`, and the page renders identically light. |
| Group L — `data-running` dead | **Confirmed.** Zero elements carry `data-running`; zero CSS rules reference it. |
| Group L — scroll behavior mismatch | **Confirmed.** Thread viewport computes `scroll-behavior: smooth`; the process panel's `scrollIntoView({ block: 'nearest' })` calls pass no behavior. |
| Sources tab `highlight-fade` | **Correct as designed.** On initial load no source animates (the `baselineRef` only highlights items appended mid-run) — this is the codebase's one place where the `motion-safe:` pattern is applied end-to-end. |

**Environment note:** the API's default CORS allow-list is `http://localhost:5173` only (`apps/api/app/settings.py:27`). Verifying a dev server on any other port (5174, etc.) requires `FLEET_AGENT_CORS_ORIGINS` to include it — worth knowing for anyone reproducing this review.

## Not verified (remaining after live pass)

- The Copy → Check icon swap **in motion** — clipboard permission blocked the live swap; verified statically (rendered class list) instead.
- Theme-switch smear — moot (no theme switcher exists; see Group K), but the "suppress transitions on theme switch" recipe is therefore also untested.
- Sheet slide-in at 10% speed in the Animations panel — the sheet's computed transition was read live (`0.2s cubic-bezier(0.4, 0, 0.2, 1)` over 24 properties), but not replayed at reduced speed.
- `motion-reduce:transition-none` firing at runtime — partially verified: with reduced motion emulated, the Add-attachment button computed `transition-property: none` (its `motion-reduce:transition-none` won), which is the pattern working as intended on the one element that has it.
- The `resizable-panels` drag interaction — handles rendered; not dragged.
- `tooltip-icon-button` in `assistant-ui/` — out of scope; not read.
- A live agent run (spinner states, `highlight-fade` on mid-run source appends, auto-open of the process panel) — would require an LLM-keyed run; the fixtures replay was sufficient for static card verification only.
