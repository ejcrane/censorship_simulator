import requests
import random
import pycountry
import subprocess
from selenium import webdriver
from selenium.webdriver.firefox.service import Service as Fserv
from selenium.webdriver.chrome.service import Service as Cserv
import time
from platform import system
import os
from threading import Thread
import signal
import socket

API_URL = "https://api.ooni.io/api/v1/measurements"
HOST_IP = "127.0.0.1"
HOST_PORT = "6789"
PROXY = f"{HOST_IP}:{HOST_PORT}"
BROWSER = "firefox"

country = None
website = None
install_path = None
service_path = None
binary_path = None
driver = None
browser_command = None

headers = {
    "User-Agent": "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive"
}

driver_download_urls = {
    "firefox": "https://github.com/mozilla/geckodriver/releases/download/v0.34.0/geckodriver-v0.34.0-linux64.tar.gz",
    "chrome": "https://storage.googleapis.com/chrome-for-testing-public/126.0.6478.182/linux64/chromedriver-linux64.zip"
}

class ClientToProxy(Thread):
    def __init__(self, browser_socket : socket.socket, inet_socket : socket.socket):
        super(ClientToProxy, self).__init__()
        self.browser_socket = browser_socket
        self.inet_socket = inet_socket
        
    def run(self):
        try:
            while True:
                data = self.browser_socket.recv(4096)
                if not data:
                    break

                self.inet_socket.sendall(data)
        except Exception as e:
            print(f"Browser connection error: {e}")
        finally:
            self.browser_socket.close()
            self.inet_socket.close()

class ProxyToWeb(Thread):
    def __init__(self, inet_socket : socket.socket, browser_socket : socket.socket):
        super(ProxyToWeb, self).__init__()
        self.inet_socket = inet_socket
        self.browser_socket = browser_socket

    def run(self):
        try:
            while True:
                data = self.inet_socket.recv(4096)
                if not data:
                    break

                self.browser_socket.sendall(data)
        except Exception as e:
            print(f"Internet connection error: {e}")
        finally:
            self.inet_socket.close()
            self.browser_socket.close()

class CensorProxy(Thread):
    def __init__(self, victim, port):
        super(CensorProxy, self).__init__()
        self.victim = victim
        self.port = port

    def getHostHeaderFromRequest(self, start_data : bytes):
        print(start_data)
        try:
            headers = start_data.split(b"\r\n")
            for header in headers:
                if header.lower().find(b"host:") > -1:
                    return header.decode().split(": ")[1]
        except Exception as e:
            print(f"Couldn't find host header: {e}")
        return None
    
    def parseHostPort(self, host_header):
        if ":" in host_header:
            host, port = host_header.split(":")
            return host, int(port)
        return host_header, 80

    def newClient(self, browser_socket : socket.socket):
        start_data = browser_socket.recv(4096)
        if not start_data:
            print("Error: no data from client")
            browser_socket.close()
            return
        
        #checks if a CONNECT message is sent
        method_line = start_data.split(b"\r\n")[0].decode()
        if method_line.startswith("CONNECT"):
            self.newConnect(browser_socket, method_line)

        host_header = self.getHostHeaderFromRequest(start_data)
        if host_header:
            host, port = self.parseHostPort(host_header)
            print(f"Connecting to {host}:{port}")


            try:
                inet_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                inet_socket.connect((host, port))
                print(f"Connected to {host}:{port}")

                inet_socket.sendall(start_data)

                c2p = ClientToProxy(browser_socket, inet_socket)
                p2i = ProxyToWeb(inet_socket, browser_socket)
                c2p.start()
                p2i.start()

                c2p.join()
                p2i.join()
            except Exception as e:
                print(f"Error connecting to {host}:{port} : {e}")
                browser_socket.close()
        else:
            print("Invalid request error")
            browser_socket.close()

    def newConnect(self, browser_socket, method_line):
        try:
            _, address, _ = method_line.split()
            host, port = address.split(":")
            port = int(port)

            inet_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            inet_socket.connect((host, port))
            print(f"Connected to {host}:{port} for HTTPS")

            browser_socket.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")

            c2p = ClientToProxy(browser_socket, inet_socket)
            p2i = ProxyToWeb(inet_socket, browser_socket)
            c2p.start()
            p2i.start()

            c2p.join()
            p2i.join()
        except Exception as e:
            print(f"Error in CONNECT method handling: {e}")
            browser_socket.close()


    def run(self):
        browser_listen = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        browser_listen.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        browser_listen.bind((self.victim, self.port))
        browser_listen.listen(10)
        print("Proxy waiting for client connection...")

        while True:
            browser_socket, browser_addr = browser_listen.accept()
            print(f"Client connected at {browser_addr}")
            Thread(target=self.newClient, args=(browser_socket,)).start()

            
            

def installDriver():
    download_link = driver_download_urls[BROWSER]
    if not download_link:
        print("Unsupported browser... use Firefox or Chrome")
        exit(2)

    try:
        subprocess.run(["mkdir", "drivers"])
        subprocess.run(["mkdir", "profiles"])
    except:
        pass

    try:
        subprocess.run(["wget", "-P", "drivers/", download_link])
    except:
        print("Error downloading, check internet connection")
        exit(1)

    match BROWSER:
        case "firefox":
            print("Unpacking geckodriver-v0.34.0-linux64.tar.gz")
            subprocess.run(["tar", "-xf", f"{install_path}/drivers/geckodriver-v0.34.0-linux64.tar.gz", "-C", "drivers/"])
            print("Removing geckodriver-v0.34.0-linux64.tar.gz")
            subprocess.run(["rm", f"{install_path}/drivers/geckodriver-v0.34.0-linux64.tar.gz"])
        case "chrome":
            print("Unpacking chromedriver-linux64.zip")
            subprocess.run(["unzip", f"drivers/chromedriver-linux64.zip", "-d", f"{install_path}/drivers/"])
            print("Removing chromedriver-linux64.zip")
            subprocess.run(["rm", f"{install_path}/drivers/chromedriver-linux64.zip"])
        case _:
            print("This is a pretty bad error message to get")
            exit(2)

def loadDriver():
    global service_path
    global binary_path

    match BROWSER:
        case "firefox":
            if os.path.exists(f"{install_path}/drivers/geckodriver"):
                service_path = f"{install_path}/drivers/geckodriver"
            else:
                return False
        case "chrome":
            if os.path.exists(f"{install_path}/drivers/chromedriver-linux64/chromedriver"):
                service_path = f"{install_path}/drivers/chromedriver-linux64/chromedriver"
            else:
                return False
        case _:
            print("Unsupported browser... use Firefox or Chrome")
            exit(2)
    binary_path = getBrowserBinary(browser_command)
    return True

def setup():
    global country
    global website
    global browser_command
    global install_path

    osplatform = system()
    print(f"Platform detected: {osplatform}")

    match osplatform:
        case "Linux":
            if BROWSER == "chrome":
                browser_command = "chromium"
        case _:
            print("CRITICAL: Unsupported OS, use Linux")
            exit(2)

    if browser_command == None:
        browser_command = BROWSER

    try:
        install_path = subprocess.run(["pwd"], stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout.decode().strip()
    except:
        print("CRITICAL: Could not determine working directory")

    if not loadDriver():
        installDriver()

    loadDriver()

    while True:
        inputcountry = input("Select a Country: ")
        try:
            country = pycountry.countries.search_fuzzy(inputcountry)[0]
            break
        except:
            print("Invalid country, please try again")
    print(f"Your selected country is {country.name}")
    website = input("Enter website: ")
    print(f"Your selected website is {website}")

def checkSnap(browser):
    try:
        snapresult = subprocess.run(["snap", "list", browser], stdout=subprocess.PIPE, stdin=subprocess.PIPE)
    except Exception as e:
        print(f"Error while checking snap table: {e}")
        return False
    
    return not snapresult.returncode

def getBrowserBinary(browser):
    is_snap = checkSnap(browser)

    if is_snap:
        print("Snap installation detected")
        return f"/snap/bin/{browser}"

    try:
        rawpath = subprocess.run(["which", browser], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except Exception as e:
        print(f"Couldn't locate path of {browser}: {e}")
        exit(1)

    return rawpath.stdout.decode().strip()

def initializeSelenium():
    global driver
    if BROWSER == "firefox":
        service = Fserv(executable_path=service_path)
    elif BROWSER == "chrome":
        service = Cserv(executable_path=service_path)
    else:
        print("Unsupported browser... use Firefox or Chrome")
        exit(2)

    options = getattr(webdriver, f"{BROWSER.capitalize()}Options")()

    options.binary_location = binary_path

    options.proxy = webdriver.Proxy({
        "httpProxy": PROXY,
        # "ftpProxy": PROXY,
        "sslProxy": PROXY,
        "proxyType": "MANUAL"
    })

    if BROWSER == "firefox":
        options.add_argument("-profile")
        options.add_argument(f"{install_path}/profiles/")

    if BROWSER == "chrome":
        options.add_argument("--remote-debugging-port=9222")

    try:
        driver = getattr(webdriver, BROWSER.capitalize())(service=service, options=options)
        print(f"Booting selenium using {BROWSER}...")
        time.sleep(3)
    except Exception as e:
        print(f"Failed to initialize selenium: {e}")

def terminateSelenium():
    try:
        driver.quit()
        print("Driver terminated")
    except:
        print("No webdriver to terminate!")

def getOONIJSON(url):
    params = {
        "input": website,
        "probe_cc": country.alpha_2,
        "limit": 10
    }
    try:
        response = requests.get(url, params=params, headers=headers)
    except Exception as e:
        print(f"{e} \n Perhaps check internet connection?")
        exit(1)
    data = response.json()
    return data

def checkWebsiteStatus():
    body = getOONIJSON(API_URL)

    some_records = body["results"]

    if len(some_records) == 0:
        return "ERROR"
    
    the_chosen_one = random.choice(some_records)

    while the_chosen_one["failure"]:
        some_records.remove(the_chosen_one)
        if len(some_records) == 0:
            print("all failures!")
            return "ERROR"

        the_chosen_one = random.choice(some_records)

    if the_chosen_one["anomaly"]:
        return the_chosen_one["scores"]["analysis"]["blocking_type"]
    else:
        return "OK"

if __name__ == "__main__":
    setup()

    master_proxy = CensorProxy("127.0.0.1", int(HOST_PORT))
    master_proxy.start()

    initializeSelenium()
    print("running...")
    
    try:
        while True:
            pass
    except KeyboardInterrupt:
        pass

    print("Shutting down...")
    terminateSelenium()
    exit(0)