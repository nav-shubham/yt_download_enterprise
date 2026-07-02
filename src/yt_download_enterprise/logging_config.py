import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from .config import config_manager


def setup_logging(level: str = "INFO") -> logging.Logger:
    """Sets up rotated file and console logging."""
    logger = logging.getLogger("yt_download_enterprise")
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    
    # Avoid duplicate handlers if already set up
    if logger.handlers:
        return logger

    # Log Formatter
    formatter = logging.Formatter(
        "[%(asctime)s] %(levelname)s [%(name)s:%(filename)s:%(lineno)d] - %(message)s"
    )

    # Console Handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.INFO)
    logger.addHandler(console_handler)

    # Rotating File Handler
    log_file = config_manager.log_dir / "app.log"
    try:
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=10 * 1024 * 1024,  # 10MB
            backupCount=5,
            encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        file_handler.setLevel(logging.DEBUG)
        logger.addHandler(file_handler)
    except Exception as e:
        print(f"[!] Error creating file logger: {e}")

    # Set root logger levels for noisy dependencies
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("fastapi").setLevel(logging.INFO)
    
    logger.info("Structured logging engine initialized successfully.")
    return logger


# Instantiate logger
logger = setup_logging()
