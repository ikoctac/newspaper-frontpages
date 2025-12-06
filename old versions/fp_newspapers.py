import sys  # <--- CHANGED: Added sys
import os
import re
import time
import unicodedata
import requests
import csv 
from urllib.parse import urljoin
from datetime import datetime
from playwright.sync_api import sync_playwright
from PIL import Image

# --- CHANGED: Added this function to find files inside the .exe ---
def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)
# -----------------------------------------------------------------

class NewspaperBot:
    def __init__(self):
        # --- CHANGED: Wrapped the filename with resource_path() ---
        self.csv_path = resource_path("newspapers.csv") 
        
        # Determine where the exe is running to save images in the same folder
        if getattr(sys, 'frozen', False):
            application_path = os.path.dirname(sys.executable)
        else:
            application_path = os.path.dirname(os.path.abspath(__file__))
            
        self.root_dir = os.path.join(application_path, "downloaded_news_pictures")
        # ---------------------------------------------------------
        
        self.today_dir = self._setup_directory()
        self.downloaded_images = []
        
        # Site Configurations
        self.url_frontpages = "https://www.frontpages.gr/"
        self.url_zougla = "https://www.zougla.gr/newspapers/"

    def _setup_directory(self):
        """Creates the folder for today's downloads."""
        date_str = datetime.now().strftime('%Y-%m-%d')
        path = os.path.join(self.root_dir, date_str)
        if not os.path.exists(path):
            os.makedirs(path)
        return path

    def _read_target_newspapers(self, file_path: str) -> list[str]:
        """Reads newspaper names from a CSV file."""
        names = []
        try:
            with open(file_path, mode='r', encoding='utf-8') as file:
                reader = csv.DictReader(file)
                for row in reader:
                    # Expects the column header 'NewspaperName'
                    name = row.get('NewspaperName', '').strip()
                    if name:
                        names.append(name)
            print(f"✅ Loaded {len(names)} target newspapers from {file_path}.")
        except FileNotFoundError:
            print(f"🛑 Error: CSV file not found at {file_path}. Using empty list.")
        except KeyError:
            print("🛑 Error: 'NewspaperName' column not found in CSV. Check your column header.")
        return names

    def _normalize_text(self, text):
        """Standardizes text for comparison (lower case, no accents)."""
        if not text: return ""
        text = text.lower().strip()
        # Remove accents
        return ''.join(c for c in unicodedata.normalize('NFD', text) if unicodedata.category(c) != 'Mn')

    def _check_date_generic(self, date_text):
        """
        Parses date text to ensure it matches today.
        Returns False if the date is definitively not today's date, stopping the download.
        """
        try:
            if not date_text: 
                # If no date text is found, we assume it's today
                return True
            
            now = datetime.now().date()
            clean_text = date_text.strip()
            paper_date = None

            # 1. Check for D / M format (Frontpages: '3 / 12')
            match_short = re.search(r'(\d{1,2})\s*/\s*(\d{1,2})', clean_text)
            
            if match_short:
                day, month = map(int, match_short.groups())
                year = now.year
                
                # Check for year rollover
                if month == 12 and now.month == 1:
                    year -= 1
                
                paper_date = datetime(year, month, day).date()
            
            # 2. Check for D / M / YYYY format (Zougla)
            else:
                match_long = re.search(r'(\d{1,2})\s*/\s*(\d{1,2})\s*/\s*(\d{4})', clean_text)
                if match_long:
                    day, month, year = map(int, match_long.groups())
                    paper_date = datetime(year, month, day).date()

            if paper_date is None:
                # Date element found but format is unknown. Proceed as safe default.
                return True

            is_today = (paper_date == now)
            
            if is_today:
                print(f"   ✅ Date check: Match found ({paper_date.strftime('%Y-%m-%d')}).")
            else:
                print(f"   ⚠️ Date check: Date is old ({paper_date.strftime('%Y-%m-%d')}). Skipping download.")

            return is_today
        
        except Exception as e:
            print(f"   ⚠️ Date parsing error: {e}. Proceeding by default.")
            return True 

    def _download_file(self, page, url, filename):
        """Downloads a file using the browser context to handle cookies/headers."""
        try:
            print(f"   ⬇️  Downloading: {filename}...")
            # Use page.goto() to leverage the browser's session/cookies/headers
            response = page.goto(url, timeout=60000)
            
            if response and response.status == 200:
                # Clean filename
                clean_name = re.sub(r'[^\w\-_\.]', '', filename)
                save_path = os.path.join(self.today_dir, clean_name)
                
                with open(save_path, 'wb') as f:
                    f.write(response.body())
                
                print(f"   ✅ Saved: {clean_name}")
                return save_path
            
            print(f"   ❌ Download status error: {response.status if response else 'None'} for URL: {url}")
        except Exception as e:
            print(f"   ❌ Download failed for {url}: {e}")
        return None

    # --- POPUP HANDLER (Disabled) ---
    def _handle_popups(self, page, site_name):
        pass 
    # ---------------------------------------------


    # --- Site Logic: FRONT PAGES HELPERS ---

    def _find_frontpages_high_res_url(self, page):
        """[DEPRECATED/PLACEHOLDER]"""
        return None

    def _search_frontpages(self, page, target_name):
        """
        Frontpages Main Logic: Find small image URL on main page and construct high-res URL.
        """
        print(f"   🔎 Checking Frontpages.gr for {target_name}...")
        
        try:
            page.goto(self.url_frontpages, timeout=60000)
            
            thumbers = page.locator(".thumber").all()
            found_small_img_src = None
            
            # FIND LINK AND CHECK DATE on the main page
            for thumber in thumbers:
                name_el = thumber.locator(".paperName a")
                if not name_el.count(): continue
                
                current_raw_name = name_el.text_content()
                
                if self._normalize_text(current_raw_name) == target_name:
                    
                    # Date check logic
                    date_el = thumber.locator(".paperdate")
                    date_text = date_el.text_content() if date_el.count() else ""

                    if not self._check_date_generic(date_text):
                        # Returns None if the date check fails
                        return None 
                    
                    # Get the small image src (e.g., /data/.../MTThraki300.jpg)
                    img_el = thumber.locator("img").first
                    if img_el.count():
                        found_small_img_src = img_el.get_attribute("src")
                        print(f"   ✅ Found match. Small Image SRC: {found_small_img_src}")
                        break
            
            if not found_small_img_src:
                return None

            # CONSTRUCT HIGH-RES URL (Optimization)
            if found_small_img_src and found_small_img_src.endswith('300.jpg'):
                image_path = found_small_img_src.replace('300.jpg', 'I.jpg')
                full_img_url = urljoin(self.url_frontpages, image_path)
                
                print(f"   🖼️ Constructed High-Res URL: {full_img_url}")
                return self._download_file(page, full_img_url, f"{target_name}_fp.jpg")
            
            print("   ⚠️ Could not construct high-res URL (small image not found or wrong format).")
            return None

        except Exception as e:
            print(f"   ⚠️ Frontpages Error: {e}")
            return None

    # --- Site Logic: ZOUGLA HELPERS ---

    def _find_zougla_high_res_url(self, page, target_name):
        """
        Finds the high-resolution image URL on the Zougla detail page.
        """
        img_src = None
        
        # STRATEGY A: Explicit selector
        try:
            cover_selector = ".newspaper-cover img"
            page.wait_for_selector(cover_selector, timeout=15000)
            img_el = page.locator(cover_selector).first
            if img_el.count():
                img_src = img_el.get_attribute("src")
        except Exception as e:
            pass
            
        # STRATEGY B: Robust full-page scan
        if not img_src:
            try:
                page.wait_for_selector("img", timeout=15000)
                all_imgs = page.locator("img").all()
                
                for img_el in all_imgs:
                    src = img_el.get_attribute("src")
                    if not src: continue
                    
                    norm_src = self._normalize_text(src)
                    if target_name == norm_src and not any(x in src.lower() for x in ['-sm.', '300x', '150x']):
                        img_src = src
                        break
            except Exception as e:
                pass

        return img_src

    def _search_zougla(self, page, target_name):
        """
        Zougla Main Logic: Find link, check date, navigate, download.
        """
        print(f"   🔎 Checking Zougla.gr for {target_name}...")
        try:
            page.goto(self.url_zougla, timeout=60000)
            
            self._handle_popups(page, "Zougla.gr") 
            
            blocks = page.locator(".newspaper-block").all()
            found_link_href = None

            # FIND LINK AND CHECK DATE on the main page
            for block in blocks:
                info_div = block.locator(".newspaper-info")
                name_el = info_div.locator("strong")
                if not name_el.count(): continue
                
                if self._normalize_text(name_el.text_content()) == target_name:
                    
                    full_info_text = info_div.text_content().strip()
                    date_match = re.search(r'(\d{2}/\d{2}/\d{4})', full_info_text)
                    
                    if date_match and not self._check_date_generic(date_match.group(1)):
                        return None
                    
                    link_el = block.locator(".front-img a").first
                    if not link_el.count(): continue
                        
                    found_link_href = link_el.get_attribute("href")
                    print(f"   ✅ Found match. Detail Link: {found_link_href}")
                    break
            
            if not found_link_href:
                return None
            
            # NAVIGATE TO DETAIL PAGE
            detail_url = urljoin(self.url_zougla, found_link_href)
            print(f"   ➡️  Navigating to detail page...")
            page.goto(detail_url, timeout=60000)

            # FIND HIGH-RES IMAGE URL using helper
            img_src = self._find_zougla_high_res_url(page, target_name)
            
            if img_src:
                full_url = urljoin(self.url_zougla, img_src)
                return self._download_file(page, full_url, f"{target_name}_zg.jpg")
            
            print("   ⚠️ Could not find the high-res image on the detail page.")
            return None

        except Exception as e:
            print(f"   ⚠️ Zougla Error: {e}")
            return None

    # --- Main Orchestrator ---

    def generate_pdf(self):
        """Combines all downloaded images into a PDF."""
        if not self.downloaded_images:
            print("⚠️ No images to create PDF.")
            return

        print(f"\n📄 Creating PDF from {len(self.downloaded_images)} images...")
        # Saves the PDF to the same folder as the downloaded images
        pdf_path = os.path.join(self.today_dir, f"Papers_{datetime.now().strftime('%Y-%m-%d')}.pdf")
        
        try:
            images = []
            for path in self.downloaded_images:
                try:
                    img = Image.open(path)
                    if img.mode != 'RGB': img = img.convert('RGB')
                    images.append(img)
                except: pass
            
            if images:
                images[0].save(pdf_path, "PDF", resolution=300.0, save_all=True, append_images=images[1:])
                print(f"✅ PDF Saved: {pdf_path}")
        except Exception as e:
            print(f"❌ PDF Failed: {e}")

    def run(self):
        """Main execution loop."""
        
        # --- DYNAMIC NEWSPAPER LIST FROM CSV ---
        NEWSPAPER_LIST = self._read_target_newspapers(self.csv_path)
        # ---------------------------------------

        if not NEWSPAPER_LIST:
             print("🛑 No newspapers loaded. Exiting.")
             return

        with sync_playwright() as p:
            print("🚀 Launching scraper (Headless Mode)...")
            browser = p.chromium.launch(headless=True) 
            page = browser.new_context().new_page()
            
            for name in NEWSPAPER_LIST:
                norm_name = self._normalize_text(name)
                print(f"\n🔎 Processing: {name} (Normalized: {norm_name})")

                # 1. Try Frontpages
                result = self._search_frontpages(page, norm_name)
                
                # 2. Try Zougla (Fallback)
                if not result:
                    result = self._search_zougla(page, norm_name)
                
                if result:
                    self.downloaded_images.append(result)
                else:
                    print(f"❌ Not found or date skipped: {name}")

            browser.close()
        
        # 3. Generate PDF
        self.generate_pdf()

if __name__ == "__main__":
    bot = NewspaperBot()
    bot.run()