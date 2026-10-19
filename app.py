import json
import urllib.parse
import streamlit as st
from google import genai
from google.genai import types
from twilio.rest import Client as TwilioClient
from prompts import SUMMARY_REQUEST_PROMPT, SYSTEM_PROMPT, WELCOME_MESSAGE_TEMPLATE

# Configurable model name; defaults to gemini-3.5-flash-lite (can be set in secrets.toml via GEMINI_MODEL)
MODEL_NAME = st.secrets.get("GEMINI_MODEL", "gemini-3.5-flash-lite")

st.set_page_config(page_title="MacroSnap", page_icon="🥗")

# Secrets verification check
required_secrets = [
    "GEMINI_API_KEY",
    "TWILIO_ACCOUNT_SID",
    "TWILIO_AUTH_TOKEN",
    "TWILIO_WHATSAPP_FROM",
    "TWILIO_CONTENT_SID",
]
missing_secrets = [key for key in required_secrets if key not in st.secrets]
if missing_secrets:
    st.error(
        f"⚠️ Missing required secrets in `.streamlit/secrets.toml`: {', '.join(missing_secrets)}.\n\n"
        "Please copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml` and configure your credentials."
    )
    st.stop()

GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
TWILIO_ACCOUNT_SID = st.secrets["TWILIO_ACCOUNT_SID"]
TWILIO_AUTH_TOKEN = st.secrets["TWILIO_AUTH_TOKEN"]
TWILIO_WHATSAPP_FROM = st.secrets["TWILIO_WHATSAPP_FROM"]
TWILIO_CONTENT_SID = st.secrets["TWILIO_CONTENT_SID"]

if GEMINI_API_KEY == "your-gemini-api-key-here" or not GEMINI_API_KEY.strip():
    st.error(
        "⚠️ **Gemini API Key Required**\n\n"
        "`.streamlit/secrets.toml` still has the placeholder `your-gemini-api-key-here`.\n\n"
        "1. Open [Google AI Studio](https://aistudio.google.com/app/apikey) and create a free API key.\n"
        "2. Open [`.streamlit/secrets.toml`](file:///c:/Users/nsrfl/OneDrive/Desktop/AI_Vision_Chatbot/.streamlit/secrets.toml) and replace `your-gemini-api-key-here` with your key.\n"
        "3. Refresh this page to start chatting!"
    )
    st.stop()


@st.cache_resource
def get_gemini_client(api_key):
    return genai.Client(api_key=api_key)


@st.cache_resource
def get_twilio_client(account_sid, auth_token):
    return TwilioClient(account_sid, auth_token)


gemini_client = get_gemini_client(GEMINI_API_KEY)
twilio_client = get_twilio_client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)


def render_message(message):
    with st.chat_message(message["role"]):
        if message["kind"] == "text":
            st.write(message["content"])
        elif message["kind"] == "image":
            st.image(message["content"])


def add_message(role, kind, content):
    st.session_state.messages.append({"role": role, "kind": kind, "content": content})
    render_message(st.session_state.messages[-1])


def ask_gemini(parts):
    try:
        return st.session_state.chat.send_message(parts).text
    except Exception as error:
        return f"Sorry, something went wrong: {error}"


def clean_whatsapp_text(text):
    if not text:
        return "No nutrition summary available."
    text = " ".join(text.split())  # collapse whitespace/newlines
    return text[:1500] + "..." if len(text) > 1500 else text


def format_whatsapp_number(to_number):
    digits = "".join(c for c in to_number if c.isdigit())
    # Standard 10-digit mobile number (India +91)
    if len(digits) == 10:
        return f"+91{digits}"
    # 11-digit starting with 0 (e.g. 09030485331)
    if len(digits) == 11 and digits.startswith("0"):
        return f"+91{digits[1:]}"
    # 12-digit starting with 91 (e.g. 919030485331)
    if len(digits) == 12 and digits.startswith("91"):
        return f"+{digits}"
    return f"+{digits}"


def send_whatsapp(to_number, user_name, summary):
    # Content template expects {{1}} = name, {{2}} = summary.
    if (
        TWILIO_ACCOUNT_SID == "your-twilio-account-sid-here"
        or TWILIO_AUTH_TOKEN == "your-twilio-auth-token-here"
        or TWILIO_CONTENT_SID == "your-content-template-sid-here"
    ):
        return (
            False,
            "Twilio credentials are not set up yet in `.streamlit/secrets.toml`. Please add your Twilio SID, Auth Token, and Content Template SID.",
        )
    try:
        clean_number = format_whatsapp_number(to_number)

        content_variables = json.dumps(
            {"1": user_name, "2": clean_whatsapp_text(summary)}, ensure_ascii=False
        )
        message = twilio_client.messages.create(
            from_=TWILIO_WHATSAPP_FROM,
            to=f"whatsapp:{clean_number}",
            content_sid=TWILIO_CONTENT_SID,
            content_variables=content_variables,
        )
        return True, message.sid
    except Exception as error:
        return False, str(error)


# Step 1: onboarding
if "onboarded" not in st.session_state:
    st.title("🥗 MacroSnap")
    st.caption("Snap it. Track it. Text yourself the results.")
    with st.form("onboarding_form"):
        name = st.text_input("Your name")
        whatsapp_number = st.text_input(
            "WhatsApp number (with country code)",
            placeholder="+91XXXXXXXXXX",
            help="This is the number MacroSnap will text your summary to.",
        )
        submitted = st.form_submit_button("Let's go 🚀")
        if submitted:
            if not name.strip() or not whatsapp_number.strip():
                st.warning("Please fill in both your name and WhatsApp number.")
            else:
                st.session_state.name = name.strip()
                st.session_state.whatsapp_number = format_whatsapp_number(
                    whatsapp_number.strip()
                )
                st.session_state.chat = gemini_client.chats.create(
                    model=MODEL_NAME,
                    config=types.GenerateContentConfig(system_instruction=SYSTEM_PROMPT),
                )
                st.session_state.messages = []
                st.session_state.onboarded = True
                st.rerun()
    st.stop()

# Step 2: chat interface
with st.sidebar:
    st.header("⚙️ Session")
    st.write(f"**Name:** {st.session_state.get('name', '')}")
    current_num = st.session_state.get("whatsapp_number", "")
    new_num = st.text_input(
        "WhatsApp Number",
        value=current_num,
        help="Include country code, e.g. +919030485331",
    )
    if new_num != current_num:
        st.session_state.whatsapp_number = new_num
        st.rerun()

    if st.button("🔄 Reset Chat / Re-login", use_container_width=True):
        st.session_state.clear()
        st.rerun()

header_col, button_col = st.columns([5, 2], vertical_alignment="center")
with header_col:
    st.title("🥗 MacroSnap")
with button_col:
    send_disabled = len(st.session_state.messages) <= 2
    if st.button("📤 Send to WhatsApp", disabled=send_disabled, use_container_width=True):
        with st.spinner("Summarizing your day..."):
            summary = ask_gemini([SUMMARY_REQUEST_PROMPT])
            st.session_state.latest_summary = summary
            success, info = send_whatsapp(
                st.session_state.whatsapp_number, st.session_state.name, summary
            )
            if success:
                st.success(f"Twilio ping sent to {st.session_state.whatsapp_number}! 📲")
            else:
                st.warning(f"Twilio status: {info}")

st.caption(
    f"Logged in as {st.session_state.name} - updates go to {st.session_state.whatsapp_number}"
)

# Display latest nutrition summary if generated
if "latest_summary" in st.session_state:
    with st.expander("📋 Your MacroSnap Daily Summary", expanded=True):
        st.write(st.session_state.latest_summary)
        clean_digits = "".join(c for c in st.session_state.whatsapp_number if c.isdigit())
        encoded_text = urllib.parse.quote(
            f"Hi {st.session_state.name}! Here is your MacroSnap summary:\n\n{st.session_state.latest_summary}"
        )
        wa_url = f"https://wa.me/{clean_digits}?text={encoded_text}"
        st.link_button("📲 Open Full Summary in WhatsApp", wa_url, use_container_width=True)

if not st.session_state.messages:
    add_message(
        "assistant", "text", WELCOME_MESSAGE_TEMPLATE.format(name=st.session_state.name)
    )
else:
    for message in st.session_state.messages:
        render_message(message)

user_input = st.chat_input(
    "Ask a question, or attach a photo of your meal",
    accept_file=True,
    file_type=["jpg", "jpeg", "png"],
)

if user_input:
    photo = user_input.files[0] if user_input.files else None
    text = user_input.text
    parts = []
    if photo is not None:
        photo_bytes = photo.getvalue()
        add_message("user", "image", photo_bytes)
        parts.append(types.Part.from_bytes(data=photo_bytes, mime_type=photo.type))
    if text:
        add_message("user", "text", text)
        parts.append(text)
    elif photo is not None:
        parts.append("What is this meal? Give me the calories and macros.")

    with st.spinner("Crunching the numbers..."):
        answer = ask_gemini(parts)
        add_message("assistant", "text", answer)
