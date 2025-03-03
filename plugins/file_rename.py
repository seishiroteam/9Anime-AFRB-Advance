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

# Global variables for sequences
active_sequences = {}

@Client.on_message(filters.command("ssequence") & filters.private)
async def start_sequence(client, message: Message):
    user_id = message.from_user.id
    if user_id in active_sequences:
        await message.reply_text("A sequence is already active! Use /esequence to end it.")
        return
    active_sequences[user_id] = []  # Start a new sequence
    await message.reply_text("Sequence started! Send your files.")

@Client.on_message(filters.command("esequence") & filters.private)
async def end_sequence(client, message: Message):
    user_id = message.from_user.id
    if user_id not in active_sequences or not active_sequences[user_id]:
        await message.reply_text("No active sequence found!")
        return

    file_list = active_sequences.pop(user_id)  # Get the stored files

    if not file_list:
        await message.reply_text("No files were sent in this sequence!")
        return

    # Function to extract episode number
    def extract_episode_number(filename):
        patterns = [
            re.compile(r'S(\d+)(?:E|EP)(\d+)'),  # S01E01 or S01EP01
            re.compile(r'S(\d+)\s*(?:E|EP|-\s*EP)(\d+)'),  # S01 E01 or S01 - EP01
            re.compile(r'(?:[([ }]?)'),
            re.compile(r'(?:\s*-\s*(\d+)\s*)'),  # -01 or - 01
            re.compile(r'S(\d+)[^\d]*(\d+)', re.IGNORECASE),  # S01-01 or S01 01
            re.compile(r'(\d+)')  # Fallback: Any number
        ]
        for pattern in patterns:
            match = re.search(pattern, filename)
            if match:
                return int(match.group(2)) if len(match.groups()) > 1 else int(match.group(1))
        return float('inf')  # Default if no match found

    # Function to extract quality and assign priority
    def get_quality_priority(filename):
        quality = extract_quality(filename)
        quality_order = {"480p": 1, "720p": 2, "1080p": 3, "Unknown": 4}
        return quality_order.get(quality, 5)  # Default to 5 if quality is not in the list

    # Sort the file list by quality priority and then by episode number
    file_list.sort(key=lambda file: (
        get_quality_priority(file.get("file_name", "")),  # Sort by quality
        extract_episode_number(file.get("file_name", ""))  # Sort by episode number
    ))

    await message.reply_text(f"Sequence ended! Sending {len(file_list)} files back...")

    for file in file_list:
        await client.send_document(
            message.chat.id,
            file["file_id"],
            caption=f"**{file.get('file_name', '')}**",
        )

@Client.on_message(filters.command("cancel") & filters.private)
async def cancel_sequence(client, message: Message):
    user_id = message.from_user.id
    if user_id in active_sequences:
        del active_sequences[user_id]
        await message.reply_text("File sequencing process canceled.")
    else:
        await message.reply_text("No active sequencing process to cancel.")

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

    # Extract episode number and quality
    episode_number = extract_episode_number(file_name)
    extracted_quality = extract_quality(file_name)

    # Replace placeholders in format template
    if episode_number:
        placeholders = ["episode", "Episode", "EPISODE", "{episode}"]
        for placeholder in placeholders:
            format_template = format_template.replace(placeholder, str(episode_number), 1)

    if extracted_quality != "Unknown":
        quality_placeholders = ["quality", "Quality", "QUALITY", "{quality}"]
        for placeholder in quality_placeholders:
            if placeholder in format_template:
                format_template = format_template.replace(placeholder, extracted_quality)

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

def extract_quality(filename):
    # Patterns for quality extraction
    patterns = [
        re.compile(r'\b(?:.*?(\d{3,4}[^\dp]*p).*?|.*?(\d{3,4}p))\b', re.IGNORECASE),  # 720p, 1080p, etc.
        re.compile(r'\b(?:4k|2k|HDRip|4kX264|4kx265)\b', re.IGNORECASE)  # Special qualities
    ]
    for pattern in patterns:
        match = re.search(pattern, filename)
        if match:
            return match.group(1) or match.group(2)  # Extracted quality
    return "Unknown"  # Default if no match found

def extract_episode_number(filename):
    patterns = [
        re.compile(r'S(\d+)(?:E|EP)(\d+)'),  # S01E01 or S01EP01
        re.compile(r'S(\d+)\s*(?:E|EP|-\s*EP)(\d+)'),  # S01 E01 or S01 - EP01
        re.compile(r'(?:[([ }]?)'),
        re.compile(r'(?:\s*-\s*(\d+)\s*)'),  # -01 or - 01
        re.compile(r'S(\d+)[^\d]*(\d+)', re.IGNORECASE),  # S01-01 or S01 01
        re.compile(r'(\d+)')  # Fallback: Any number
    ]
    for pattern in patterns:
        match = re.search(pattern, filename)
        if match:
            return int(match.group(2)) if len(match.groups()) > 1 else int(match.group(1))
    return None  # Return None if no match found
