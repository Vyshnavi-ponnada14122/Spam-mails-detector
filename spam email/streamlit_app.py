import streamlit as st
from datetime import datetime
from db import init_db, get_db_session
from auth import authenticate_user, register_user
from models import EmailAccount, ScannedEmail, Notification
from email_service import EMAIL_CREDENTIALS, scan_all_accounts
from scheduler import start_scheduler
from ml_model import load_or_train_model

init_db()
load_or_train_model()

st.set_page_config(page_title="AI Spam Detector", page_icon="📧", layout="wide")

if "user_id" not in st.session_state:
    st.session_state.user_id = None
if "username" not in st.session_state:
    st.session_state.username = ""
if "scheduler_started" not in st.session_state:
    start_scheduler()
    st.session_state.scheduler_started = True


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
            user = register_user(session, username.strip(), email.strip().lower(), password)
            st.success("Registration successful. You can now log in.")
            st.info("Please log in to continue.")
        except Exception as exc:
            st.error(str(exc))
        finally:
            session.close()


def logout():
    st.session_state.user_id = None
    st.session_state.username = ""
    st.success("Logged out successfully.")


def connection_panel(user_id):
    session = get_db_session()
    account = session.query(EmailAccount).filter(EmailAccount.user_id == user_id).first()

    st.subheader("Email Integration")
    if account and account.connection_status == "connected":
        st.success(f"Connected: {account.email_address}")
        if account.last_sync:
            st.write(f"Last sync: {account.last_sync}")
    else:
        st.warning("No Gmail account connected yet.")

    with st.expander("Connect Gmail account"):
        email_address = st.text_input("Gmail address", value=account.email_address if account else "")
        app_password = st.text_input(
            "App password (Gmail app password for development)",
            type="password",
        )
        if st.button("Connect account"):
            if not email_address or not app_password:
                st.error("Email and app password are required.")
            else:
                from email_service import connect_gmail_email
                try:
                    mail = connect_gmail_email(email_address, app_password)
                    mail.logout()
                    if not account:
                        account = EmailAccount(
                            user_id=user_id,
                            email_address=email_address,
                            connection_status="connected",
                            last_sync=datetime.utcnow(),
                        )
                    else:
                        account.email_address = email_address
                        account.connection_status = "connected"
                        account.last_sync = datetime.utcnow()
                    session.add(account)
                    session.commit()
                    # Store app password only in memory for the running process.
                    # For production use OAuth2 and do not persist raw passwords.
                    EMAIL_CREDENTIALS[account.id] = app_password
                    st.success("Gmail account connected successfully.")
                except Exception as exc:
                    msg = str(exc)
                    if "Application-specific password required" in msg or "app password" in msg.lower():
                        st.error("Unable to connect: Application-specific password required.")
                        st.markdown(
                            "Follow Google's instructions to create an app password:"
                        )
                        st.markdown("https://support.google.com/accounts/answer/185833")
                        st.info(
                            "If your account uses 2-Step Verification, create an app password and paste it above."
                        )
                    else:
                        st.error(f"Unable to connect: {exc}")
    session.close()


def show_notifications(user_id):
    session = get_db_session()
    notifications = (
        session.query(Notification)
        .filter(Notification.user_id == user_id)
        .order_by(Notification.created_at.desc())
        .all()
    )
    unread = [n for n in notifications if not n.is_read]
    st.subheader(f"Notifications ({len(unread)} unread)")

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

    st.subheader("Spam Dashboard")
    col1, col2, col3 = st.columns(3)
    col1.metric("Total Scanned", total_scanned)
    col2.metric("Spam", total_spam)
    col3.metric("Safe", total_safe)

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
    sender_counts = {}
    for sender, in top_senders:
        sender_counts[sender] = sender_counts.get(sender, 0) + 1

    if sender_counts:
        sorted_senders = sorted(sender_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        st.write("### Most Frequent Spam Senders")
        for sender, count in sorted_senders:
            st.write(f"- {sender}: {count}")
    else:
        st.write("No spam senders yet.")

    session.close()


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
    st.subheader("Scanned Emails")
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


def main():
    st.title("📧 AI Spam Detection Dashboard")

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
        if st.button("Scan now"):
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
