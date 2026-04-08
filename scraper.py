"""Core scraper module for masothue.com"""

import time
import re
import requests
from bs4 import BeautifulSoup
from config import BASE_URL, SEARCH_URL, PROVINCES_URL, HEADERS, REQUEST_DELAY, REQUEST_TIMEOUT, MAX_RETRIES


class MasoThueScraper:
    def __init__(self, delay=REQUEST_DELAY):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.delay = delay

    def _get(self, url):
        """GET request with retries and rate limiting."""
        for attempt in range(MAX_RETRIES):
            try:
                time.sleep(self.delay)
                resp = self.session.get(url, timeout=REQUEST_TIMEOUT)
                resp.raise_for_status()
                resp.encoding = "utf-8"
                return resp
            except requests.RequestException as e:
                print(f"  [Retry {attempt+1}/{MAX_RETRIES}] {e}")
                if attempt == MAX_RETRIES - 1:
                    raise
                time.sleep(self.delay * (attempt + 1))

    def _soup(self, url):
        return BeautifulSoup(self._get(url).text, "lxml")

    # ------------------------------------------------------------------
    # Search mode
    # ------------------------------------------------------------------
    def search(self, query):
        """Search by tax ID or company name. Returns list of company dicts."""
        # Use type=name for all searches (type=auto has anti-bot redirect issues)
        url = f"{SEARCH_URL}?q={requests.utils.quote(query)}&type=name"
        soup = self._soup(url)

        # Check if we landed directly on a company detail page
        detail = self._parse_detail_page(soup)
        if detail and detail.get("tax_id"):
            return [detail]

        # Otherwise parse search result listing
        return self._parse_listing(soup, url)

    # ------------------------------------------------------------------
    # Crawl-all mode
    # ------------------------------------------------------------------
    def get_provinces(self):
        """Return list of (name, url) for all provinces."""
        soup = self._soup(PROVINCES_URL)
        provinces = []
        for a in soup.select("table.tax-listing td a[href*='tra-cuu-ma-so-thue-theo-tinh']"):
            href = a.get("href", "")
            if not href.startswith("http"):
                href = BASE_URL + href
            provinces.append((a.get_text(strip=True), href))
        # fallback: try div-based links
        if not provinces:
            for a in soup.select("a[href*='tra-cuu-ma-so-thue-theo-tinh/']"):
                href = a.get("href", "")
                name = a.get_text(strip=True)
                if not name or name in ("Theo tỉnh thành phố", "Tỉnh / Thành phố"):
                    continue
                if not href.startswith("http"):
                    href = BASE_URL + href
                if href != PROVINCES_URL and href != PROVINCES_URL + "/" and (name, href) not in provinces:
                    provinces.append((name, href))
        # Filter out the general provinces page link
        provinces = [(n, u) for n, u in provinces
                     if u.rstrip("/") != PROVINCES_URL.rstrip("/")]
        return provinces

    def crawl_province(self, province_url, max_pages=None, callback=None):
        """Crawl all companies in a province. Yields company dicts."""
        page = 1
        while True:
            if max_pages and page > max_pages:
                break
            url = f"{province_url}?page={page}" if page > 1 else province_url
            print(f"  Page {page}: {url}")
            soup = self._soup(url)
            companies = self._parse_listing(soup, url)
            if not companies:
                break
            for c in companies:
                if callback:
                    callback(c)
                yield c
            # Check if there is a next page
            if not self._has_next_page(soup, page):
                break
            page += 1

    # ------------------------------------------------------------------
    # Detail page
    # ------------------------------------------------------------------
    def get_company_detail(self, detail_url):
        """Fetch and parse a single company detail page."""
        soup = self._soup(detail_url)
        return self._parse_detail_page(soup)

    def _parse_detail_page(self, soup):
        """Parse company detail from a BeautifulSoup object.
        Returns None if this is not a detail page (e.g. search listing)."""
        data = {}

        # The reliable indicator of a detail page is table.table-taxinfo
        taxinfo_table = soup.select_one("table.table-taxinfo")
        if not taxinfo_table:
            return None

        # Tax ID and company name from h1: "TAXID - Company Name"
        h1 = soup.select_one("h1")
        if h1:
            h1_text = h1.get_text(strip=True)
            match = re.search(r"(\d{10,14})", h1_text)
            if match:
                data["tax_id"] = match.group(1)
            name_match = re.search(r"\d{10,14}\s*-\s*(.+)", h1_text)
            if name_match:
                data["company_name"] = name_match.group(1).strip()

        # Parse all rows from table.table-taxinfo
        for row in taxinfo_table.select("tr"):
            cells = row.select("td")
            if len(cells) >= 2:
                label = cells[0].get_text(strip=True).rstrip(":").strip()
                value = cells[1].get_text(" ", strip=True)
                self._map_field(data, label, value)

        return data if data.get("tax_id") else None

    def _map_field(self, data, label, value):
        label_lower = label.lower()
        mapping = {
            "mã số thuế": "tax_id",
            "ma so thue": "tax_id",
            "tên công ty": "company_name",
            "ten cong ty": "company_name",
            "tên quốc tế": "international_name",
            "tên viết tắt": "short_name",
            "địa chỉ thuế": "tax_address",
            "địa chỉ": "address",
            "dia chi": "address",
            "người đại diện": "representative",
            "nguoi dai dien": "representative",
            "giám đốc": "representative",
            "điện thoại": "phone",
            "trạng thái": "status",
            "tình trạng": "status",
            "trang thai": "status",
            "loại doanh nghiệp": "company_type",
            "ngày hoạt động": "start_date",
            "quản lý bởi": "tax_authority",
            "cơ quan thuế": "tax_authority",
            "loại hình dn": "company_type",
            "loại hình doanh nghiệp": "company_type",
            "ngành nghề chính": "main_business",
        }
        for keyword, field in mapping.items():
            if keyword in label_lower:
                if field not in data or not data[field]:
                    # Clean representative: remove "Ngoài ra, ... còn đại diện..." suffix
                    if field == "representative" and "Ngoài ra" in value:
                        value = value.split("Ngoài ra")[0].strip()
                    # Clean main_business: remove "Chi tiết:" suffix
                    if field == "main_business" and "Chi tiết:" in value:
                        value = value.split("Chi tiết:")[0].strip()
                    data[field] = value
                break

    # ------------------------------------------------------------------
    # Listing page
    # ------------------------------------------------------------------
    def _parse_listing(self, soup, current_url):
        """Parse a listing page and return list of basic company info dicts."""
        results = []

        # Primary: div[data-prefetch] entries (current site structure)
        for entry in soup.select("div[data-prefetch]"):
            href = entry.get("data-prefetch", "")
            if not href.startswith("http"):
                href = BASE_URL + href

            # Company name from h3 > a
            name_el = entry.select_one("h3 a")
            name = name_el.get_text(strip=True) if name_el else ""

            # Tax ID from href pattern
            href_match = re.search(r"/(\d{10,14})-", href)
            tax_id = href_match.group(1) if href_match else ""

            # Representative from em > a or just text after "Người đại diện:"
            rep = ""
            rep_el = entry.select_one("em a")
            if rep_el:
                rep = rep_el.get_text(strip=True)

            # Address from <address> tag
            addr = ""
            addr_el = entry.select_one("address")
            if addr_el:
                addr = addr_el.get_text(strip=True)

            if name or tax_id:
                results.append({
                    "tax_id": tax_id,
                    "company_name": name,
                    "representative": rep,
                    "address": addr,
                    "detail_url": href,
                })

        # Fallback: any link that looks like a company page
        if not results:
            for a in soup.select("a[href]"):
                href = a.get("href", "")
                match = re.match(r"^/?(\d{10,14})-", href.lstrip("/"))
                if match:
                    if not href.startswith("http"):
                        href = BASE_URL + "/" + href.lstrip("/")
                    name = a.get_text(strip=True)
                    if name and len(name) > 3 and not name.isdigit():
                        results.append({
                            "tax_id": match.group(1),
                            "company_name": name,
                            "detail_url": href,
                        })

        # Deduplicate
        seen = set()
        unique = []
        for r in results:
            key = r.get("tax_id") or r.get("detail_url")
            if key and key not in seen:
                seen.add(key)
                unique.append(r)
        return unique

    def _has_next_page(self, soup, current_page):
        """Check if pagination has a next page."""
        for a in soup.select("a[href*='page=']"):
            href = a.get("href", "")
            m = re.search(r"page=(\d+)", href)
            if m and int(m.group(1)) == current_page + 1:
                return True
        return False
