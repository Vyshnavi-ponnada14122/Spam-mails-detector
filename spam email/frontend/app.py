import sys
import os

# Ensure the project root is on sys.path so that `backend` package is importable
# when Streamlit is launched from any working directory.
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import streamlit as st
from pathlib import Path
from datetime import datetime

from backend.db import init_db, get_db_session
from backend.auth import authenticate_user, register_user
from backend.models import EmailAccount, ScannedEmail, Notification
from backend.email_service import EMAIL_CREDENTIALS, scan_all_accounts
from backend.scheduler import start_scheduler
from backend.ml_model import load_or_train_model

# ── Initialise DB and ML model on first run ────────────────────────────────
init_db()
load_or_train_model()

st.set_page_config(page_title="AI Spam Detector", page_icon="📧", layout="wide")

# ── Logo path ──────────────────────────────────────────────────────────────
_LOGO_PATH = Path(__file__).parent / "logo.png"

# ── Global styling ─────────────────────────────────────────────────────────
st.markdown("""
<style>
    /* Sidebar logo container */
    .sidebar-logo {
        display: flex;
        flex-direction: column;
        align-items: center;
        padding: 1rem 0 0.5rem 0;
    }
    /* App header banner */
    .app-header {
        display: flex;
        align-items: center;
        gap: 1rem;
        padding: 0.5rem 0 1rem 0;
        border-bottom: 2px solid rgba(99, 102, 241, 0.3);
        margin-bottom: 1.2rem;
    }
    .app-header h1 {
        margin: 0;
        font-size: 2rem;
        background: linear-gradient(135deg, #6366f1 0%, #a855f7 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        font-weight: 800;
    }
    .app-header p {
        margin: 0;
        color: #94a3b8;
        font-size: 0.9rem;
    }
</style>
""", unsafe_allow_html=True)

# ── Session-state defaults ─────────────────────────────────────────────────
if "user_id" not in st.session_state:
    st.session_state.user_id = None
if "username" not in st.session_state:
    st.session_state.username = ""
if "scheduler_started" not in st.session_state:
    start_scheduler()
    st.session_state.scheduler_started = True


# ── Auth forms ─────────────────────────────────────────────────────────────
def show_login_form():
    st.header("Login")
    with st.form("login_form"):
        email = st.text_input("Email")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Login")

    if submitted:
        session = get_db_session()
        user = authenticate_user(session, email.strip().lower(), password)
        session.close()
        if user:
            st.session_state.user_id = user.id
            st.session_state.username = user.username
            st.success(f"Welcome back, {user.username}!")
            st.rerun()
        else:
            st.error("Invalid email or password.")


def show_register_form():
    st.header("Create an account")
    with st.form("register_form"):
        username = st.text_input("Username")
        email = st.text_input("Email")
        password = st.text_input("Password", type="password")
        confirm_password = st.text_input("Confirm Password", type="password")
        submitted = st.form_submit_button("Register")

    if submitted:
        if password != confirm_password:
            st.error("Passwords do not match.")
            return

        session = get_db_session()
        try:
            register_user(session, username.strip(), email.strip().lower(), password)
            st.success("Registration successful. You can now log in.")
            st.info("Please switch to Login from the sidebar.")
        except Exception as exc:
            st.error(str(exc))
        finally:
            session.close()


def logout():
    st.session_state.user_id = None
    st.session_state.username = ""
    st.success("Logged out successfully.")


# ── Gmail connection panel ─────────────────────────────────────────────────
def connection_panel(user_id):
    session = get_db_session()
    account = session.query(EmailAccount).filter(EmailAccount.user_id == user_id).first()

    st.subheader("📬 Email Integration")
    if account and account.connection_status == "connected":
        st.success(f"Connected: {account.email_address}")
        if account.last_sync:
            st.write(f"Last sync: {account.last_sync}")
    else:
        st.warning("No Gmail account connected yet.")

    with st.expander("Connect Gmail account"):
        # ── Always-visible setup guide ─────────────────────────────────────
        st.info(
            "**Gmail requires a 16-character App Password** — not your normal password.\n\n"
            "Quick links: "
            "[1️⃣ Enable 2-Step Verification](https://myaccount.google.com/security)  |  "
            "[2️⃣ Enable IMAP in Gmail](https://mail.google.com/mail/u/0/#settings/fwdandpop)  |  "
            "[3️⃣ Create App Password](https://myaccount.google.com/apppasswords)"
        )

        email_address = st.text_input("Gmail address", value=account.email_address if account else "")
        app_password = st.text_input(
            "App Password (16-character code from Google — no spaces)",
            type="password",
            placeholder="e.g. abcd efgh ijkl mnop  →  abcdefghijklmnop",
        )

        if st.button("Connect account"):
            if not email_address or not app_password:
                st.error("Both Gmail address and App Password are required.")
            else:
                # Strip spaces — Google shows password with spaces but IMAP needs none
                clean_password = app_password.replace(" ", "")
                from backend.email_service import connect_gmail_email
                try:
                    mail = connect_gmail_email(email_address.strip(), clean_password)
                    mail.logout()
                    if not account:
                        account = EmailAccount(
                            user_id=user_id,
                            email_address=email_address.strip(),
                            connection_status="connected",
                            last_sync=datetime.utcnow(),
                        )
                    else:
                        account.email_address = email_address.strip()
                        account.connection_status = "connected"
                        account.last_sync = datetime.utcnow()
                    session.add(account)
                    session.commit()
                    # Store app password only in memory for the running process.
                    EMAIL_CREDENTIALS[account.id] = clean_password
                    st.success("✅ Gmail account connected successfully!")
                    st.rerun()
                except Exception as exc:
                    raw_msg = str(exc)
                    msg_lower = raw_msg.lower()
                    auth_keywords = [
                        "authenticationfailed",
                        "invalid credentials",
                        "application-specific password required",
                        "app-specific",
                        "app password",
                        "authentication failed",
                        "login failed",
                    ]
                    if any(kw in msg_lower for kw in auth_keywords):
                        st.error("❌ Gmail rejected the credentials — follow the checklist below.")
                        st.markdown("""
#### 🔧 Fix checklist — complete all 3 steps

| Step | What to do | Link |
|------|-----------|------|
| **1** | Enable **2-Step Verification** on your Google account | [Open Security settings](https://myaccount.google.com/security) |
| **2** | Enable **IMAP** inside Gmail settings → Forwarding and POP/IMAP | [Open Gmail IMAP settings](https://mail.google.com/mail/u/0/#settings/fwdandpop) |
| **3** | Generate a **16-char App Password** (select "Mail" + "Windows Computer") | [Create App Password](https://myaccount.google.com/apppasswords) |

**Then paste the 16-character code** (spaces are stripped automatically) into the field above.

> ⚠️ Your **normal Gmail password** will always fail here.  
> ⚠️ The App Passwords page only appears **after** Step 1 is done.
""")
                    elif "imap" in msg_lower or "connection" in msg_lower or "network" in msg_lower:
                        st.error("❌ Could not reach Gmail servers.")
                        st.markdown("Check your internet connection and confirm IMAP is enabled: [Gmail IMAP settings →](https://mail.google.com/mail/u/0/#settings/fwdandpop)")
                    else:
                        st.error(f"❌ Connection error: {raw_msg}")
    session.close()


# ── Notifications panel ────────────────────────────────────────────────────
def show_notifications(user_id):
    session = get_db_session()
    notifications = (
        session.query(Notification)
        .filter(Notification.user_id == user_id)
        .order_by(Notification.created_at.desc())
        .all()
    )
    unread = [n for n in notifications if not n.is_read]
    st.subheader(f"🔔 Notifications ({len(unread)} unread)")

    if not notifications:
        st.info("No notifications yet.")
        session.close()
        return

    for notification in notifications:
        if not notification.is_read:
            st.warning(notification.message)
        else:
            st.info(notification.message)

        if st.button("Mark read", key=f"read_{notification.id}"):
            notification.is_read = True
            session.add(notification)
            session.commit()
            st.rerun()

    session.close()


# ── Spam dashboard ─────────────────────────────────────────────────────────
def show_spam_dashboard(user_id):
    session = get_db_session()
    total_scanned = (
        session.query(ScannedEmail).filter(ScannedEmail.user_id == user_id).count()
    )
    total_spam = (
        session.query(ScannedEmail)
        .filter(ScannedEmail.user_id == user_id)
        .filter(ScannedEmail.prediction == "Spam")
        .count()
    )
    total_safe = total_scanned - total_spam

    st.subheader("📊 Spam Dashboard")
    col1, col2, col3 = st.columns(3)
    col1.metric("Total Scanned", total_scanned)
    col2.metric("🚨 Spam", total_spam)
    col3.metric("✅ Safe", total_safe)

    recent_spam = (
        session.query(ScannedEmail)
        .filter(ScannedEmail.user_id == user_id)
        .filter(ScannedEmail.prediction == "Spam")
        .order_by(ScannedEmail.scanned_at.desc())
        .limit(5)
        .all()
    )

    st.write("### Recent Spam Alerts")
    if recent_spam:
        for email_item in recent_spam:
            st.write(
                f"**{email_item.scanned_at.strftime('%Y-%m-%d %H:%M')}** — {email_item.sender} — {email_item.subject}"
            )
    else:
        st.write("No spam alerts yet.")

    top_senders = (
        session.query(ScannedEmail.sender)
        .filter(ScannedEmail.user_id == user_id)
        .filter(ScannedEmail.prediction == "Spam")
        .all()
    )
    sender_counts: dict = {}
    for (sender,) in top_senders:
        sender_counts[sender] = sender_counts.get(sender, 0) + 1

    if sender_counts:
        sorted_senders = sorted(sender_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        st.write("### Most Frequent Spam Senders")
        for sender, count in sorted_senders:
            st.write(f"- {sender}: {count}")
    else:
        st.write("No spam senders yet.")

    session.close()


# ── Email management ───────────────────────────────────────────────────────
def show_email_management(user_id):
    session = get_db_session()
    query = session.query(ScannedEmail).filter(ScannedEmail.user_id == user_id)

    filter_option = st.selectbox("Filter emails", ["All", "Spam", "Not Spam"])
    if filter_option != "All":
        query = query.filter(ScannedEmail.prediction == filter_option)

    search_term = st.text_input("Search subject, sender, or content")
    if search_term:
        like_term = f"%{search_term}%"
        query = query.filter(
            ScannedEmail.subject.ilike(like_term)
            | ScannedEmail.sender.ilike(like_term)
            | ScannedEmail.email_content.ilike(like_term)
        )

    emails = query.order_by(ScannedEmail.scanned_at.desc()).limit(50).all()
    st.subheader("📥 Scanned Emails")

    if not emails:
        st.info("No emails match the current filter.")
        session.close()
        return

    for email_item in emails:
        with st.expander(f"{email_item.prediction} — {email_item.subject}"):
            st.write(f"**From:** {email_item.sender}")
            st.write(f"**Received:** {email_item.scanned_at}")
            st.write(f"**Confidence:** {email_item.confidence:.2f}")
            st.write(email_item.email_content)
            if st.button("Delete record", key=f"delete_{email_item.id}"):
                session.delete(email_item)
                session.commit()
                st.success("Scan history deleted.")
                st.rerun()

    st.divider()
    if st.button("🗑️ Delete all scan history", type="primary"):
        session.query(ScannedEmail).filter(ScannedEmail.user_id == user_id).delete()
        session.commit()
        st.success("All scan history deleted.")
        st.rerun()

    session.close()


# ── Main entrypoint ────────────────────────────────────────────────────────
def main():
    # ── Sidebar logo ───────────────────────────────────────────────────────
    with st.sidebar:
        if _LOGO_PATH.exists():
            st.markdown('<div class="sidebar-logo">', unsafe_allow_html=True)
            st.image(str(_LOGO_PATH), width=120)
            st.markdown('</div>', unsafe_allow_html=True)
        st.markdown("---")

    # ── Main header ────────────────────────────────────────────────────────
    col_logo, col_title = st.columns([1, 9])
    with col_logo:
        if _LOGO_PATH.exists():
            st.image(str(_LOGO_PATH), width=80)
    with col_title:
        st.markdown("""
        <div class="app-header">
            <div>
                <h1>AI Spam Detection Dashboard</h1>
                <p>Powered by Machine Learning &mdash; Protect your inbox in real time</p>
            </div>
        </div>
        """, unsafe_allow_html=True)

    if st.session_state.user_id is None:
        page = st.sidebar.selectbox("Menu", ["Login", "Register"])
        if page == "Login":
            show_login_form()
        else:
            show_register_form()
        return

    st.sidebar.write(f"Logged in as: **{st.session_state.username}**")
    if st.sidebar.button("Logout"):
        logout()
        st.rerun()

    action = st.sidebar.selectbox(
        "Dashboard",
        ["Overview", "Notifications", "Email Management", "Connect Gmail"],
    )

    if action == "Overview":
        connection_panel(st.session_state.user_id)
        if st.button("🔄 Scan now"):
            with st.spinner("Scanning emails…"):
                results = scan_all_accounts()
            st.write(results)
        show_spam_dashboard(st.session_state.user_id)

    elif action == "Notifications":
        show_notifications(st.session_state.user_id)

    elif action == "Email Management":
        connection_panel(st.session_state.user_id)
        show_email_management(st.session_state.user_id)

    elif action == "Connect Gmail":
        connection_panel(st.session_state.user_id)


if __name__ == "__main__":
    main()
