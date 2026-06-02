#!/usr/bin/env python3
"""
scraper.py — Recolhe preços de robôs de piscina de 6 vendedores.
Referência: Pools and More. Só inclui robôs listados em Pools and More.
Gera data.json para o dashboard.
"""

import argparse
import json
import os
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
    "Accept": "application/json, text/html, */*;q=0.5",
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
    # Bombas de calor
    "bomba", "calor", "aquecedor", "aquecimento", "heat", "pump",
    "inverter", "titanio", "titanium", "silencioso", "monofasico",
    "trifasico", "fasico", "fase",
    # Eletrólise de sal
    "eletrolise", "electrolise", "sal", "clorador", "salino",
    "salina", "cloro", "salt", "chlorinator", "celula", "salinidade",
    "tratamento", "geracao", "electrolysis", "cloracion",
}

KNOWN_BRANDS = {
    "zodiac", "dolphin", "wybot", "aiper", "beatbot", "bestway", "cudell",
    "aquaviva", "hayward", "jandy", "maytronics", "intex", "fluidra",
    "kokido", "orca", "barracuda", "astralpool", "bayrol", "blue", "water",
    "wave", "aquabot", "polaris", "kreepy", "krauly", "pentair",
    "ibot", "vektro", "igarden", "aquasphere", "spyder",
    # Bombas de calor / Eletrólise de sal
    "thermotec", "fairland", "pahlen", "waterco", "waterair",
    "elecro", "heatline", "gre", "phnix", "inverboost",
    "bayrol", "ccei", "poolrite", "davey",
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


def get(url: str, delay: float = 0.8, retries: int = 3) -> requests.Response:
    time.sleep(delay)
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=30)
            r.raise_for_status()
            return r
        except requests.exceptions.HTTPError as e:
            code = e.response.status_code if e.response else 0
            if code in (429, 503) and attempt < retries - 1:
                wait = (attempt + 1) * 15
                log(f"  ⚠ Rate limit {code} — aguardando {wait}s antes de retentar...")
                time.sleep(wait)
            else:
                raise
        except requests.exceptions.RequestException as e:
            if attempt < retries - 1:
                log(f"  ⚠ Erro de rede ({e}) — tentativa {attempt + 2}/{retries}...")
                time.sleep(5)
            else:
                raise
    raise RuntimeError("unreachable")


# ---------------------------------------------------------------------------
# Sessões persistentes por domínio Shopify (cookies + headers de browser real)
# ---------------------------------------------------------------------------

_sessions: dict = {}

_BROWSER_EXTRA = {
    "sec-ch-ua": '"Google Chrome";v="124", "Chromium";v="124", "Not-A.Brand";v="99"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}


def _session_for(domain: str) -> requests.Session:
    """Devolve (ou cria) uma sessão com cookies para um domínio."""
    if domain in _sessions:
        return _sessions[domain]
    s = requests.Session()
    s.headers.update(HEADERS)
    s.headers.update(_BROWSER_EXTRA)
    s.headers["Referer"] = domain + "/"
    # Warm-up: visita a homepage para obter cookies de sessão
    try:
        s.get(domain + "/", timeout=15, allow_redirects=True)
        time.sleep(2.0)
    except Exception as e:
        log(f"  (warm-up {domain} falhou: {e})")
    _sessions[domain] = s
    return s


def shopify_get(url: str, domain: str, delay: float = 1.0, retries: int = 3) -> requests.Response:
    """GET com sessão persistente por domínio + retry automático."""
    s = _session_for(domain)
    time.sleep(delay)
    for attempt in range(retries):
        try:
            r = s.get(url, timeout=30)
            r.raise_for_status()
            return r
        except requests.exceptions.HTTPError as e:
            code = e.response.status_code if e.response else 0
            if code == 403:
                log(f"  !! 403 Forbidden — {domain} está a bloquear este IP.")
                log(f"     Aguarda 30-60 min e volta a correr o scraper.")
                raise
            if code in (429, 503) and attempt < retries - 1:
                wait = (attempt + 1) * 20
                log(f"  ⚠ Rate limit {code} — aguardando {wait}s...")
                time.sleep(wait)
            else:
                raise
        except requests.exceptions.RequestException as e:
            if attempt < retries - 1:
                time.sleep(5)
            else:
                raise
    raise RuntimeError("unreachable")


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


def _parse_shopify_page(r: requests.Response, vendor_name: str, domain: str,
                         seen: set, products: list, all_variants: bool = False) -> bool:
    """Processa uma página products.json. Devolve False se não há mais produtos."""
    ct = r.headers.get("Content-Type", "")
    if "json" not in ct and not r.text.strip().startswith("{"):
        log(f"  !! {vendor_name} devolveu HTML (bloqueio/redirect). Content-Type: {ct}")
        return False
    data = r.json()
    prods = data.get("products", [])
    if not prods:
        return False
    for p in prods:
        base_title = p.get("title", "").strip()
        if not base_title:
            continue
        if all_variants:
            for var in p.get("variants", []):
                vt = var.get("title", "")
                name = f"{base_title} ({vt})" if vt and vt != "Default Title" else base_title
                if name in seen:
                    continue
                seen.add(name)
                pc = parse_price(var.get("price"))
                pb = parse_price(var.get("compare_at_price"))
                if pb and pc and pb <= pc:
                    pb = None
                handle = p.get("handle", "")
                products.append({
                    "name": name, "price_current": pc, "price_before": pb,
                    "url": f"{domain}/products/{handle}" if handle else None,
                    "vendor": p.get("vendor", ""),  # filled by caller
                    "brand": extract_brand(name, p.get("vendor", "")),
                })
        else:
            if base_title in seen:
                continue
            seen.add(base_title)
            variants = [v for v in p.get("variants", []) if v.get("available", True)] or p.get("variants", [])
            if not variants:
                continue
            var = variants[0]
            pc = parse_price(var.get("price"))
            pb = parse_price(var.get("compare_at_price"))
            if pb and pc and pb <= pc:
                pb = None
            handle = p.get("handle", "")
            products.append({
                "name": base_title, "price_current": pc, "price_before": pb,
                "url": f"{domain}/products/{handle}" if handle else None,
                "vendor": "",  # filled by caller
                "brand": extract_brand(base_title, p.get("vendor", "")),
            })
    return True


def _shopify_fetch(base_url: str, max_pages: int, vendor_name: str,
                   all_variants: bool = False) -> list[dict]:
    """Núcleo de scraping Shopify com sessão persistente."""
    products = []
    seen: set = set()
    domain = base_url.split("/collections/")[0]
    for page in range(1, max_pages + 2):
        url = f"{base_url}?page={page}&limit=250"
        log(f"  {vendor_name} pág {page} ...")
        try:
            r = shopify_get(url, domain, delay=1.0)
            more = _parse_shopify_page(r, vendor_name, domain, seen, products, all_variants)
            if not more:
                break
        except Exception as e:
            log(f"  !! {vendor_name} pág {page} ERRO: {type(e).__name__}: {e}")
            break
    # Corrige o campo vendor (foi deixado vazio em _parse_shopify_page)
    for p in products:
        p["vendor"] = vendor_name
    log(f"  {vendor_name}: {len(products)} produtos")
    return products


def _shopify_json(base_url: str, max_pages: int, vendor_name: str) -> list[dict]:
    return _shopify_fetch(base_url, max_pages, vendor_name, all_variants=False)


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
# Helpers genéricos por plataforma
# ---------------------------------------------------------------------------

def _scrape_pm_woocommerce(base_url: str, n_pages: int, label: str) -> list[dict]:
    """WooCommerce genérico para qualquer categoria do Pools and More."""
    products = []
    seen = set()
    for page in range(1, n_pages + 2):
        url = base_url if page == 1 else base_url.rstrip("/") + f"/page/{page}/"
        log(f"  P&M [{label}] pág {page} ...")
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
                if not name or name in seen:
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
            log(f"  P&M [{label}] pág {page} erro: {e}")
    log(f"  P&M [{label}]: {len(products)} produtos")
    return products


def _scrape_hidraulicart_magento(url_pattern: str, n_pages: int, label: str) -> list[dict]:
    """Magento genérico para qualquer categoria da Hidraulicart."""
    products = []
    seen = set()
    for page in range(1, n_pages + 2):
        url = url_pattern.replace("{}", str(page))
        log(f"  Hidraulicart [{label}] pág {page} ...")
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
                products.append({
                    "name": name,
                    "price_current": price_current,
                    "price_before": price_before,
                    "url": link["href"] if link and link.get("href") else None,
                    "vendor": "Hidraulicart",
                    "brand": extract_brand(name),
                })
        except Exception as e:
            log(f"  Hidraulicart [{label}] pág {page} erro: {e}")
    log(f"  Hidraulicart [{label}]: {len(products)} produtos")
    return products


# ---------------------------------------------------------------------------
# Helpers com suporte a variantes (Bombas de Calor / Eletrólise de Sal)
# ---------------------------------------------------------------------------

def _scrape_pm_woocommerce_variants(base_url: str, n_pages: int, label: str) -> list[dict]:
    """P&M WooCommerce: vai a cada página de produto e extrai variantes."""
    import json as _json
    product_urls = []
    for page in range(1, n_pages + 2):
        url = base_url if page == 1 else base_url.rstrip("/") + f"/page/{page}/"
        log(f"  P&M [{label}] listagem pág {page} ...")
        try:
            r = get(url)
            r.encoding = "utf-8"
            s = BeautifulSoup(r.text, "html.parser")
            links = list(dict.fromkeys(
                a["href"] for a in s.select("div.product-small a[href*='/produto/']") if a.get("href")
            ))
            if not links:
                break
            product_urls.extend(links)
        except Exception as e:
            log(f"  P&M [{label}] listagem pág {page} erro: {e}")

    product_urls = list(dict.fromkeys(product_urls))
    products = []
    seen: set[str] = set()

    for prod_url in product_urls:
        try:
            r = get(prod_url, delay=1.2)
            r.encoding = "utf-8"
            s = BeautifulSoup(r.text, "html.parser")
            h1 = s.select_one("h1.product_title")
            if not h1:
                continue
            base_name = h1.get_text(strip=True)

            var_form = s.select_one("form.variations_form")
            if var_form and var_form.get("data-product_variations"):
                for var in _json.loads(var_form["data-product_variations"]):
                    if not var.get("display_price"):
                        continue
                    attrs = ", ".join(v for v in var.get("attributes", {}).values() if v)
                    name = f"{base_name} ({attrs})" if attrs else base_name
                    if name in seen:
                        continue
                    seen.add(name)
                    p_cur = float(var["display_price"])
                    p_reg = float(var["display_regular_price"]) if var.get("display_regular_price") else p_cur
                    products.append({
                        "name": name,
                        "price_current": p_cur,
                        "price_before": p_reg if p_reg > p_cur else None,
                        "url": prod_url,
                        "vendor": "Pools and More",
                        "brand": extract_brand(base_name),
                    })
            else:
                # Produto simples
                if base_name in seen:
                    continue
                seen.add(base_name)
                dels = [d.get_text(strip=True) for d in s.select("del .woocommerce-Price-amount")]
                ins  = [i.get_text(strip=True) for i in s.select("ins .woocommerce-Price-amount")]
                amts = [a.get_text(strip=True) for a in s.select(".price .woocommerce-Price-amount")]
                if dels and ins:
                    p_before = parse_price(dels[0])
                    p_cur    = parse_price(ins[0])
                elif amts:
                    p_cur    = parse_price(amts[0])
                    p_before = None
                else:
                    p_cur = p_before = None
                products.append({
                    "name": base_name,
                    "price_current": p_cur,
                    "price_before": p_before,
                    "url": prod_url,
                    "vendor": "Pools and More",
                    "brand": extract_brand(base_name),
                })
        except Exception as e:
            log(f"  P&M [{label}] produto {prod_url} erro: {e}")

    log(f"  P&M [{label}]: {len(products)} variantes de {len(product_urls)} produtos")
    return products


def _shopify_json_variants(base_url: str, max_pages: int, vendor_name: str) -> list[dict]:
    return _shopify_fetch(base_url, max_pages, vendor_name, all_variants=True)


def _scrape_hidraulicart_variants(url_pattern: str, n_pages: int, label: str) -> list[dict]:
    """Hidraulicart Magento: visita cada produto e extrai linhas da tabela agrupada."""
    product_urls = []
    for page in range(1, n_pages + 2):
        url = url_pattern.replace("{}", str(page))
        log(f"  Hidraulicart [{label}] listagem pág {page} ...")
        try:
            r = get(url)
            r.encoding = "utf-8"
            s = BeautifulSoup(r.text, "html.parser")
            links = [a["href"] for nm in s.select(".product-name") for a in nm.select("a") if a.get("href")]
            if not links:
                break
            product_urls.extend(links)
        except Exception as e:
            log(f"  Hidraulicart [{label}] listagem pág {page} erro: {e}")

    product_urls = list(dict.fromkeys(product_urls))
    products = []
    seen: set[str] = set()

    for prod_url in product_urls:
        try:
            r = get(prod_url, delay=1.2)
            r.encoding = "utf-8"
            s = BeautifulSoup(r.text, "html.parser")
            h1 = s.select_one("h1.product-name, h1.page-title, h1")
            base_name = h1.get_text(strip=True) if h1 else ""

            rows = s.select("#super-product-table tbody tr")
            if rows:
                for row in rows:
                    nm_el = row.select_one("td:nth-child(1)")
                    if not nm_el:
                        continue
                    raw = nm_el.find(string=True, recursive=False)
                    name = (raw.strip() if raw else nm_el.get_text(strip=True))
                    if not name or name in seen:
                        continue
                    seen.add(name)
                    old_el  = row.select_one(".old-price .price")
                    sale_el = row.select_one(".special-price .price")
                    norm_el = row.select_one(".price")
                    if old_el and sale_el:
                        p_before  = parse_price(old_el.get_text())
                        p_current = parse_price(sale_el.get_text())
                    elif norm_el:
                        p_current = parse_price(norm_el.get_text())
                        p_before  = None
                    else:
                        continue
                    products.append({
                        "name": name,
                        "price_current": p_current,
                        "price_before": p_before,
                        "url": prod_url,
                        "vendor": "Hidraulicart",
                        "brand": extract_brand(name),
                    })
            else:
                # Produto simples (sem tabela agrupada)
                if not base_name or base_name in seen:
                    continue
                seen.add(base_name)
                old = s.select_one(".old-price .price")
                sp  = s.select_one(".special-price .price")
                reg = s.select_one(".regular-price .price")
                if old and sp:
                    p_before  = parse_price(old.get_text())
                    p_current = parse_price(sp.get_text())
                elif reg:
                    p_current = parse_price(reg.get_text())
                    p_before  = None
                else:
                    p_current = p_before = None
                products.append({
                    "name": base_name,
                    "price_current": p_current,
                    "price_before": p_before,
                    "url": prod_url,
                    "vendor": "Hidraulicart",
                    "brand": extract_brand(base_name),
                })
        except Exception as e:
            log(f"  Hidraulicart [{label}] produto {prod_url} erro: {e}")

    log(f"  Hidraulicart [{label}]: {len(products)} variantes de {len(product_urls)} produtos")
    return products


# ---------------------------------------------------------------------------
# Bombas de Calor
# ---------------------------------------------------------------------------

def scrape_pm_heat_pumps() -> list[dict]:
    return _scrape_pm_woocommerce_variants(
        "https://poolsandmore.pt/categoria-produto/bombas-de-calor-piscina/",
        1, "Bombas de Calor",
    )


def scrape_bricoandpool_heat_pumps() -> list[dict]:
    return _shopify_json_variants(
        "https://bricoandpool.com/pt-pt/collections/bombas-de-calor-de-piscina/products.json",
        1, "Bricoandpool",
    )


def scrape_carolpiscina_heat_pumps() -> list[dict]:
    return _shopify_json_variants(
        "https://carolpiscina.pt/collections/bombas-de-calor/products.json",
        1, "Carol Piscina",
    )


def scrape_shop4pool_heat_pumps() -> list[dict]:
    return _shopify_json_variants(
        "https://shop4pool.com/collections/bombas-de-calor/products.json",
        2, "Shop4Pool",
    )


def scrape_hidraulicart_heat_pumps() -> list[dict]:
    return _scrape_hidraulicart_variants(
        "https://www.hidraulicart.pt/loja-online/bombas-de-calor/?p={}",
        3, "Bombas de Calor",
    )


def scrape_iotpool_heat_pumps() -> list[dict]:
    return _shopify_json_variants(
        "https://www.iot-pool.com/collections/bombas-de-calor/products.json",
        10, "IoT Pool",
    )


# ---------------------------------------------------------------------------
# Eletrólise de Sal
# ---------------------------------------------------------------------------

def scrape_pm_salt() -> list[dict]:
    return _scrape_pm_woocommerce_variants(
        "https://poolsandmore.pt/categoria-produto/tratamento-agua/eletrolise-de-sal/",
        1, "Eletrólise de Sal",
    )


def scrape_bricoandpool_salt() -> list[dict]:
    return _shopify_json_variants(
        "https://bricoandpool.com/collections/cloradores-salinos/products.json",
        6, "Bricoandpool",
    )


def scrape_carolpiscina_salt() -> list[dict]:
    return _shopify_json_variants(
        "https://carolpiscina.pt/collections/eletrolises-de-sal/products.json",
        1, "Carol Piscina",
    )


def scrape_shop4pool_salt() -> list[dict]:
    return _shopify_json_variants(
        "https://shop4pool.com/collections/eletrolise-de-sal-1/products.json",
        2, "Shop4Pool",
    )


def scrape_hidraulicart_salt() -> list[dict]:
    return _scrape_hidraulicart_variants(
        "https://www.hidraulicart.pt/loja-online/aparelhos-sal-2/?p={}",
        4, "Eletrólise de Sal",
    )


def scrape_iotpool_salt() -> list[dict]:
    return _shopify_json_variants(
        "https://www.iot-pool.com/collections/eletrolise-de-sal/products.json",
        3, "IoT Pool",
    )


# ---------------------------------------------------------------------------
# Canonicalizadores — normalizam nomes antes do matching
# ---------------------------------------------------------------------------

# ── Bombas de Calor ──────────────────────────────────────────────────────────

_KW_TO_SIZE: dict = {
    5.1:70, 7.0:70, 70:70,
    6.5:90, 9.0:90, 9.1:90, 90:90,
    7.3:110, 11.0:110, 12.2:110, 110:110,
    9.2:140, 13.5:140, 13.8:140, 14.0:140, 140:140,
    12.4:170, 16.3:170, 17.0:170, 170:170,
    12.5:190, 17.5:190, 18.5:190, 19.0:190, 190:190,
    14.7:220, 21.5:220, 22.0:220, 220:220,
    18.0:270, 24.3:270, 26.0:270, 26.5:270, 270:270,
    28.3:320, 31.5:320, 320:320,
    40.5:410, 410:410,
}
_IB_MODELS: list = [(7.0,"IB07"),(9.0,"IB09"),(11.0,"IB11"),(14.0,"IB14")]


def _kw_to_size(val: float) -> str | None:
    if val in _KW_TO_SIZE:
        return str(_KW_TO_SIZE[val])
    closest = min(_KW_TO_SIZE, key=lambda k: abs(k - val))
    return str(_KW_TO_SIZE[closest]) if abs(closest - val) <= 2.0 else None


def _is_tri(s: str) -> bool:
    return bool(re.search(r'\bTRI\b', s) or '400V' in s or re.search(r'\bTD\d+\b', s))


def _tri(s: str, extra: bool = False) -> str:
    return " (TRI)" if (_is_tri(s) or extra) else ""


def _extract_power(s: str) -> str | None:
    m = re.search(r'\b(\d+(?:\.\d+)?)\s?[MT]\b', s)
    if m:
        val = float(m.group(1))
        return _kw_to_size(val) or str(int(val))
    m = re.search(r'(\d+(?:\.\d+)?)\s*KW', s)
    if m:
        return _kw_to_size(float(m.group(1)))
    for tok in re.findall(r'\b\d{2,3}\b', s):
        sz = _kw_to_size(float(tok))
        if sz:
            return sz
    return None


def _zodiac_md(s: str, brand: str) -> str | None:
    m = re.search(r'\b(MD|TD)\s*(\d+)\b', s)
    if m:
        return f"{brand} ({m.group(1)}{m.group(2)}){_tri(s, extra=m.group(1)=='TD')}"
    return None


def _zodiac_num(s: str, brand: str, choices: list) -> str | None:
    m = re.search(r'\b(' + '|'.join(choices) + r')\b', s)
    return f"{brand} {m.group(1)}{_tri(s)}" if m else None


def _inverboy(s: str) -> str | None:
    m = re.search(r'\bIB\s*0?(\d+)\b', s)
    if m:
        return f"Aquark Inverboy IB{int(m.group(1)):02d}"
    m = re.search(r'(\d+(?:\.\d+)?)\s*[-–]\s*(\d+(?:\.\d+)?)\s*KW', s)
    if m:
        code = min(_IB_MODELS, key=lambda x: abs(x[0]-float(m.group(2))))[1]
        return f"Aquark Inverboy {code}"
    m = re.search(r'(\d+(?:\.\d+)?)\s*KW', s)
    if m:
        code = min(_IB_MODELS, key=lambda x: abs(x[0]-float(m.group(1))))[1]
        return f"Aquark Inverboy {code}"
    return None


def _fairland_inverx(s: str) -> str | None:
    m = re.search(r'X\s*20\s*[-–]\s*(\d+)\s*(T?)\b', s)
    if m:
        return f"Fairland InverX20 {m.group(1)}kW{' (TRI)' if m.group(2)=='T' else ''}"
    m = re.search(r'(\d+(?:\.\d+)?)\s*KW', s)
    return f"Fairland InverX20 {m.group(1)}kW{_tri(s)}" if m else None


def _fairland_xp26(s: str) -> str | None:
    m = re.search(r'X\s*P?\s*26\s*[-–]\s*(\d+)\s*P(T?)\b', s, re.IGNORECASE)
    if m:
        return f"Fairland XP26 {m.group(1)}kW{' (TRI)' if m.group(2).upper()=='T' else ''}"
    return None


def _silverline(s: str, sub: str) -> str | None:
    label = f"Poolex Silverline{' '+sub if sub else ''}"
    pat = sub or "SILVERLINE"
    m = re.search(rf'\b{pat}\s+(\d{{2,3}})(T?)\b', s, re.IGNORECASE)
    if m:
        return f"{label} {m.group(1)}{' (TRI)' if m.group(2).upper()=='T' else ''}"
    for mt in re.finditer(r'\b(\d{2,3})(T?)\b', s):
        n = int(mt.group(1))
        if n >= 50:
            return f"{label} {n}{' (TRI)' if mt.group(2).upper()=='T' else ''}"
    m = re.search(r'(\d+(?:\.\d+)?)\s*KW', s)
    if m:
        sz = _kw_to_size(float(m.group(1)))
        return f"{label} {sz}{_tri(s)}" if sz else None
    return None


def canonical_heat_pump(name: str) -> str | None:
    """Normaliza o nome de uma bomba de calor para efeitos de matching."""
    s = str(name).upper()
    s = re.sub(r'[()\[\]]', ' ', s).replace(',', '.').replace('–', '-')
    s = re.sub(r'\s+', ' ', s).strip()

    if re.search(r'Z\s*650', s):          return _zodiac_md(s, 'Zodiac Z650iQ')
    if re.search(r'ZS?\s*550|Z\s*550', s): return _zodiac_md(s, 'Zodiac Z550iQ')
    if re.search(r'Z\s*400', s):          return _zodiac_md(s, 'Zodiac Z400iQ')
    if re.search(r'Z\s*350', s):          return _zodiac_md(s, 'Zodiac Z350iQ')
    if re.search(r'Z\s*250', s):          return _zodiac_md(s, 'Zodiac Z250iQ')
    if re.search(r'Z\s*950', s):
        return _zodiac_num(s, 'Zodiac Z950', ['120','90','60','45','35'])
    if re.search(r'\bHPO\b', s):
        return _zodiac_num(s, 'Zodiac HPO', ['18','14','11','9','8','6'])
    if re.search(r'\bPM40\b', s):         return _zodiac_md(s, 'Zodiac PM40')
    if re.search(r'\bPX50\b', s):         return _zodiac_md(s, 'Zodiac PX50')
    if re.search(r'POWER\s*FORCE', s):
        return _zodiac_num(s, 'Zodiac Power Force', ['35','25'])
    if re.search(r'INVERT?\s*BOY|INVERBOY', s): return _inverboy(s)
    if re.search(r'INVERX\s*20|INVER\s*X\s*20', s): return _fairland_inverx(s)
    if re.search(r'XP\s*26|X26', s):      return _fairland_xp26(s)
    if re.search(r'SILVERLINE\s*TOP', s): return _silverline(s, 'Top')
    if re.search(r'SILVERLINE\s*FI', s):  return _silverline(s, 'Fi')
    if re.search(r'SILVERLINE', s):       return _silverline(s, '')
    if re.search(r'SILENT\s*MAX', s):
        p = _extract_power(s)
        return f"Poolex Silent Max {p}{_tri(s)}" if p else None
    for kw, modelo in [
        ('PERFECT',   'Aquark Mr. Perfect'),
        ('SILENCE',   'Aquark Mr. Silence'),
        ('SMILE',     'Bluezone Mr. Smile'),
        ('SUMHEAT',   'Hayward SumHeat'),
        ('AQUASPHERE','Aquasphere FSN'),
    ]:
        if kw in s:
            p = _extract_power(s)
            return f"{modelo} {p}{_tri(s)}" if p else modelo
    if re.search(r'ECO\s*ELYO|ELYO', s):
        p = _extract_power(s); return f"AstralPool Eco Elyo {p}{_tri(s)}" if p else None
    if re.search(r'DURA\s*VI', s):
        p = _extract_power(s); return f"Dura VI {p}{_tri(s)}" if p else None
    if 'FAIRLAND' in s:
        p = _extract_power(s); return f"Fairland {p}{_tri(s)}" if p else None
    return None


# ── Eletrólise de Sal ──────────────────────────────────────────────────────────

_SALT_MODELS: list = [
    ('HYDROXINATOR', 'Zodiac Hydroxinator'),
    ('ELITE CONNECT', 'AstralPool Elite Connect'),
    ('SMART NEXT', 'AstralPool Smart Next'),
    ('ENERGY CONNECT', 'AstralPool Energy Connect'),
    ('CLEAR CONNECT', 'AstralPool Clear Connect'),
    ('E-NEXT', 'AstralPool E-Next'),
    ('ENEXT', 'AstralPool E-Next'),
    ('AQUARITE PLUS', 'Hayward Aquarite Plus'),
    ('AQUARITE LT', 'Hayward Aquarite LT'),
    ('AQUARITE', 'Hayward Aquarite'),
    ('EXO IQ LS', 'Zodiac eXO iQ LS'),
    ('EXO IQ', 'Zodiac eXO iQ'),
    ('EXOIQ', 'Zodiac eXO iQ'),
    ('EXPERT', 'Zodiac eXPERT'),
    ('EISALT', 'Zodiac EiSalt'),
    ('CTX PRO', 'CTX Go Salt'),
    ('GO SALT', 'CTX Go Salt'),
    ('CTX', 'CTX Go Salt'),
    ('INVERCLEAR', 'Aquark InverClear'),
    ('MR. PURE', 'Aquark Mr. Pure'),
    ('MR PURE', 'Aquark Mr. Pure'),
    ('DELUXE PLUS', 'Deluxe Plus+'),
    ('PH LINK', 'Zodiac pH/Dual Link'),
    ('DUAL LINK', 'Zodiac pH/Dual Link'),
    ('ECOSALT 2', 'Davey EcoSalt 2'),
]

_SALT_JUNK = [
    'CARRO','SUPORTE','ESCOVA','SACO','CABO','FONTE','TAMPA',
    'PEÇAS','CORREIA','CAPA','OPCIONAL','FILTRO','PLACA',
]


def canonical_salt(name: str) -> str | None:
    """Normaliza o nome de um produto de eletrólise para efeitos de matching."""
    nome = str(name).upper()
    nome = re.sub(r'[®©™]', '', nome).replace('–', '-').replace(',', '.')
    nome = re.sub(r'(\d+)\s?(G/H|GR/H|GR|G|HR)', r'\1G', nome)

    # Acessórios — ignorar
    if any(x in nome for x in _SALT_JUNK) and not re.search(r'(\d+G|GS-\d+|SV\d+|IQ\d+)', nome):
        return None

    modelo = None
    for key, oficial in _SALT_MODELS:
        if key in nome:
            modelo = oficial
            break
    if not modelo:
        return None

    # Capacidade em gramas
    p = ""
    iq_m = re.search(r'IQ(\d{2,3})', nome)
    gs_m = re.search(r'GS[- ]?(\d{1,2})', nome)
    sv_m = re.search(r'SV(\d{2,3})', nome)
    g_m  = re.search(r'(\d{1,3})G', nome)
    if iq_m:   p = f" {iq_m.group(1)}g"
    elif gs_m: p = f" {gs_m.group(1)}g"
    elif sv_m: p = f" {sv_m.group(1)}g"
    elif g_m:  p = f" {g_m.group(1)}g"
    else:
        nums = re.findall(r'\b\d{1,3}\b', nome)
        if nums:
            p = f" {nums[-1]}g"

    extras = []
    if "SCALABLE" in nome:
        extras.append("Scalable")
    if any(x in nome for x in ["LS", "LOW SALT", "1.5G/L"]) and "LS" not in modelo:
        extras.append("Low Salt")
    if any(x in nome for x in ["PH", "PERISTALTICA"]):
        if not re.search(r'(SIN|NO|WITHOUT)\s+(KIT\s+)?PH', nome):
            extras.append("pH")
    if any(x in nome for x in ["RX", "ORP", "REDOX", "DUAL"]):
        if not re.search(r'(SIN|NO|WITHOUT)\s+(KIT\s+)?(ORP|RX|REDOX)', nome):
            extras.append("Rx")

    extras_str = f" ({' + '.join(dict.fromkeys(extras))})" if extras else ""
    return f"{modelo}{p}{extras_str}".strip()


def _apply_canonical(products: list, fn) -> list:
    """Adiciona campo 'canonical' a cada produto."""
    for p in products:
        p['canonical'] = fn(p['name'])
    return products


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------

def build_matched_data(
    reference: list[dict],
    all_vendor_products: dict[str, list[dict]],
    match_threshold: int = 3,
    canonicalize=None,
) -> list[dict]:
    """
    Matching com dois modos:
      - Sem canonicalize (robôs): token matching puro, threshold=3
      - Com canonicalize (bombas/sal): canonical exacto quando disponível,
        fallback a token matching para produtos não identificados
    """
    items = []

    for ref in reference:
        ref_brand = ref.get("brand") or extract_brand(ref["name"])
        ref_canon = ref.get("canonical") if canonicalize else None

        entry = {
            "name": ref["name"],
            "brand": ref_brand,
            "prices": {
                "Pools and More": {
                    "current": ref["price_current"],
                    "before":  ref["price_before"],
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
                cand_canon = cand.get("canonical") if canonicalize else None

                if ref_canon is not None and cand_canon is not None:
                    score = 100 if ref_canon == cand_canon else 0
                else:
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
                    "before":  best["price_before"],
                    "matched_name": best["name"],
                    "url": best.get("url"),
                    "match_score": best_score,
                }
                log(f"    [{best_score:3d}] {ref['name']!r} → {vendor}: {best['name']!r}")
            else:
                entry["prices"][vendor] = None

        items.append(entry)
    return items


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Funções de scraping por categoria (chamadas por main)
# ---------------------------------------------------------------------------

def _run_robots() -> list[dict]:
    log("=== [Robôs] Pools and More...")
    pm      = scrape_poolsandmore()
    log("=== [Robôs] Bricoandpool...")
    brico   = scrape_bricoandpool()
    log("=== [Robôs] Carol Piscina...")
    carol   = scrape_carolpiscina()
    log("=== [Robôs] Shop4Pool...")
    shop4   = scrape_shop4pool()
    log("=== [Robôs] Hidraulicart...")
    hidra   = scrape_hidraulicart()
    log("=== [Robôs] IoT Pool...")
    iotpool = scrape_iotpool()
    log("=== Matching robôs...")
    return build_matched_data(pm, {
        "Pools and More": pm,   "Bricoandpool": brico,
        "Carol Piscina":  carol,"Shop4Pool":    shop4,
        "Hidraulicart":   hidra,"IoT Pool":     iotpool,
    })


def _run_heat_pumps() -> list[dict]:
    log("=== [Bombas] Pools and More...")
    hp_pm      = _apply_canonical(scrape_pm_heat_pumps(),           canonical_heat_pump)
    log("=== [Bombas] Bricoandpool...")
    hp_brico   = _apply_canonical(scrape_bricoandpool_heat_pumps(), canonical_heat_pump)
    log("=== [Bombas] Carol Piscina...")
    hp_carol   = _apply_canonical(scrape_carolpiscina_heat_pumps(), canonical_heat_pump)
    log("=== [Bombas] Shop4Pool...")
    hp_shop4   = _apply_canonical(scrape_shop4pool_heat_pumps(),    canonical_heat_pump)
    log("=== [Bombas] Hidraulicart...")
    hp_hidra   = _apply_canonical(scrape_hidraulicart_heat_pumps(), canonical_heat_pump)
    log("=== [Bombas] IoT Pool...")
    hp_iotpool = _apply_canonical(scrape_iotpool_heat_pumps(),      canonical_heat_pump)
    log("=== Matching bombas...")
    return build_matched_data(hp_pm, {
        "Pools and More": hp_pm,    "Bricoandpool": hp_brico,
        "Carol Piscina":  hp_carol, "Shop4Pool":    hp_shop4,
        "Hidraulicart":   hp_hidra, "IoT Pool":     hp_iotpool,
    }, canonicalize=canonical_heat_pump)


def _run_salt() -> list[dict]:
    log("=== [Sal] Pools and More...")
    salt_pm      = _apply_canonical(scrape_pm_salt(),           canonical_salt)
    log("=== [Sal] Bricoandpool...")
    salt_brico   = _apply_canonical(scrape_bricoandpool_salt(), canonical_salt)
    log("=== [Sal] Carol Piscina...")
    salt_carol   = _apply_canonical(scrape_carolpiscina_salt(), canonical_salt)
    log("=== [Sal] Shop4Pool...")
    salt_shop4   = _apply_canonical(scrape_shop4pool_salt(),    canonical_salt)
    log("=== [Sal] Hidraulicart...")
    salt_hidra   = _apply_canonical(scrape_hidraulicart_salt(), canonical_salt)
    log("=== [Sal] IoT Pool...")
    salt_iotpool = _apply_canonical(scrape_iotpool_salt(),      canonical_salt)
    log("=== Matching eletrólise...")
    return build_matched_data(salt_pm, {
        "Pools and More": salt_pm,    "Bricoandpool": salt_brico,
        "Carol Piscina":  salt_carol, "Shop4Pool":    salt_shop4,
        "Hidraulicart":   salt_hidra, "IoT Pool":     salt_iotpool,
    }, canonicalize=canonical_salt)


def _save(output: dict) -> None:
    """Grava data.json e embute dados no index.html."""
    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    js_payload  = json.dumps(output, ensure_ascii=False)
    placeholder = "null; /* __DASHBOARD_DATA__ */"
    replacement = f"{js_payload}; /* __DASHBOARD_DATA__ */"
    src = "index.html" if os.path.exists("index.html") else "dashboard.html"
    with open(src, "r", encoding="utf-8") as f:
        html = f.read()
    if placeholder in html:
        html = html.replace(placeholder, replacement)
    else:
        import re as _re
        html = _re.sub(
            r'window\.DASHBOARD_DATA\s*=\s*.+?/\* __DASHBOARD_DATA__ \*/',
            f'window.DASHBOARD_DATA = {replacement}',
            html, flags=_re.DOTALL
        )
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html)


def _print_summary(output: dict) -> None:
    for label, key in [("Robôs","robots"),("Bombas","heat_pumps"),("Sal","salt_electrolysis")]:
        items = output.get(key, [])
        if not items:
            continue
        log(f"  [{label}] {len(items)} produtos | matches:")
        for v in VENDORS[1:]:
            matched = sum(1 for r in items if r["prices"].get(v) is not None)
            log(f"    {v}: {matched}/{len(items)}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Scraper de preços de piscina")
    parser.add_argument(
        "--categoria", "-c",
        choices=["robots", "bombas", "sal", "todas"],
        default="robots",
        help="Categoria a scraper. 'todas' corre as 3 em sequência (default: robots)",
    )
    args = parser.parse_args()
    cat = args.categoria

    # Carrega dados existentes para preservar categorias não scraped nesta sessão
    existing: dict = {}
    if os.path.exists("data.json"):
        with open("data.json", encoding="utf-8") as f:
            try:
                existing = json.load(f)
            except Exception:
                existing = {}

    output = {
        "generated_at":    datetime.now().isoformat(timespec="seconds"),
        "vendors":         VENDORS,
        "robots":          existing.get("robots",           []),
        "heat_pumps":      existing.get("heat_pumps",       []),
        "salt_electrolysis": existing.get("salt_electrolysis", []),
    }

    def _update(key: str, fn, label: str):
        result = fn()
        if result:
            output[key] = result
            output["generated_at"] = datetime.now().isoformat(timespec="seconds")
            _save(output)
            log(f"\n--- {label} gravado(a): {len(result)} produtos. ---")
        else:
            log(f"\n⚠ {label}: scraping devolveu 0 resultados — dados anteriores mantidos.")

    if cat in ("robots", "todas"):
        _update("robots", _run_robots, "Robôs")

    if cat in ("bombas", "todas"):
        _update("heat_pumps", _run_heat_pumps, "Bombas de Calor")

    if cat in ("sal", "todas"):
        _update("salt_electrolysis", _run_salt, "Eletrólise de Sal")

    log(f"\n=== Concluído! ({cat})")
    _print_summary(output)


if __name__ == "__main__":
    main()
