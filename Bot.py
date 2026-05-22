import asyncio
import sqlite3
import hashlib
from datetime import datetime
from collections import defaultdict
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes

TOKEN = "8057027369:AAHYNKzmODeDrKVfESjAYFe141wf4TewV2o"
SOURCE_CHANNEL_ID = -1003885849601
ARCHIVE_CHANNEL_ID = -1003988667734

conn = sqlite3.connect('archive.db', check_same_thread=False)
cursor = conn.cursor()
cursor.execute('''
    CREATE TABLE IF NOT EXISTS messages (
        source_id INTEGER PRIMARY KEY,
        archive_ids TEXT,
        text_hash TEXT,
        media_group_id TEXT,
        edit_count INTEGER DEFAULT 0
    )
''')
conn.commit()

pending_albums = defaultdict(dict)

def get_text_hash(text):
    return hashlib.md5((text or "").encode()).hexdigest()

async def copy_album(bot, messages, archive_chat_id, source_msg_id):
    media_group = []
    caption_added = False
    for msg in sorted(messages, key=lambda x: x.message_id):
        if msg.photo:
            if not caption_added:
                media_group.append({'type': 'photo', 'media': msg.photo[-1].file_id, 'caption': msg.caption or ""})
                caption_added = True
            else:
                media_group.append({'type': 'photo', 'media': msg.photo[-1].file_id})
        elif msg.video:
            if not caption_added:
                media_group.append({'type': 'video', 'media': msg.video.file_id, 'caption': msg.caption or "", 'supports_streaming': True})
                caption_added = True
            else:
                media_group.append({'type': 'video', 'media': msg.video.file_id, 'supports_streaming': True})
    if media_group:
        try:
            result = await bot.send_media_group(chat_id=archive_chat_id, media=media_group)
            archive_ids = [str(msg.message_id) for msg in result]
            cursor.execute('INSERT OR REPLACE INTO messages (source_id, archive_ids, text_hash, media_group_id, edit_count) VALUES (?, ?, ?, ?, 0)', 
                          (source_msg_id, ",".join(archive_ids), get_text_hash(messages[0].caption or ""), messages[0].media_group_id))
            conn.commit()
            print(f"📸 Альбом скопирован: {len(media_group)} медиа")
        except Exception as e:
            print(f"Ошибка альбома: {e}")

async def copy_single_message(bot, message, archive_chat_id):
    try:
        if message.photo:
            await bot.send_photo(chat_id=archive_chat_id, photo=message.photo[-1].file_id, caption=message.caption)
        elif message.video:
            await bot.send_video(chat_id=archive_chat_id, video=message.video.file_id, caption=message.caption, supports_streaming=True)
        elif message.document:
            await bot.send_document(chat_id=archive_chat_id, document=message.document.file_id, caption=message.caption)
        elif message.text:
            await bot.send_message(chat_id=archive_chat_id, text=message.text)
        else:
            await bot.copy_message(chat_id=archive_chat_id, from_chat_id=message.chat_id, message_id=message.message_id)
        cursor.execute('INSERT OR REPLACE INTO messages (source_id, text_hash, edit_count) VALUES (?, ?, 0)',
                      (message.message_id, get_text_hash(message.caption or message.text or "")))
        conn.commit()
        print(f"✅ Пост {message.message_id} скопирован")
    except Exception as e:
        print(f"Ошибка: {e}")

async def handle_new_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.channel_post
    if not message or message.chat.id != SOURCE_CHANNEL_ID:
        return
    cursor.execute('SELECT source_id FROM messages WHERE source_id = ?', (message.message_id,))
    if cursor.fetchone():
        return
    if message.media_group_id:
        group_key = f"{SOURCE_CHANNEL_ID}_{message.media_group_id}"
        pending_albums[group_key][message.message_id] = message
        await asyncio.sleep(2)
        if pending_albums[group_key]:
            await copy_album(context.bot, list(pending_albums[group_key].values()), ARCHIVE_CHANNEL_ID, message.message_id)
            del pending_albums[group_key]
    else:
        await copy_single_message(context.bot, message, ARCHIVE_CHANNEL_ID)

async def handle_edit_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.edited_channel_post
    if not message or message.chat.id != SOURCE_CHANNEL_ID:
        return
    cursor.execute('SELECT edit_count FROM messages WHERE source_id = ?', (message.message_id,))
    row = cursor.fetchone()
    if row:
        edit_mark = f"\n\n🔄 Изменено: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        new_caption = (message.caption or message.text or "") + edit_mark
        try:
            await context.bot.edit_message_caption(chat_id=ARCHIVE_CHANNEL_ID, message_id=message.message_id, caption=new_caption)
            cursor.execute('UPDATE messages SET edit_count = ? WHERE source_id = ?', (row[0] + 1, message.message_id))
            conn.commit()
            print(f"✏️ Обновлен пост {message.message_id}")
        except:
            pass

def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(MessageHandler(filters.Chat(chat_id=SOURCE_CHANNEL_ID) & filters.ChannelPost, handle_new_message))
    app.add_handler(MessageHandler(filters.Chat(chat_id=SOURCE_CHANNEL_ID) & filters.UpdateType.EDITED_CHANNEL_POST, handle_edit_message))
    print("🚀 Бот-архиватор запущен")
    print(f"📡 Исходный канал ID: {SOURCE_CHANNEL_ID}")
    print(f"💾 Архивный канал ID: {ARCHIVE_CHANNEL_ID}")
    print("👀 Слежу за новыми постами и изменениями...")
    app.run_polling()

if __name__ == "__main__":
    main()
