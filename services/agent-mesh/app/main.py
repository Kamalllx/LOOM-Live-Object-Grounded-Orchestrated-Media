from fastapi import FastAPI

app = FastAPI(
    title="LOOM Agent Mesh",
    version="1.0.0",
)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "agent-mesh",
    }

