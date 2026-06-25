import time
import os
import csv
import json
import argparse
import sys
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup

# Ensure utf-8 output on Windows
sys.stdout.reconfigure(encoding='utf-8')

# Built-in list of popular Indonesian local skincare brands
DEFAULT_INDONESIAN_BRANDS = [
    "Somethinc", "Wardah", "Avoskin", "Whitelab", "Emina", "Scarlett", 
    "Elsheskin", "Lacoco", "Viva Cosmetics", "Sariayu", "Mustika Ratu", 
    "MS Glow", "Kahf", "Studio Tropik", "Bhumi", "Npure", "Sensatia Botanicals",
    "Dear Me Beauty", "Reset the Skin", "Rose All Day", "Luxcrime", 
    "Hanasui", "Implora", "Azarine", "Pratista"
]

def get_driver():
    options = Options()
    options.add_argument('--headless')
    options.add_argument('--disable-gpu')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
    options.add_argument('--disable-blink-features=AutomationControlled')
    
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    driver.set_page_load_timeout(20)
    # Bypass navigator.webdriver detection
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    })
    return driver

def load_existing_urls(csv_path):
    if not os.path.exists(csv_path):
        return set(), 1
        
    urls = set()
    max_id = 0
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get('product_url'):
                urls.add(row['product_url'])
            try:
                max_id = max(max_id, int(row['id']))
            except (ValueError, TypeError):
                pass
    return urls, max_id + 1

def parse_product_page(driver, url):
    print(f"Navigating to detail: {url}")
    driver.get(url)
    
    # Wait for page load
    time.sleep(3)
    
    html = driver.page_source
    soup = BeautifulSoup(html, 'html.parser')
    
    # 1. Product Name
    name_tag = soup.find('h1')
    product_name = name_tag.get_text(strip=True) if name_tag else ""
    if not product_name:
        # Fallback
        meta_title = soup.find('title')
        if meta_title:
            product_name = meta_title.get_text(strip=True).split('–')[0].strip()
            
    # 2. Brand Name
    brand = ""
    for script in soup.find_all('script', type='application/ld+json'):
        try:
            data = json.loads(script.string)
            if isinstance(data, dict):
                if data.get("@type") == "Product":
                    brand_info = data.get('brand')
                    if isinstance(brand_info, dict):
                        brand = brand_info.get('name', '')
                    else:
                        brand = brand_info or ''
                    break
                elif "@graph" in data:
                    for obj in data["@graph"]:
                        if obj.get("@type") == "Product":
                            brand_info = obj.get('brand')
                            if isinstance(brand_info, dict):
                                brand = brand_info.get('name', '')
                            else:
                                brand = brand_info or ''
                            break
        except Exception:
            pass
            
    # Fallback brand if not found in JSON-LD
    if not brand and product_name:
        for a in soup.find_all('a', href=True):
            if '/collections/' in a['href'] and a.get_text(strip=True).lower() in product_name.lower():
                brand = a.get_text(strip=True)
                break

    # 3. Ingredients (INCI)
    ingredients_raw = ""
    labels = soup.find_all('label')
    for label in labels:
        label_text = label.get_text(strip=True).lower()
        if "full ingredients" in label_text and "inci" in label_text:
            container = label.find_next('div', class_='pp-acc-content')
            if container:
                # Find all paragraphs and choose the one with the most commas (best indicator of INCI ingredients list)
                paragraphs = container.find_all('p')
                max_commas = -1
                best_p = ""
                for p in paragraphs:
                    p_text = p.get_text(strip=True)
                    commas = p_text.count(',')
                    if commas > max_commas and len(p_text) > 30:
                        max_commas = commas
                        best_p = p_text
                if best_p and max_commas >= 3:
                    ingredients_raw = best_p
            break
            
    if not ingredients_raw:
        # Fallback search - search all paragraphs on the page
        max_commas = -1
        best_p = ""
        for p in soup.find_all('p'):
            p_text = p.get_text(strip=True)
            if len(p_text) > 30:
                p_text_lower = p_text.lower()
                
                # Check if paragraph is inside a modal or tooltip
                is_disclaimer = False
                parent = p.parent
                while parent:
                    p_classes = parent.get('class') or []
                    if any(c in p_classes for c in ['modal-custom', 'modal-window', 'main-modal-content', 'tooltip-custom', 'tooltiptext', 'modal']):
                        is_disclaimer = True
                        break
                    parent = parent.parent
                    
                if is_disclaimer:
                    continue
                    
                # Keyword checks to avoid common Skincarisma explanations
                exclude_keywords = [
                    "these include:", 
                    "understanding parabens", 
                    "parabens are a", 
                    "sulfates are a", 
                    "alcohol ingredients are",
                    "scientific committee on consumer safety",
                    "pityrosporum folliculitis",
                    "fungal-safe label",
                    "notable effects & ingredients"
                ]
                if any(kw in p_text_lower for kw in exclude_keywords):
                    continue
                    
                # Must not start with common sentence starters to avoid matching prose
                if p_text_lower.startswith(("it ", "it's ", "this ", "these ", "we ", "you ", "they ", "who ", "which ", "quick ", "just ", "have ", "not ", "why ", "one ", "general ", "made ", "the ", "a ", "paraben", "sulfate", "silicone", "alcohol", "itdoesn", "ithas", "thisproduct", "theseinclude", "somethinc is")):
                    continue
                    
                has_indicator = any(x in p_text_lower for x in ["aqua", "water", "glycerin", "butylene glycol", "propanediol"])
                commas = p_text.count(',')
                if commas > max_commas and (commas >= 10 or (has_indicator and commas >= 6)):
                    max_commas = commas
                    best_p = p_text
        if best_p:
            ingredients_raw = best_p
                    
    # Clean any prefix like "38 ingredients:" or "41 ingredients" or similar from the front
    import re
    if ingredients_raw:
        ingredients_raw = re.sub(r'^\d+\s*ingredients(?:\s*list)?(?:\s*\(inci\))?[:\s]*', '', ingredients_raw, flags=re.IGNORECASE)
        # Clean zero-width space characters from ingredients string
        ingredients_raw = ingredients_raw.replace('\u200b', '').replace('\u200e', '').strip()

    # 4. Categories/Badges mapping
    categories_list = []
    free_div = soup.find('div', class_='free-list')
    if free_div:
        free_text = free_div.get_text(strip=True)
        if "FREE FROM:" in free_text:
            items_str = free_text.replace("FREE FROM:", "").strip()
            items = [item.strip().lower() for item in items_str.split('·')]
            for item in items:
                if 'fragrance' in item:
                    categories_list.append("#fragrance & essentialoil-free")
                elif 'paraben' in item:
                    categories_list.append("#paraben-free")
                elif 'sulfate' in item:
                    categories_list.append("#sulfate-free")
                elif 'alcohol' in item:
                    categories_list.append("#alcohol-free")
                elif 'silicone' in item:
                    categories_list.append("#silicone-free")
                    
    categories_str = ", ".join(categories_list)
    
    # 5. Price extraction
    price = ""
    # Method A: DOM pp-spec Price Val
    for spec in soup.find_all(class_='pp-spec'):
        lbl = spec.find(class_='lbl')
        if lbl and lbl.get_text(strip=True).lower() == 'price':
            val = spec.find(class_='val')
            if val:
                price = val.get_text(strip=True)
                break
                
    # Method B: JSON-LD offers metadata fallback
    if not price or price in ["$0.00", "0", "0.00"]:
        for script in soup.find_all('script', type='application/ld+json'):
            try:
                data = json.loads(script.string)
                if isinstance(data, dict):
                    def search_key(d, key):
                        if key in d:
                            return d[key]
                        for k, v in d.items():
                            if isinstance(v, dict):
                                res = search_key(v, key)
                                if res: return res
                            elif isinstance(v, list):
                                for item in v:
                                    if isinstance(item, dict):
                                        res = search_key(item, key)
                                        if res: return res
                        return None
                    
                    offers = search_key(data, "offers")
                    if isinstance(offers, dict):
                        p = offers.get("price")
                        c = offers.get("priceCurrency", "")
                        if p and float(p) > 0:
                            price = f"{c} {p}".strip()
                            break
            except Exception:
                pass

    if price in ["$0.00", "0", "0.00"]:
        price = ""
    
    return {
        "product_name": product_name,
        "brand": brand,
        "category": categories_str,
        "ingredient_raw": ingredients_raw,
        "price": price
    }

def discover_product_urls_by_search(driver, query, max_pages=3):
    print(f"Discovering product URLs by searching brand/query: {query}")
    product_urls = []
    
    for page in range(1, max_pages + 1):
        url = f"https://www.skincarisma.com/search?q={query}&page={page}"
        print(f"Loading search page {page}: {url}")
        driver.get(url)
        time.sleep(4)
        
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        
        # Find links matching /products/
        page_links = []
        for a in soup.find_all('a', href=True):
            href = a['href']
            if '/products/' in href:
                full_url = "https://www.skincarisma.com" + href.split('?')[0]
                page_links.append(full_url)
                
        unique_page_links = list(set(page_links))
        print(f"Found {len(unique_page_links)} unique product URLs on search page {page}.")
        
        if not unique_page_links:
            # No search results found
            break
            
        product_urls.extend(unique_page_links)
        
    return list(set(product_urls))

def main():
    parser = argparse.ArgumentParser(description="Scrape skincare product ingredients and details from Skincarisma")
    parser.add_argument('--limit', type=int, default=10, help="Total number of products to scrape (default: 10)")
    parser.add_argument('--brands', type=str, default="all", help="Comma-separated list of brand search queries, or 'all' for built-in Indonesian brands")
    parser.add_argument('--delay', type=float, default=3.0, help="Delay in seconds between page crawls (default: 3.0)")
    parser.add_argument('--output', type=str, default=r"data/dataset_scincare/skincarisma_products.csv", help="Path to output CSV file")
    args = parser.parse_args()
    
    output_path = args.output
    # Create directory if it doesn't exist
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    
    # Resolve brand list
    if args.brands.lower() == 'all':
        brands_to_search = DEFAULT_INDONESIAN_BRANDS
    else:
        brands_to_search = [b.strip() for b in args.brands.split(',') if b.strip()]
        
    print(f"Target Indonesian Brands to search: {brands_to_search}")
    print(f"Target output file: {output_path}")
    
    existing_urls, next_id = load_existing_urls(output_path)
    print(f"Loaded {len(existing_urls)} existing URLs from dataset. Next ID to append: {next_id}")
    
    # Write header and handle migration
    if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
        with open(output_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['id', 'product_name', 'brand', 'category', 'product_url', 'ingredient_raw', 'price'])
    else:
        # Check if 'price' is in headers
        need_migration = False
        rows = []
        with open(output_path, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            headers = next(reader, [])
            if 'price' not in headers:
                need_migration = True
                for row in reader:
                    # Append empty string for price
                    rows.append(row + [""])
        
        if need_migration:
            print(f"Migrating {output_path} to include 'price' column...")
            with open(output_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(['id', 'product_name', 'brand', 'category', 'product_url', 'ingredient_raw', 'price'])
                writer.writerows(rows)
            print("Migration complete.")
            
    driver = get_driver()
    scraped_count = 0
    
    try:
        for brand in brands_to_search:
            if scraped_count >= args.limit:
                break
                
            discovered = discover_product_urls_by_search(driver, brand, max_pages=2)
            # Filter out duplicates and already crawled
            urls_to_crawl = [u for u in set(discovered) if u not in existing_urls]
            print(f"Brand '{brand}': discovered {len(discovered)} URLs. Remaining to crawl: {len(urls_to_crawl)}")
            
            for url in urls_to_crawl:
                if scraped_count >= args.limit:
                    print(f"Reached crawl limit of {args.limit} products.")
                    break
                    
                try:
                    product_data = parse_product_page(driver, url)
                    if product_data['product_name'] and product_data['ingredient_raw']:
                        # Save to CSV
                        with open(output_path, 'a', newline='', encoding='utf-8') as f:
                            writer = csv.writer(f)
                            writer.writerow([
                                next_id,
                                product_data['product_name'],
                                product_data['brand'],
                                product_data['category'],
                                url,
                                product_data['ingredient_raw'],
                                product_data.get('price', '')
                            ])
                        print(f"Successfully scraped: {product_data['product_name']} by {product_data['brand']}")
                        existing_urls.add(url)
                        next_id += 1
                        scraped_count += 1
                    else:
                        print(f"Skipping {url} due to missing name or ingredients raw text.")
                except Exception as e:
                    print(f"Error scraping {url}: {e}")
                    
                # Respect rate limiting
                time.sleep(args.delay)
                
    except Exception as e:
        print(f"General error: {e}")
    finally:
        print(f"Scrape job complete. Total products scraped: {scraped_count}")
        driver.quit()

if __name__ == "__main__":
    main()
