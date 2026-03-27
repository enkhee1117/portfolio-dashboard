import firebase_admin
from firebase_admin import credentials, firestore
import os

def get_db():
    if not firebase_admin._apps:
        cred_path = os.path.join(os.path.dirname(__file__), "..", "firebase-credentials.json")
        if os.path.exists(cred_path):
            cred = credentials.Certificate(cred_path)
            firebase_admin.initialize_app(cred)
        else:
            # Fallback for production if using environment variables
            firebase_admin.initialize_app()
            
    return firestore.client()
