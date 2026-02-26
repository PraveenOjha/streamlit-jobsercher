import streamlit as st
import praw
import time
import requests
import threading
import json
import os

SETTINGS_FILE = "settings.json"

# --- Default Configuration ---
DEFAULT_SETTINGS = {
    "reddit_client": "",
    "reddit_secret": "",
    "discord_hook": "",
    "tunnel_url": "https://ai.stoxsage.com/v1/models",
    "emergency_keywords": [
        "TurboModuleRegistry.getEnforcing", # React Native JSI/TurboModules missing native link
        "Undefined symbols for architecture arm64", # iOS M1/Simulator x86 mismatch or Swift/C++ link error
        "Execution failed for task ':app:mergeExtDexDebug'", # Android Gradle dependency clash (e.g., duplicated classes)
        "JNI DETECTED ERROR IN APPLICATION", # Android C++/Java bridge pointer crash
        "No visible @interface for 'RCTBridge'" # iOS Cocoapods header search path failure post-upgrade
    ]
}

def load_settings():
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r") as f:
                settings = json.load(f)
                # Ensure all default keys exist
                for k, v in DEFAULT_SETTINGS.items():
                    if k not in settings:
                        settings[k] = v
                return settings
        except Exception:
            pass
    return DEFAULT_SETTINGS.copy()

def save_settings(settings):
    with open(SETTINGS_FILE, "w") as f:
        json.dump(settings, f, indent=4)

# Load current settings into a variable
app_settings = load_settings()

st.set_page_config(page_title="Bounty Hunter 💰", layout="wide")

if "scanner_thread" not in st.session_state:
    st.session_state.scanner_thread = None
if "scanner_running" not in st.session_state:
    st.session_state.scanner_running = False

# --- Tunnel Check ---
def check_tunnel(url):
    """Pings the Gemma 3 model tunnel."""
    if not url:
        return False
    try:
        response = requests.get(url, timeout=3)
        return response.status_code == 200
    except requests.RequestException:
        return False

# --- Live Search Loop ---
def live_search_loop(client_id, client_secret, webhook_url, keywords):
    """Background thread that runs every 5 minutes (300s) pinging Discord."""
    try:
        reddit = praw.Reddit(
            client_id=client_id,
            client_secret=client_secret,
            user_agent="NativeBountyHunter/1.0"
        )
    except Exception as e:
        return
    
    # Track seen posts to avoid duplicate Discord pings
    seen_posts = set()

    while st.session_state.scanner_running:
        try:
            # Subreddits where these native crashes appear most
            subreddit = reddit.subreddit("reactnative+iosprogramming+androiddev")
            for submission in subreddit.new(limit=20):
                if submission.id in seen_posts:
                    continue
                
                text_to_search = f"{submission.title} {submission.selftext}".lower()
                
                for keyword in keywords:
                    if keyword.lower() in text_to_search:
                        # Pattern Match trigger
                        if webhook_url:
                            payload = {
                                "content": f"🚨 **NATIVE EMERGENCY DETECTED** 🚨\n**Keyword:** `{keyword}`\n**Link:** https://reddit.com{submission.permalink}\n*Time to act: < 5 mins.*"
                            }
                            requests.post(webhook_url, json=payload)
                        
                        seen_posts.add(submission.id)
                        break 
        except Exception as e:
            # Silent fail for the background task, could log locally
            pass
            
        # The 300s ping loop as per Golden Rules
        time.sleep(300)

# --- Navigation ---
st.sidebar.title("Navigation")
page = st.sidebar.radio("Go to", ["Dashboard", "Settings"])

if page == "Settings":
    st.title("System Settings")
    st.subheader("API Keys (T-Minus 48h Setup)")
    
    with st.form("settings_form"):
        reddit_client = st.text_input("Reddit Client ID", value=app_settings["reddit_client"], type="password")
        reddit_secret = st.text_input("Reddit Secret", value=app_settings["reddit_secret"], type="password")
        discord_hook = st.text_input("Discord Webhook", value=app_settings["discord_hook"], type="password")
        tunnel_url = st.text_input("Tunnel URL", value=app_settings["tunnel_url"])
        
        st.subheader("Emergency Keywords")
        st.info("Enter one keyword per line.")
        keywords_text = st.text_area("Keywords", value="\n".join(app_settings["emergency_keywords"]), height=200)
        
        submitted = st.form_submit_button("Save Settings")
        if submitted:
            app_settings["reddit_client"] = reddit_client
            app_settings["reddit_secret"] = reddit_secret
            app_settings["discord_hook"] = discord_hook
            app_settings["tunnel_url"] = tunnel_url
            app_settings["emergency_keywords"] = [k.strip() for k in keywords_text.split("\n") if k.strip()]
            save_settings(app_settings)
            st.success("Settings saved successfully!")


elif page == "Dashboard":
    # --- UI Layout ---
    st.title("Target Acquisition: Native Bounties")

    # Sidebar: Config & Tunnel Pulse
    st.sidebar.title("System Status")
    tunnel_ok = check_tunnel(app_settings["tunnel_url"])
    if tunnel_ok:
        st.sidebar.success(f"🟢 Tunnel Online")
    else:
        st.sidebar.error(f"🔴 Tunnel Down")

    if st.sidebar.button("Toggle Scanner"):
        if not app_settings["reddit_client"] or not app_settings["reddit_secret"]:
            st.sidebar.error("Error: Please configure Reddit API keys in Settings.")
        else:
            st.session_state.scanner_running = not st.session_state.scanner_running
            if st.session_state.scanner_running:
                t = threading.Thread(
                    target=live_search_loop, 
                    args=(app_settings["reddit_client"], app_settings["reddit_secret"], app_settings["discord_hook"], app_settings["emergency_keywords"]), 
                    daemon=True
                )
                t.start()
                st.session_state.scanner_thread = t
                st.sidebar.success("Scanner armed. Pinging every 300s.")
            else:
                st.sidebar.warning("Scanner disarmed.")

    if st.session_state.scanner_running:
        st.sidebar.success("Scanner is CURRENTLY ARMED and running in background.")

    # Main: The Template & Pitch Generator
    st.subheader("Manual Lead Evaluation")

    # The Loom Button Rule
    loom_link = st.text_input("🔗 The 'Loom' Link (Pre-recorded Native Fix):", value="https://www.loom.com/share/your-native-fix-video-id")

    lead_data = st.text_area("LEAD DATA: [Paste Reddit/Twitter post here]", height=150)

    if st.button("Generate Triage DM (Dry Run)"):
        if not lead_data:
            st.error("Missing Lead Data.")
        else:
            # In the final version, this prompt gets sent via ai.stoxsage.com/v1/chat/completions to Gemma 3.
            # For now, generating the exact requested template output.
            st.markdown("### Suggested Outreach DM:")
            st.info(f'''This looks like a **[Extracted Native Architecture/Linking]** error.

I'm on Garuda Linux/Gemma 3, can fix this in 30 mins via Zoom for a $100 bounty. I handle the Java/Swift native parts that standard devs miss.

Watch how I fixed this exact module issue here: {loom_link}''')

    st.divider()
    st.subheader("Configured Emergency Keywords")
    if not app_settings["emergency_keywords"]:
        st.info("No keywords configured. Add some in Settings.")
    else:
        for kw in app_settings["emergency_keywords"]:
            st.code(kw)
