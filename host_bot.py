#!/usr/bin/env python3
import time
import subprocess
import sys
import os
import logging

logging.basicConfig(
    filename="bot_runner.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

BOT_SCRIPT = os.path.join(os.path.dirname(__file__), "bot.py")

def run_bot():
    logging.info("Starting ZenQuant Auto-Bot host daemon...")
    print("🤖 ZenQuant Auto-Bot hosting service started.")
    
    while True:
        try:
            logging.info("Launching bot.py process...")
            p = subprocess.Popen([sys.executable, BOT_SCRIPT])
            p.wait()
            ret_code = p.returncode
            logging.warning(f"bot.py process exited with code {ret_code}.")
            print(f"⚠️ bot.py exited with code {ret_code}. Restarting in 5 seconds...")
        except KeyboardInterrupt:
            logging.info("Hosting service stopped manually by keyboard interrupt.")
            print("\nStopping hosting service.")
            break
        except Exception as e:
            logging.error(f"Unexpected error in host daemon: {e}")
            print(f"Error: {e}")
        
        time.sleep(5)

if __name__ == "__main__":
    run_bot()
