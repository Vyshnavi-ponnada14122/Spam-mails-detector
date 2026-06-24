import os
import joblib
import pandas as pd
from pathlib import Path
from sklearn.feature_extraction.text import CountVectorizer
from sklearn.naive_bayes import MultinomialNB
from sklearn.pipeline import make_pipeline

# Always resolve the model file relative to the project root (parent of this backend/ folder)
PROJECT_ROOT = Path(__file__).parent.parent
MODEL_PATH = PROJECT_ROOT / "spam_detector.joblib"


def get_sample_training_data() -> pd.DataFrame:
    spam_samples = [
        "Win a free iPhone now",
        "Your account was hacked, update your password",
        "Congratulations! You are selected for a prize",
        "Urgent: confirm your bank details",
        "Offer expires today, click here",
        "You've won a lottery, claim your reward",
    ]
    ham_samples = [
        "Meeting tomorrow at 10am",
        "Your order has been shipped",
        "Here's the weekly project update",
        "Lunch plan for this afternoon",
        "Invoice for your recent purchase",
        "Can we reschedule our call?",
    ]

    texts = spam_samples + ham_samples
    labels = ["Spam"] * len(spam_samples) + ["Not Spam"] * len(ham_samples)
    return pd.DataFrame({"text": texts, "label": labels})


def train_spam_model():
    training_data = get_sample_training_data()
    model = make_pipeline(CountVectorizer(stop_words="english"), MultinomialNB())
    model.fit(training_data["text"], training_data["label"])
    joblib.dump(model, MODEL_PATH)
    return model


def load_or_train_model():
    if os.path.exists(MODEL_PATH):
        return joblib.load(MODEL_PATH)
    return train_spam_model()


def predict_email(text: str, model=None):
    if model is None:
        model = load_or_train_model()

    prediction = model.predict([text])[0]
    probabilities = model.predict_proba([text])[0]
    confidence = float(max(probabilities))
    return prediction, confidence
