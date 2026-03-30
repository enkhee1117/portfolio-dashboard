import sys
import os

# Add the api directory to Python path so 'app' package can be found
sys.path.insert(0, os.path.dirname(__file__))

from app.main import app
