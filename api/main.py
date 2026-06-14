import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from api.routes import flows, runs, regression, analytics

app = FastAPI(
    title="Browser Automation AI Agent",
    description="E2E Self-Healing Browser Automation System",
    version="1.0"
)

# Allow CORS for all origins (frontend development support)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include sub-routers
app.include_router(flows.router, prefix="/api/flows", tags=["flows"])
app.include_router(runs.router, prefix="/api/runs", tags=["runs"])
app.include_router(regression.router, prefix="/api/regression", tags=["regression"])
app.include_router(analytics.router, prefix="/api/analytics", tags=["analytics"])

# Define paths
STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
ARTIFACTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "artifacts")

os.makedirs(STATIC_DIR, exist_ok=True)
os.makedirs(ARTIFACTS_DIR, exist_ok=True)

# Mount artifacts folder statically to allow viewing screenshots/logs directly in the browser
app.mount("/artifacts", StaticFiles(directory=ARTIFACTS_DIR), name="artifacts")

# Fallback route to serve frontend app
@app.get("/")
def read_root():
    index_path = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "Browser Automation AI Agent API is running. Create static/index.html to view dashboard."}

# Mount static directory at last so index fallback works properly
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="localhost", port=9090)
