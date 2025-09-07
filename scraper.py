import os
import time
import traceback
from selenium import webdriver
from selenium.common.exceptions import TimeoutException, NoSuchElementException, WebDriverException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


class Scraper:
    def __init__(self, notification_callback=None):
        """Initialize scraper automation
        
        Args:
            notification_callback: Function to call for notifications (channel.send, etc.)
        """
        self.driver = None
        self.notify = notification_callback or print
        
    def _setup_driver(self):
        """Configure Chrome WebDriver with default profile"""
        chrome_options = Options()
        chrome_options.add_argument("--window-size=1920,1080")
        chrome_options.add_argument("--start-maximized")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-extensions")
        chrome_options.add_argument("--headless=new")
        home_dir = os.path.expanduser("~")
        chrome_options.add_argument(f"user-data-dir={home_dir}/.config/google-chrome")
        chrome_options.add_argument("--profile-directory=Default")  # need this line
        
        self.driver = webdriver.Chrome(options=chrome_options)
        return self.driver

    async def _notify_async(self, message):
        """Handle async notifications"""
        try:
            if self.notify:
                if hasattr(self.notify, '__call__'):
                    if hasattr(self.notify, 'send'):
                        await self.notify.send(message)
                    else:
                        self.notify(message)
        except Exception as e:
            print(f"Notification error: {e}")
    
    def _login(self):
        """Navigate to transport site and complete login process"""
        try:
            self.driver.get("https://transport2.tamu.edu/Account/Login.aspx?ReturnUrl=%2faccount")
            self.driver.implicitly_wait(5)
            
            # click login button
            login_button = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, "/html/body/div[2]/form/div[3]/div/div[3]/div[2]/div/p[2]/input"))
            )
            login_button.click()
            
            # wait for page load and click account link
            account_link = WebDriverWait(self.driver, 15).until(
                EC.element_to_be_clickable((By.XPATH, "/html/body/main/div/div/div/a[1]"))
            )
            account_link.click()
            
            # wait for final page load
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.XPATH, "/html/body/div[2]/form/div[4]/div/div[3]/div[2]/div/div/div[1]/div/table/tbody/tr/td/div/div[2]/div[1]"))
            )
            
            return True
            
        except TimeoutException:
            raise Exception("Login timeout - page elements not found")
        except Exception as e:
            raise Exception(f"Login failed: {str(e)}")
    
    def _get_current_user(self):
        """Get currently active user from parking pass display"""
        try:
            current_user_element = self.driver.find_element(
                By.XPATH, 
                "/html/body/div[2]/form/div[4]/div/div[3]/div[2]/div/div/div[1]/div/table/tbody/tr/td/div/div[2]/div[1]/table/tbody/tr/td/div/div/div[2]/span"
            )
            return current_user_element.text.strip()
        except NoSuchElementException:
            raise Exception("Current user element not found")
    
    def _navigate_to_update_plate(self):
        """Click update plate link and wait for page load"""
        try:
            update_link = self.driver.find_element(
                By.XPATH, 
                "/html/body/div[2]/form/div[4]/div/div[3]/div[2]/div/div/div[1]/div/table/tbody/tr/td/div/div[2]/div[1]/a"
            )
            update_link.click()
            
            # wait for plate selection page
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.XPATH, "/html/body/div[2]/form/div[4]/div/div/div[2]/div[1]/div[2]/div/div[2]/div/table/tbody"))
            )
            
        except TimeoutException:
            raise Exception("Update plate page load timeout")
        except NoSuchElementException:
            raise Exception("Update plate link not found")
    
    def _process_plate_selection(self, target_memo):
        """Uncheck current selection and check target user's plate"""
        try:
            # get all table rows
            table_body = self.driver.find_element(
                By.XPATH, 
                "/html/body/div[2]/form/div[4]/div/div/div[2]/div[1]/div[2]/div/div[2]/div/table/tbody"
            )
            rows = table_body.find_elements(By.TAG_NAME, "tr")
            
            target_found = False
            current_unchecked = False
            
            for i, row in enumerate(rows, 1):
                # get checkbox
                checkbox_xpath = f"/html/body/div[2]/form/div[4]/div/div/div[2]/div[1]/div[2]/div/div[2]/div/table/tbody/tr[{i}]/td[1]/input"
                checkbox = row.find_element(By.XPATH, f"td[1]/input")
                
                # get memo
                memo_xpath = f"/html/body/div[2]/form/div[4]/div/div/div[2]/div[1]/div[2]/div/div[2]/div/table/tbody/tr[{i}]/td[3]/span[2]"
                memo_element = row.find_element(By.XPATH, f"td[3]/span[2]")
                memo_text = memo_element.text.strip()
                
                # uncheck if currently checked
                if checkbox.get_attribute("checked"):
                    checkbox.click()
                    current_unchecked = True
                
                # check if this is our target memo
                if memo_text == target_memo:
                    if not checkbox.is_selected():
                        checkbox.click()
                    target_found = True
            
            if not current_unchecked:
                raise Exception("No currently checked item found to uncheck")
            
            if not target_found:
                raise Exception(f"Target memo '{target_memo}' not found in plate list")
                
            return True
            
        except Exception as e:
            raise Exception(f"Plate selection processing failed: {str(e)}")
    
    def _submit_changes(self):
        """Submit the plate update form"""
        try:
            submit_button = self.driver.find_element(
                By.XPATH, 
                "/html/body/div[2]/form/div[4]/div/div/div[2]/div[1]/div[2]/div/input[1]"
            )
            submit_button.click()
            
            # wait for page to process
            time.sleep(3)
            
        except NoSuchElementException:
            raise Exception("Submit button not found")
    
    async def refresh_current_user(self):
        """Get current parking pass owner from transport site"""
        try:
            await self._notify_async("Starting parking pass refresh...")
            
            self._setup_driver()
            await self._notify_async("Browser initialized, logging in...")
            
            self._login()
            await self._notify_async("Login successful, retrieving current user...")
            
            current_user = self._get_current_user()
            await self._notify_async(f"Current parking pass owner: {current_user}")
            
            return current_user
            
        except Exception as e:
            await self._notify_async(f"Refresh failed: {str(e)}")
            raise e
        finally:
            if self.driver:
                self.driver.quit()
    
    async def update_parking_pass(self, target_memo):
        """Update parking pass to user with specified memo"""
        try:
            await self._notify_async(f"Starting parking pass update to: {target_memo}")
            
            self._setup_driver()
            await self._notify_async("Browser initialized, logging in...")
            
            self._login()
            await self._notify_async("Login successful, navigating to update page...")
            
            self._navigate_to_update_plate()
            await self._notify_async("Update page loaded, processing plate selection...")
            
            self._process_plate_selection(target_memo)
            await self._notify_async(f"Plate selection updated, submitting changes...")
            
            self._submit_changes()
            await self._notify_async(f"Parking pass successfully updated to: {target_memo}")
            
            return True
            
        except Exception as e:
            await self._notify_async(f"Update failed: {str(e)}")
            raise e
        finally:
            if self.driver:
                self.driver.quit()
