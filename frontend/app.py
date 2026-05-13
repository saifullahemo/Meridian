"""
frontend/app.py
---------------
Personal OS - Unified Interface
Three modes: Chat | Conversation Mode | Data Explorer | Dashboard
"""

import sys
import json
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import streamlit as st
import pandas as pd

st.set_page_config(
    page_title="Personal OS",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
<style>
    .stApp { background-color: #0f1117; color: #e0e0e0; }
    section[data-testid="stSidebar"] { background-color: #1a1a2e; }

    .user-msg {
        background: #1e3a5f;
        color: #fff;
        padding: 10px 16px;
        border-radius: 16px 16px 4px 16px;
        margin: 6px 0 6px auto;
        max-width: 78%;
        font-size: 14px;
    }
    .ai-msg {
        background: #1a1a2e;
        color: #e0e0e0;
        padding: 10px 16px;
        border-radius: 16px 16px 16px 4px;
        margin: 6px auto 6px 0;
        max-width: 85%;
        border-left: 3px solid #2e75b6;
        font-size: 14px;
    }
    .ok  { color: #4ade80; font-weight: bold; }
    .err { color: #f87171; font-weight: bold; }

    .stat-card {
        background: #1a1a2e;
        border: 1px solid #2e3a4e;
        border-radius: 12px;
        padding: 20px;
        text-align: center;
        margin: 6px;
    }
    .stat-number { font-size: 36px; font-weight: bold; color: #2e75b6; }
    .stat-label  { font-size: 13px; color: #888; margin-top: 4px; }

    .mode-active {
        background: #2e75b6 !important;
        color: white !important;
        border-radius: 8px;
    }

    #MainMenu, footer, .stDeployButton { display: none; }
    div[data-testid="stDataFrame"] { border-radius: 10px; overflow: hidden; }
</style>
""",
    unsafe_allow_html=True,
)


# ─────────────────────────────────────────────
# Load backend
# ─────────────────────────────────────────────

from backend.core import memory as mem


@st.cache_resource
def load_backend():
    try:
        from backend.core import brain, router
        from backend.agents import universal_agent
        from backend.data import database

        database.init_all_tables()
        return brain, router, universal_agent, database, None
    except Exception as e:
        return None, None, None, None, str(e)


brain, router, universal_agent, database, load_error = load_backend()


# ─────────────────────────────────────────────
# Session state
# ─────────────────────────────────────────────

if "messages" not in st.session_state:
    st.session_state.messages = []
if "session_id" not in st.session_state:
    st.session_state.session_id = mem.today_session_id()
if "mode" not in st.session_state:
    st.session_state.mode = "chat"
if "conversation_pending" not in st.session_state:
    st.session_state.conversation_pending = None
if "conversation_files" not in st.session_state:
    st.session_state.conversation_files = []
if "active_mod" not in st.session_state:
    st.session_state.active_mod = None
if "edit_record" not in st.session_state:
    st.session_state.edit_record = None


# ─────────────────────────────────────────────
# Load modules config
# ─────────────────────────────────────────────


def load_modules():
    try:
        with open(ROOT / "config" / "modules.json") as f:
            return json.load(f).get("modules", {})
    except Exception:
        return {}


modules = load_modules()


# ─────────────────────────────────────────────
# Sidebar
# ─────────────────────────────────────────────

with st.sidebar:
    st.markdown("## 🧠 Personal OS")
    st.markdown("---")

    st.markdown("### Mode")
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        if st.button(
            "💬\nChat",
            use_container_width=True,
            type="primary" if st.session_state.mode == "chat" else "secondary",
        ):
            st.session_state.mode = "chat"
            st.rerun()

        if st.button(
            "🗣️\nConversation",
            use_container_width=True,
            type="primary" if st.session_state.mode == "conversation" else "secondary",
        ):
            st.session_state.mode = "conversation"
            st.rerun()

    with col2:
        if st.button(
            "📊\nData",
            use_container_width=True,
            type="primary" if st.session_state.mode == "data" else "secondary",
        ):
            st.session_state.mode = "data"
            st.rerun()

    with col3:
        if st.button(
            "📈\nDash",
            use_container_width=True,
            type="primary" if st.session_state.mode == "dashboard" else "secondary",
        ):
            st.session_state.mode = "dashboard"
            st.rerun()

    st.markdown("---")

    st.markdown("### AI Status")
    if load_error:
        st.error("Backend error")
    else:
        try:
            status = brain.get_status()
            if status["ready"]:
                st.success("🟢 AI Brain Online")
                st.caption("Model: " + status["model"])
            else:
                st.error("🔴 AI Offline")
                if not status.get("ollama_running"):
                    st.code("ollama serve")
                else:
                    st.code("ollama pull llama3.2")
        except Exception:
            st.warning("🟡 Status unknown")

    st.markdown("---")

    st.markdown("### Modules")
    for key, mod in modules.items():
        count = 0
        try:
            count = database.count(key)
        except Exception:
            pass
        label = mod.get("icon", "📁") + " " + mod.get("label", key)
        if st.button(
            label + " (" + str(count) + ")",
            use_container_width=True,
            key="mod_" + key,
        ):
            st.session_state.mode = "data"
            st.session_state.active_mod = key
            st.rerun()

    st.markdown("---")

    if st.session_state.mode == "chat":
        st.markdown("### Try These")
        examples = [
            "Show all my job applications",
            "Add expense $50 lunch today",
            "Summarize my jobs data",
            "How many jobs this month?",
            "I want to track my reading list",
        ]
        for ex in examples:
            if st.button(ex, use_container_width=True, key="ex_" + ex[:25]):
                st.session_state["pending"] = ex
                st.rerun()

    if st.button("🗑 Clear Chat", use_container_width=True):
        st.session_state.messages = []
        st.session_state.conversation_pending = None
        st.session_state.conversation_files = []
        st.rerun()

    st.markdown("---")

    st.markdown("### 🧠 Memory")
    session_id = st.session_state.get("session_id", mem.today_session_id())
    st.caption("Session: " + session_id)

    try:
        history = mem.get_history(session_id, limit=100)
        st.caption(str(len(history)) + " messages remembered")
    except Exception:
        st.caption("Memory not available")

    col_mem1, col_mem2 = st.columns(2)
    with col_mem1:
        if st.button("Summarize", use_container_width=True):
            with st.spinner("Summarizing..."):
                summary = mem.summarize_session(session_id)
            st.info(summary)
    with col_mem2:
        if st.button("Clear Memory", use_container_width=True):
            mem.clear_session(session_id)
            st.success("Memory cleared")

    mem_search = st.text_input(
        "Search past conversations",
        placeholder="e.g. jobs, expense...",
        label_visibility="collapsed",
    )
    if mem_search:
        results = mem.search_all_sessions(mem_search)
        if results:
            for r in results[:3]:
                st.markdown("**" + r["role"] + ":** " + r["content"][:100])
        else:
            st.caption("Nothing found for: " + mem_search)


# ─────────────────────────────────────────────
# Process instruction (router-based chat)
# ─────────────────────────────────────────────


def process(instruction: str):
    """Route and execute an instruction."""
    if load_error:
        return {"success": False, "message": "Backend not loaded.", "data": []}
    try:
        route = router.route(instruction)
        result = universal_agent.execute(route)
        # Save to memory
        try:
            session_id = st.session_state.get("session_id", mem.today_session_id())
            mem.save_exchange(
                session_id,
                instruction,
                result.get("message", ""),
                result.get("action", ""),
            )
        except Exception:
            pass
        return result
    except Exception as e:
        return {"success": False, "message": "Error: " + str(e), "data": []}


# ─────────────────────────────────────────────
# Process conversation (freeform + optional files)
# ─────────────────────────────────────────────


def _extract_uploaded_text(uploaded_file):
    """Best-effort text extraction from uploaded files."""
    # Streamlit uploaded files behave like file-like objects; ensure we start from byte 0.
    try:
        uploaded_file.seek(0)
    except Exception:
        pass
    raw = uploaded_file.read()
    name = getattr(uploaded_file, "name", "uploaded_file")
    ext = name.split(".")[-1].lower() if "." in name else ""

    extracted = ""

    if ext == "pdf":
        try:
            import pdfplumber
            from io import BytesIO

            with pdfplumber.open(BytesIO(raw)) as pdf:
                extracted = "\n".join([(p.extract_text() or "") for p in pdf.pages])
        except Exception:
            extracted = ""
    elif ext in ("txt", "md"):
        try:
            extracted = raw.decode("utf-8", errors="ignore")
        except Exception:
            extracted = ""
    elif ext in ("json", "csv"):
        try:
            extracted = raw.decode("utf-8", errors="ignore")
        except Exception:
            extracted = ""
    elif ext in ("docx",):
        try:
            import docx
            from io import BytesIO

            doc = docx.Document(BytesIO(raw))
            extracted = "\n".join([p.text for p in doc.paragraphs])
        except Exception:
            extracted = ""
    else:
        # Best-effort: treat unknown as utf-8 text
        try:
            extracted = raw.decode("utf-8", errors="ignore")
        except Exception:
            extracted = ""

    return name, ext, extracted


def process_conversation(instruction: str):
    """Ask the AI freely (math/advice/etc). Forces conversational mode.

    If files are uploaded, extract text (best-effort) and prepend it to the instruction.
    """
    if load_error:
        return {"success": False, "message": "Backend not loaded.", "data": []}

    try:
        file_text_blobs = []
        files = st.session_state.get("conversation_files", []) or []

        for f in files:
            try:
                name, ext, extracted = _extract_uploaded_text(f)

                if extracted.strip():
                    file_text_blobs.append(
                        f"\n--- FILE: {name} (type={ext}) ---\n" + extracted[:20000]
                    )
                else:
                    file_text_blobs.append(
                        f"\n--- FILE: {name} (type={ext}) ---\n"
                        + "[No text could be extracted from this file.]"
                    )
            except Exception:
                continue

        augmented_instruction = instruction
        if file_text_blobs:
            augmented_instruction = (
                "You have uploaded the following files. "
                "Use them to answer the user's request as best as you can. "
                "If you cannot read something, say so and suggest next steps.\n\n"
                + "".join(file_text_blobs)
                + "\n\nUSER REQUEST:\n"
                + instruction
            )

        forced_route = {
            "action": "read_data",
            "module": None,
            "parameters": {"raw_instruction": augmented_instruction},
            "explanation": "Forced conversational routing (with optional file context)",
            "steps": [],
        }

        result = universal_agent.execute(forced_route)

        # Save to memory (store original instruction)
        try:
            session_id = st.session_state.get("session_id", mem.today_session_id())
            mem.save_exchange(
                session_id,
                instruction,
                result.get("message", ""),
                result.get("action", ""),
            )
        except Exception:
            pass

        return result

    except Exception as e:
        return {"success": False, "message": "Error: " + str(e), "data": []}


# ─────────────────────────────────────────────
# Conversation Mode UI
# ─────────────────────────────────────────────


def render_conversation():
    st.markdown("## 🗣️ Conversation Mode")
    st.caption(
        "Ask the AI anything — math, career advice, interview prep, etc. "
        "Upload a file to let the AI use it."
    )
    st.markdown("---")

    # Upload UI inside the message composer area (matches the chatbox-style upload)
    # Use a compact expander so it stays near the input without looking like a sidebar.
    with st.container():
        col_up, col_clear = st.columns([5, 1], vertical_alignment="bottom")

        with col_up:
            st.caption("📎 Upload files (optional)")
            uploaded = st.file_uploader(
                "",
                type=None,
                accept_multiple_files=True,
                key="conversation_uploader",
                label_visibility="collapsed",
            )
            if uploaded is not None:
                st.session_state.conversation_files = uploaded

        with col_clear:
            if st.button("Clear", use_container_width=True, key="conversation_clear_files"):
                st.session_state.conversation_files = []

        if st.session_state.conversation_files:
            st.caption(
                "Uploaded: " + ", ".join([f.name for f in st.session_state.conversation_files])
            )


    # Optional pending (if you later add quick buttons)

    if st.session_state.get("conversation_pending"):
        instr = st.session_state.conversation_pending
        st.session_state.conversation_pending = None
        st.session_state.messages.append({"role": "user", "content": instr})
        with st.spinner("Thinking..."):
            result = process_conversation(instr)
        st.session_state.messages.append(
            {
                "role": "assistant",
                "content": result.get("message", ""),
                "success": result.get("success", False),
                "data": result.get("data", []),
            }
        )
        st.rerun()

    instruction = st.chat_input("Type your question...")
    if instruction:
        st.session_state.messages.append({"role": "user", "content": instruction})
        with st.spinner("Thinking..."):
            result = process_conversation(instruction)
        st.session_state.messages.append(
            {
                "role": "assistant",
                "content": result.get("message", ""),
                "success": result.get("success", False),
                "data": result.get("data", []),
            }
        )
        st.rerun()

    for msg in st.session_state.messages:
        if msg.get("role") == "user":
            st.markdown(
                '<div class="user-msg">' + msg.get("content", "") + '</div>',
                unsafe_allow_html=True,
            )
        elif msg.get("role") == "assistant":
            icon = '<span class="ok">✓</span>' if msg.get("success") else '<span class="err">✗</span>'
            st.markdown(
                '<div class="ai-msg">' + icon + ' ' + msg.get("content", "") + '</div>',
                unsafe_allow_html=True,
            )


# ─────────────────────────────────────────────
# Chat Mode UI (router-based)
# ─────────────────────────────────────────────


def render_chat():
    st.markdown("## 💬 Chat (router-based) with your AI")
    st.caption("Type any instruction in plain English.")
    st.markdown("---")

    # Handle pending from sidebar click
    if "pending" in st.session_state:
        instr = st.session_state.pop("pending")
        st.session_state.messages.append({"role": "user", "content": instr})
        with st.spinner("Thinking..."):
            result = process(instr)
        st.session_state.messages.append(
            {
                "role": "assistant",
                "content": result["message"],
                "success": result["success"],
                "data": result.get("data", []),
            }
        )
        st.rerun()

    for msg in st.session_state.messages:
        if msg["role"] == "user":
            st.markdown(
                "<div class=\"user-msg\">" + msg["content"] + "</div>",
                unsafe_allow_html=True,
            )
        else:
            icon = (
                '<span class="ok">✓</span>'
                if msg.get("success")
                else '<span class="err">✗</span>'
            )
            st.markdown(
                '<div class="ai-msg">' + icon + ' ' + msg["content"] + '</div>',
                unsafe_allow_html=True,
            )

            data = msg.get("data", [])
            if isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict):
                df = pd.DataFrame(data)
                drop = [c for c in ["created_at", "updated_at"] if c in df.columns]
                if drop:
                    df = df.drop(columns=drop)
                with st.expander("📋 View " + str(len(data)) + " records"):
                    st.dataframe(df, use_container_width=True, hide_index=True)

    instruction = st.chat_input("Type your instruction...")
    if instruction:
        st.session_state.messages.append({"role": "user", "content": instruction})
        with st.spinner("Thinking..."):
            result = process(instruction)
        st.session_state.messages.append(
            {
                "role": "assistant",
                "content": result["message"],
                "success": result["success"],
                "data": result.get("data", []),
            }
        )
        st.rerun()


# ─────────────────────────────────────────────
# Data Explorer Mode
# ─────────────────────────────────────────────


def render_data():
    st.markdown("## 📊 Data Explorer")

    module_keys = list(modules.keys())
    module_labels = [
        modules[k].get("icon", "") + " " + modules[k].get("label", k)
        for k in module_keys
    ]

    active_idx = 0
    if st.session_state.active_mod in module_keys:
        active_idx = module_keys.index(st.session_state.active_mod)

    selected_label = st.selectbox(
        "Select Module", module_labels, index=active_idx
    )
    selected_key = module_keys[module_labels.index(selected_label)]
    st.session_state.active_mod = selected_key

    schema = modules.get(selected_key, {})
    st.caption(schema.get("description", ""))
    st.markdown("---")

    col_search, col_filter, col_add = st.columns([3, 2, 1])

    with col_search:
        search = st.text_input(
            "🔍 Search", placeholder="Search any field...", label_visibility="collapsed"
        )

    with col_filter:
        status_options = []
        for f in schema.get("fields", []):
            if f["name"] == "status" and f.get("options"):
                status_options = ["All"] + f["options"]
                break
        status_filter = "All"
        if status_options:
            status_filter = st.selectbox("Status", status_options, label_visibility="collapsed")

    with col_add:
        add_clicked = st.button("➕ Add", use_container_width=True)

    try:
        records = database.select(selected_key, limit=500)
    except Exception as e:
        st.error("Could not load records: " + str(e))
        return

    if search:
        search_lower = search.lower()
        records = [r for r in records if any(search_lower in str(v).lower() for v in r.values())]

    if status_filter and status_filter != "All":
        records = [r for r in records if r.get("status") == status_filter]

    total = database.count(selected_key)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Records", total)
    c2.metric("Showing", len(records))
    if records:
        c3.metric("Latest", (records[0].get("created_at", "") or "")[:10] if records else "-")
    c4.metric("Module", schema.get("icon", "") + " " + schema.get("label", ""))

    st.markdown("---")

    if add_clicked:
        st.session_state.edit_record = "new"

    if st.session_state.edit_record == "new":
        st.markdown("### ➕ Add New Record")
        fields = schema.get("fields", [])
        new_data = {}
        cols = st.columns(2)
        for i, field in enumerate(fields):
            with cols[i % 2]:
                fname = field["name"]
                ftype = field["type"]
                label = fname.replace("_", " ").title()

                if ftype == "enum" and field.get("options"):
                    new_data[fname] = st.selectbox(label, field["options"], key="new_" + fname)
                elif ftype == "date":
                    new_data[fname] = st.date_input(label, key="new_" + fname)
                    new_data[fname] = str(new_data[fname])
                elif ftype == "number":
                    new_data[fname] = st.number_input(label, key="new_" + fname)
                elif ftype == "boolean":
                    new_data[fname] = st.checkbox(label, key="new_" + fname)
                else:
                    new_data[fname] = st.text_input(label, key="new_" + fname)

        col_save, col_cancel = st.columns([1, 4])
        with col_save:
            if st.button("💾 Save", type="primary"):
                try:
                    record_id = database.insert(selected_key, new_data)
                    record = database.select_one(selected_key, record_id)
                    try:
                        from backend.data import excel_manager

                        excel_manager.append_row(selected_key, record)
                    except Exception:
                        pass
                    st.session_state.edit_record = None
                    st.success("Record saved!")
                    time.sleep(0.5)
                    st.rerun()
                except Exception as e:
                    st.error("Save failed: " + str(e))
        with col_cancel:
            if st.button("Cancel"):
                st.session_state.edit_record = None
                st.rerun()

        st.markdown("---")

    if not records:
        st.info("No records found. Add one above or use Chat to add via AI.")
        return

    df = pd.DataFrame(records)

    priority = [
        "id",
        "company",
        "position",
        "country",
        "status",
        "date_applied",
        "date",
        "title",
        "type",
        "amount",
        "category",
        "notes",
    ]
    ordered = [c for c in priority if c in df.columns]
    rest = [c for c in df.columns if c not in ordered and c not in ["created_at", "updated_at"]]
    df = df[ordered + rest]

    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "id": st.column_config.NumberColumn("ID", width="small"),
            "status": st.column_config.TextColumn("Status", width="medium"),
            "amount": st.column_config.NumberColumn("Amount", format="$%.2f"),
        },
    )

    st.markdown("---")
    with st.expander("🗑 Delete a record"):
        del_id = st.number_input("Record ID to delete", min_value=1, step=1)
        if st.button("Delete", type="secondary"):
            deleted = database.delete(selected_key, int(del_id))
            if deleted:
                st.success("Deleted record " + str(del_id))
                time.sleep(0.5)
                st.rerun()
            else:
                st.error("Record not found.")

    with st.expander("📥 Export to Excel"):
        if st.button("Export current view to Excel"):
            try:
                from backend.data import excel_manager

                path = excel_manager.export_filtered(selected_key, {})
                st.success("Exported to: " + str(path))
            except Exception as e:
                st.error("Export failed: " + str(e))


# ─────────────────────────────────────────────
# Dashboard Mode
# ─────────────────────────────────────────────


def render_dashboard():
    st.markdown("## 📈 Dashboard")
    st.caption("Overview of all your personal data.")
    st.markdown("---")

    cols = st.columns(len(modules) if modules else 1)
    for i, (key, mod) in enumerate(modules.items()):
        with cols[i % len(cols)]:
            try:
                count = database.count(key)
            except Exception:
                count = 0
            st.markdown(
                "<div class='stat-card'>"
                "<div style='font-size:32px'>" + mod.get("icon", "📁") + "</div>"
                "<div class='stat-number'>" + str(count) + "</div>"
                "<div class='stat-label'>" + mod.get("label", key) + "</div>"
                "</div>",
                unsafe_allow_html=True,
            )

    st.markdown("---")

    for key, mod in modules.items():
        try:
            records = database.select(key, limit=5, order_by="created_at DESC")
            if not records:
                continue

            st.markdown("### " + mod.get("icon", "") + " " + mod.get("label", key))
            df = pd.DataFrame(records)
            drop = [c for c in ["created_at", "updated_at", "id"] if c in df.columns]
            if drop:
                df = df.drop(columns=drop)
            st.dataframe(df, use_container_width=True, hide_index=True)

            col1, col2 = st.columns([1, 5])
            with col1:
                if st.button("View All", key="dash_view_" + key):
                    st.session_state.mode = "data"
                    st.session_state.active_mod = key
                    st.rerun()
            st.markdown("---")
        except Exception:
            continue


# ─────────────────────────────────────────────
# Render active mode
# ─────────────────────────────────────────────

if st.session_state.mode == "chat":
    render_chat()
elif st.session_state.mode == "conversation":
    render_conversation()
elif st.session_state.mode == "data":
    render_data()
elif st.session_state.mode == "dashboard":
    render_dashboard()

