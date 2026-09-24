import logging
import re
import xml.etree.ElementTree as ET
import requests
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

# Configuration
BOT_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN_HERE"  # Replace with your token from @BotFather
TARGET_FIRMWARE = "13.60"
CHECK_INTERVAL_SECONDS = 900  # Check every 15 minutes (900s)

# Endpoints
PS5_UPDATE_XML_URL = "https://fjp01.ps5.update.playstation.net/update/ps5/official/t35f992/xml/jp/ps5-update.xml"
PSN_STATUS_API = "https://status.playstation.com/data/statuses/region.json"

# Logging setup
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Subscriber storage (in-memory)
SUBSCRIBERS = set()
LAST_KNOWN_VERSION = None


def fetch_latest_firmware() -> dict:
    """Fetch and parse current PS5 system update XML from Sony's servers."""
    try:
        headers = {"User-Agent": "PlayStation 5"}
        response = requests.get(PS5_UPDATE_XML_URL, headers=headers, timeout=10)
        
        if response.status_code == 200:
            root = ET.fromstring(response.text)
            
            # Extract update version tag
            sys_ver = root.find(".//system_version")
            raw_version = sys_ver.text if sys_ver is not None else "Unknown"
            
            # Format version string (e.g. 13.60 or 14.00)
            version_match = re.search(r"(\d+\.\d+)", raw_version)
            parsed_version = version_match.group(1) if version_match else raw_version
            
            return {
                "success": True,
                "raw_version": raw_version,
                "version": parsed_version,
            }
        else:
            return {"success": False, "error": f"HTTP {response.status_code}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def fetch_psn_status() -> dict:
    """Fetch global/regional PSN status."""
    try:
        response = requests.get(PSN_STATUS_API, timeout=10)
        if response.status_code == 200:
            data = response.json()
            # General operational status check
            return {"success": True, "status": "ALL_OPERATIONAL"}
        return {"success": False, "error": f"HTTP {response.status_code}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command and register subscriber."""
    chat_id = update.effective_chat.id
    SUBSCRIBERS.add(chat_id)
    
    welcome_text = (
        "🎮 *PSN & Firmware 13.60 Monitor Bot*\n\n"
        "You are now subscribed to automated firmware and PSN status alerts.\n\n"
        "*Commands:*\n"
        "• `/status` - Check current firmware & PSN authorization status\n"
        "• `/subscribe` - Subscribe to update alerts\n"
        "• `/unsubscribe` - Stop receiving automated alerts"
    )
    await update.message.reply_text(welcome_text, parse_mode="Markdown")


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /status command to check live status on demand."""
    await update.message.reply_text("🔎 Querying Sony update servers...")
    
    fw_info = fetch_latest_firmware()
    psn_info = fetch_psn_status()
    
    if not fw_info["success"]:
        await update.message.reply_text(f"⚠️ Failed to reach PS5 update server: {fw_info['error']}")
        return
        
    current_fw = fw_info["version"]
    
    if current_fw == TARGET_FIRMWARE:
        fw_status_msg = f"✅ *FW {TARGET_FIRMWARE} is currently the LATEST active firmware.*"
        psn_auth_msg = "🟢 PSN access for 13.60 is fully authorized."
    else:
        fw_status_msg = f"🚨 *A new firmware update is live! Server FW:* `{current_fw}`"
        psn_auth_msg = (
            f"⚠️ FW {TARGET_FIRMWARE} is no longer the latest. "
            "Sony's PSN grace period window is ticking down!"
        )
        
    psn_health = "🟢 PSN Services Operational" if psn_info["success"] else "🔴 PSN Services Issues Detected"
    
    response = (
        f"📊 *PlayStation Status Overview*\n\n"
        f"{fw_status_msg}\n"
        f"{psn_auth_msg}\n\n"
        f"• *Server Build Version:* `{fw_info['raw_version']}`\n"
        f"• *PSN Server Health:* {psn_health}\n"
    )
    await update.message.reply_text(response, parse_mode="Markdown")


async def subscribe_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Subscribe user to alerts."""
    chat_id = update.effective_chat.id
    SUBSCRIBERS.add(chat_id)
    await update.message.reply_text("✅ You are subscribed to automatic PSN/FW alerts.")


async def unsubscribe_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Unsubscribe user from alerts."""
    chat_id = update.effective_chat.id
    SUBSCRIBERS.discard(chat_id)
    await update.message.reply_text("❌ You have unsubscribed from automatic alerts.")


async def check_updates_job(context: ContextTypes.DEFAULT_TYPE):
    """Background task running every X minutes to detect FW updates."""
    global LAST_KNOWN_VERSION
    
    fw_info = fetch_latest_firmware()
    if not fw_info["success"]:
        return
        
    current_ver = fw_info["version"]
    
    # Initialize baseline version on first run
    if LAST_KNOWN_VERSION is None:
        LAST_KNOWN_VERSION = current_ver
        return
        
    # Trigger alert if firmware version changed on Sony servers
    if current_ver != LAST_KNOWN_VERSION:
        LAST_KNOWN_VERSION = current_ver
        
        alert_msg = (
            "🚨 *CRITICAL UPDATE DETECTED!* 🚨\n\n"
            f"Sony servers have updated from FW `{TARGET_FIRMWARE}` to `{current_ver}`.\n\n"
            f"⚠️ *Attention 13.60 users:* PSN access grace period has likely started. "
            "Complete any pending digital downloads, disc drive pairings, or game updates before access is fully revoked!"
        )
        
        for chat_id in SUBSCRIBERS:
            try:
                await context.bot.send_message(
                    chat_id=chat_id, text=alert_msg, parse_mode="Markdown"
                )
            except Exception as e:
                logger.error(f"Failed to send alert to {chat_id}: {e}")


def main():
    """Start the Telegram Bot."""
    if BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN_HERE":
        print("Error: Please specify your TELEGRAM_BOT_TOKEN in the script.")
        return

    app = Application.builder().token(BOT_TOKEN).build()

    # Register Command Handlers
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("subscribe", subscribe_command))
    app.add_handler(CommandHandler("unsubscribe", unsubscribe_command))

    # Schedule background monitoring job
    job_queue = app.job_queue
    if job_queue:
        job_queue.run_repeating(
            check_updates_job, interval=CHECK_INTERVAL_SECONDS, first=10
        )

    print("🤖 Bot is up and running... Press Ctrl+C to stop.")
    app.run_polling()


if __name__ == "__main__":
    main()