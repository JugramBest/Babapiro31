import telebot
import os
import sqlite3
from collections import deque
import threading
import time
import re
import subprocess
from datetime import datetime, timedelta

# Token, Admin ID ve Log Kanal ID'si
TOKEN = "8111922247:AAGPP46hAv9nJ7x1EbbkcihUTNePbYInmik"
ADMIN_ID = 7548004442
LOG_CHANNEL_ID = -1002436272904

bot = telebot.TeleBot(TOKEN)

# Queue to manage log requests
log_queue = deque()
processing_lock = threading.Lock()

# Database setup
DB_FILE = 'bot_data.db'

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS authorized_users (
            user_id INTEGER PRIMARY KEY
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS vip_status (
            user_id INTEGER PRIMARY KEY,
            end_time TEXT,
            request_count INTEGER
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_requests (
            user_id INTEGER,
            request_time REAL
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS log_queue (
            user_id INTEGER,
            site TEXT,
            queue_position INTEGER
        )
    ''')
    conn.commit()
    conn.close()

def add_authorized_user(user_id):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('INSERT OR IGNORE INTO authorized_users (user_id) VALUES (?)', (user_id,))
    conn.commit()
    conn.close()

def is_authorized_user(user_id):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('SELECT 1 FROM authorized_users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result is not None

def add_vip_status(user_id, end_time, request_count=0):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO vip_status (user_id, end_time, request_count)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET end_time=excluded.end_time, request_count=excluded.request_count
    ''', (user_id, end_time.isoformat(), request_count))
    conn.commit()
    conn.close()

def get_vip_status(user_id):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('SELECT end_time, request_count FROM vip_status WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    conn.close()
    if result:
        return {"end_time": datetime.fromisoformat(result[0]), "request_count": result[1]}
    else:
        return None

def update_vip_request_count(user_id, request_count):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('UPDATE vip_status SET request_count = ? WHERE user_id = ?', (request_count, user_id))
    conn.commit()
    conn.close()

def add_user_request(user_id, request_time):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('INSERT INTO user_requests (user_id, request_time) VALUES (?, ?)', (user_id, request_time))
    conn.commit()
    conn.close()

def get_recent_user_requests(user_id, limit=3):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT request_time FROM user_requests 
        WHERE user_id = ? 
        ORDER BY request_time DESC 
        LIMIT ?
    ''', (user_id, limit))
    result = cursor.fetchall()
    conn.close()
    return [r[0] for r in result]

def add_log_queue(user_id, site, queue_position):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('INSERT INTO log_queue (user_id, site, queue_position) VALUES (?, ?, ?)', (user_id, site, queue_position))
    conn.commit()
    conn.close()

def remove_log_queue(user_id, site, queue_position):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('DELETE FROM log_queue WHERE user_id = ? AND site = ? AND queue_position = ?', (user_id, site, queue_position))
    conn.commit()
    conn.close()

def get_log_queue():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('SELECT user_id, site, queue_position FROM log_queue ORDER BY queue_position')
    result = cursor.fetchall()
    conn.close()
    return result

def read_viplog_file():
    try:
        with open('ArselVipLog.txt', 'r', encoding='utf-8') as file:
            return file.readlines()
    except FileNotFoundError:
        return None
    except Exception as e:
        raise e

def search_site_in_viplog(site):
    lines = read_viplog_file()
    if lines is None:
        return None, "ArselVipLog.txt dosyası bulunamadı."
    
    matched_lines = [line for line in lines if site in line]
    return matched_lines, None

def save_to_file(filename, data):
    with open(filename, 'w', encoding='utf-8') as file:
        file.writelines(data)

def file_size_within_limit(filepath):
    return os.path.getsize(filepath) <= MAX_FILE_SIZE

def sanitize_filename(filename):
    return re.sub(r'[^a-zA-Z0-9_\-\.]', '_', filename)

def log_to_channel(message):
    bot.send_message(LOG_CHANNEL_ID, message)

def ping_site(site):
    try:
        output = subprocess.check_output(['ping', '-c', '4', site], universal_newlines=True)
        return output
    except subprocess.CalledProcessError as e:
        return f"Ping failed: {e.output}"

def process_queue():
    while True:
        queue = get_log_queue()
        if queue:
            with processing_lock:
                user_id, site, queue_position = queue[0]
                bot.send_message(user_id, f"{queue_position}. sıradasınız. İşleminiz başlıyor...")
                log_to_channel(f"{user_id} kullanıcısının {queue_position}. sıradaki isteği işleniyor.")
                try:
                    matched_lines, error = search_site_in_viplog(site)
                    if error:
                        bot.send_message(user_id, error)
                        log_to_channel(f"Error for {user_id}: {error}")
                        continue

                    count = len(matched_lines)
                    if count > 0:
                        ping_result = ping_site(site)
                        sanitized_site = sanitize_filename(site)
                        result_filename = f"{sanitized_site}_Adet_{count}.txt"
                        
                        # Append ping result to the log file
                        matched_lines.append("\nPing Sonuçları:\n")
                        matched_lines.append(ping_result)
                        
                        save_to_file(result_filename, matched_lines)

                        viplog_size = os.path.getsize('ArselVipLog.txt')
                        result_file_size = os.path.getsize(result_filename)

                        if file_size_within_limit(result_filename):
                            bot.send_message(user_id, f"İşlem başarılı şekilde ilerliyor\n\nLog boyut: {result_file_size} bytes\nViplog boyut: {viplog_size} bytes")
                            with open(result_filename, 'rb') as result_file:
                                bot.send_document(user_id, result_file)
                            os.remove(result_filename)  # Delete the temporary file
                        else:
                            bot.send_message(user_id, "Oluşturulan dosya boyutu Telegram'ın sınırlarını aşıyor.")
                            os.remove(result_filename)
                    else:
                        bot.send_message(user_id, f"{site} için herhangi bir giriş bulunamadı.")
                except Exception as e:
                    bot.send_message(user_id, f"Bir hata oluştu: {e}")
                    log_to_channel(f"Exception for {user_id}: {e}")
                finally:
                    remove_log_queue(user_id, site, queue_position)
        
        # Sleep for a short period to avoid busy-waiting
        time.sleep(1)

@bot.message_handler(commands=['promote'])
def handle_izin(message):
    if message.from_user.id == ADMIN_ID:
        try:
            user_id = int(message.text.split()[1])
            if not is_authorized_user(user_id):
                add_authorized_user(user_id)
                bot.send_message(user_id, f"Merhaba {bot.get_chat(user_id).username}, /sort komutunu kullanmaya hak kazandınız. İyi günler!")
                bot.reply_to(message, f"Kullanıcı {user_id} yetkilendirildi.")
                log_to_channel(f"User {user_id} has been authorized by admin.")
            else:
                bot.reply_to(message, f"Kullanıcı {user_id} zaten yetkilidir.")
        except (IndexError, ValueError):
            bot.reply_to(message, "Lütfen /izin komutunu şu formatta kullanın: /promote {ID}")
        except Exception as e:
            bot.reply_to(message, f"Bir hata oluştu: {e}")
    else:
        bot.reply_to(message, "Bu komutu yalnızca admin kullanabilir.")

@bot.message_handler(commands=['sort'])
def handle_log(message):
    if is_authorized_user(message.from_user.id):
        try:
            site = message.text.split()[1]
        except IndexError:
            bot.reply_to(message, "Lütfen /log komutunu şu formatta kullanın: /sort {site}")
            return
        
        current_time = time.time()
        user_id = message.from_user.id
        
        # Add the current request time to the user's request list
        add_user_request(user_id, current_time)
        
        # Get recent user requests
        recent_requests = get_recent_user_requests(user_id)
        
        # Check request rate limiting
        if len(recent_requests) == 3 and (recent_requests[-1] - recent_requests[0]) < 10:
            bot.reply_to(message, "Çok sık istek yapıyorsunuz. Lütfen 10 saniye bekleyin.")
            return
        
        # Add to log queue
        queue_position = len(get_log_queue()) + 1
        add_log_queue(user_id, site, queue_position)
        
        bot.reply_to(message, f"{queue_position}. Sıraya eklediniz. Lütfen sıranızı bekleyin.")
        log_to_channel(f"{user_id} kullanıcısının {queue_position}. sıradaki isteği: {site}")
    else:
        bot.reply_to(message, "Bu komutu kullanma yetkiniz yok. Lütfen admin ile iletişime geçin.")

# Start the bot and the queue processing thread
threading.Thread(target=process_queue, daemon=True).start()
bot.polling()
