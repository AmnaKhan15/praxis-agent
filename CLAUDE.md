# Praxis: project memory

This file is the project's memory. Claude Code reads it at the start of every session,
so keep it short, true and up to date. Decisions and their reasons live in DECISIONS.md.

## What this project is
An AI agent gets a goal ("Prepare the March expense report"), reads 24 messy receipt
files in a sandboxed workspace, and produces a real `expense_report.xlsx`. A checker
script verifies the real file (7 checks). The agent's behaviour is improved by changing
one of three levers: context, workspace (tools), instructions.

Built as a capstone applying the framework from Mercor's "Introduction to Agents" course.
Never name any employer, client or third-party benchmark anywhere in this repo.

## Commands
- Run tests (no extra installs needed): `python -m unittest discover -s tests -v`
- Run the agent from the terminal: `python -m praxis run --provider demo --setup baseline`
- Compare the four setups: `python -m praxis compare --provider gemini --runs 5`
- Start the web app: `uvicorn app:app --reload` (or `python scripts/dev_server.py`, no installs)
- Regenerate receipts and the answer key: `python -m praxis make-data`
- Docker: `docker build -t praxis .` then `docker run --rm -p 8000:8000 --env-file .env praxis` (or `docker compose up --build`)

## Map of the code (praxis/)
- `config.py`     paths, the three levers, the four setups
- `receipts.py`   builds the 24 receipts and the private answer key
- `tools.py`      sandboxed tools the agent may call
- `llm.py`        provider adapters (Gemini, Groq, OpenRouter, Claude) behind one interface
- `demo_model.py` scripted stand-in for an LLM (NOT an AI), used for offline demos and tests
- `agent.py`      the agent loop (ask model, run tools, feed results back)
- `checker.py`    the 7 deterministic checks on the real output file
- `diagnose.py`   turns failed checks and tool errors into "which lever to change"
- `pipeline.py`   one full run: workspace, agent, check, diagnose, save log
- `compare.py`    runs every setup N times and saves a results table
- `runlog.py`, `caps.py`, `viewmodel.py`, `cli.py`
- `observe.py`    one structured JSON log line per run (no keys, no receipt text)
- `web_core.py`   all web API logic, no framework (tested)
- `app.py` (repo root) is the thin FastAPI wiring; `public/` is the page (HTML/CSS/JS); `scripts/dev_server.py` is a no-install preview server

## Rules to keep
1. The answer key is never copied into the agent's workspace.
2. Never commit API keys. Keys come from `.env` or Vercel environment variables, or the visitor pastes one.
3. The demo model is scripted. Anything it produces must be labelled DEMO in the UI, logs and README.
4. Numbers in the README must come from real measured runs. Never invent results.
5. Keep code simple and commented in plain English. Each file should stay readable by a beginner.

6. Only claim a concept (observability, reliability, evaluation, orchestration, fine-tuning...) in any doc, resume or post if a file in this repo does it. See the README concepts table and DECISIONS D26 and D27.

## Current status
- Core (tools, adapters, agent, checker, diagnosis, compare, CLI) is built and unit tested offline.
- The Gemini, Groq, OpenRouter and Claude adapters are tested against recorded response shapes only.
  They have NOT been called live yet: the first real run with a key is still to do.
- The page (public/) and web_core are tested in a real browser through scripts/dev_server.py.
  `app.py` (FastAPI) and the Vercel deploy have NOT been run yet: the build sandbox could not install FastAPI.
  First step on a real machine: `pip install -r requirements-dev.txt && uvicorn app:app --reload`.
- All offline tests pass (tests/test_api.py is skipped unless FastAPI is installed, so it has not run yet). CI runs them on GitHub (.github/workflows/ci.yml).
- Dockerfile, .dockerignore, docker-compose.yml and a CI `docker` job exist (D28) but the image has NOT been built yet: the build sandbox had no Docker daemon. First build happens in CI.
- README results table is empty on purpose until real runs are measured.
- README.md and BUILD_GUIDE.md are written. Remaining for the owner: live key test, real `compare` numbers, deploy to Vercel.

## Front end and media (added later)
- `public/index.html`, `style.css`, `app.js`: guided four-round page (rounds first, video in a modal, agent-vs-chatbot card). No framework, `textContent` only.
- `public/praxis-explainer.mp4/.webm`: explainer video built from HTML scenes + a real app recording (see DECISIONS D22, D23). Narration is a synthetic open-source voice; keep it disclosed.
- `docs/TECH_STACK.md` what each module, package and service is and where it comes from. `docs/FLOW.md` code flow, `docs/VOICEOVER_SCRIPT.md` narration, `docs/HIGGSFIELD_BRIEF.md` optional AI-video script.
- Wording rule: the agent-vs-chatbot difference is who drives the loop. Never claim a chatbot cannot use files or tools.

## Known gotchas
- Free-tier LLM keys hit rate limits quickly with agents. The adapters retry with backoff, but
  spread long `compare` runs over time or use a second provider.
- Model names change. Defaults live in `llm.py` and can be overridden with `AGENT_MODEL`.
