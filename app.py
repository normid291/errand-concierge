"""
Errand Concierge - Web UI (Streamlit)

Run with: streamlit run app.py

This wraps the same agent used by main.py in a browser chat interface,
plus a sidebar showing full errand history (pending, done, cancelled).
"""

import logging
import warnings

logging.disable(logging.WARNING)
warnings.filterwarnings("ignore")

import streamlit as st
from agent import agent
import storage

st.set_page_config(page_title="Errand Concierge", page_icon="\U0001F4CB", layout="wide")

# --- Sidebar: history ---
with st.sidebar:
    st.header("📋 Your Errands")

    view = st.radio("Show", ["Pending", "Done", "Cancelled", "All"], horizontal=False)
    status_map = {"Pending": "pending", "Done": "done", "Cancelled": "cancelled", "All": None}
    tasks = storage.list_tasks(status=status_map[view])

    if not tasks:
        st.caption(f"No {view.lower()} errands yet.")
    else:
        # newest first
        tasks_sorted = sorted(tasks, key=lambda t: t.get("created_at", ""), reverse=True)
        for t in tasks_sorted:
            status_emoji = {"pending": "🕓", "done": "✅", "cancelled": "❌"}.get(t["status"], "•")
            with st.container(border=True):
                st.markdown(f"{status_emoji} **{t['title']}**")
                if t.get("due"):
                    st.caption(f"Due: {t['due']}")
                if t.get("notes"):
                    st.caption(t["notes"])
                st.caption(f"Added: {t.get('created_at', '')[:16].replace('T', ' ')}")
                if t.get("completed_at"):
                    st.caption(f"Completed: {t['completed_at'][:16].replace('T', ' ')}")
                if t.get("cancelled_at"):
                    st.caption(f"Cancelled: {t['cancelled_at'][:16].replace('T', ' ')}")

    st.divider()
    if st.button("🔄 Refresh"):
        st.rerun()

# --- Main: chat interface ---
st.title("🧾 Errand Concierge")
st.caption("Dump your errands, I'll organize, remind, and reschedule them for you.")

if "messages" not in st.session_state:
    st.session_state.messages = []
    st.session_state.messages.append(
        {"role": "assistant", "content": "Hi! Tell me what's on your plate — bills, appointments, errands, anything you keep forgetting."}
    )

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.write(msg["content"])

if prompt := st.chat_input("e.g. pay electricity bill by Friday, dentist next week..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.write(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Working on it..."):
            response = agent(prompt)
            response_text = str(response)
        st.write(response_text)

    st.session_state.messages.append({"role": "assistant", "content": response_text})
    st.rerun()
