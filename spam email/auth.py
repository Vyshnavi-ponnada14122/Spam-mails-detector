from passlib.hash import pbkdf2_sha256
from models import User


def hash_password(password: str) -> str:
    return pbkdf2_sha256.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return pbkdf2_sha256.verify(password, password_hash)


def register_user(session, username: str, email: str, password: str) -> User:
    existing = session.query(User).filter(User.email == email).first()
    if existing:
        raise ValueError("A user with this email already exists.")

    password_hash = hash_password(password)
    user = User(username=username, email=email, password_hash=password_hash)
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def authenticate_user(session, email: str, password: str):
    user = session.query(User).filter(User.email == email).first()
    if user and verify_password(password, user.password_hash):
        return user
    return None


def get_user_by_email(session, email: str):
    return session.query(User).filter(User.email == email).first()
