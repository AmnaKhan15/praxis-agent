# Design notes

## The brief
**Subject:** an AI agent that does real bookkeeping work: it reads a folder of messy receipts and builds an expense report.
**Audience:** a recruiter or hiring manager with about 30 seconds, and the author presenting it in an interview.
**Primary job of the page:** let someone watch the agent work, then see proof (a checker) that it did or did not do the job.

## First plan (and why I rejected it)
First instinct: a dark dashboard, one accent colour, a row of metric cards (score, steps, tokens) and a
chat-style log. That is the look of every agent demo, and it hides the one thing that makes this project
different: the agent produces a real working record, step by step.

## Revised plan: the desk
The subject has its own vocabulary: receipts, till tape, ledger pads, "checked" stamps. The design borrows from it
in exactly one bold place and stays quiet everywhere else.

**The one memorable thing:** the agent's trajectory is printed live on a paper receipt tape, in a typewriter face,
with a torn edge. You watch the receipt of its own work come out.

### Colour (named, with the job each one does)
| Name | Hex | Used for |
|---|---|---|
| Desk | `#E6EBE8` | page background, a cool grey-green like a columnar accounting pad |
| Paper | `#FCFCFA` | the tape, the plan ledger, panels that hold content |
| Ink | `#1D2733` | text |
| Ledger blue | `#2747C9` | the step in progress, the lever names, comparison bars |
| Stamp green | `#1F7A4D` | checks that passed, finished steps |
| Stamp red | `#B3261E` | checks that failed, tool errors, the demo-model warning |
Rules: `#5B6670` for secondary text, `#C9D2CD` for ruled lines. All text pairs meet WCAG AA contrast on Paper.

### Type
- **Bricolage Grotesque**: the interface, headings and body. A characterful grotesque with a little
  quirk, rather than the usual neutral sans.
- **Courier Prime**: only the tape and the raw receipts. A typewriter face because that is what receipts look like.
  It is not used for small labels elsewhere, so it stays special.
Fallbacks are system sans and Courier New, so the page still works offline.

### Layout (left aligned throughout)
```
 Praxis                                    sidebar
 Give an AI agent a job. Watch it work...      -------
 [ notice: demo model / live model ]           brain
                                               key
 Goal: Prepare the March expense report.       model
 24 receipts in four layouts are waiting.      -------
 ( Run the agent )                             three levers
                                               [ ] context
 +- plan (ledger lines) -+ +---- tape ------+  [ ] tool
 | o Look at the folder  | | 5  read_file .. |  [ ] instructions
 | o Read every receipt  | | 6  read_file .. |
 | o ...                 | | 7  add_sheet    |
 +-----------------------+ |    ! not avail. |
                           \/\/\/\/\/\/\/\/\/
 5 of 7 checks passed
 Pass  Report opens ...        What to change next
 Fail  Euro receipt ...        Context: the euro receipt ...
```
Tabs: Run, Compare setups, How it works, The receipts.

### Principles
1. Show the work, not a dashboard: the live tape and plan are the hero, not a row of KPI tiles.
2. Structure carries information: ruled lines mean "ledger", the torn edge means "output of a process",
   stamps mean "verdict". Nothing is decoration.
3. Paper elements are square-cornered (2px). Only buttons are rounded. No identical card grid, no gradients.
4. Sentence case everywhere. No tracked-out capital labels, no arrows on buttons, no numbered badges except the
   how-it-works steps, which really are a sequence.
5. No decorative motion. The only movement is real: lines print on the tape as the agent acts.
6. Honesty is part of the design: a red notice always says when the scripted demo model is running.

## Review against the brief: what changed and why
- Dropped the metric-card row. The score is stated as a sentence ("5 of 7 checks passed") above the list of checks,
  because the checks matter more than the number.
- Dropped a dark theme. A light, paper-like page matches the subject and is easier to read when screen-shared.
- Kept the sidebar plain. It holds controls only, so the main page can stay about the work.
- Tape scrolls to the newest line automatically, because a recruiter should never have to scroll to see the agent act.

## Implementation notes
- The page is plain HTML/CSS/JS in `public/`. `public/app.js` builds every element with `textContent`, never `innerHTML`.
- Agent output is untrusted text, so it is only ever inserted as text, never as HTML.
- Keyboard focus is visible, columns stack on narrow screens, and no colour is the only signal
  (each check says Pass or Fail, each failed tool line starts with ERROR).
