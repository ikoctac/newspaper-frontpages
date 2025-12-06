import sys
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

# 1. HELPER: Finds the internal CSV file when running as .exe
# NOTE: This function is kept, but it is not used for the external CSV file.
def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)

class NewspaperBot:
    def __init__(self):
        # 2. CONFIG: Determine the application's root path (where the .exe is)
        if getattr(sys, 'frozen', False):
            # If running as .exe, get the folder of the executable
            self.application_path = os.path.dirname(sys.executable)
        else:
            # If running as script, get the folder of the script
            self.application_path = os.path.dirname(os.path.abspath(__file__))
            
        # 3. CONFIG: The script looks for "newspapers.csv" in the same folder as the .exe
        self.csv_path = os.path.join(self.application_path, "newspapers.csv") 
        
        # 4. CONFIG: Save output files in a subfolder next to the .exe
        self.root_dir = os.path.join(self.application_path, "downloaded_news_pictures")
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
        names = []
        try:
            with open(file_path, mode='r', encoding='utf-8') as file:
                reader = csv.DictReader(file)
                for row in reader:
                    name = row.get('NewspaperName', '').strip()
                    if name:
                        names.append(name)
            print(f"✅ Loaded {len(names)} target newspapers from '{os.path.basename(file_path)}'.")
        except FileNotFoundError:
            print(f"🛑 Error: CSV file not found at {file_path}")
        except KeyError:
            print("🛑 Error: 'NewspaperName' column not found in CSV.")
        return names

    def _normalize_text(self, text):
        if not text: return ""
        text = text.lower().strip()
        # Normalize text to remove accents/diacritics for better comparison
        return ''.join(c for c in unicodedata.normalize('NFD', text) if unicodedata.category(c) != 'Mn')

    def _check_date_generic(self, date_text):
        try:
            if not date_text: return True
            
            now = datetime.now().date()
            clean_text = date_text.strip()
            paper_date = None

            # Check D/M
            match_short = re.search(r'(\d{1,2})\s*/\s*(\d{1,2})', clean_text)
            if match_short:
                day, month = map(int, match_short.groups())
                year = now.year
                # Handle cases where the displayed date is Dec/Jan rollover
                if month == 12 and now.month == 1: year -= 1
                paper_date = datetime(year, month, day).date()
            else:
                # Check D/M/YYYY
                match_long = re.search(r'(\d{1,2})\s*/\s*(\d{1,2})\s*/\s*(\d{4})', clean_text)
                if match_long:
                    day, month, year = map(int, match_long.groups())
                    paper_date = datetime(year, month, day).date()

            if paper_date is None: return True

            is_today = (paper_date == now)
            if is_today:
                print(f"    ✅ Date Match: {paper_date}")
            else:
                print(f"    ⚠️ Old Date: {paper_date}. Skipping.")
            return is_today
        except Exception:
            return True 

    def _download_file(self, page, url, filename):
        try:
            print(f"    ⬇️  Downloading: {filename}...")
            # Use requests for direct file download, as it's cleaner for binary files
            # and avoids Playwright's page context.
            response = requests.get(url, timeout=60, stream=True)
            response.raise_for_status() # Raise exception for bad status codes
            
            clean_name = re.sub(r'[^\w\-_\.]', '', filename)
            save_path = os.path.join(self.today_dir, clean_name)
            
            with open(save_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
                    
            print(f"    ✅ Saved: {clean_name}")
            return save_path
        except requests.exceptions.RequestException as e:
            print(f"    ❌ Download failed (Requests Error): {e}")
        except Exception as e:
            print(f"    ❌ Download failed (General Error): {e}")
        return None

    def _handle_popups(self, page, site_name):
        # Placeholder for potential cookie/popup handling on Zougla.gr
        pass 

    # --- Site Logic ---
    def _search_frontpages(self, page, target_name):
        print(f"    🔎 Checking Frontpages.gr for {target_name}...")
        try:
            page.goto(self.url_frontpages, timeout=60000)
            thumbers = page.locator(".thumber").all()
            found_small_img_src = None
            
            for thumber in thumbers:
                name_el = thumber.locator(".paperName a")
                if not name_el.count(): continue
                
                # Compare normalized names
                if self._normalize_text(name_el.text_content()) == target_name:
                    date_el = thumber.locator(".paperdate")
                    # Check the date and skip if it's old
                    if not self._check_date_generic(date_el.text_content() if date_el.count() else ""):
                        return None 
                        
                    img_el = thumber.locator("img").first
                    if img_el.count():
                        found_small_img_src = img_el.get_attribute("src")
                        break
            
            if found_small_img_src and found_small_img_src.endswith('300.jpg'):
                # Convert small image URL to high-res image URL
                image_path = found_small_img_src.replace('300.jpg', 'I.jpg')
                full_img_url = urljoin(self.url_frontpages, image_path)
                
                # NOTE: Switched to requests download for stability
                return self._download_file(page, full_img_url, f"{target_name}_fp.jpg")
            return None
        except Exception as e:
            print(f"    ⚠️ Frontpages.gr search failed: {e}")
            return None

    def _search_zougla(self, page, target_name):
        print(f"    🔎 Checking Zougla.gr for {target_name}...")
        try:
            page.goto(self.url_zougla, timeout=60000)
            self._handle_popups(page, "Zougla.gr") 
            blocks = page.locator(".newspaper-block").all()
            found_link_href = None

            for block in blocks:
                info = block.locator(".newspaper-info")
                if not info.locator("strong").count(): continue
                
                # Compare normalized names
                if self._normalize_text(info.locator("strong").text_content()) == target_name:
                    date_match = re.search(r'(\d{2}/\d{2}/\d{4})', info.text_content())
                    if date_match and not self._check_date_generic(date_match.group(1)): return None
                    
                    link_el = block.locator(".front-img a").first
                    if link_el.count():
                        found_link_href = link_el.get_attribute("href")
                        break
            
            if not found_link_href: return None
            
            # Go to the detail page
            page.goto(urljoin(self.url_zougla, found_link_href), timeout=60000)
            
            # Find High Res image source
            img_src = None
            if page.locator(".newspaper-cover img").count():
                img_src = page.locator(".newspaper-cover img").first.get_attribute("src")
            
            if img_src:
                # NOTE: Switched to requests download for stability
                full_img_url = urljoin(self.url_zougla, img_src)
                return self._download_file(page, full_img_url, f"{target_name}_zg.jpg")
            return None
        except Exception as e:
            print(f"    ⚠️ Zougla.gr search failed: {e}")
            return None

    def generate_pdf(self):
        if not self.downloaded_images:
            print("⚠️ No images to create PDF.")
            return
        print(f"\n📄 Creating PDF from {len(self.downloaded_images)} images...")
        pdf_path = os.path.join(self.today_dir, f"Papers_{datetime.now().strftime('%Y-%m-%d')}.pdf")
        try:
            images = []
            for path in self.downloaded_images:
                try:
                    # Open and convert to RGB, required for saving as PDF
                    img = Image.open(path).convert('RGB')
                    images.append(img)
                except Exception as e: 
                    print(f"    ❌ Could not process image {os.path.basename(path)} for PDF: {e}")
            
            if images:
                # Save the first image, appending the rest
                images[0].save(pdf_path, "PDF", resolution=300.0, save_all=True, append_images=images[1:])
                print(f"✅ PDF Saved: {pdf_path}")
        except Exception as e:
            print(f"❌ PDF Failed: {e}")

    def run(self):
        # Check if the external CSV file exists before attempting to read
        if not os.path.exists(self.csv_path):
            print(f"🛑 ERROR: Required data file not found.")
            print(f"Please ensure '{os.path.basename(self.csv_path)}' is in the same folder as the executable.")
            time.sleep(10) # Pause so the user can see the error
            return

        NEWSPAPER_LIST = self._read_target_newspapers(self.csv_path)
        if not NEWSPAPER_LIST: return

        with sync_playwright() as p:
            print("🚀 Launching scraper...")
            
            browser = None
            # 5. CRITICAL: Try system-installed browsers (Chrome first, then Edge)
            # NOTE: If you bundled the browser using PLAYWRIGHT_BROWSERS_PATH=0, 
            # Playwright will automatically find the bundled browser here.
            try:
                browser = p.chromium.launch(headless=True, channel="chrome")
            except Exception:
                print("⚠️ Google Chrome not found, trying Microsoft Edge...")
                try:
                    browser = p.chromium.launch(headless=True, channel="msedge")
                except Exception:
                    # Fallback if both system browsers fail (Playwright will try its own bundled browser if one exists)
                    try:
                        print("⚠️ Neither system browser found. Attempting to launch generic bundled Chromium...")
                        browser = p.chromium.launch(headless=True)
                    except Exception:
                        print("🛑 ERROR: Failed to launch any Chromium browser.")
                        print("👉 Please ensure Chrome/Edge is installed or that you bundled a Playwright browser.")
                        time.sleep(10)
                        return
                    
            if browser:
                # Use a new context to avoid sharing cookies/cache between runs
                page = browser.new_context().new_page()
                
                for name in NEWSPAPER_LIST:
                    norm_name = self._normalize_text(name)
                    print(f"\n🔎 Processing: {name}")
                    
                    # Search Frontpages first
                    result = self._search_frontpages(page, norm_name)
                    
                    # If not found, search Zougla
                    if not result: 
                        result = self._search_zougla(page, norm_name)
                    
                    if result: 
                        self.downloaded_images.append(result)
                    else: 
                        print(f"❌ Not found: {name}")

                browser.close()
                self.generate_pdf()
            
        print("\n✨ Process finished.")
        time.sleep(3) # Pause briefly at the end

if __name__ == "__main__":
    bot = NewspaperBot()
    bot.run()