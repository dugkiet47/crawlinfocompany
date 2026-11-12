"""Core scraper module for masothue.com"""

import time
import re
from urllib.parse import urljoin, urlsplit, parse_qs
import requests
from bs4 import BeautifulSoup
from config import BASE_URL, SEARCH_URL, PROVINCES_URL, HEADERS, REQUEST_DELAY, REQUEST_TIMEOUT, MAX_RETRIES


class SourceBlockedError(requests.RequestException):
    """Terminal source refusal: stop this run without automatic retry."""


class DataMismatchError(ValueError):
    """A returned company does not match the requested tax ID."""


def normalize_tax_id(value):
    value = str(value or "").strip()
    if re.fullmatch(r"[0-9]{13}", value):
        return value[:10] + "-" + value[10:]
    return value if re.fullmatch(r"[0-9]{10}(?:-[0-9]{3})?", value) else None


def source_url(href, base=BASE_URL):
    url = urljoin(base, href)
    parts = urlsplit(url)
    if (parts.scheme != "https" or parts.netloc.lower() != urlsplit(BASE_URL).netloc.lower()
            or parts.username or parts.password):
        raise ValueError("URL outside source: " + url)
    return parts._replace(fragment="").geturl()


def tax_id_from_url(url):
    match = re.match(r"^/([0-9]{10}(?:-[0-9]{3}|[0-9]{3})?)(?:-|/?$)", urlsplit(url).path)
    return normalize_tax_id(match.group(1)) if match else None


class MasoThueScraper:
    def __init__(self, delay=REQUEST_DELAY):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.delay = delay
        self._last_request = None

    def _get(self, url):
        """Rate limit redirects too; retry network/5xx failures only."""
        url = source_url(url)
        redirects = 0
        for attempt in range(MAX_RETRIES):
            try:
                while True:
                    if self._last_request is not None:
                        time.sleep(max(0, self.delay - (time.monotonic() - self._last_request)))
                    self._last_request = time.monotonic()
                    resp = self.session.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=False)
                    if resp.status_code in (403, 429):
                        raise SourceBlockedError(f"Source returned HTTP {resp.status_code}; stop run", response=resp)
                    if not resp.is_redirect:
                        break
                    redirects += 1
                    if redirects > 5:
                        raise ValueError("Too many redirects")
                    location = resp.headers.get("Location")
                    if not location:
                        raise ValueError("Redirect without Location")
                    next_url = source_url(location, url)
                    resp.close()
                    url = next_url
                resp.raise_for_status()
                resp.encoding = "utf-8"
                page = BeautifulSoup(resp.text, "lxml")
                title = page.title.get_text(" ", strip=True).lower() if page.title else ""
                if (any(marker in title for marker in ("just a moment", "check bot", "access denied"))
                        or page.select_one("#challenge-form, #cf-challenge-running, .g-recaptcha, .h-captcha")):
                    raise SourceBlockedError("Source challenge; stop run", response=resp)
                return resp
            except SourceBlockedError:
                raise
            except requests.HTTPError as e:
                if e.response is None or e.response.status_code < 500 or attempt == MAX_RETRIES - 1:
                    raise
                time.sleep(self.delay * (attempt + 1))
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
        expected = normalize_tax_id(query)
        if re.fullmatch(r"[0-9-]+", query.strip()) and not expected:
            raise ValueError("Tax ID must have 10 digits or 10 digits plus a 3-digit branch suffix")
        # Use type=name for all searches (type=auto has anti-bot redirect issues)
        url = f"{SEARCH_URL}?q={requests.utils.quote(query)}&type=name"
        soup = self._soup(url)

        # Check if we landed directly on a company detail page
        detail = self._parse_detail_page(soup)
        if detail and detail.get("tax_id"):
            if expected and detail["tax_id"] != expected:
                raise DataMismatchError(f"Requested {expected}, received {detail['tax_id']}")
            return [detail]

        # Otherwise parse search result listing
        results = self._parse_listing(soup, url)
        return [r for r in results if r["tax_id"] == expected] if expected else results

    # ------------------------------------------------------------------
    # Crawl-all mode
    # ------------------------------------------------------------------
    def get_provinces(self):
        """Return list of (name, url) for all provinces."""
        soup = self._soup(PROVINCES_URL)
        provinces, seen = [], set()
        links = soup.select("table.tax-listing td a[href*='tra-cuu-ma-so-thue-theo-tinh/']")
        if not links:
            links = soup.select("a[href*='tra-cuu-ma-so-thue-theo-tinh/']")
        for a in links:
            try:
                href = source_url(a.get("href", ""), PROVINCES_URL)
            except ValueError:
                continue
            path = urlsplit(href).path.rstrip("/")
            prefix = urlsplit(PROVINCES_URL).path.rstrip("/") + "/"
            name = a.get_text(" ", strip=True)
            if not name or not path.startswith(prefix) or "/" in path[len(prefix):]:
                continue
            href = urlsplit(href)._replace(path=path, query="").geturl()
            if href not in seen:
                seen.add(href)
                provinces.append((name, href))
        return provinces

    def crawl_province(self, province_url, max_pages=None, callback=None):
        """Crawl all companies in a province. Yields company dicts."""
        page, url, seen = 1, source_url(province_url), set()
        while True:
            if max_pages and page > max_pages:
                break
            print(f"  Page {page}: {url}")
            soup = self._soup(url)
            companies = self._parse_listing(soup, url)
            if not companies:
                break
            for c in companies:
                if c["tax_id"] in seen:
                    continue
                seen.add(c["tax_id"])
                if callback:
                    callback(c)
                yield c
            # Check if there is a next page
            next_url = self._next_page_url(soup, page, url)
            if not next_url:
                break
            url = next_url
            page += 1

    # ------------------------------------------------------------------
    # Detail page
    # ------------------------------------------------------------------
    def get_company_detail(self, detail_url, expected_tax_id=None):
        """Fetch and parse a single company detail page."""
        detail_url = source_url(detail_url)
        expected = normalize_tax_id(expected_tax_id) if expected_tax_id is not None else tax_id_from_url(detail_url)
        if expected_tax_id is not None and not expected:
            raise ValueError("Invalid expected tax ID")
        soup = self._soup(detail_url)
        detail = self._parse_detail_page(soup)
        if detail and expected and detail["tax_id"] != expected:
            raise DataMismatchError(f"Requested {expected}, received {detail['tax_id']}")
        return detail

    def _parse_detail_page(self, soup):
        """Parse company detail from a BeautifulSoup object.
        Returns None if this is not a detail page (e.g. search listing)."""
        data = {}

        # The reliable indicator of a detail page is table.table-taxinfo
        taxinfo_table = soup.select_one("table.table-taxinfo")
        if not taxinfo_table:
            return None

        # Parse all rows from table.table-taxinfo
        for row in taxinfo_table.select("tr"):
            cells = row.select("td")
            if len(cells) >= 2:
                label = cells[0].get_text(strip=True).rstrip(":").strip()
                value = cells[1].get_text(" ", strip=True)
                self._map_field(data, label, value)
        # Structured table fields take priority over the heading.
        tax_node = taxinfo_table.select_one('[itemprop="taxID"]')
        raw_tax = tax_node.get_text(" ", strip=True) if tax_node else data.get("tax_id")
        tax = normalize_tax_id(raw_tax)
        if raw_tax and not tax:
            raise DataMismatchError("Invalid tax ID in company table")
        if tax and data.get("tax_id") and normalize_tax_id(data["tax_id"]) != tax:
            raise DataMismatchError("Tax ID differs between table fields")
        h1 = soup.select_one("h1")
        heading = re.match(r"^([0-9]{10}(?:-[0-9]{3}|[0-9]{3})?)\s*-\s*(.+)$",
                           h1.get_text(" ", strip=True)) if h1 else None
        heading_tax = normalize_tax_id(heading.group(1)) if heading else None
        if tax and heading_tax and tax != heading_tax:
            raise DataMismatchError("Tax ID differs between table and heading")
        data["tax_id"] = tax or heading_tax
        name_node = taxinfo_table.select_one('[itemprop="name"]')
        if name_node:
            data["company_name"] = name_node.get_text(" ", strip=True)
        elif heading and not data.get("company_name"):
            data["company_name"] = heading.group(2).strip()
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
            try:
                href = source_url(entry.get("data-prefetch", ""), current_url)
            except ValueError:
                continue

            # Company name from h3 > a
            name_el = entry.select_one("h3 a")
            name = name_el.get_text(strip=True) if name_el else ""

            # Tax ID from href pattern
            tax_id = tax_id_from_url(href)

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

            if tax_id:
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
                try:
                    href = source_url(a.get("href", ""), current_url)
                except ValueError:
                    continue
                tax_id = tax_id_from_url(href)
                if tax_id:
                    name = a.get_text(strip=True)
                    if name and len(name) > 3 and not name.isdigit():
                        results.append({
                            "tax_id": tax_id,
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

    def _next_page_url(self, soup, current_page, current_url):
        """Follow only the advertised next page in this same listing."""
        current = urlsplit(source_url(current_url))
        filters = parse_qs(current.query)
        filters.pop("page", None)
        for a in soup.select("a[href*='page=']"):
            try:
                href = source_url(a.get("href", ""), current_url)
            except ValueError:
                continue
            target = urlsplit(href)
            query = parse_qs(target.query)
            page = query.pop("page", [])
            if (target.path.rstrip("/") == current.path.rstrip("/")
                    and query == filters and page == [str(current_page + 1)]):
                return href
        return None

    def _has_next_page(self, soup, current_page, current_url=BASE_URL):
        return self._next_page_url(soup, current_page, current_url) is not None
