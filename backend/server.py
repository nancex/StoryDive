"""StoryDive API Server - Entry Point."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .routes import router

app = FastAPI(title="StoryDive API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)

if __name__ == "__main__":
    import uvicorn
    log_config = {
        "version": 1,
        "disable_existing_loggers": True,
        "formatters": {
            "plain": {
                "format": "%(asctime)s [%(levelname)s] %(message)s",
                "datefmt": "%H:%M:%S",
            }
        },
        "handlers": {
            "plain": {"class": "logging.StreamHandler", "formatter": "plain"}
        },
        "loggers": {
            "": {"handlers": ["plain"], "level": "INFO"},
            "uvicorn": {"level": "INFO"},
            "uvicorn.access": {"level": "INFO"}
        },
    }
    uvicorn.run(app, host="0.0.0.0", port=8800, log_config=log_config)
