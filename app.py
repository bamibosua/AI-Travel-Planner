import time
import streamlit as st
import pyrebase
import firebase_admin
from firebase_admin import credentials, firestore
from collections import deque
from datetime import datetime, timezone
from ollama import Client
from streamlit_extras.stylable_container import stylable_container

# ===== Basic Config =====
st.set_page_config(page_title="Mini-travel Application", page_icon="💬")
MODEL = "gpt-oss:20b"
client = Client(host="https://jzloi-34-187-146-27.a.free.pinggy.link")

# ===== Firebase Setup =====
@st.cache_resource
def get_firebase_clients():
    firebase_cfg = st.secrets["firebase_client"]
    firebase_app = pyrebase.initialize_app(firebase_cfg)
    auth = firebase_app.auth()

    if not firebase_admin._apps:
        cred = credentials.Certificate(dict(st.secrets["firebase_admin"]))
        firebase_admin.initialize_app(cred)
    db = firestore.client()
    return auth, db

auth, db = get_firebase_clients()

# ===== Firestore Helpers =====
def save_message(uid: str, role: str, content: str):
    doc = {"role": role, "content": content, "ts": datetime.now(timezone.utc)}
    db.collection("chats").document(uid).collection("messages").add(doc)

def load_last_messages(uid: str, limit: int = 8):
    q = (
        db.collection("chats")
        .document(uid)
        .collection("messages")
        .order_by("ts", direction=firestore.Query.DESCENDING)
        .limit(limit)
    )
    docs = list(q.stream())
    docs.reverse()
    return [{"role": d.to_dict().get("role", "assistant"), "content": d.to_dict().get("content", "")} for d in docs]

def save_trip(uid: str, trip_data: dict):
    trip_data["ts"] = datetime.now(timezone.utc)
    db.collection("trips").document(uid).collection("user_trips").add(trip_data)

def load_trips(uid: str):
    q = (
        db.collection("trips")
        .document(uid)
        .collection("user_trips")
        .order_by("ts", direction=firestore.Query.DESCENDING)
    )
    docs = list(q.stream())
    return [d.to_dict() for d in docs]

# ===== LLM Function =====
def ollama_stream(history_messages: list[dict]):
    response = client.chat(model=MODEL, messages=history_messages)
    return response["message"]["content"]

# ===== Auth Forms =====
def login_form():
    st.markdown("<h3 style='text-align:center;'>Login</h3>", unsafe_allow_html=True)
    with st.form("login_form"):
        email = st.text_input("Email")
        password = st.text_input("Password", type="password")
        col1, col2 = st.columns(2)
        with col1:
            login = st.form_submit_button("Login")
        with col2:
            goto_signup = st.form_submit_button("Create Account")

    if goto_signup:
        st.session_state["show_signup"] = True
        st.session_state["show_login"] = False
        st.rerun()

    if login:
        try:
            user = auth.sign_in_with_email_and_password(email, password)
            st.session_state.user = {"email": email, "uid": user["localId"], "idToken": user["idToken"]}
            msgs = load_last_messages(st.session_state.user["uid"], limit=8)
            trips = load_trips(st.session_state.user["uid"])
            st.session_state.messages = deque(msgs or [{"role": "assistant", "content": "Hello 👋! I'm Mika."}], maxlen=8)
            st.session_state.past_trips = trips
            st.success("Login successful!")
            st.rerun()
        except Exception as e:
            st.error(f"Login error: {e}")

def signup_form():
    st.markdown("<h3 style='text-align:center;'>Sign Up</h3>", unsafe_allow_html=True)
    with st.form("signup_form"):
        email = st.text_input("Email")
        password = st.text_input("Password (≥6 characters)", type="password")
        col1, col2 = st.columns(2)
        with col1:
            signup = st.form_submit_button("Create Account")
        with col2:
            goto_login = st.form_submit_button("Login")

    if goto_login:
        st.session_state["show_signup"] = False
        st.session_state["show_login"] = True
        st.rerun()

    if signup:
        try:
            auth.create_user_with_email_and_password(email, password)
            st.success("Account created! Please log in.")
            time.sleep(2)
            st.session_state["show_signup"] = False
            st.session_state["show_login"] = True
            st.rerun()
        except Exception as e:
            st.error(f"Signup error: {e}")

@st.dialog("Trợ lý Mika")
def chat_dialog():
    if not st.session_state.user:
        st.info("Bạn cần đăng nhập để chat và lưu lịch sử.")
        return
    
    chat_body = st.container(height=600, border=True)

    def render_history():
        chat_body.empty()
        with chat_body:
            for msg in list(st.session_state.messages):
                with st.chat_message(msg["role"]):
                    st.markdown(msg["content"])
    render_history()

    user_input = st.chat_input("Nhập tin nhắn...", key="dialog_input")
        
    if user_input:
        st.session_state.messages.append({"role": "user", "content": user_input})
        with chat_body:
            with st.chat_message("user"):
                st.markdown(user_input)
        save_message(st.session_state.user["uid"], "user", user_input)
        try:
            reply = ollama_stream(st.session_state.messages)
        except requests.RequestException as e:
            st.error(f"Ollama request failed: {e}")
            reply = ""
        st.session_state.messages.append({"role": "assistant", "content": reply})
        save_message(st.session_state.user["uid"], "assistant", reply)
        st.session_state.chat_open = True
        st.rerun()

# ===== Main UI =====
st.markdown("<h1 style='text-align:center;'>Mika Travel Assistant</h1>", unsafe_allow_html=True)
st.divider()

if "user" not in st.session_state:
    st.session_state.user = None
if "messages" not in st.session_state:
    st.session_state.messages = deque([{"role": "assistant", "content": "Hello 👋! I'm Mika."}], maxlen=8)
if "chat_open" not in st.session_state:
    st.session_state.chat_open = False
if "current_trip" not in st.session_state:
    st.session_state.current_trip = None
if "past_trips" not in st.session_state:
    st.session_state.past_trips = []

if st.session_state.user:
    st.success(f"Logged in as: {st.session_state.user['email']}")
    if st.button("Logout"):
        st.session_state.user = None
        st.session_state.chat_open = False
        st.rerun()
else:
    if st.session_state.get("show_signup", False):
        signup_form()
    else:
        login_form()

st.divider()

if st.session_state.user:
    st.subheader("Trip Management")
    tab_new, tab_history = st.tabs(["New Trip", "Trip History"])

    with tab_new:
        st.write("Enter your trip details:")

        with st.form("trip_form"):
            origin = st.text_input("Origin city")
            destination = st.text_input("Destination city")
            start_date = st.date_input("Start date")
            end_date = st.date_input("End date")
            interests = st.multiselect(
                "Interests",
                ["Food", "Museums", "Nature", "Nightlife"],
                default=["Food"]
            )
            pace = st.selectbox("Travel pace", ["Relaxed", "Normal", "Tight"])
            submit = st.form_submit_button("Generate Itinerary")

        if submit:
            st.info("Generating itinerary...")
            prompt = (
                f"Generate a detailed {pace.lower()} itinerary from {origin} to {destination} "
                f"from {start_date} to {end_date}, focusing on {', '.join(interests)}. "
                "Split by morning, afternoon, and evening with short explanations."
            )
            history = [{"role": "user", "content": prompt}]
            try:
                response = client.chat(model=MODEL, messages=history)
                itinerary = response["message"]["content"]
                st.session_state.current_trip = {
                    "origin": origin,
                    "destination": destination,
                    "start_date": str(start_date),
                    "end_date": str(end_date),
                    "interests": interests,
                    "pace": pace,
                    "itinerary": itinerary,
                }
                save_trip(st.session_state.user["uid"], st.session_state.current_trip)
                st.session_state.past_trips = load_trips(st.session_state.user["uid"])
                st.success("Itinerary created successfully!")
            except Exception as e:
                st.error(f"Error generating itinerary: {e}")

        if st.session_state.current_trip:
            st.markdown("### Current Itinerary")
            st.markdown(st.session_state.current_trip["itinerary"])

    with tab_history:
        st.write("Your past trips:")
        past_trips = st.session_state.get("past_trips", [])
        if not past_trips:
            st.info("No past trips yet.")
        else:
            for i, trip in enumerate(past_trips, 1):
                with st.expander(f"{i}. {trip['origin']} → {trip['destination']} ({trip['start_date']} - {trip['end_date']})"):
                    st.caption(f"Interests: {', '.join(trip['interests'])}")
                    st.markdown(trip["itinerary"])

st.divider()
st.markdown("<h5 style='text-align:center;'>Click 💬 to chat with Mika</h5>", unsafe_allow_html=True)
st.markdown('<div id="fab-anchor"></div>', unsafe_allow_html=True)

with stylable_container(
    "chat-btn",
    css_styles="button {background-color:#66c334;color:black;width:704px !important;height:30px;}",
):
    fab_clicked = st.button("💬", key="open_chat", help="Open chat")

if fab_clicked:
    st.session_state.chat_open = True
    st.rerun()
if st.session_state.chat_open:
    chat_dialog()

st.markdown("""
<style>
#fab-anchor + div button {
    position: fixed;
    bottom: 16px;
    right: 16px;
    width: 90px !important;
    height: 90px;
    border-radius: 50%;
    font-size: 30px;
    box-shadow: 0 6px 18px rgba(0,0,0,0.25);
    z-index: 10000;
}
#fab-anchor + div button:hover {
    transform: translateY(-2px);
    box-shadow: 0 10px 24px rgba(250,206,175,0.28);
}
</style>
""", unsafe_allow_html=True)