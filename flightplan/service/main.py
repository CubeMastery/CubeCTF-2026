from fastapi import FastAPI

from config import PORTAL_NAME
from database import init_db
from routes import router


app = FastAPI(title=PORTAL_NAME, docs_url=None, redoc_url=None)
app.include_router(router)


@app.on_event("startup")
def startup():
    init_db()
