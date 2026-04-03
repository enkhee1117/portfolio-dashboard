"""Shared FastAPI dependencies — avoids circular imports between main.py and routes."""
import os
import json
import logging

logger = logging.getLogger("portfolio")


def _init_firebase():
    import firebase_admin
    from firebase_admin import credentials
    if firebase_admin._apps:
        return
    cred_path = os.path.join(os.path.dirname(__file__), "..", "firebase-credentials.json")
    if os.path.exists(cred_path):
        cred = credentials.Certificate(cred_path)
        firebase_admin.initialize_app(cred)
    elif "FIREBASE_CREDENTIALS_JSON" in os.environ:
        cred_dict = json.loads(os.environ["FIREBASE_CREDENTIALS_JSON"])
        cred = credentials.Certificate(cred_dict)
        firebase_admin.initialize_app(cred)
    else:
        firebase_admin.initialize_app()

_init_firebase()


def get_db():
    from firebase_admin import firestore
    return firestore.client()
