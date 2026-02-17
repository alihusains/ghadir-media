#!/usr/bin/env python3
import csv
import logging
import os
import sys
from typing import List, Dict, Any, Sequence, Tuple
from urllib.parse import urlparse, quote

import requests

# --- Configuration ---
INPUT_CSV = "downloader.csv"
OUTPUT_CSV = "updated.csv"
BRANCH = "main"
REPO = "alihusains/ghadir-media"
TIMEOUT = 60  # seconds
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AudioDownloader/1.0"

# Mapping of common audio content types to file extensions
CONTENT_TYPE_EXTENSIONS = {
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/ogg": ".ogg",
    "audio/opus": ".opus",
    "audio/mp4": ".m4a",
    "audio/x-m4a": ".m4a",
    "audio/aac": ".aac",
}

# Setup Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)


def infer_extension(content_type: str) -> str:
    """Returns the matching extension for a mime type or an empty string."""
    if not content_type:
        return ""
    mime = content_type.split(";")[0].strip().lower()
    return CONTENT_TYPE_EXTENSIONS.get(mime, "")


def load_csv_data(path: str) -> Tuple[List[Dict[str, Any]], Sequence[str]]:
    """Reads the CSV and returns rows and the original header sequence."""
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Input CSV not found: {path}")
    
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames if reader.fieldnames is not None else []
        return list(reader), fieldnames


def write_csv_data(path: str, rows: List[Dict[str, Any]], original_headers: Sequence[str]) -> None:
    """Writes the updated data to CSV with new columns included."""
    new_columns = ["github_audio_url", "cdnjs_url", "status", "detected_content_type"]
    
    # Create a fresh list for headers to satisfy type checkers and avoid mutation
    final_headers = list(original_headers)
    for col in new_columns:
        if col not in final_headers:
            final_headers.append(col)

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=final_headers)
        writer.writeheader()
        writer.writerows(rows)


def main():
    try:
        rows, input_headers = load_csv_data(INPUT_CSV)
    except Exception as e:
        logger.critical(f"Failed to load input file: {e}")
        sys.exit(1)

    if not rows:
        logger.warning("No rows found in CSV. Exiting.")
        write_csv_data(OUTPUT_CSV, [], input_headers)
        return

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    updated_rows = []

    logger.info(f"Processing {len(rows)} entries...")

    for idx, row in enumerate(rows, start=1):
        folder = row.get("folder_name", "").strip().rstrip("/")
        audio_name = row.get("audio_name", "").strip()
        audio_url = row.get("audio_url", "").strip()

        # Initialize output metadata
        res = dict(row)
        res.update({
            "github_audio_url": "",
            "cdnjs_url": "",
            "status": "pending",
            "detected_content_type": ""
        })

        if not audio_url:
            res["status"] = "error: missing url"
            updated_rows.append(res)
            continue

        try:
            parsed = urlparse(audio_url)
            ext = os.path.splitext(parsed.path)[1].lower()

            # Ensure local directory exists
            if folder:
                os.makedirs(folder, exist_ok=True)

            with session.get(audio_url, timeout=TIMEOUT, stream=True) as r:
                r.raise_for_status()
                
                content_type = r.headers.get("Content-Type", "")
                res["detected_content_type"] = content_type

                if not ext:
                    ext = infer_extension(content_type)
                    if not ext:
                        raise ValueError(f"Could not determine extension for {content_type}")

                # Construct clean filename
                base = audio_name or os.path.basename(parsed.path) or f"audio_{idx}"
                filename = base if base.lower().endswith(ext) else f"{base}{ext}"
                
                # Sanitize path for local OS
                rel_path = os.path.join(folder, filename) if folder else filename
                
                if os.path.isfile(rel_path):
                    res["status"] = "already_exists"
                    logger.info(f"[{idx}] Already exists: {rel_path}")
                else:
                    with open(rel_path, "wb") as f:
                        for chunk in r.iter_content(chunk_size=16384):
                            f.write(chunk)
                    res["status"] = "downloaded"
                    logger.info(f"[{idx}] Saved: {rel_path}")

                # URL-safe encoding for GitHub/CDN paths (replaces spaces with %20, etc.)
                safe_rel_path = quote(rel_path.replace("\\", "/"))
                res["github_audio_url"] = f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/{safe_rel_path}"
                res["cdnjs_url"] = f"https://cdn.jsdelivr.net/gh/{REPO}@{BRANCH}/{safe_rel_path}"

        except Exception as e:
            res["status"] = f"error: {str(e)}"
            logger.error(f"[{idx}] Failed {audio_url}: {e}")

        updated_rows.append(res)

    # Save the results
    try:
        write_csv_data(OUTPUT_CSV, updated_rows, input_headers)
        logger.info(f"Successfully wrote results to {OUTPUT_CSV}")
    except Exception as e:
        logger.error(f"Failed to write output CSV: {e}")

if __name__ == "__main__":
    main()