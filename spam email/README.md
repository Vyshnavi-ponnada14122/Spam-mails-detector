# AI Spam Email Detector

An AI-powered spam detection app built with Streamlit, SQLite, and scikit-learn.

## Project Structure

```
spam email/
├── backend/                  ← All server-side logic
│   ├── __init__.py
│   ├── models.py             ← SQLAlchemy ORM models
│   ├── db.py                 ← Database engine & session factory
│   ├── auth.py               ← User registration & authentication
│   ├── ml_model.py           ← Spam classifier (Naïve Bayes)
│   ├── email_service.py      ← Gmail IMAP scanning & notifications
│   └── scheduler.py          ← Background job to scan every 5 min
├── frontend/                 ← Streamlit UI
│   └── app.py
├── spam_app.db               ← SQLite database (auto-created)
├── spam_detector.joblib      ← Trained ML model (auto-created)
├── requirements.txt
├── run.py                    ← Convenience launcher
└── README.md
```

## Setup

```bash
# 1. Create and activate a virtual environment (optional but recommended)
python -m venv .venv
.venv\Scripts\activate        # Windows
source .venv/bin/activate     # macOS/Linux

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run the app
python run.py
# OR
streamlit run frontend/app.py
```

## Usage

1. Register an account and log in.
2. Go to **Connect Gmail** and enter your Gmail address + an [App Password](https://support.google.com/accounts/answer/185833).
3. Use **Scan now** on the Overview page to scan unseen emails immediately.
4. The background scheduler also scans every **5 minutes** automatically.
5. Spam alerts appear in **Notifications**; browse detected emails in **Email Management**.

## Notes

- App passwords are stored **only in memory** for the current process. Restart clears them.
- For production use, replace app-password auth with **OAuth2**.
