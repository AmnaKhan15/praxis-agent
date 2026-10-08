# Decision log

One entry per real decision: what we chose, why, and what we gave up.
Newest decisions go at the bottom. If a decision is reversed, add a new entry; do not edit history.

## D1. One job, done end to end
**Chose:** a single realistic job (March expense report from 24 messy receipts).
**Why:** one story is easy to demo and to explain. The agent produces a finished file, and the project
measures how well it did.
**Gave up:** breadth. A suite of many tasks would give stronger statistics but a muddier story.

## D2. Write the agent loop by hand (no agent framework)
**Chose:** a ~100 line loop: ask the model, run the tools it requested, feed the results back, repeat.
**Why:** it is the clearest way to show how an agent works, and I can explain every line.
**Gave up:** framework features such as built-in tracing and retries.

## D3. Provider adapters behind one small interface (`llm.py`)
**Chose:** one `chat()` shape with adapters for Gemini, Groq, OpenRouter (all OpenAI-compatible) and Claude.
**Why:** a free Gemini key lets anyone run the demo, while Claude stays available when credit is added.
Swapping the brain is one setting, and comparing models becomes a real experiment.
**Gave up:** provider-specific extras.

## D4. Plain `requests`, not vendor SDKs
**Chose:** call the HTTP APIs directly.
**Why:** fewer dependencies, and the request and response shapes are visible in the code, which is
better for learning and interviews. It also meant the core could be tested in an offline build sandbox.
**Gave up:** SDK conveniences (typed responses, automatic retries). Retries are implemented in `llm.py`.

## D5. A neutral message format inside the agent
**Chose:** the agent stores messages in its own simple format and each adapter translates it.
**Why:** the loop does not care which provider is used.

## D6. Preserve `extra_content` on tool calls
**Chose:** if a provider attaches extra data to a tool call (some newer Gemini models attach a "thought
signature"), the adapter keeps it and sends it back on the next turn.
**Why:** dropping it can make follow-up requests fail on those models.

## D7. Fresh sandbox for every run
**Chose:** copy the receipts into a new temporary folder per run; tools can only touch that folder.
**Why:** one run can never affect the next, and the agent cannot wander through the machine.
**Evidence of safety:** the checker hashes the originals after the run (check 7). File permissions alone
are not relied on.

## D8. Deterministic checker, not an AI judge
**Chose:** a script opens the real xlsx and checks it.
**Why:** same answer every time, and it cannot be talked into passing. The agent saying "done" is never trusted.

## D9. The answer key lives outside the workspace
**Chose:** `data/answer_key.json` is read only by the checker.
**Why:** the agent must not be able to read the answers.

## D10. Each lever maps to one trap in the data
**Chose:** euro rate and meal policy are only in the context lever, the `add_sheet` tool is only in the
workspace lever, and duplicate handling is only in the clear-instructions lever.
**Why:** the four setups then show a clean, explainable score progression.
**Honest note:** checks 5 and 6 need two levers each (the Flags sheet needs the tool, and the rule that
says what to flag comes from context or instructions). The README explains this.

## D11. Scripted demo model, clearly labelled
**Chose:** a deterministic stand-in for an LLM that follows simple rules based on what it is shown.
**Why:** it lets the harness, tests, UI and replay work with no key and no cost.
**Guardrail:** it is NOT an AI and its scores are NOT results. It is labelled DEMO everywhere.

## D12. Public demo safety
**Chose:** the web app runs only the built-in receipts (no uploads, no free-text goal), caps daily runs
on the host's key, falls back to replay mode, and lets visitors paste their own key for the session only.
**Why:** a public page with a free-tier key can be drained or abused within minutes.

## D13. (Superseded by D16) Streamlit for the UI, Hugging Face Spaces for hosting
Replaced: Hugging Face made Gradio/Docker Spaces paid and Streamlit is no longer offered for free.

## D14. Standard library CLI and plain test classes
**Chose:** `argparse` for the CLI and `unittest`-style tests (they also run under pytest).
**Why:** nothing extra to install, and the build sandbox could not download packages.

## D15. Honest README
**Chose:** results table left empty, origin line says the project applies the course framework, no client names.
**Why:** claims must be provable in an interview.

## D16. FastAPI + static page on Vercel
**Chose:** a FastAPI API (`app.py`) that streams agent steps as Server-Sent Events, a plain HTML/CSS/JS page in `public/`, deployed on Vercel.
**Why:** free hosting (Vercel Hobby allows 300 s streaming functions), closer to production practice, and the page is simple to explain.
**Gave up:** Streamlit's speed of building. The UI was rewritten.
**Structure:** all logic is in `praxis/web_core.py` with no framework, so it is unit tested without FastAPI installed. `scripts/dev_server.py` serves the same routes with the standard library for a no-install preview.
**Honest limits:** the daily run cap is best effort on serverless (temp-folder counter); the FastAPI wiring is a thin layer that was not executed in the build sandbox (no package access).

## D17. One safe JSON log line per run
**Chose:** `praxis/observe.py` logs a numbers-only summary of every web run (score, failed check ids, steps, tokens, seconds, stop reason) to stdout, plus a `run_failed` line when a run cannot start.
**Why:** the trajectory shows one run, but nobody could see how the agent behaves across runs. Vercel's Logs tab can search these lines.
**Guardrails:** never logs keys, receipt text, agent output or lever text; error text is cut to 200 characters and visitor keys are redacted. Tests enforce this.
**Gave up:** a dashboard or tracing platform (Langfuse, OpenTelemetry): more setup than the project needs.

## D18. A guided four-round page, not a control panel
**Chose:** the page walks a first-time visitor through four rounds ("No help", "Add company facts", "Add a new ability", "Add clear instructions"), with a score ladder and a "start the next round" coach. The switches for mixing your own help are tucked under "Advanced".
**Why:** the first versions exposed the three levers as toggles and testers (and the project owner) could not tell what to do. The four rounds are the same four setups the core already had, so no logic changed.
**Gave up:** a free-form playground as the first thing you see.

## D19. Visual identity and plain language, driven by feedback
**Chose:** warm orange on ink and grey, Plus Jakarta Sans, tooltips on every piece of jargon, one short sentence per round, and "help chips" that light up as help is added.
**Why:** the owner rejected a blue/white look (too close to another project), purple, and two common fonts. Explaining by showing (chips, score pips) beat explaining by paragraph.
**Safety rule kept:** the page builds text with `textContent` and a small `el()` helper, never `innerHTML`.

## D20. AI chooser lives in the top bar; a visitor's key is used once
**Chose:** a fixed-width dropdown beside the tabs. Picking a real provider reveals a key field. The key is used for that one run and never stored. The host's own key has a daily cap.
**Why:** people could not find the model setting when it sat inside the page. A fixed width with ellipsis stops long names overflowing the header.

## D21. The 4 rounds come first; the video opens in a pop-up
**Chose:** the interactive rounds sit directly under the hero, and the explainer video is a "Watch the video" button that opens a modal.
**Why:** the point of the project is to try it, and attention is short. An inline video pushed the main feature down the page.

## D22. The explainer video is built from the real UI, not generated
**Chose:** scenes written in HTML (receipts, the $75 rule, the duplicate, agent vs chatbot, the loop, the four rounds) recorded with a headless browser, followed by a real screen recording of the app running, joined with ffmpeg.
**Why:** exact numbers and receipt text stay correct (AI video tools garble small text), it costs nothing, and it can be rebuilt after any UI change. A Higgsfield script is kept in `docs/HIGGSFIELD_BRIEF.md` as an optional alternative; it was not used because it needs the owner's own account.
**Honesty:** the app clip is captioned as practice mode, so scores from the scripted demo model are never presented as results.

## D23. Narration from a free, local, open-source voice
**Chose:** Kokoro ("af_sarah"), run locally through sherpa-onnx (an earlier cut used Piper "lessac" and sounded read-aloud). Lines are spoken one sentence at a time with short pauses, and each scene lasts as long as its speech.
**Why:** no account or key, no cost, reproducible. Voice cloning (for example ElevenLabs) needs the owner's own sample, consent and account, so it was left as an option.
**Disclosure:** the voice is synthetic and says so in `docs/VOICEOVER_SCRIPT.md`. The script never says "AI" aloud because the voice read it as a single letter; it says "agent".

## D24. Agent vs chatbot: the claim was corrected
**Chose:** the page and README say the difference is **who drives the loop**, not whether files are involved.
**Why:** an earlier draft said a chatbot "never touches your files". That is false: chat apps accept uploads and some run code or use tools. An interviewer could break the claim in one sentence.
**What it still claims, honestly:** Praxis is a small agent (a handful of tools, one sandboxed task, up to 30 steps), not a general computer-use agent.

## D25. Documentation and project memory
**Chose:** `CLAUDE.md` is the short, current memory (what the project is, commands, code map, rules, status, gotchas) that the coding assistant reads at the start of every session. `DECISIONS.md` is append-only history. `docs/FLOW.md` is the code flow. `BUILD_GUIDE.md` is the owner's step-by-step.
**Why:** keeps the project explainable and keeps assistant sessions consistent without re-explaining everything.

## D26. State plainly which production-AI concepts are covered
**Chose:** a table in the README (and the PDF guide) that marks each concept (agentic workflow, harness engineering, evaluation, observability, reliability, improvement loop, model adaptation, fine-tuning, multi-agent orchestration, delivery, scalability, safety) as Built, Partly, or Not covered, with the file that does it.
**Why:** these terms are used loosely. Claiming all of them would not survive an interview question. Naming the strong ones (harness, evaluation, improvement loop) and admitting the gaps is more credible.
**Gave up:** the impression of covering everything.

## D27. Describe the project with the market's terms, but only claim what is built
**Chose:** the README, resume text and LinkedIn post use the terms hiring teams search for (agent harness, evaluation, observability, reliability, CI delivery, model adaptation) next to what was actually built, and name fine-tuning, multi-agent orchestration and scaling as not covered.
**Why:** the work genuinely covers the first group and recruiters filter on those words. Claiming the second group would fail the first follow-up question.
**Rule:** a concept is only claimed if a file in the repo does it. See the table in the README.

## D28. Containerize with Docker, and prove it in CI
**Chose:** a `Dockerfile` (python:3.12-slim, packages installed before code for caching, non-root user, health check, no keys inside), a `.dockerignore` that keeps `.env` out, a `docker-compose.yml`, and a CI job that builds the image and smoke-tests `/api/health`, `/api/config` and a practice-mode run.
**Why:** one command runs the whole app anywhere, the environment matches CI, and it gives a route off serverless limits. Recruiters expect containerized AI services.
**Gave up:** nothing material. Vercel stays the main deploy; Docker is the run-anywhere option.
**Honest status:** the build sandbox had no Docker daemon, so the image has not been built by us. The CI job is the first real build. Claim it as built only after that job is green.
