# Build guide: how we made Praxis, step by step

Read this once and you can explain every part in an interview.

## Why the name
Praxis means putting theory into practice. Interview line: "The course taught the theory of agents, context and feedback loops. Praxis is me putting it into practice, with a checker to prove it works."

CV line: *Praxis: a from-scratch AI agent that completes a task in a sandbox and is scored by code; tuned via context, workspace and instructions (Python, Streamlit, Gemini/Claude).*
GitHub repo: `praxis-agent`. Description: "Theory into practice: an AI agent that does a real task, then gets checked."

## 0. The one-minute story

> "I took the framework from Mercor's agents course and built it. An agent gets a goal, works in a sandbox
> with tools, produces a real spreadsheet, and a script checks it. When it scores badly, I change one of three
> levers (context, workspace, instructions) and measure again. I wrote the loop myself, with no framework,
> so I can say exactly what an agent is."

## 1. What is an agent? (course idea 1)
A chatbot answers. An agent **pursues a goal over several steps** using tools. The loop is:
ask the model → if it asks for a tool, run it → give it the result → repeat until it says it is finished.
That is `praxis/agent.py`.

## 2. The model has no memory (course idea 2)
Every call starts blank. So each turn we resend: the system prompt, the goal, and everything that happened so far.
Whatever is not in that bundle does not exist for the model. That is why **context** decides quality.

## 3. The workspace (course idea 3)
The agent can only act through tools we give it: `list_files`, `read_file`, `write_cell`, `write_rows`, and (in some setups) `add_sheet`.
`tools.py` makes this safe: a fresh copy of the receipts each run, no reading or writing outside it, formulas rejected,
and a hash check that the originals are untouched.

## 4. Trajectory and the feedback loop (course ideas 4 and 5)
Every step is recorded: what the agent said, which tool, what came back. Read it and you see *where* it went wrong.
`diagnose.py` turns that into advice: "euro receipt not converted → add the rate to **context**".
Then you change one lever and run again.

## 5. The files, in the order we built them
1. `receipts.py`: 24 receipts in 4 layouts, with deliberate traps, plus a private answer key.
2. `tools.py`: the sandbox and tools.
3. `llm.py`: provider adapters (see section 7).
4. `agent.py`: the loop.
5. `checker.py`: 7 deterministic checks on the real file.
6. `diagnose.py`, `pipeline.py`, `compare.py`: diagnose, run end to end, run all four setups several times.
7. `demo_model.py`: a scripted stand-in so everything can be tested with no key. **It is not an AI.**
8. `cli.py` and `app.py`: terminal and web front ends over the same code.
9. `tests/`: 97 tests, no network needed.

## 6. The web layer: FastAPI + a plain page
- **FastAPI** is a small Python web framework. `app.py` has a handful of routes (`/api/config`, `/api/run`, ...). Each one just calls a function in `praxis/web_core.py`, where the real logic lives and is tested.
- **The page** (`public/`) is plain HTML, CSS and JavaScript. No React, no build step. It calls the API.
- **Live updates:** `/api/run` streams the agent's steps with Server-Sent Events (SSE): the server sends one small message per step and the page prints it on the receipt tape as it arrives.
- **Why Vercel:** it hosts the page free on its CDN and runs the API as a serverless function. The Hobby plan allows functions up to 300 seconds with streaming, enough for a run.
- **Why not Streamlit/Gradio:** they are quicker, but free hosting for them was not available to us (Hugging Face now charges for Gradio/Docker Spaces). FastAPI plus a static page is also closer to what companies ship.

## 7. `llm.py` in plain words
Providers speak slightly different formats. We keep our own simple message format and have one small adapter per provider
that translates to and from it. The agent never knows which provider it is talking to. Switching = changing `LLM_PROVIDER`.
Adapters also retry on rate limits (429) and server errors, show friendly errors, and never put the key in a URL.

Free models are often weaker. So the README has a table where you record **which model** produced each score. That table is
a finding, not a flaw: it shows what the model, versus the levers, contributes.

## 8. Get a free key and run it
1. Go to Google AI Studio (aistudio.google.com) → "Get API key" (free tier).
2. `cp .env.example .env`, paste it as `GEMINI_API_KEY=...`.
3. `python -m praxis run --provider gemini --setup baseline`
4. If the model name is rejected, set `AGENT_MODEL` in `.env` to a current one from the provider's model list.
   (Defaults in `llm.py` were not verified live. This is the first thing to check.)

## 9. Collect real numbers
```bash
python -m praxis compare --provider gemini --runs 5
```
Copy the table into README "Results" with the model name. Never paste demo numbers there. If you hit rate limits, wait and rerun, or use `--provider groq`.
Optionally run a second model and add a second row for the comparison table.

## 10. Run the web app
```bash
pip install -r requirements-dev.txt
uvicorn app:app --reload          # open http://127.0.0.1:8000
```
No installs? `python scripts/dev_server.py` serves the same page and API using only the standard library. The page was tested in a real browser this way; the FastAPI wiring (`app.py`) was not run where it was built, so check it once: open the page, press Run with the demo model, and watch the tape fill.

## 11. Push to GitHub
```bash
git remote add origin https://github.com/<you>/praxis-agent.git
git push -u origin main
```
`.env` is git-ignored. Check `git status` shows no key before pushing.

## 12. Deploy free on Vercel
1. Push the repo to GitHub (section 11).
2. Go to vercel.com, sign in with GitHub, choose **Add New → Project**, and import `praxis-agent`.
3. Leave the framework on auto-detect (it finds `app.py`, a FastAPI app). No build command is needed.
4. Project → **Settings → Environment Variables**: add `GEMINI_API_KEY` (your free key) and `DAILY_RUN_CAP` (for example 20). Apply to Production, then redeploy.
5. Open the URL. Press Run with the demo model, then with Gemini.
6. Put the link in the README and under your certificate.

Things to know:
- `vercel.json` sets the function to 300 seconds and bundles the data folders it reads.
- The daily cap lives in the function's temp folder, so it is **best effort**: it can reset when Vercel starts a new instance. A free-tier Gemini key has its own limits, so use a key made only for this demo, or leave the host key off and let visitors paste their own.
- A live run makes about 30 model calls, so on a free Gemini key expect it to be slow or rate limited sometimes.

## 13. Interview questions you will get
- **How is this different from ChatGPT?** It acts: reads files, calls tools, produces a file, and is scored by code. A chat only replies.
- **Why no LangChain?** To understand the loop. It is about 100 lines.
- **How do you know it worked?** A checker opens the real file and tests 7 things against an answer key the agent never sees.
- **What if the model lies?** The checker doesn't read what it says, only the file.
- **What did you learn from the levers?** Report your real table. Say which model and how many runs.
- **Why FastAPI and a static page?** The API streams steps with SSE and the page stays simple. It also deploys free on Vercel.
- **Safety?** Sandboxed copy, path guards, write-only to one file, run cap, no uploads on the public demo.
- **What would you do next?** More tasks, more models, a larger set of receipts, an LLM-judge for open-ended outputs.

## 14. Describing your earlier contract work honestly
You can say: *"I worked on contract building sandboxed desktop-task environments for AI agents: task files, reset-to-clean
state, and automated graders that check the final file state. Praxis is my own small version of that idea."*
Don't name the client, don't claim a title you didn't hold, and don't say the project was assigned or reviewed by Mercor:
it applies the course's framework.
