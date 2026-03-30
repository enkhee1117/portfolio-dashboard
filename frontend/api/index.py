import sys
import os

# Add the api directory to Python path so 'app' package can be found
sys.path.insert(0, os.path.dirname(__file__))

from fastapi import FastAPI
from app.main import app as api_app

# Mount the API app under /api prefix for Vercel
app = FastAPI()
app.mount("/api", api_app)
