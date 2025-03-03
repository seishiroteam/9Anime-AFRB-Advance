import os
import re
import time
import shutil
import asyncio
from datetime import datetime
from PIL import Image
from pyrogram import Client, filters
from pyrogram.errors import FloodWait
from pyrogram.types import InputMediaDocument, Message
from hachoir.metadata import extractMetadata
from hachoir.parser import createParser
from plugins.antinsfw import check_anti_nsfw
from helper.utils import progress_for_pyrogram, humanbytes, convert
from helper.database import codeflixbots
from config import Config

renaming_operations = {}
active_sequences = {}

@Client.on_message(filters.command("ssequence") & filters.private)
async def start_sequence(client, message: Message):
    user_id = message.from_user.id
    if user_id in active_sequences:
        await message.reply_text("A sequence is already active! Use /esequence to end it.")
    else:
        active_sequences[user_id] = []  # Start a new sequence
        await message.reply_text("Sequence started! Send your files.")

@Client.on_message(filters.command("esequence") & filters.private)
async def end_sequence(client, message: Message):
    user_id = message.from_user.id
    if user_id not in active_sequences:
        await message.reply_text("No active sequence found!")
        return
    
    file_list = active_sequences.pop(user_id)  # Get the stored files
    
    if not file_list:
        await message.reply_text("No files were sent in this sequence!")
        return

    # Function to extract and correctly parse episode number
    def extract_ep_number(filename):
        match = re.search(r'\[ S\d+-(\d+)\]', filename)  # Extracts episode number from [S1-XX]
        return int(match.group(1)) if match else float('inf')  # Convert episode number to int

    # Function to extract quality and assign priority
    def get_quality_priority(filename):
        quality = extract_quality(filename)
        # Define priority order for qualities
        quality_order = {"480p": 1, "720p": 2, "1080p": 3, "Unknown": 4}
        return quality_order.get(quality, 5)  # Default to 5 if quality is not in the list

    # Sort the file list by quality priority and then by episode number
    file_list.sort(key=lambda file: (get_quality_priority(file.get("file_name", "")), extract_ep_number(file.get("file_name", ""))))

    await message.reply_text(f"Sequence ended! Sending {len(file_list)} files back...")

    for file in file_list:
        await client.send_document(
            message.chat.id, 
            file["file_id"], 
            caption=f"**{file.get('file_name', '')}**", 
        )

# Patterns for Episode Number Extraction
pattern1 = re.compile(r'S(\d+)(?:E|EP)(\d+)')
pattern2 = re.compile(r'S(\d+)\s*(?:E|EP|-\s*EP)(\d+)')
pattern3 = re.compile(r'(?:[([ }]?)')
pattern3_2 = re.compile(r'(?:\s*-\s*(\d+)\s*)')
pattern4 = re.compile(r'S(\d+)[^\d]*(\d+)', re.IGNORECASE)
patternX = re.compile(r'(\d+)')

# Quality Patterns
pattern5 = re.compile(r'\b(?:.*?(\d{3,4}[^\dp]*p).*?|.*?(\d{3,4}p))\b', re.IGNORECASE)
pattern6 = re.compile(r'[([ }]?', re.IGNORECASE)
pattern7 = re.compile(r'[([ }]?', re.IGNORECASE)
pattern8 = re.compile(r'[([ }]?|\bHdRip\b', re.IGNORECASE)
pattern9 = re.compile(r'[([ }]?', re.IGNORECASE)
pattern10 = re.compile(r'[([ }]?', re.IGNORECASE)

def extract_quality(filename):
    # Try Quality Patterns
    match5 = re.search(pattern5, filename)
    if match5:
        quality5 = match5.group(1) or match5.group(2)  # Extracted quality from both patterns
        return quality5

    match6 = re.search(pattern6, filename)
    if match6:
        return "4k"

    match7 = re.search(pattern7, filename)
    if match7:
        return "2k"

    match8 = re.search(pattern8, filename)
    if match8:
        return "HdRip"

    match9 = re.search(pattern9, filename)
    if match9:
        return "4kX264"

    match10 = re.search(pattern10, filename)
    if match10:
        return "4kx265"

    # Return "Unknown" if no pattern matches
    return "Unknown"

def extract_episode_number(filename):     
    # Try Pattern 1
    match = re.search(pattern1, filename)
    if match:
        return match.group(2)  # Extracted episode number
    
    # Try Pattern 2
    match = re.search(pattern2, filename)
    if match:
        return match.group(2)  # Extracted episode number

    # Try Pattern 3
    match = re.search(pattern3, filename)
    if match:
        return match.group(1)  # Extracted episode number

    # Try Pattern 3_2 
    match = re.search(pattern3_2, filename)
    if match:
        return match.group(1)  # Extracted episode number
        
    # Try Pattern 4
    match = re.search(pattern4, filename)
    if match:
        return match.group(2)  # Extracted episode number

    # Try Pattern X
    match = re.search(patternX, filename)
    if match:
        return match.group(1)  # Extracted episode number
        
    # Return None if no pattern matches
    return None

@Client.on_message(filters.private & (filters.document | filters.video | filters.audio))
async def auto_rename_files(client, message):
    user_id = message.from_user.id
    file_id = message.document.file_id if message.document else message.video.file_id if message.video else message.audio.file_id
    file_name = message.document.file_name if message.document else message.video.file_name if message.video else message.audio.file_name

    if user_id in active_sequences:
        # If sequence is active, store the file instead of renaming
        file_info = {
            "file_id": file_id,
            "file_name": file_name if file_name else "Unknown"
        }
        active_sequences[user_id].append(file_info)
        await message.reply_text("File received in sequence...")
        return  # Do not process auto-rename when in sequence mode

    # Auto-Rename Logic (Runs only when not in sequence mode)
    format_template = await codeflixbots.get_format_template(user_id)
    media_preference = await codeflixbots.get_media_preference(user_id)

    if not format_template:
        return await message.reply_text("Please Set An Auto Rename Format First Using /autorename")

    if message.document:
        file_id = message.document.file_id
        file_name = message.document.file_name
        media_type = media_preference or "document"
    elif message.video:
        file_id = message.video.file_id
        file_name = f"{message.video.file_name}.mp4"
        media_type = media_preference or "video"
    elif message.audio:
        file_id = message.audio.file_id
        file_name = f"{message.audio.file_name}.mp3"
        media_type = media_preference or "audio"
    else:
        return await message.reply_text("Unsupported File Type")

    # Anti-NSFW check
    if await check_anti_nsfw(file_name, message):
        return await message.reply_text("NSFW content detected. File upload rejected.")

    if file_id in renaming_operations:
        elapsed_time = (datetime.now() - renaming_operations[file_id]).seconds
        if elapsed_time < 10:
            return

    renaming_operations[file_id] = datetime.now()

    episode_number = extract_episode_number(file_name)
    if episode_number:
        placeholders = ["episode", "Episode", "EPISODE", "{episode}"]
        for placeholder in placeholders:
            format_template = format_template.replace(placeholder, str(episode_number), 1)

        # Add extracted qualities to the format template
        quality_placeholders = ["quality", "Quality", "QUALITY", "{quality}"]
        for quality_placeholder in quality_placeholders:
            if quality_placeholder in format_template:
                extracted_qualities = extract_quality(file_name)
                if extracted_qualities == "Unknown":
                    await message.reply_text("**__I Was Not Able To Extract The Quality Properly. Renaming As 'Unknown'...__**")
                    del renaming_operations[file_id]
                    return  # Exit the handler if quality extraction fails
                
                format_template = format_template.replace(quality_placeholder, "".join(extracted_qualities))

    _, file_extension = os.path.splitext(file_name)
    renamed_file_name = f"{format_template}{file_extension}"
    renamed_file_path = f"downloads/{renamed_file_name}"
    metadata_file_path = f"Metadata/{renamed_file_name}"
    os.makedirs(os.path.dirname(renamed_file_path), exist_ok=True)
    os.makedirs(os.path.dirname(metadata_file_path), exist_ok=True)

    download_msg = await message.reply_text("**__Downloading...__**")

    try:
        path = await client.download_media(
            message,
            file_name=renamed_file_path,
            progress=progress_for_pyrogram,
            progress_args=("Download Started...", download_msg, time.time()),
        )
    except Exception as e:
        del renaming_operations[file_id]
        return await download_msg.edit(f"**Download Error:** {e}")

    await download_msg.edit("**__Renaming and Adding Metadata...__**")

    try:
        # Rename the file
        os.rename(path, renamed_file_path)
        path = renamed_file_path

        # Prepare metadata command
        ffmpeg_cmd = shutil.which('ffmpeg')
        metadata_command = [
            ffmpeg_cmd,
            '-i', path,
            '-metadata', f'title={await codeflixbots.get_title(user_id)}',
            '-metadata', f'artist={await codeflixbots.get_artist(user_id)}',
            '-metadata', f'author={await codeflixbots.get_author(user_id)}',
            '-metadata:s:v', f'title={await codeflixbots.get_video(user_id)}',
            '-metadata:s:a', f'title={await codeflixbots.get_audio(user_id)}',
            '-metadata:s:s', f'title={await codeflixbots.get_subtitle(user_id)}',
            '-metadata', f'encoded_by={await codeflixbots.get_encoded_by(user_id)}',
            '-metadata', f'custom_tag={await codeflixbots.get_custom_tag(user_id)}',
            '-map', '0',
            '-c', 'copy',
            '-loglevel', 'error',
            metadata_file_path
        ]

        # Execute the metadata command
        process = await asyncio.create_subprocess_exec(
            *metadata_command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            error_message = stderr.decode()
            await download_msg.edit(f"**Metadata Error:**\n{error_message}")
            return

        # Use the new metadata file path for the upload
        path = metadata_file_path

        # Upload the file
        upload_msg = await download_msg.edit("**__Uploading...__**")

        ph_path = None
        c_caption = await codeflixbots.get_caption(message.chat.id)
        c_thumb = await codeflixbots.get_thumbnail(message.chat.id)

        caption = (
            c_caption.format(
                filename=renamed_file_name,
                filesize=humanbytes(message.document.file_size),
                duration=convert(0),
            )
            if c_caption
            else f"**{renamed_file_name}**"
        )

        if c_thumb:
            ph_path = await client.download_media(c_thumb)
        elif media_type == "video" and message.video.thumbs:
            ph_path = await client.download_media(message.video.thumbs[0].file_id)

        if ph_path:
            img = Image.open(ph_path).convert("RGB")
            img = img.resize((320, 320))
            img.save(ph_path, "JPEG")

        try:
            if media_type == "document":
                await client.send_document(
                    message.chat.id,
                    document=path,
                    thumb=ph_path,
                    caption=caption,
                    progress=progress_for_pyrogram,
                    progress_args=("Upload Started...", upload_msg, time.time()),
                )
            elif media_type == "video":
                await client.send_video(
                    message.chat.id,
                    video=path,
                    caption=caption,
                    thumb=ph_path,
                    duration=0,
                    progress=progress_for_pyrogram,
                    progress_args=("Upload Started...", upload_msg, time.time()),
                )
            elif media_type == "audio":
                await client.send_audio(
                    message.chat.id,
                    audio=path,
                    caption=caption,
                    thumb=ph_path,
                    duration=0,
                    progress=progress_for_pyrogram,
                    progress_args=("Upload Started...", upload_msg, time.time()),
                )
        except Exception as e:
            os.remove(renamed_file_path)
            if ph_path:
                os.remove(ph_path)
            return await upload_msg.edit(f"Error: {e}")

        await download_msg.delete() 
        os.remove(path)
        if ph_path:
            os.remove(ph_path)

    finally:
        # Clean up
        if os.path.exists(renamed_file_path):
            os.remove(renamed_file_path)
        if os.path.exists(metadata_file_path):
            os.remove(metadata_file_path)
        if ph_path and os.path.exists(ph_path):
            os.remove(ph_path)
        del renaming_operations[file_id]
