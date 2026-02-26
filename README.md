# Antigravity Lead Radar 💰

An autonomous scanning and sales dashboard built explicitly to find engineering leads where autonomous AI assistance or custom human-driven expertise can secure bounties ($50 - $500 per request).

## Architecture Stack

*   **Backend Scanner:** Python, `praw` (Reddit API)
*   **Database:** MongoDB Atlas (`pymongo`)
*   **AI Integration:** Agnostic. Works out of the box with custom endpoints (e.g. `https://ai.stoxsage.com/v1` for a local Gemma-3 instance) or standard OpenAI-compatible endpoints by specifying the URL, API Key, and Model string.
*   **Frontend UI:** Streamlit (`streamlit`)

---

## 🚀 Deployment to Streamlit Cloud

Streamlit Community Cloud allows you to deploy Python apps directly from your GitHub repository for free.

### Step 1: Push to GitHub
Upload this exact directory (`app.py`, `README.md`, and any `requirements.txt` you create) to a public or private GitHub repository.

You will need a `requirements.txt` file at the root of your repository so Streamlit Cloud installs your project dependencies. Create a file called `requirements.txt` containing the following:
```text
streamlit
praw
pymongo
requests
```

### Step 2: Connect Streamlit Cloud
1. Go to [share.streamlit.io](https://share.streamlit.io/) and log in with your GitHub account.
2. Click **New app**.
3. Point Streamlit to your Repository, Branch, and specify the Main file path as `app.py`.
4. Click **Deploy!**

### Step 3: Configure Settings State Persistence (IMPORTANT!)
This application features a dynamic UI configuration menu that saves your sensitive tokens (API keys, Mongo URI) into a `settings.json` file on disk.

Because Streamlit Cloud containers are ephemeral (they sleep when inactive and wipe changes to local disk), **your configurations will wipe if the container reboots.** 

To circumvent this and secure your keys:
1. In your deployed Streamlit App site, click the `...` menu icon in the top right corner.
2. Select **Settings** -> **Secrets**.
3. While the UI dynamically generates `settings.json`, passing standard environment variables inside the Streamlit Secrets TOML box allows standard OS persistence if you decide to modify `app.py` directly to read from `st.secrets` in the future.
4. *Alternatively, simply re-enter your tokens into the Settings UI if your container restarts, and everything will pick up right where it left off from your MongoDB Database since the lead state exists outside of Streamlit.*

---

## Features

1.  **AI Agnostic Generation:** Plug in **ANY** AI endpoint compatible with OpenAI's Chat specification. Enter your URL, Key, and Model name to automatically construct $100 pitch DMs tailored instantly to a user's technical problem.
2.  **State Management (MongoDB):** Real-time tracking of leads (`New` / `Pitched` / `Fixed`) with full text search archiving. Leads are pulled dynamically limiting duplication via `reddit_id` tracking.
3.  **Live 24h Feed:** Tracks only freshly scraped posts for high-conversion triage within the crucial first 24-hours of someone requesting emergency help.
4.  **Discord Pinging:** Webhook triggering so you don't even need the dashboard open to be alerted about a potential payout target.
