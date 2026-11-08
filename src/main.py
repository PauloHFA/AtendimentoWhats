from fastapi import FastAPI

app = FastAPI(
    title="Atendimento WhatsApp",
    description="API de automação de atendimento via WhatsApp.",
    version="0.1.0",
)


@app.get("/health", tags=["operational"])
def health() -> dict[str, str]:
    return {"status": "ok"}
