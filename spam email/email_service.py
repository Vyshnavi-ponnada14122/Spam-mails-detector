import imaplib
import email
import email.utils
import re
from datetime import datetime
from email.header import decode_header
from models import EmailAccount, ScannedEmail, Notification
from db import get_db_session
from ml_model import load_or_train_model, predict_email

EMAIL_CREDENTIALS = {}

# Lazy model reference — loaded on first scan, not at import time.
_MODEL = None


def _get_model():
    global _MODEL
    if _MODEL is None:
        _MODEL = load_or_train_model()
    return _MODEL


def decode_mime_header(value):
    if not value:
        return ""

    decoded_parts = decode_header(value)
    header = ""
    for text, encoding in decoded_parts:
        if isinstance(text, bytes):
            header += text.decode(encoding or "utf-8", errors="ignore")
        else:
            header += text
    return header


def clean_text(text: str) -> str:
    if not text:
        return ""
    text = text.replace("\r", " ").replace("\n", " ")
    return re.sub(r"\s+", " ", text).strip()


def extract_email_body(message):
    if message.is_multipart():
        for part in message.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get("Content-Disposition", ""))
            if content_type == "text/plain" and "attachment" not in content_disposition:
                body = part.get_payload(decode=True)
                return body.decode(part.get_content_charset("utf-8"), errors="ignore")

        for part in message.walk():
            content_type = part.get_content_type()
            if content_type == "text/html":
                html = part.get_payload(decode=True).decode(part.get_content_charset("utf-8"), errors="ignore")
                return re.sub(r"<[^>]+>", " ", html)
        return ""

    body = message.get_payload(decode=True)
    if body is None:
        return ""
    return body.decode(message.get_content_charset("utf-8"), errors="ignore")


def connect_gmail_email(email_address: str, app_password: str):
    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    try:
        mail.login(email_address, app_password)
    except imaplib.IMAP4.error as e:
        msg = str(e)
        # Detect common Google app-password prompt and raise a clearer error
        if "Application-specific password required" in msg or "app-specific" in msg.lower():
            raise ValueError(
                "Application-specific password required. Visit https://support.google.com/accounts/answer/185833 to create an app password for IMAP access."
            )
        raise
    return mail


def fetch_unseen_messages(mail):
    mail.select("inbox")
    status, data = mail.search(None, "UNSEEN")
    if status != "OK":
        return []

    message_ids = data[0].split()
    messages = []
    for message_id in message_ids:
        status, msg_data = mail.fetch(message_id, "RFC822")
        if status != "OK" or not msg_data or not msg_data[0]:
            continue
        raw_email = msg_data[0][1]
        messages.append((message_id, raw_email))
    return messages


def parse_message(raw_email):
    message = email.message_from_bytes(raw_email)
    subject = decode_mime_header(message.get("Subject"))
    from_header = decode_mime_header(message.get("From"))
    sender = from_header
    received = message.get("Date")
    message_id = message.get("Message-ID")
    body = extract_email_body(message)
    return {
        "subject": clean_text(subject),
        "sender": clean_text(sender),
        "body": clean_text(body),
        "received": received,
        "message_id": message_id,
    }


def normalize_received(received_str: str):
    """Parse an RFC 2822 Date header into a naive local datetime."""
    if not received_str:
        return datetime.utcnow()
    try:
        # email.utils.parsedate_to_datetime handles all RFC 2822 variants
        dt = email.utils.parsedate_to_datetime(received_str)
        return dt.astimezone().replace(tzinfo=None)
    except Exception:
        return datetime.utcnow()


def scan_email_account(account: EmailAccount):
    password = EMAIL_CREDENTIALS.get(account.id)
    if not password:
        return

    try:
        mail = connect_gmail_email(account.email_address, password)
        unseen = fetch_unseen_messages(mail)
        session = get_db_session()
        model = _get_model()
        duplicates = 0
        added = 0

        for uid, raw_email in unseen:
            parsed = parse_message(raw_email)
            received_time = normalize_received(parsed["received"])
            message_id = parsed.get("message_id")

            already = None
            if message_id:
                already = (
                    session.query(ScannedEmail)
                    .filter(ScannedEmail.user_id == account.user_id)
                    .filter(ScannedEmail.message_id == message_id)
                    .first()
                )

            if not already:
                already = (
                    session.query(ScannedEmail)
                    .filter(ScannedEmail.user_id == account.user_id)
                    .filter(ScannedEmail.sender == parsed["sender"])
                    .filter(ScannedEmail.subject == parsed["subject"])
                    .filter(ScannedEmail.scanned_at == received_time)
                    .first()
                )

            if already:
                duplicates += 1
                continue

            text_for_model = f"{parsed['subject']} {parsed['body']}"
            prediction, confidence = predict_email(text_for_model, model=model)
            scanned_email = ScannedEmail(
                user_id=account.user_id,
                sender=parsed["sender"],
                subject=parsed["subject"],
                email_content=parsed["body"],
                prediction=prediction,
                confidence=confidence,
                scanned_at=received_time,
                message_id=message_id,
            )
            session.add(scanned_email)
            session.commit()
            added += 1

            if prediction == "Spam":
                notification = Notification(
                    user_id=account.user_id,
                    message=(
                        f"⚠️ Warning: A suspicious spam email was detected from {parsed['sender']} "
                        f"with subject '{parsed['subject']}'"
                    ),
                    notification_type="spam_alert",
                )
                session.add(notification)
                session.commit()

        account.last_sync = datetime.utcnow()
        session.add(account)
        session.commit()
        session.close()

        try:
            mail.logout()
        except Exception:
            pass

        return {"added": added, "duplicates": duplicates}
    except imaplib.IMAP4.error as ex:
        return {"error": str(ex)}
    except Exception as ex:
        return {"error": str(ex)}


def scan_all_accounts():
    session = get_db_session()
    connected_accounts = session.query(EmailAccount).filter(EmailAccount.connection_status == "connected").all()
    results = []
    for account in connected_accounts:
        result = scan_email_account(account)
        results.append({"account_id": account.id, "email": account.email_address, "result": result})
    session.close()
    return results
