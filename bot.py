import aiohttp, asyncio, warnings, pytz
from datetime import datetime, timedelta
from pytz import timezone
from pyrogram import Client, __version__
from pyrogram.raw.all import layer
from config import Config
from aiohttp import web
from route import web_server
import pyrogram.utils
import pyromod
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
import os
import time


from telegram import Update
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext
import re

TOKEN = "8082722336:AAHZO6Xn1y0al6X23cwiDTZAGVwovoGx2Vk"
user_file_sequences = {}

def start(update: Update, context: CallbackContext):
    update.message.reply_text("Welcome! Use /ssequence to start file sequencing, /esequence to finish, and /cancel to cancel.")

def start_sequence(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    if user_id in user_file_sequences:
        update.message.reply_text("You already have an active sequencing session. Use /esequence to complete it.")
        return
    user_file_sequences[user_id] = []
    update.message.reply_text("File sequencing started. Send documents and videos. Use /esequence to finish.")

def detect_quality(file_name):
    """ Detects video quality from filename """
    quality_order = {"480p": 1, "720p": 2, "1080p": 3}
    match = re.search(r"(480p|720p|1080p)", file_name)
    return quality_order.get(match.group(1), 4) if match else 4  # Default priority = 4

def process_file(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    if user_id not in user_file_sequences:
        update.message.reply_text("Start a sequence first using /ssequence.")
        return
    file = update.message.document or update.message.video
    if file:
        user_file_sequences[user_id].append(file)
        update.message.reply_text("File received and added to the sequence.")
    else:
        update.message.reply_text("Unsupported file type. Send documents or videos only.")

def end_sequence(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    if user_id not in user_file_sequences or not user_file_sequences[user_id]:
        update.message.reply_text("No files to sequence. Use /ssequence first.")
        return
    
    sorted_files = sorted(user_file_sequences[user_id], key=lambda f: (
        detect_quality(f.file_name) if hasattr(f, 'file_name') else 4,  # Sort by quality
        f.file_name if hasattr(f, 'file_name') else ""
    ))

    for file in sorted_files:
        if hasattr(file, 'file_id'):
            if hasattr(file, 'file_name') and file.file_name.endswith(('.mp4', '.mov', '.avi')):
                update.message.reply_video(file.file_id)
            else:
                update.message.reply_document(file.file_id)
    
    del user_file_sequences[user_id]
    update.message.reply_text("File sequencing completed.")

def cancel_sequence(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    if user_id in user_file_sequences:
        del user_file_sequences[user_id]
        update.message.reply_text("File sequencing process canceled.")
    else:
        update.message.reply_text("No active sequencing process to cancel.")

def main():
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("ssequence", start_sequence))
    dp.add_handler(MessageHandler(Filters.document | Filters.video, process_file))
    dp.add_handler(CommandHandler("esequence", end_sequence))
    dp.add_handler(CommandHandler("cancel", cancel_sequence))
    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()


pyrogram.utils.MIN_CHANNEL_ID = -1002258136705

# Setting SUPPORT_CHAT directly here
SUPPORT_CHAT = os.environ.get("SUPPORT_CHAT", "@ravitimepass")

class Bot(Client):

    def __init__(self):
        super().__init__(
            name="codeflixbots",
            api_id=Config.API_ID,
            api_hash=Config.API_HASH,
            bot_token=Config.BOT_TOKEN,
            workers=200,
            plugins={"root": "plugins"},
            sleep_threshold=15,
        )
        # Initialize the bot's start time for uptime calculation
        self.start_time = time.time()

    async def start(self):
        await super().start()
        me = await self.get_me()
        self.mention = me.mention
        self.username = me.username  
        self.uptime = Config.BOT_UPTIME     
        if Config.WEBHOOK:
            app = web.AppRunner(await web_server())
            await app.setup()       
            await web.TCPSite(app, "0.0.0.0", 8080).start()     
        print(f"{me.first_name} Is Started.....✨️")

        # Calculate uptime using timedelta
        uptime_seconds = int(time.time() - self.start_time)
        uptime_string = str(timedelta(seconds=uptime_seconds))

        for chat_id in [Config.LOG_CHANNEL, SUPPORT_CHAT]:
            try:
                curr = datetime.now(timezone("Asia/Kolkata"))
                date = curr.strftime('%d %B, %Y')
                time_str = curr.strftime('%I:%M:%S %p')
                
                # Send the message with the photo
                await self.send_photo(
                    chat_id=chat_id,
                    photo=Config.START_PIC,
                    caption=(
                        "**9Anime Zoro ɪs ʀᴇsᴛᴀʀᴛᴇᴅ ᴀɢᴀɪɴ  !**\n\n"
                        f"ɪ ᴅɪᴅɴ'ᴛ sʟᴇᴘᴛ sɪɴᴄᴇ​: `{uptime_string}`"
                    ),
                    reply_markup=InlineKeyboardMarkup(
                        [[
                            InlineKeyboardButton("ᴜᴘᴅᴀᴛᴇs", url="https://t.me/Blakite_Ravii")
                        ]]
                    )
                )

            except Exception as e:
                print(f"Failed to send message in chat {chat_id}: {e}")

Bot().run()
