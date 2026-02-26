import streamlit as st
import praw
import time
import requests
import threading

# --- Top 5 Emergency Keywords ---
EMERGENCY_KEYWORDS = [
    "TurboModuleRegistry.getEnforcing", # React Native JSI/TurboModules missing native link
    "Undefined symbols for architecture arm64", # iOS M1/Simulator x86 mismatch or Swift/C++ link error
    "Execution failed for task ':app:mergeExtDexDebug'", # Android Gradle dependency clash (e.g., duplicated classes)
    "JNI DETECTED ERROR IN APPLICATION", # Android C++/Java bridge pointer crash
    "No visible @interface for 'RCTBridge'" # iOS Cocoapods header search path failure post-upgrade
]

st.set_page_config(page_title="Bounty Hunter 💰", layout="wide")

if "scanner_thread" not in st.session_state:
    st.session_state.scanner_thread = None
if "scanner_running" not in st.session_state:
    st.session_state.scanner_running = False

# --- Tunnel Check ---
def check_tunnel():
    """Pings the Gemma 3 model tunnel."""
    try:
        response = requests.get("https://ai.stoxsage.com/v1/models", timeout=3)
        return response.status_code == 200
    except requests.RequestException:
        return False

# --- Live Search Loop ---
def live_search_loop(client_id, client_secret, webhook_url):
    """Background thread that runs every 5 minutes (300s) pinging Discord."""
    reddit = praw.Reddit(
        client_id=client_id,
        client_secret=client_secret,
        user_agent="NativeBountyHunter/1.0"
    )
    
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
                
                for keyword in EMERGENCY_KEYWORDS:
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

# --- UI Layout ---
st.title("Target Acquisition: Native Bounties")

# Sidebar: Config & Tunnel Pulse
st.sidebar.title("System Status")
tunnel_ok = check_tunnel()
if tunnel_ok:
    st.sidebar.success("🟢 Tunnel Online (ai.stoxsage.com)")
else:
    st.sidebar.error("🔴 Tunnel Down (ai.stoxsage.com)")

st.sidebar.subheader("API Keys (T-Minus 48h Setup)")
reddit_client = st.sidebar.text_input("Reddit Client ID", type="password")
reddit_secret = st.sidebar.text_input("Reddit Secret", type="password")
discord_hook = st.sidebar.text_input("Discord Webhook", type="password")

if st.sidebar.button("Toggle Scanner"):
    st.session_state.scanner_running = not st.session_state.scanner_running
    if st.session_state.scanner_running:
        t = threading.Thread(target=live_search_loop, args=(reddit_client, reddit_secret, discord_hook), daemon=True)
        t.start()
        st.sidebar.success("Scanner armed. Pinging every 300s.")
    else:
        st.sidebar.warning("Scanner disarmed.")

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
for kw in EMERGENCY_KEYWORDS:
    st.code(kw)
