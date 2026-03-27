from fastapi import FastAPI
from api.app.main import app as core_app

app = FastAPI()

# Mount the existing app at /api so routes resolve correctly
app.mount("/api", core_app)
