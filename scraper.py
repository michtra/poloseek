import inspect
import os
from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


class Scraper:
    def __init__(self, notification_callback=None):
        self.driver = None
        self.notify = notification_callback or print

    def _setup_driver(self):
        chrome_options = Options()
        chrome_options.add_argument("--window-size=1920,1080")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-extensions")
        chrome_options.add_argument("--headless=new")
        home_dir = os.path.expanduser("~")
        chrome_options.add_argument(f"user-data-dir={home_dir}/.config/google-chrome")
        chrome_options.add_argument("--profile-directory=Default")
        self.driver = webdriver.Chrome(options=chrome_options)

    async def _notify_async(self, message):
        try:
            if self.notify:
                if hasattr(self.notify, 'send'):
                    await self.notify.send(message)
                elif inspect.iscoroutinefunction(self.notify):
                    await self.notify(message)
                else:
                    self.notify(message)
        except Exception as e:
            print(f"Notification error: {e}")

    def _login(self):
        self.driver.get("https://myparking.tamu.edu/")

        WebDriverWait(self.driver, 20).until(
            EC.any_of(
                EC.presence_of_element_located((By.ID, "active-permits-heading")),
                EC.element_to_be_clickable((By.ID, "loginButton")),
            )
        )

        if self.driver.find_elements(By.ID, "active-permits-heading"):
            return

        existing_handles = set(self.driver.window_handles)
        self.driver.find_element(By.ID, "loginButton").click()

        def sso_ready(d):
            new = set(d.window_handles) - existing_handles
            if new:
                d.switch_to.window(new.pop())
            return d.find_elements(By.LINK_TEXT, "Texas A&M University NetID")

        WebDriverWait(self.driver, 15).until(sso_ready)
        self.driver.find_element(By.LINK_TEXT, "Texas A&M University NetID").click()

        WebDriverWait(self.driver, 30).until(
            EC.presence_of_element_located((By.ID, "active-permits-heading"))
        )

    def _dismiss_tour(self):
        try:
            close = WebDriverWait(self.driver, 5).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "button.framer-tour-close"))
            )
            close.click()
        except TimeoutException:
            pass

    def _open_manage_vehicles(self):
        self._dismiss_tour()
        btn = WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.XPATH, "//button[contains(., 'Manage Vehicles')]"))
        )
        self.driver.execute_script("arguments[0].click();", btn)

        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.XPATH, "//div[@role='dialog']"))
        )

    def _get_current_user(self):
        try:
            aria = self.driver.find_element(
                By.XPATH, "//button[contains(@aria-label, 'Unlink')]"
            ).get_attribute("aria-label")
            return aria.replace("Unlink ", "").split(" from ")[0].strip()
        except NoSuchElementException:
            raise Exception("No linked vehicle found")

    def _swap_vehicle(self, target_memo):
        WebDriverWait(self.driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, "//button[contains(@aria-label, 'Unlink')]"))
        ).click()

        WebDriverWait(self.driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, f"//button[@aria-label='Link {target_memo} to Polo Rd. Garage']"))
        ).click()

        WebDriverWait(self.driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, "//div[@role='dialog']//button[contains(., 'Save')]"))
        ).click()

        WebDriverWait(self.driver, 15).until(
            EC.invisibility_of_element_located((By.XPATH, "//div[@role='dialog']"))
        )

    async def refresh_current_user(self):
        try:
            self._setup_driver()
            self._login()
            self._open_manage_vehicles()
            current_user = self._get_current_user()
            await self._notify_async(f"Current parking pass owner: {current_user}")
            return current_user
        except Exception as e:
            await self._notify_async(f"Refresh failed: {str(e)}")
            raise
        finally:
            if self.driver:
                self.driver.quit()

    async def update_parking_pass(self, target_memo):
        try:
            self._setup_driver()
            self._login()
            self._open_manage_vehicles()
            self._swap_vehicle(target_memo)
            await self._notify_async(f"Parking pass successfully updated to: {target_memo}")
            return True
        except Exception as e:
            await self._notify_async(f"Update failed: {str(e)}")
            raise
        finally:
            if self.driver:
                self.driver.quit()
