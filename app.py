import streamlit as st
import time
import requests
import threading
import json
import os
import yagmail
from pymongo import MongoClient
from datetime import datetime, timedelta, timezone

SETTINGS_FILE = "settings.json"

# --- Default Configuration ---
DEFAULT_SETTINGS = {
    "discord_hook": "",
    "mongo_uri": "",
    "ai_base_url": "https://ai.stoxsage.com/v1",
    "ai_api_key": "",
    "ai_model": "gemma-3",
    "email_address": "",
    "email_app_password": "",
    "tags": ["react-native", "python", "javascript"],
    "emergency_keywords": ["help", "bug", "emergency", "error", "crash", "native module", "scraper"]
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

if "scanner_thread" not in st.session_state:
    st.session_state.scanner_thread = None
if "scanner_running" not in st.session_state:
    st.session_state.scanner_running = False

# --- Database Connection ---
@st.cache_resource
def get_db_collection(uri):
    if not uri:
        return None
    try:
        client = MongoClient(uri, serverSelectionTimeoutMS=5000)
        client.admin.command('ping')  # Establish connection
        # Try to access a db named 'antigravity' and collection 'leads'
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
Diagnose the problem from the following StackOverflow question and draft a friendly, professional DM offering a 30-min live fix for roughly $50-$100 depending on complexity. 
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

# --- Scanner Loop ---
def live_search_loop():
    """Background thread that runs pinging StackExchange API."""
    settings = load_settings()
    col = get_db_collection(settings["mongo_uri"])
    
    while st.session_state.scanner_running:
        if col is None:
            time.sleep(60)
            col = get_db_collection(load_settings()["mongo_uri"])
            continue

        try:
            tags = settings.get("tags", [])
            keywords = settings.get("emergency_keywords", [])
            
            for tag in tags:
                if not st.session_state.scanner_running:
                    break
                    
                url = "https://api.stackexchange.com/2.3/questions"
                params = {
                    "order": "desc",
                    "sort": "creation",
                    "tagged": tag,
                    "site": "stackoverflow",
                    "filter": "withbody"
                }

                resp = requests.get(url, params=params, timeout=15)
                if resp.status_code == 200:
                    items = resp.json().get("items", [])
                    for question in items:
                        question_id = question.get("question_id")
                        
                        # Duplicate check in DB
                        if col.find_one({"source_id": f"so_{question_id}"}):
                            continue
                            
                        title = question.get("title", "")
                        body = question.get("body", "")
                        link = question.get("link", "")
                        creation_date = question.get("creation_date")
                        
                        text_to_search = f"{title} {body}".lower()
                        matched_kw = None
                        for keyword in keywords:
                            if keyword.lower() in text_to_search:
                                matched_kw = keyword
                                break
                        
                        if matched_kw:
                            dt = datetime.fromtimestamp(creation_date, timezone.utc)
                            lead_doc = {
                                "source_id": f"so_{question_id}",
                                "title": title,
                                "url": link,
                                "content": body[:2000], # store up to 2000 chars of body
                                "tag": tag,
                                "source": "StackOverflow",
                                "matched_keyword": matched_kw,
                                "status": "New",
                                "created_at": dt,
                                "generated_pitch": ""
                            }
                            col.insert_one(lead_doc)
                            
                            if settings.get("discord_hook"):
                                payload = {
                                    "content": f"🚨 **NEW AUTOMATED LEAD (SO)** 🚨\n**Tag:** `{tag}`\n**Keyword:** `{matched_kw}`\n**Title:** {title}\n**Link:** {link}"
                                }
                                requests.post(settings["discord_hook"], json=payload)
                
                # Sleep a tiny bit to avoid hitting rate limits instantly
                time.sleep(2)
                
        except Exception as e:
            pass  # Silent fail for the background task
            
        # Wait 5 minutes before the next scrape cycle
        for _ in range(300):
            if not st.session_state.scanner_running:
                break
            time.sleep(1)

# --- Navigation & UI ---
st.sidebar.title("Navigation")
page = st.sidebar.radio("Go to", ["Dashboard", "Settings"])

leads_col = get_db_collection(app_settings["mongo_uri"])

if page == "Settings":
    st.title("System Settings")
    st.subheader("General Configuration")
    
    with st.form("settings_form"):
        st.markdown("**1. Database**")
        st.caption("🔗 [Get MongoDB URI from MongoDB Atlas](https://cloud.mongodb.com/) (Select 'Connect' ➡️ 'Drivers' ➡️ 'Python')")
        mongo_uri = st.text_input("MongoDB Connection String URI", value=app_settings["mongo_uri"], type="password")
        
        st.markdown("**2. Discord**")
        st.caption("Discord App ➡️ Server Settings ➡️ Integrations ➡️ Webhooks ➡️ New Webhook")
        discord_hook = st.text_input("Discord Webhook", value=app_settings.get("discord_hook", ""), type="password")
        
        st.markdown("**3. AI Configuration (Agnostic)**")
        ai_base_url = st.text_input("AI Base URL (e.g. https://api.openai.com/v1 OR https://ai.stoxsage.com/v1)", value=app_settings.get("ai_base_url", "https://ai.stoxsage.com/v1"))
        ai_api_key = st.text_input("AI API Key (if required)", value=app_settings.get("ai_api_key", ""), type="password")
        ai_model = st.text_input("AI Model Name (e.g. gemma-3, gpt-4)", value=app_settings.get("ai_model", "gemma-3"))
        
        st.markdown("**4. Email Configuration (Optional)**")
        st.info("Setup Gmail App Passwords to enable sending AI pitches directly via Email. \n\n🔗 [Click here to create a Google App Password](https://myaccount.google.com/apppasswords)")
        email_address = st.text_input("Gmail Address", value=app_settings.get("email_address", ""))
        email_app_password = st.text_input("Gmail App Password", value=app_settings.get("email_app_password", ""), type="password")
        
        st.markdown("**5. Scraper Parameters (StackOverflow)**")
        tags_text = st.text_area("StackOverflow Tags (One per line)", value="\n".join(app_settings.get("tags", [])), height=100)
        keywords_text = st.text_area("Emergency Keywords (One per line)", value="\n".join(app_settings.get("emergency_keywords", [])), height=150)
        
        submitted = st.form_submit_button("Save Settings")
        if submitted:
            app_settings["mongo_uri"] = mongo_uri
            app_settings["discord_hook"] = discord_hook
            app_settings["ai_base_url"] = ai_base_url
            app_settings["ai_api_key"] = ai_api_key
            app_settings["ai_model"] = ai_model
            app_settings["email_address"] = email_address
            app_settings["email_app_password"] = email_app_password
            app_settings["tags"] = [k.strip() for k in tags_text.split("\n") if k.strip()]
            app_settings["emergency_keywords"] = [k.strip() for k in keywords_text.split("\n") if k.strip()]
            save_settings(app_settings)
            
            # Clear resource cache so DB reconnects if URI changed
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

    if st.sidebar.button("Toggle Scanner"):
        if not app_settings["mongo_uri"]:
            st.sidebar.error("Error: Please configure MongoDB URI in Settings first.")
        else:
            st.session_state.scanner_running = not st.session_state.scanner_running
            if st.session_state.scanner_running:
                t = threading.Thread(target=live_search_loop, daemon=True)
                t.start()
                st.session_state.scanner_thread = t
                st.rerun()

    if st.session_state.scanner_running:
        st.sidebar.success("Scanner: ARMED (Running in background on StackExchange API)")
    else:
        st.sidebar.warning("Scanner: DISARMED")

    # --- Main Content Tabs ---
    tab1, tab2 = st.tabs(["Live Feed (Last 24 Hours)", "Archive Database"])

    with tab1:
        st.subheader("New Targets")
        if leads_col is None:
            st.warning("Connect Database to view Live Feed.")
        else:
            twenty_four_hours_ago = datetime.now(timezone.utc) - timedelta(hours=24)
            # Find documents matching New status and created in last 24 h
            cursor = leads_col.find({
                "status": "New", 
                "created_at": {"$gte": twenty_four_hours_ago}
            }).sort("created_at", -1)
            
            fresh_leads = list(cursor)
            
            if len(fresh_leads) == 0:
                st.info("No fresh leads found in the last 24 hours. Keep scanning!")
            
            for lead in fresh_leads:
                lead_tag = lead.get('tag', 'Unknown')
                with st.expander(f"🔴 [{lead_tag}] {lead['title']}", expanded=True):
                    st.caption(f"Matched Keyword: `{lead['matched_keyword']}` | Posted: {lead['created_at'].strftime('%Y-%m-%d %H:%M:%S UTC')}")
                    st.markdown(f"**Description:**\n\n> {lead['content'][:500]}...")
                    st.markdown(f"[🔗 View Original Post]({lead['url']})")
                    
                    # Generate pitch button logic
                    if st.button("Generate AI Pitch & Move to Pitched", key=f"pitch_{lead['_id']}"):
                        with st.spinner(f"Requesting {app_settings['ai_model']} from {app_settings['ai_base_url']}..."):
                            pitch_text = generate_pitch(lead, app_settings)
                            
                        # Update DB
                        leads_col.update_one(
                            {"_id": lead["_id"]}, 
                            {"$set": {"status": "Pitched", "generated_pitch": pitch_text}}
                        )
                        st.success("Pitch generated! Lead moved to Archive -> Pitched.")
                        st.rerun()

                    # Send Email button logic
                    if app_settings.get("email_address") and app_settings.get("email_app_password"):
                        receiver_email = st.text_input("Recipient Email", key=f"rec_email_{lead['_id']}")
                        if st.button("Send Pitch via Email", key=f"send_email_{lead['_id']}"):
                                if not lead.get("generated_pitch"):
                                    st.error("Please generate a pitch first! (Check Archive if you just hit generate).")
                                elif not receiver_email:
                                    st.error("Please enter a recipient email address.")
                                else:
                                    try:
                                        with st.spinner("Sending email..."):
                                            yag = yagmail.SMTP(app_settings["email_address"], app_settings["email_app_password"])
                                            yag.send(
                                                to=receiver_email,
                                                subject=f"Re: Native Fix for {lead['title']}",
                                                contents=lead.get("generated_pitch", "Check out my 30 min native fix!")
                                            )
                                        st.success(f"Email sent successfully to {receiver_email}!")
                                    except Exception as e:
                                        st.error(f"Failed to send email: {str(e)}")


    with tab2:
        st.subheader("Lead Archive")
        if leads_col is None:
            st.warning("Connect Database to view Archive.")
        else:
            # Filter bar
            colA, colB = st.columns(2)
            with colA:
                filter_status = st.selectbox("Status Filter", ["All", "New", "Pitched", "Fixed"])
            with colB:
                # Dynamically collect tags from app_settings
                tags_list = ["All"] + app_settings.get("tags", [])
                filter_sub = st.selectbox("Tag Filter", tags_list)
                
            query = {}
            if filter_status != "All":
                query["status"] = filter_status
            if filter_sub != "All":
                query["tag"] = filter_sub
                
            archive_cursor = leads_col.find(query).sort("created_at", -1).limit(50)
            archived_leads = list(archive_cursor)
            
            st.caption(f"Showing up to {len(archived_leads)} recent archived leads...")
            
            for lead in archived_leads:
                icon = "🟢" if lead["status"] == "New" else ("🔵" if lead["status"] == "Pitched" else "✅")
                lead_tag = lead.get('tag', 'Unknown')
                with st.expander(f"{icon} [{lead['status']}] {lead['title']} - [{lead_tag}]"):
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
                                             subject=f"Re: Native Fix for {lead['title']}",
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
