"""Authentication dependencies and user utility functions."""
from fastapi import HTTPException, Header
from google.cloud.firestore_v1.base_query import FieldFilter
from typing import Optional
import logging

logger = logging.getLogger("portfolio")


def get_current_user(authorization: Optional[str] = Header(None)) -> str:
    """Extract user_id from Firebase ID token. Raises 401 if not authenticated."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authentication required")
    try:
        from firebase_admin import auth
        token = authorization.replace("Bearer ", "")
        decoded = auth.verify_id_token(token)
        return decoded['uid']
    except Exception as e:
        logger.warning(f"Auth token verification failed: {e}")
        raise HTTPException(status_code=401, detail="Invalid or expired token")


def get_optional_user(authorization: Optional[str] = Header(None)) -> str:
    """Extract user_id if token present, otherwise return 'anonymous'."""
    if not authorization or not authorization.startswith("Bearer "):
        return "anonymous"
    try:
        from firebase_admin import auth
        token = authorization.replace("Bearer ", "")
        decoded = auth.verify_id_token(token)
        return decoded['uid']
    except Exception:
        return "anonymous"


def get_user_tickers(db, user_id: str) -> set[str]:
    """Return tickers from user's asset_themes subcollection."""
    tickers: set[str] = set()
    for doc in db.collection('users').document(user_id).collection('asset_themes').stream():
        tickers.add(doc.id)
    return tickers


def normalize_theme(name: str) -> str:
    """Normalize theme names to Title Case for consistent grouping."""
    return name.strip().title() if name else ""
