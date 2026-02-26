import streamlit as st
import time
import requests
import threading
import asyncio
import json
import os
import yagmail
import discord
from pymongo import MongoClient
from datetime import datetime, timedelta, timezone
from collections import deque

SETTINGS_FILE = "settings.json"

# --- Default Configuration ---
DEFAULT_SETTINGS = {
    "discord_bot_token": "",
    "github_token": "",
    "mongo_uri": "",
    "ai_base_url": "https://ai.stoxsage.com/v1",
    "ai_api_key": "",
    "ai_model": "gemma-3",
    "email_address": "",
    "email_app_password": "",
    "emergency_keywords": ["help", "bug", "emergency", "error", "crash", "native module", "scraper"],
    "github_keywords": ["bounty", "help wanted"],
    "hn_keywords": ["freelance", "bug", "bounty"]
}

def load_settings():
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r") as f:
                settings = json.load(f)
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

app_settings = load_settings()

st.set_page_config(page_title="Antigravity Lead Radar 💰", layout="wide")

# Persistent state for background thread across streamlit reruns
@st.cache_resource
def get_scanner_state():
    class ScannerState:
        discord_running = False
        github_running = False
        hn_running = False
        
        discord_thread = None
        github_thread = None
        hn_thread = None
        
        loop = None
        client = None
        
        logs = deque(maxlen=50) # Maintain last 50 log events
        
        def log(self, msg):
            timestamp = datetime.now().strftime("%H:%M:%S")
            self.logs.appendleft(f"[{timestamp}] {msg}")
            
    return ScannerState()

scanner_state = get_scanner_state()

# --- Database Connection ---
@st.cache_resource
def get_db_collection(uri):
    if not uri:
        return None
    try:
        client = MongoClient(uri, serverSelectionTimeoutMS=5000)
        client.admin.command('ping')  # Establish connection
        return client.antigravity.leads
    except Exception as e:
        return None

# --- AI Backend Integration ---
def generate_pitch(lead, settings):
    url = f"{settings['ai_base_url'].rstrip('/')}/chat/completions"
    headers = {
        "Content-Type": "application/json"
    }
    if settings.get("ai_api_key"):
        headers["Authorization"] = f"Bearer {settings['ai_api_key']}"
        
    prompt = f"""You are a Senior Full-Stack Engineer looking to provide technical solutions as a service.
You need to help an engineering user with a specific issue. 
Diagnose the problem/request from the following {lead['source']} post and draft a friendly, professional DM offering a 30-min live fix or implementation for roughly $50-$100 depending on complexity. 
Your tone should be autonomous, confident, yet human. Prove you know the solution.

Title: {lead['title']}
Content: {lead['content']}
"""
    
    payload = {
        "model": settings.get("ai_model", "gemma-3"),
        "messages": [{"role": "user", "content": prompt}]
    }
    
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=30)
        resp_json = resp.json()
        if "choices" in resp_json and len(resp_json["choices"]) > 0:
            return resp_json["choices"][0]["message"]["content"]
        else:
            return f"Unexpected API Response: {resp_json}"
    except Exception as e:
        return f"Error generating pitch: {str(e)}"

# --- Scanner Loops ---
def run_discord_scanner():
    """Background thread that runs the Discord Bot Scanner."""
    settings = load_settings()
    col = get_db_collection(settings["mongo_uri"])
    token = settings.get("discord_bot_token", "")
    
    if not token or col is None:
        scanner_state.log("❌ Discord Scanner failed to start (Missing Token or DB).")
        scanner_state.discord_running = False
        return
        
    scanner_state.log("👾 Initializing Discord Client...")
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    scanner_state.loop = loop
    
    intents = discord.Intents.default()
    intents.message_content = True
    
    client = discord.Client(intents=intents)
    scanner_state.client = client
    
    @client.event
    async def on_ready():
        scanner_state.log(f"✅ Logged into Discord as {client.user} - Listening!")
        
    @client.event
    async def on_message(message):
        if not scanner_state.discord_running:
            await client.close()
            return
            
        if message.author == client.user or message.author.bot:
            return
            
        text_to_search = message.content.lower()
        matched_kw = None
        keywords = load_settings().get("emergency_keywords", [])
        
        for keyword in keywords:
            if keyword.lower() in text_to_search:
                matched_kw = keyword
                break
                
        if matched_kw:
            if col.find_one({"source_id": f"discord_{message.id}"}):
                return
            
            scanner_state.log(f"👾 Discord Match: '{matched_kw}' by {message.author.name}")
            dt = datetime.fromtimestamp(message.created_at.timestamp(), timezone.utc)
            channel_name = message.channel.name if hasattr(message.channel, 'name') else "DM"
            server_name = message.guild.name if message.guild else "Direct Message"
            
            lead_doc = {
                "source_id": f"discord_{message.id}",
                "title": f"Message in #{channel_name} ({server_name}) from {message.author.name}",
                "url": message.jump_url,
                "content": message.content[:2000],
                "tag": f"#{channel_name}",
                "source": "Discord",
                "matched_keyword": matched_kw,
                "status": "New",
                "created_at": dt,
                "generated_pitch": ""
            }
            col.insert_one(lead_doc)

    try:
        loop.run_until_complete(client.start(token))
    except Exception as e:
        scanner_state.log(f"❌ Discord Scanner Error: {str(e)}")
    finally:
        scanner_state.discord_running = False
        scanner_state.log("🛑 Discord Scanner Stopped.")


def run_github_scanner():
    """Background thread for GitHub REST API."""
    settings = load_settings()
    col = get_db_collection(settings["mongo_uri"])
    gh_token = settings.get("github_token", "")
    
    if col is None:
        scanner_state.log("❌ GitHub Scanner failed (No DB).")
        scanner_state.github_running = False
        return
        
    scanner_state.log("🐙 GitHub Scanner started.")
    headers = {"Accept": "application/vnd.github.v3+json"}
    if gh_token: headers["Authorization"] = f"token {gh_token}"
            
    while scanner_state.github_running:
        settings = load_settings()
        github_keywords = settings.get("github_keywords", [])
        
        for gh_kw in github_keywords:
            if not scanner_state.github_running: break
            scanner_state.log(f"🐙 Querying GitHub for: {gh_kw}")
            
            try:
                url = "https://api.github.com/search/issues"
                # Added filters to avoid issues labeled as "hardware" or "hard"
                q = f"{gh_kw} is:issue is:open -label:hardware -label:hard"
                params = {"q": q, "sort": "created", "order": "desc", "per_page": 50}
                resp = requests.get(url, params=params, headers=headers, timeout=15)
                
                if resp.status_code == 200:
                    for issue in resp.json().get("items", []):
                        issue_id = issue.get("id")
                        if col.find_one({"source_id": f"gh_{issue_id}"}):
                            continue
                            
                        scanner_state.log(f"🐙 GitHub Match: {issue.get('title')[:30]}...")
                        dt = datetime.fromisoformat(issue.get("created_at").replace('Z', '+00:00'))
                        lead_doc = {
                            "source_id": f"gh_{issue_id}",
                            "title": issue.get("title", ""),
                            "url": issue.get("html_url", ""),
                            "content": issue.get("body", "No description provided.")[:2000],
                            "tag": gh_kw,
                            "source": "GitHub",
                            "matched_keyword": gh_kw,
                            "status": "New",
                            "created_at": dt,
                            "generated_pitch": ""
                        }
                        col.insert_one(lead_doc)
            except Exception as e:
                scanner_state.log(f"❌ GitHub API Error: {str(e)}")
            
            time.sleep(5) # Throttle GH requests

        if not scanner_state.github_running: break
        scanner_state.log("🐙 GitHub Scanner sleeping for 5 minutes...")
        for _ in range(300):
            if not scanner_state.github_running: break
            time.sleep(1)
            
    scanner_state.log("🛑 GitHub Scanner Stopped.")


def run_hn_scanner():
    """Background thread for HackerNews Algolia API."""
    settings = load_settings()
    col = get_db_collection(settings["mongo_uri"])
    
    if col is None:
        scanner_state.log("❌ HN Scanner failed (No DB).")
        scanner_state.hn_running = False
        return

    scanner_state.log("📰 HackerNews Scanner started.")
    while scanner_state.hn_running:
        settings = load_settings()
        hn_keywords = settings.get("hn_keywords", [])
        
        for hn_kw in hn_keywords:
            if not scanner_state.hn_running: break
            scanner_state.log(f"📰 Querying HackerNews for: {hn_kw}")
            
            try:
                url = "http://hn.algolia.com/api/v1/search_by_date"
                params = {"query": hn_kw, "tags": "story", "hitsPerPage": 50}
                resp = requests.get(url, params=params, timeout=15)
                
                if resp.status_code == 200:
                    for hit in resp.json().get("hits", []):
                        hit_id = hit.get("objectID")
                        if col.find_one({"source_id": f"hn_{hit_id}"}):
                            continue
                            
                        scanner_state.log(f"📰 HN Match: {hit.get('title')[:30]}...")
                        created_at = hit.get("created_at_i")
                        if created_at:
                            dt = datetime.fromtimestamp(created_at, timezone.utc)
                        else:
                            dt = datetime.now(timezone.utc)
                            
                        url = hit.get("url")
                        if not url:
                            url = f"https://news.ycombinator.com/item?id={hit_id}"
                        
                        story_text = hit.get("story_text") or ""
                        lead_doc = {
                            "source_id": f"hn_{hit_id}",
                            "title": hit.get("title", ""),
                            "url": url,
                            "content": story_text[:2000],
                            "tag": hn_kw,
                            "source": "HackerNews",
                            "matched_keyword": hn_kw,
                            "status": "New",
                            "created_at": dt,
                            "generated_pitch": ""
                        }
                        col.insert_one(lead_doc)
            except Exception as e:
                scanner_state.log(f"❌ HN API Error: {str(e)}")
                
            time.sleep(3) # Throttle HN requests

        if not scanner_state.hn_running: break
        scanner_state.log("📰 HackerNews Scanner sleeping for 5 minutes...")
        for _ in range(300):
            if not scanner_state.hn_running: break
            time.sleep(1)
            
    scanner_state.log("🛑 HackerNews Scanner Stopped.")


# --- Navigation & UI ---
st.sidebar.title("Navigation")
page = st.sidebar.radio("Go to", ["Dashboard", "Settings"])

leads_col = get_db_collection(app_settings["mongo_uri"])

if page == "Settings":
    st.title("System Settings")
    st.subheader("General Configuration")
    
    with st.form("settings_form"):
        st.markdown("**1. Database**")
        st.caption("🔗 [Get MongoDB URI from MongoDB Atlas](https://cloud.mongodb.com/)")
        mongo_uri = st.text_input("MongoDB Connection String URI", value=app_settings.get("mongo_uri", ""), type="password")
        
        st.markdown("**2. AI & Emailing Tools**")
        col1, col2 = st.columns(2)
        with col1:
            ai_base_url = st.text_input("AI Base URL", value=app_settings.get("ai_base_url", "https://ai.stoxsage.com/v1"))
            ai_model = st.text_input("AI Model Name", value=app_settings.get("ai_model", "gemma-3"))
        with col2:
            ai_api_key = st.text_input("AI API Key", value=app_settings.get("ai_api_key", ""), type="password")
            email_address = st.text_input("Gmail Address", value=app_settings.get("email_address", ""))
            email_app_password = st.text_input("Gmail App Password", value=app_settings.get("email_app_password", ""), type="password")

        st.markdown("**3. Platform API Keys**")
        st.caption("Optional configuration to expand scanning breadth or rate limits.")
        col3, col4 = st.columns(2)
        with col3:
            st.markdown("🚨 **[Click here to get a Discord Bot Token](https://discord.com/developers/applications)**")
            st.caption("To use, create a New Application -> Bot -> Reset Token -> Copy. Make sure to toggle **Message Content Intent** ON under the Bot tab before saving!")
            discord_bot_token = st.text_input("Discord Bot Token", value=app_settings.get("discord_bot_token", ""), type="password")
        with col4:
            st.markdown("🐙 **[Click here to get a GitHub Token](https://github.com/settings/tokens/new)**")
            st.caption("A Fine-grained token or Classic Token (no scopes required) increases the Rate Limit of searches from 10 to 30 requests per minute.")
            github_token = st.text_input("GitHub Token (Increases Rate Limit)", value=app_settings.get("github_token", ""), type="password")
        
        st.markdown("**4. Scraper Keywords / Parameters**")
        kw1, kw2, kw3 = st.columns(3)
        with kw1:
            discord_keywords = st.text_area("Discord Emergency Keywords", value="\n".join(app_settings.get("emergency_keywords", [])), height=150)
        with kw2:
            github_keywords = st.text_area("GitHub Keywords (e.g. bounty, bug)", value="\n".join(app_settings.get("github_keywords", [])), height=150)
        with kw3:
            hn_keywords = st.text_area("HackerNews/Indie Keywords", value="\n".join(app_settings.get("hn_keywords", [])), height=150)
            
        submitted = st.form_submit_button("Save Settings")
        if submitted:
            app_settings["mongo_uri"] = mongo_uri
            app_settings["discord_bot_token"] = discord_bot_token
            app_settings["github_token"] = github_token
            app_settings["ai_base_url"] = ai_base_url
            app_settings["ai_api_key"] = ai_api_key
            app_settings["ai_model"] = ai_model
            app_settings["email_address"] = email_address
            app_settings["email_app_password"] = email_app_password
            app_settings["emergency_keywords"] = [k.strip() for k in discord_keywords.split("\n") if k.strip()]
            app_settings["github_keywords"] = [k.strip() for k in github_keywords.split("\n") if k.strip()]
            app_settings["hn_keywords"] = [k.strip() for k in hn_keywords.split("\n") if k.strip()]
            
            save_settings(app_settings)
            st.cache_resource.clear()
            st.success("Settings saved successfully!")


elif page == "Dashboard":
    st.title("Antigravity Lead Radar 📡")

    # --- Sidebar Controls ---
    st.sidebar.title("Scanner Control")
    
    if leads_col is not None:
        st.sidebar.success("🟢 MongoDB Connected")
    else:
        st.sidebar.error("🔴 MongoDB Disconnected / Not Configured")

    st.sidebar.markdown("### Manual Control")
    
    # Check if DB configured for interactions
    is_ready = bool(app_settings.get("mongo_uri"))
    
    # Discord Toggle
    target_discord = st.sidebar.toggle("Discord Scanner", value=scanner_state.discord_running, disabled=not is_ready)
    if target_discord != scanner_state.discord_running:
        if target_discord and app_settings.get("discord_bot_token"):
            scanner_state.discord_running = True
            t_d = threading.Thread(target=run_discord_scanner, daemon=True)
            scanner_state.discord_thread = t_d
            t_d.start()
        elif target_discord:
            st.sidebar.error("Missing Discord Token")
        else:
            scanner_state.discord_running = False
            if scanner_state.client and scanner_state.loop:
                try: asyncio.run_coroutine_threadsafe(scanner_state.client.close(), scanner_state.loop)
                except: pass
        if app_settings.get("discord_bot_token") or not target_discord: st.rerun()

    # GitHub Toggle
    target_github = st.sidebar.toggle("GitHub Scanner", value=scanner_state.github_running, disabled=not is_ready)
    if target_github != scanner_state.github_running:
        if target_github:
            scanner_state.github_running = True
            t_g = threading.Thread(target=run_github_scanner, daemon=True)
            scanner_state.github_thread = t_g
            t_g.start()
        else:
            scanner_state.github_running = False
        st.rerun()

    # HN Toggle
    target_hn = st.sidebar.toggle("HackerNews Scanner", value=scanner_state.hn_running, disabled=not is_ready)
    if target_hn != scanner_state.hn_running:
        if target_hn:
            scanner_state.hn_running = True
            t_h = threading.Thread(target=run_hn_scanner, daemon=True)
            scanner_state.hn_thread = t_h
            t_h.start()
        else:
            scanner_state.hn_running = False
        st.rerun()

    running_any = scanner_state.discord_running or scanner_state.github_running or scanner_state.hn_running
    if running_any:
        st.sidebar.success("Status: **ACTIVE**")
    else:
        st.sidebar.warning("Status: **IDLE**")

    # --- Main Content Tabs ---
    tab1, tab2, tab3 = st.tabs(["Live Feed (Last 24 Hours)", "Archive Database", "System Logs / Terminal"])

    with tab1:
        st.subheader("New Targets")
        if leads_col is None:
            st.warning("Connect Database to view Live Feed.")
        else:
            time_filter = st.selectbox("Show leads from the last:", ["24 Hours", "3 Days", "7 Days", "30 Days"])
            hours = 24
            if time_filter == "3 Days": hours = 72
            elif time_filter == "7 Days": hours = 168
            elif time_filter == "30 Days": hours = 720
                
            lookback_time = datetime.now(timezone.utc) - timedelta(hours=hours)
            cursor = leads_col.find({
                "status": "New", 
                "created_at": {"$gte": lookback_time}
            }).sort("created_at", -1)
            
            fresh_leads = list(cursor)
            
            if len(fresh_leads) == 0:
                st.info(f"No fresh leads found in the last {time_filter}. Keep scanning!")
            
            for lead in fresh_leads:
                lead_tag = lead.get('tag', 'Unknown')
                source_emoji = "👾" if lead['source'] == "Discord" else ("🐙" if lead['source'] == "GitHub" else "📰")
                
                with st.expander(f"{source_emoji} [{lead['source']} - {lead_tag}] {lead['title']}", expanded=True):
                    st.caption(f"Matched Keyword: `{lead['matched_keyword']}` | Posted: {lead['created_at'].strftime('%Y-%m-%d %H:%M:%S UTC')}")
                    content_preview = lead['content'][:500] if lead['content'] else "No text provided."
                    st.markdown(f"**Description:**\n\n> {content_preview}...")
                    st.markdown(f"[🔗 View Original Post]({lead['url']})")
                    
                    if st.button("Generate AI Pitch & Move to Pitched", key=f"pitch_{lead['_id']}"):
                        with st.spinner(f"Requesting {app_settings['ai_model']} from {app_settings['ai_base_url']}..."):
                            pitch_text = generate_pitch(lead, app_settings)
                            
                        leads_col.update_one(
                            {"_id": lead["_id"]}, 
                            {"$set": {"status": "Pitched", "generated_pitch": pitch_text}}
                        )
                        st.success("Pitch generated! Lead moved to Archive -> Pitched.")
                        st.rerun()

    with tab2:
        st.subheader("Lead Archive")
        if leads_col is None:
            st.warning("Connect Database to view Archive.")
        else:
            colA, colB = st.columns(2)
            with colA:
                filter_status = st.selectbox("Status Filter", ["All", "New", "Pitched", "Fixed"])
            with colB:
                filter_sub = st.text_input("Source/Keywords Search Filter", value="")
                
            query = {}
            if filter_status != "All":
                query["status"] = filter_status
            if filter_sub.strip():
                query["$or"] = [
                    {"source": {"$regex": filter_sub.strip(), "$options": "i"}},
                    {"tag": {"$regex": filter_sub.strip(), "$options": "i"}}
                ]
                
            archive_cursor = leads_col.find(query).sort("created_at", -1).limit(50)
            archived_leads = list(archive_cursor)
            
            st.caption(f"Showing up to {len(archived_leads)} recent archived leads...")
            
            for lead in archived_leads:
                icon = "🟢" if lead["status"] == "New" else ("🔵" if lead["status"] == "Pitched" else "✅")
                lead_tag = lead.get('tag', 'Unknown')
                source_emoji = "👾" if lead['source'] == "Discord" else ("🐙" if lead['source'] == "GitHub" else "📰")
                
                with st.expander(f"{icon} {source_emoji} [{lead['status']}] {lead['title']} - [{lead_tag}]"):
                    st.markdown(f"[🔗 Source Link]({lead['url']})")
                    if lead.get("generated_pitch"):
                        st.markdown("**Generated Pitch:**")
                        st.info(lead["generated_pitch"])
                    
                    if app_settings.get("email_address") and app_settings.get("email_app_password") and lead.get("generated_pitch"):
                        archive_receiver_email = st.text_input("Recipient Email", key=f"arc_rec_email_{lead['_id']}")
                        if st.button("Send Pitch via Email", key=f"arc_send_email_{lead['_id']}"):
                             if not archive_receiver_email:
                                  st.error("Please enter a recipient email.")
                             else:
                                 try:
                                     with st.spinner("Sending email..."):
                                         yag = yagmail.SMTP(app_settings["email_address"], app_settings["email_app_password"])
                                         yag.send(
                                             to=archive_receiver_email,
                                             subject=f"Re: Solution/Proposal for {lead['title']}",
                                             contents=lead["generated_pitch"]
                                         )
                                     st.success(f"Email sent to {archive_receiver_email}!")
                                 except Exception as e:
                                     st.error(f"Failed to send email: {str(e)}")

                    new_status = st.selectbox("Update Status", ["New", "Pitched", "Fixed"], 
                                              index=["New", "Pitched", "Fixed"].index(lead["status"] if lead["status"] in ["New", "Pitched", "Fixed"] else "New"),
                                              key=f"status_{lead['_id']}")
                    if new_status != lead["status"]:
                        leads_col.update_one({"_id": lead["_id"]}, {"$set": {"status": new_status}})
                        st.success(f"Status updated to {new_status}!")
                        st.rerun()

    with tab3:
        st.subheader("Scanner Terminal Output")
        st.caption("This live log shows precisely what the scanners are searching behind the scenes.")
        
        # Action Bar
        col1, col2 = st.columns([1, 10])
        with col1:
             st.button("🔄 Refresh")
             
        log_text = "\n".join(scanner_state.logs)
        st.code(log_text if log_text else "Scanner is idle. System logs will appear here...", language="text")
