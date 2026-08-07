# AI Open Source Mentor++

A hackathon MVP that helps developers onboard to unfamiliar GitHub repos:
repo Q&A, issue recommendation, a learning roadmap, and a PR readiness check.

This README assumes you've never set up a Python backend before. Follow it top to bottom.

## Folder structure

```
ai-oss-mentor/
├── .env.example        # template for your secret keys — copy this to .env
├── .gitignore
├── requirements.txt     # Python packages this project needs
├── config.py            # loads .env into one place
├── main.py              # the web server — this is what you run
├── indexing.py              # Step 1: turns a repo into a searchable knowledge base
├── rag_qa.py                # Step 2: answers questions using that knowledge base
├── issue_recommendation.py  # recommends a good issue to start on
├── learning_roadmap.py      # generates a reading order for the repo
├── pr_readiness.py          # checks a PR diff before you submit it
├── github_client.py  # talks to GitHub's API
├── embeddings.py     # chunks text and turns it into vectors
├── vector_store.py   # stores and searches those vectors (Chroma, runs locally)
└── data/
    └── chroma/            # the local database gets created here automatically
```

## 1. Install Python

You need Python 3.10 or newer. Check with:
```bash
python3 --version
```
If you don't have it, download from https://www.python.org/downloads/

## 2. Set up a virtual environment

This keeps this project's packages separate from everything else on your machine.

```bash
cd ai-oss-mentor
python3 -m venv .venv

# activate it — do this every time you open a new terminal for this project
source .venv/bin/activate        # Mac/Linux
.venv\Scripts\activate           # Windows
```

You'll know it worked because your terminal prompt will show `(.venv)` at the start.

## 3. Install the packages

```bash
pip install -r requirements.txt
```

## 4. Set up your API keys

```bash
cp .env.example .env
```

Now open `.env` in any text editor and fill in:

- **GROQ_API_KEY** — required. Get one free at https://console.groq.com/keys
- **GEMINI_API_KEY** — required (used for embeddings). Get one free at https://aistudio.google.com/apikey
- **GITHUB_TOKEN** — optional but recommended. Get one at https://github.com/settings/tokens
  → "Generate new token (classic)" → check the `repo` box → generate.
  Without this, you can still use public repos but you'll hit GitHub's rate limit quickly.

Leave the other variables as-is unless you know you want to change them.

## 5. Run the server

```bash
uvicorn main:app --reload
```

You should see something like `Uvicorn running on http://127.0.0.1:8000`.

## 6. Try it out

Open **http://127.0.0.1:8000/docs** in your browser. This is an automatic
interactive test page — you can try every endpoint from here without writing
any code.

The order to try things in:

1. **POST /index** — body: `{"repo_url": "https://github.com/some/small-repo"}`
   Do this first for any repo. Pick a small public repo for your first test —
   indexing a huge repo takes longer and costs more in API calls.
2. **POST /ask** — body: `{"repo_url": "...", "question": "What does this repo do?"}`
3. **GET /recommend-issue** — query param `repo_url`
4. **POST /roadmap** — body: `{"repo_url": "..."}`
5. **POST /pr-check** — body: `{"diff_text": "...paste a git diff here..."}`

## Common problems

- **Auth/API errors from Groq or Gemini** — you forgot step 4, or forgot to save `.env`
- **GitHub rate limit errors** — add a `GITHUB_TOKEN` (step 4)
- **Indexing takes a while / costs API credit** — this is normal; each file
  gets split into chunks and each chunk calls the embeddings API. Start with
  a small repo (under ~50 files) for your first test.
- **`ModuleNotFoundError`** — make sure your virtual environment is activated
  (you should see `(.venv)` in your prompt) and that you ran `pip install -r requirements.txt`

## What's not built yet (see the original plan)

- Repository architecture/dependency visualization
- Similar PR retrieval for PR readiness (the module has a comment showing
  exactly where to plug it in)
- The n8n webhook automation for auto-triggering indexing on repo updates
- A frontend — right now everything is tested through `/docs`
