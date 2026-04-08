BASE_URL = "https://masothue.com"
SEARCH_URL = f"{BASE_URL}/Search/"
PROVINCES_URL = f"{BASE_URL}/tra-cuu-ma-so-thue-theo-tinh"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

REQUEST_DELAY = 1.0        # seconds between requests
REQUEST_TIMEOUT = 30        # seconds
MAX_RETRIES = 3
OUTPUT_DIR = "output"
