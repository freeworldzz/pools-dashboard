#!/usr/bin/env python3
"""
scraper.py — Recolhe preços de robôs de piscina de 6 vendedores.
Referência: Pools and More. Só inclui robôs listados em Pools and More.
Gera data.json para o dashboard.
"""

import json
import re
import sys
import time
from datetime import datetime
from unicodedata import normalize as unorm

import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pt-PT,pt;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

VENDORS = [
    "Pools and More",
    "Bricoandpool",
    "Carol Piscina",
    "Shop4Pool",
    "Hidraulicart",
    "IoT Pool",
]

STOPWORDS = {
    "aspirador", "aspiradora", "aspiradores", "robot", "robots",
    "robo", "robô", "de", "para", "a", "o", "as", "os", "em", "com",
    "sem", "e", "el", "la", "los", "las", "sin",
    "piscina", "piscinas", "fios", "cabo", "automatico", "automático",
    "automatica", "bateria", "electrico", "eletrico", "electrica",
    "eletrica", "limpa", "fundos", "limpafondos", "limpiafondos",
    "limpiafondo", "serie", "wifi", "inteligente", "solar", "wireless",
    "fondo", "fondos", "pool", "cleaner", "robotic", "automatic",
    "swimming", "tipo", "novo", "nova", "new", "piscine",
    "electronico", "cable", "con", "por", "aspiracion", "aspiracao",
    "turbo",
}

KNOWN_BRANDS = {
    "zodiac", "dolphin", "wybot", "aiper", "beatbot", "bestway", "cudell",
    "aquaviva", "hayward", "jandy", "maytronics", "intex", "fluidra",
    "kokido", "orca", "barracuda", "astralpool", "bayrol", "blue", "water",
    "wave", "aquabot", "polaris", "kreepy", "krauly", "pentair",
    "ibot", "vektro", "igarden", "aquasphere", "spyder",
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def log(msg: str):
    print(msg, file=sys.stderr, flush=True)


def parse_price(s) -> float | None:
    if not s:
        return None
    s = str(s).strip()
    s = re.sub(r"[€$£€\s\xa0 ]", "", s)
    # PT format: 1.299,00 → 1299.00
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    s = re.sub(r"[^\d.]", "", s)
    try:
        v = float(s)
        return v if v > 0 else None
    except ValueError:
        return None


def norm_text(text: str) -> str:
    if not text:
        return ""
    t = unorm("NFKD", text).encode("ascii", "ignore").decode("ascii")
    t = t.lower()
    t = re.sub(r"[^a-z0-9\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def tokenize(name: str) -> list[str]:
    return [w for w in norm_text(name).split() if w not in STOPWORDS and len(w) >= 2]


def extract_brand(name: str, vendor_brand: str = "") -> str:
    if vendor_brand:
        nb = norm_text(vendor_brand).split()
        for t in nb:
            if t in KNOWN_BRANDS:
                return t
        if nb:
            return nb[0]
    for b in KNOWN_BRANDS:
        if b in norm_text(name).split():
            return b
    toks = tokenize(name)
    return toks[0] if toks else ""


def match_score(ref_name: str, ref_brand: str, cand_name: str, cand_brand: str) -> int:
    rb = ref_brand or extract_brand(ref_name)
    cb = cand_brand or extract_brand(cand_name)

    # Brands must agree if both are known
    if rb and cb and rb != cb:
        return 0

    ref_toks = set(tokenize(ref_name))
    cand_toks = set(tokenize(cand_name))

    ref_nums = {t for t in ref_toks if re.search(r"\d", t)}
    cand_nums = {t for t in cand_toks if re.search(r"\d", t)}

    if ref_nums and cand_nums:
        shared_nums = ref_nums & cand_nums
        if not shared_nums:
            return 0  # same brand, different model numbers → different product
        score = len(shared_nums) * 4
    else:
        score = 1  # no numeric tokens; rely on alpha overlap

    ref_alpha = {t for t in ref_toks if not re.search(r"\d", t)}
    cand_alpha = {t for t in cand_toks if not re.search(r"\d", t)}
    score += len(ref_alpha & cand_alpha)

    return score


def get(url: str, delay: float = 0.8) -> requests.Response:
    time.sleep(delay)
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r


# ---------------------------------------------------------------------------
# Scrapers
# ---------------------------------------------------------------------------

def scrape_poolsandmore() -> list[dict]:
    products = []
    seen = set()
    for page in range(1, 4):
        url = (
            f"https://poolsandmore.pt/categoria-produto/material-de-limpeza/"
            f"aspiradores-automaticos/page/{page}/"
        )
        log(f"  P&M página {page} ...")
        try:
            r = get(url)
            r.encoding = "utf-8"
            s = BeautifulSoup(r.text, "html.parser")
            prods = [
                el for el in s.find_all(class_="product")
                if el.select_one(".woocommerce-loop-product__title")
            ]
            if not prods:
                break
            for p in prods:
                name = p.select_one(".woocommerce-loop-product__title").get_text(strip=True)
                if name in seen:
                    continue
                seen.add(name)

                dels = [d.get_text(strip=True) for d in p.select("del")]
                ins  = [i.get_text(strip=True) for i in p.select("ins")]
                amts = [a.get_text(strip=True) for a in p.select(".woocommerce-Price-amount")]

                if dels and ins:
                    price_before  = parse_price(dels[0])
                    price_current = parse_price(ins[0])
                elif amts:
                    price_current = parse_price(amts[0])
                    price_before  = None
                else:
                    price_current = None
                    price_before  = None

                link = p.select_one("a[href]")
                products.append({
                    "name": name,
                    "price_current": price_current,
                    "price_before": price_before,
                    "url": link["href"] if link else None,
                    "vendor": "Pools and More",
                    "brand": extract_brand(name),
                })
        except Exception as e:
            log(f"  P&M página {page} erro: {e}")
    log(f"  P&M: {len(products)} produtos")
    return products


def scrape_bricoandpool() -> list[dict]:
    products = []
    seen = set()
    for page in range(1, 8):
        url = f"https://bricoandpool.com/pt-pt/collections/types?q=Limpiafondos&page={page}"
        log(f"  Brico página {page} ...")
        try:
            r = get(url)
            r.encoding = "utf-8"
            s = BeautifulSoup(r.text, "html.parser")
            cards = s.select(".product-card")
            if not cards:
                break
            for c in cards:
                title_el  = c.select_one(".product-card__title")
                vendor_el = c.select_one(".product-card__vendor")
                name  = title_el.get_text(strip=True) if title_el else ""
                brand = vendor_el.get_text(strip=True) if vendor_el else ""
                if not name or name in seen:
                    continue
                seen.add(name)

                nums = [v for v in (parse_price(x.get_text(strip=True))
                                    for x in c.select(".f-price-item")) if v]
                if len(nums) >= 2:
                    price_current = min(nums)
                    price_before  = max(nums)
                    if price_current == price_before:
                        price_before = None
                elif len(nums) == 1:
                    price_current = nums[0]
                    price_before  = None
                else:
                    price_current = None
                    price_before  = None

                link = c.select_one("a[href]")
                products.append({
                    "name": name,
                    "price_current": price_current,
                    "price_before": price_before,
                    "url": ("https://bricoandpool.com" + link["href"]) if link else None,
                    "vendor": "Bricoandpool",
                    "brand": extract_brand(name, brand),
                })
        except Exception as e:
            log(f"  Brico página {page} erro: {e}")
    log(f"  Brico: {len(products)} produtos")
    return products


def _shopify_json(base_url: str, max_pages: int, vendor_name: str) -> list[dict]:
    products = []
    seen = set()
    domain = base_url.split("/collections/")[0]
    for page in range(1, max_pages + 2):
        url = f"{base_url}?page={page}&limit=250"
        log(f"  {vendor_name} página {page} ...")
        try:
            r = get(url)
            data = r.json()
            prods = data.get("products", [])
            if not prods:
                break
            for p in prods:
                name = p.get("title", "").strip()
                if not name or name in seen:
                    continue
                seen.add(name)

                # Prefer available variants; fallback to all
                variants = [v for v in p.get("variants", []) if v.get("available", True)]
                if not variants:
                    variants = p.get("variants", [])
                if not variants:
                    continue
                var = variants[0]

                price_current = parse_price(var.get("price"))
                price_before  = parse_price(var.get("compare_at_price"))
                if price_before and price_current and price_before <= price_current:
                    price_before = None

                handle = p.get("handle", "")
                products.append({
                    "name": name,
                    "price_current": price_current,
                    "price_before": price_before,
                    "url": f"{domain}/products/{handle}" if handle else None,
                    "vendor": vendor_name,
                    "brand": extract_brand(name, p.get("vendor", "")),
                })
        except Exception as e:
            log(f"  {vendor_name} página {page} erro: {e}")
            break
    log(f"  {vendor_name}: {len(products)} produtos")
    return products


def scrape_carolpiscina() -> list[dict]:
    return _shopify_json(
        "https://carolpiscina.pt/collections/robot-electrico/products.json",
        2, "Carol Piscina",
    )


def scrape_shop4pool() -> list[dict]:
    return _shopify_json(
        "https://shop4pool.com/collections/aspiradores/products.json",
        6, "Shop4Pool",
    )


def scrape_iotpool() -> list[dict]:
    return _shopify_json(
        "https://www.iot-pool.com/collections/aspiradores/products.json",
        10, "IoT Pool",
    )


def scrape_hidraulicart() -> list[dict]:
    products = []
    seen = set()
    for page in range(1, 13):
        url = f"https://www.hidraulicart.pt/loja-online/aspiradoras-robotizadas-automaticas/?p={page}"
        log(f"  Hidraulicart página {page} ...")
        try:
            r = get(url)
            r.encoding = "utf-8"
            s = BeautifulSoup(r.text, "html.parser")
            boxes = s.select(".price-box")
            if not boxes:
                break
            for b in boxes:
                parent = b.find_parent("li") or b.find_parent(
                    attrs={"class": re.compile(r"product")}
                )
                nm = parent.select_one(".product-name") if parent else None
                if not nm:
                    continue
                name = nm.get_text(strip=True)
                if not name or name in seen:
                    continue
                seen.add(name)

                reg = b.select_one(".regular-price .price")
                old = b.select_one(".old-price .price")
                sp  = b.select_one(".special-price .price")

                if old and sp:
                    price_before  = parse_price(old.get_text(strip=True))
                    price_current = parse_price(sp.get_text(strip=True))
                elif reg:
                    price_current = parse_price(reg.get_text(strip=True))
                    price_before  = None
                else:
                    price_current = None
                    price_before  = None

                link = nm.select_one("a") or (parent.select_one("a[href]") if parent else None)
                href = link["href"] if link and link.get("href") else None

                products.append({
                    "name": name,
                    "price_current": price_current,
                    "price_before": price_before,
                    "url": href,
                    "vendor": "Hidraulicart",
                    "brand": extract_brand(name),
                })
        except Exception as e:
            log(f"  Hidraulicart página {page} erro: {e}")
    log(f"  Hidraulicart: {len(products)} produtos")
    return products


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------

def build_matched_data(
    reference: list[dict],
    all_vendor_products: dict[str, list[dict]],
) -> list[dict]:
    robots = []
    match_threshold = 3

    for ref in reference:
        ref_brand = ref.get("brand") or extract_brand(ref["name"])
        entry = {
            "name": ref["name"],
            "brand": ref_brand,
            "prices": {
                "Pools and More": {
                    "current": ref["price_current"],
                    "before": ref["price_before"],
                    "matched_name": ref["name"],
                    "url": ref.get("url"),
                }
            },
        }

        for vendor in VENDORS:
            if vendor == "Pools and More":
                continue
            candidates = all_vendor_products.get(vendor, [])
            best = None
            best_score = match_threshold - 1
            for cand in candidates:
                score = match_score(
                    ref["name"], ref_brand,
                    cand["name"], cand.get("brand", ""),
                )
                if score > best_score:
                    best_score = score
                    best = cand

            if best:
                entry["prices"][vendor] = {
                    "current": best["price_current"],
                    "before": best["price_before"],
                    "matched_name": best["name"],
                    "url": best.get("url"),
                    "match_score": best_score,
                }
                log(f"    [{best_score:2d}] {ref['name']!r} → {vendor}: {best['name']!r}")
            else:
                entry["prices"][vendor] = None

        robots.append(entry)
    return robots


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    log("=== Scraping Pools and More (referência)...")
    pm       = scrape_poolsandmore()
    log("=== Scraping Bricoandpool...")
    brico    = scrape_bricoandpool()
    log("=== Scraping Carol Piscina...")
    carol    = scrape_carolpiscina()
    log("=== Scraping Shop4Pool...")
    shop4    = scrape_shop4pool()
    log("=== Scraping Hidraulicart...")
    hidra    = scrape_hidraulicart()
    log("=== Scraping IoT Pool...")
    iotpool  = scrape_iotpool()

    all_products = {
        "Pools and More": pm,
        "Bricoandpool":   brico,
        "Carol Piscina":  carol,
        "Shop4Pool":      shop4,
        "Hidraulicart":   hidra,
        "IoT Pool":       iotpool,
    }

    log("=== Matching produtos...")
    robots = build_matched_data(pm, all_products)

    output = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "vendors": VENDORS,
        "robots": robots,
    }

    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    # Embute os dados directamente no dashboard.html (funciona com file://)
    js_payload = json.dumps(output, ensure_ascii=False)
    placeholder = "null; /* __DASHBOARD_DATA__ */"
    replacement = f"{js_payload}; /* __DASHBOARD_DATA__ */"
    with open("dashboard.html", "r", encoding="utf-8") as f:
        html = f.read()
    if placeholder in html:
        html = html.replace(placeholder, replacement)
    else:
        # Já tem dados — substituir o bloco anterior
        import re as _re
        html = _re.sub(
            r'window\.DASHBOARD_DATA\s*=\s*.+?/\* __DASHBOARD_DATA__ \*/',
            f'window.DASHBOARD_DATA = {replacement}',
            html, flags=_re.DOTALL
        )
    with open("dashboard.html", "w", encoding="utf-8") as f:
        f.write(html)

    log(f"\n=== Concluído! {len(robots)} robôs. data.json gerado e dados embutidos em dashboard.html.")
    log("    Matches por vendedor:")
    for v in VENDORS[1:]:
        matched = sum(1 for r in robots if r["prices"].get(v) is not None)
        log(f"      {v}: {matched}/{len(robots)}")


if __name__ == "__main__":
    main()
