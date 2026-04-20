#!/usr/bin/env python3
"""
NFC data updater — runs weekly via GitHub Actions.
Scrapes GSMArena for new NFC-capable Android 8.1+ phones,
adds new models to data.js without modifying existing entries.
"""
import re, sys, time, json
from datetime import datetime
try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print("Dependencies not available, skipping update")
    sys.exit(0)

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; NFC-Guide-Bot/1.0)"}
GSMARENA_BASE = "https://www.gsmarena.com"

# Brands to check and their GSMArena IDs
BRANDS = {
    "samsung": 9,
    "apple": 48,
    "google": 107,
    "sony": 7,
    "xiaomi": 80,
    "oneplus": 95,
    "motorola": 4,
    "honor": 121,
    "oppo": 82,
}

# NFC-capable model detection keywords
NFC_KEYWORDS = ["NFC", "nfc"]
SKIP_KEYWORDS = ["Watch", "Tab ", "Pad ", "Buds", "Band", "Gear", "Galaxy Fit"]

def get_brand_phones(brand_id, max_pages=2):
    """Scrape first N pages of a brand's phone list from GSMArena"""
    phones = []
    for page in range(1, max_pages + 1):
        url = f"{GSMARENA_BASE}/search.php3?sMakers={brand_id}&sOSes=2&sAvailabilities=1&p={page}"
        try:
            r = requests.get(url, headers=HEADERS, timeout=10)
            if not r.ok:
                break
            soup = BeautifulSoup(r.text, "html.parser")
            items = soup.select("div.makers ul li")
            if not items:
                break
            for item in items:
                a = item.find("a")
                img = item.find("img")
                if not a or not img:
                    continue
                name = img.get("title", "").strip()
                href = a.get("href", "")
                # Extract bigpic slug
                img_src = img.get("src", "")
                slug_match = re.search(r"/bigpic/([^.]+)\.jpg", img_src)
                slug = slug_match.group(1) if slug_match else ""
                if name and href and slug:
                    phones.append({"name": name, "href": href, "slug": slug})
            time.sleep(0.5)
        except Exception as e:
            print(f"  Error page {page}: {e}")
            break
    return phones

def slug_to_key(name, brand):
    """Convert phone name to a simple key"""
    key = name.lower()
    key = re.sub(r"[^a-z0-9]", "-", key)
    key = re.sub(r"-+", "-", key).strip("-")
    return key[:30]

def get_year_from_gsmarena(href):
    """Try to get release year from GSMArena phone page"""
    try:
        url = GSMARENA_BASE + "/" + href
        r = requests.get(url, headers=HEADERS, timeout=10)
        if not r.ok:
            return datetime.now().year
        # Look for "Released YYYY" pattern
        match = re.search(r"Released\s+(\d{4})", r.text)
        if match:
            return int(match.group(1))
    except:
        pass
    return datetime.now().year

def load_data_js(path="data.js"):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

def get_existing_slugs(data_js_content):
    """Extract all image slugs already in data.js"""
    return set(re.findall(r"gi\('[^']+','([^']+)'\)", data_js_content))

def get_existing_brands(data_js_content):
    """Get all brand model blocks"""
    return re.findall(r"\n(\w+):\{label:'([^']+)',models:", data_js_content)

def append_new_models(data_js_content, brand_key, new_entries):
    """Append new model entries to an existing brand block in data.js"""
    if not new_entries:
        return data_js_content, 0
    
    # Find the brand models opening
    pattern = f"\n{brand_key}:{{label:'[^']+',models:{{"
    match = re.search(pattern, data_js_content)
    if not match:
        print(f"  Brand {brand_key} not found in data.js")
        return data_js_content, 0
    
    # Insert after the opening brace
    insert_pos = match.end()
    entries_str = "\n" + "\n".join(new_entries)
    data_js_content = data_js_content[:insert_pos] + entries_str + data_js_content[insert_pos:]
    return data_js_content, len(new_entries)

def should_skip(name):
    return any(kw.lower() in name.lower() for kw in SKIP_KEYWORDS)

def get_crop_for_brand(brand_key):
    crops = {"samsung": "R", "apple": "L", "google": "L"}
    return crops.get(brand_key, "C")

def get_nfc_pos(brand_key, name_lower):
    """Best-guess NFC position based on brand/model patterns"""
    if brand_key == "apple":
        return "top_edge", "Tranche supérieure", "<b>Tranche supérieure</b>."
    if "ultra" in name_lower and "samsung" in brand_key:
        if any(y in name_lower for y in ["s23", "s20", "s21", "note"]):
            return "mid_back", "Centre dos", "<b>Centre du dos</b>."
        return "top_back2", "Tiers sup. dos", "<b>Tiers supérieur du dos</b>."
    if any(x in name_lower for x in ["fold", "flip", "trifold"]):
        return "mid_back", "Centre dos (plié)", "Téléphone plié — <b>panneau dos</b>."
    return "top_back2", "Tiers sup. dos", "<b>Tiers supérieur du dos</b>."

def build_entry(key, name, year, brand_key, slug, crop):
    pos, pos_lbl, tap = get_nfc_pos(brand_key, name.lower())
    ov_map = {
        "top_edge": "OV.top_edge", "top_back": "OV.top_back",
        "top_back2": "OV.top_back2", "mid_back": "OV.mid_back",
        "low_back": "OV.low_back",
    }
    ov = ov_map.get(pos, "OV.top_back2")
    score = "ok"
    if "ultra" in name.lower() and "s26" in name.lower(): score = "excellent"
    if pos == "mid_back" and "samsung" in brand_key: score = "bad"
    cls = "tb-ok" if score in ("ok","excellent") else "tb-warn" if score=="ko" else "tb-err"
    name_e = name.replace("'", "\'")
    return (
        f"  \'{key}\':"
        f"{{label:\'{name_e}\',year:{year},crop:\'{crop}\',"
        f"img:gi(\'{brand_key}\',\'{slug}\'),"
        f"chip:\'NXP (probable)\',score:\'{score}\',zones:1,range:\'3-5 cm\',dims:\'N/A\',"
        f"ants:[{{id:1,lbl:\'Antenne dos\',pos:\'{pos_lbl}\',size:\'~55x40mm\',"
        f"conf:\'estimated\',src:\'Auto-updated\',ov:{ov}}}],"
        f"tap:\'{tap}\',tapCls:\'{cls}\'}},"
    )

def main():
    print(f"[{datetime.now().isoformat()}] NFC data update starting...")
    
    data_js = load_data_js()
    existing_slugs = get_existing_slugs(data_js)
    print(f"Existing slugs: {len(existing_slugs)}")
    
    total_added = 0
    
    for brand_key, brand_id in BRANDS.items():
        print(f"\nChecking {brand_key} (id={brand_id})...")
        phones = get_brand_phones(brand_id, max_pages=1)  # Only first page = newest
        print(f"  Found {len(phones)} phones on first page")
        
        new_entries = []
        for phone in phones:
            if should_skip(phone["name"]):
                continue
            slug = phone["slug"]
            if slug in existing_slugs:
                continue
            # New model found!
            key = slug_to_key(phone["name"], brand_key)
            year = datetime.now().year  # Assume current year for new models
            crop = get_crop_for_brand(brand_key)
            entry = build_entry(key, phone["name"], year, brand_key, slug, crop)
            new_entries.append(entry)
            print(f"  + NEW: {phone['name']} ({slug})")
            time.sleep(0.3)
        
        if new_entries:
            data_js, n = append_new_models(data_js, brand_key, new_entries)
            total_added += n
            print(f"  Added {n} new models to {brand_key}")
    
    if total_added > 0:
        with open("data.js", "w", encoding="utf-8") as f:
            f.write(data_js)
        print(f"\ndata.js updated: {total_added} new models added")
    else:
        print("\nNo new models found — data.js unchanged")
    
    print(f"[{datetime.now().isoformat()}] Done.")

if __name__ == "__main__":
    main()
