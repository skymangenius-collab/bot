import os
import json
import aiohttp
import asyncio
import random
import time
import re
from datetime import datetime, timedelta
import unicodedata
from typing import Optional, Tuple

# ==================== CONFIGURATION ====================
# These are read from environment variables for cloud deployment.
# On Railway, set these in the "Variables" tab.
# Locally, you can set them in a .env file or just paste them below.

USER_TOKEN          = os.environ.get("USER_TOKEN", "")           # Your Discord user token
GROQ_API_KEY        = os.environ.get("GROQ_API_KEY", "")         # From https://console.groq.com
ANALYSIS_CHANNEL_ID = os.environ.get("ANALYSIS_CHANNEL_ID", "1297596458337439754")
ADVICE_CHANNEL_ID   = os.environ.get("ADVICE_CHANNEL_ID", "1216836991942135859")
SCREENSHOT_FOLDER   = os.environ.get("SCREENSHOT_FOLDER", "screenshots") # Put images in 'screenshots' folder
# Groq model — llama-3.2-3b-preview matches the original llama3.2:3b
# Other fast options: "llama-3.1-8b-instant", "gemma2-9b-it"
MODEL_NAME = "llama-3.3-70b-versatile"

# ==================== FAST MODE SETTINGS ====================
MIN_INTERVAL         = 150   # 2.5 minutes (150 seconds)
MAX_INTERVAL         = 180   # 3 minutes (180 seconds)
MAX_REQUESTS_PER_HOUR = 40   # increased to accommodate both loops
MIN_REQUEST_GAP      = 20    # 20 seconds between requests

# ==================== TRADING ADVICE SETTINGS ====================
ADVICE_MIN_INTERVAL  = 270   # 4.5 minutes (270 seconds)
ADVICE_MAX_INTERVAL  = 330   # 5.5 minutes (330 seconds)

# ==================== USER AGENT ROTATION ====================
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
]

# ==================== UTILITY FUNCTIONS ====================
def sanitize_filename(filename: str) -> str:
    """Remove problematic characters from filename"""
    filename = unicodedata.normalize('NFKD', filename)
    filename = filename.encode('ascii', 'ignore').decode('ascii')
    filename = filename.replace(' ', '_')
    problematic = ['@', '&', '*', '?', '!', '#', '$', '%', '^', '(', ')',
                   '[', ']', '{', '}', '|', '\\', '/', ':', ';', '"', "'",
                   '<', '>', ',', '`', '~']
    for char in problematic:
        filename = filename.replace(char, '_')
    filename = re.sub(r'_+', '_', filename)
    if '.' not in filename:
        filename = filename + '.jpg'
    return filename

def get_random_screenshot() -> Optional[str]:
    """Get screenshot with minimal delay"""
    time.sleep(random.uniform(0.3, 0.8))
    try:
        if not SCREENSHOT_FOLDER or not os.path.exists(SCREENSHOT_FOLDER):
            print(f"[INFO] No screenshot folder configured, running text-only mode.")
            return None
        images = []
        for ext in ['.png', '.jpg', '.jpeg', '.webp', '.bmp', '.gif']:
            images.extend([f for f in os.listdir(SCREENSHOT_FOLDER)
                           if f.lower().endswith(ext)])
        if not images:
            print(f"[INFO] No images found in {SCREENSHOT_FOLDER}")
            return None
        selected = random.choice(images)
        print(f"[INFO] Selected screenshot: {selected}")
        return os.path.join(SCREENSHOT_FOLDER, selected)
    except Exception as e:
        print(f"[ERROR] Getting screenshot: {e}")
        return None

def create_temp_screenshot(original_path: str) -> Optional[str]:
    """Create a temporary sanitized copy of the screenshot"""
    try:
        temp_folder = os.path.join(SCREENSHOT_FOLDER, "_temp")
        os.makedirs(temp_folder, exist_ok=True)
        original_name = os.path.basename(original_path)
        sanitized_name = sanitize_filename(original_name)
        temp_path = os.path.join(temp_folder, sanitized_name)
        import shutil
        shutil.copy2(original_path, temp_path)
        print(f"[INFO] Created sanitized temp file: {sanitized_name}")
        return temp_path
    except Exception as e:
        print(f"[ERROR] Creating temp file: {e}")
        return None

# ==================== ANTI-LOGOUT MANAGER ====================
class AntiLogoutManager:
    def __init__(self):
        self.request_timestamps = []
        self.consecutive_failures = 0
        self.last_activity_time = 0
        self.user_agent_index = 0
        self.total_requests = 0

    def check_request_safety(self) -> Tuple[bool, str]:
        """Check if it's safe to make another request"""
        now = time.time()
        self.request_timestamps = [t for t in self.request_timestamps if now - t < 7200]

        hour_timestamps = [t for t in self.request_timestamps if now - t < 3600]
        if len(hour_timestamps) >= MAX_REQUESTS_PER_HOUR:
            print(f"[SAFETY] Hourly limit: {len(hour_timestamps)}/{MAX_REQUESTS_PER_HOUR} requests")
            return False, "HOURLY_LIMIT"

        if self.request_timestamps and (now - self.request_timestamps[-1]) < MIN_REQUEST_GAP:
            gap = MIN_REQUEST_GAP - (now - self.request_timestamps[-1])
            print(f"[SAFETY] Too soon, need {gap:.1f}s gap")
            return False, "MIN_GAP"

        if self.consecutive_failures >= 3:
            print(f"[SAFETY] {self.consecutive_failures} consecutive failures, moderate cooldown")
            return False, "FAILURE_COOLDOWN"

        if random.random() < 0.01:
            print(f"[SAFETY] Random skip to appear more human")
            return False, "RANDOM_SKIP"

        return True, "OK"

    def record_success(self):
        now = time.time()
        self.request_timestamps.append(now)
        self.consecutive_failures = 0
        self.last_activity_time = now
        self.total_requests += 1
        if self.total_requests % 10 == 0:
            self.user_agent_index = (self.user_agent_index + 1) % len(USER_AGENTS)

    def record_failure(self):
        self.consecutive_failures += 1

    def get_user_agent(self) -> str:
        return USER_AGENTS[self.user_agent_index]

    async def pre_request_delay(self):
        delay = random.uniform(1, 2)
        print(f"[DELAY] Pre-request delay: {delay:.1f}s")
        await asyncio.sleep(delay)

    async def cooldown(self, reason: str):
        if reason == "HOURLY_LIMIT":
            wait_time = random.uniform(300, 600)
        elif reason == "FAILURE_COOLDOWN":
            wait_time = random.uniform(120, 240)
        elif reason == "RATE_LIMITED":
            wait_time = random.uniform(60, 120)
        elif reason == "RANDOM_SKIP":
            wait_time = random.uniform(30, 60)
        else:
            wait_time = random.uniform(30, 60)

        minutes = int(wait_time // 60)
        seconds = int(wait_time % 60)
        print(f"[COOLDOWN] {reason} - Waiting {minutes}m {seconds}s...")
        await asyncio.sleep(wait_time)

    def get_stats(self) -> dict:
        now = time.time()
        hour_count = len([t for t in self.request_timestamps if now - t < 3600])
        day_count  = len([t for t in self.request_timestamps if now - t < 86400])
        return {
            "total_requests":      self.total_requests,
            "hourly_requests":     hour_count,
            "daily_requests":      day_count,
            "consecutive_failures": self.consecutive_failures,
            "last_request_ago":    now - self.last_activity_time if self.last_activity_time else 0
        }

# ==================== TEXT PROCESSING ====================
def clean_text(text: str) -> str:
    """Clean AI-generated text"""
    if not text:
        return ""
    text = text.strip()
    if (text.startswith('"') and text.endswith('"')) or (text.startswith("'") and text.endswith("'")):
        text = text[1:-1]
    prefixes = ["Response:", "AI:", "Here's", "Analysis:", "Market:", "Commentary:",
                "The market", "Currently,", "In the market", "Market analysis:"]
    for prefix in prefixes:
        if text.lower().startswith(prefix.lower()):
            text = text[len(prefix):].strip()
    if text and len(text) > 1:
        text = text[0].upper() + text[1:]
    if text and not text.endswith(('.', '!', '?')):
        if len(text.split()) > 5:
            text += '.'
    return text

# ==================== GROQ AI ANALYSIS ====================
async def get_groq_analysis() -> Optional[str]:
    """Get GENERIC market analysis using Groq cloud API (replaces local Ollama)"""
    if not GROQ_API_KEY:
        print("[AI] No GROQ_API_KEY set — using fallback")
        return None

    try:
        from groq import AsyncGroq

        # 40% chance to skip AI and use fallback (keeps messages varied)
        if random.random() < 0.4:
            print("[AI] Using fallback instead of AI for variety")
            return None

        think_time = random.uniform(1.5, 2.5)
        print(f"[THINKING] Asking Groq for generic analysis ({think_time:.1f}s)...")
        await asyncio.sleep(think_time)

        prompts = [
            "Write a one-sentence comment about general market conditions. No specific assets or pairs.",
            "Brief observation about overall market sentiment. Generic only.",
            "What's the general market mood today? Don't name any specific instruments.",
            "Short comment about trading conditions. Keep it broad and non-specific.",
            "How are markets behaving overall? No tickers or pair names please."
        ]
        prompt = random.choice(prompts)

        client = AsyncGroq(api_key=GROQ_API_KEY)
        response = await client.chat.completions.create(
            model=MODEL_NAME,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=45,
            temperature=0.6,
            top_p=0.8
        )

        text = response.choices[0].message.content
        cleaned = clean_text(text)

        # Reject if it mentions specific pairs, assets, or prices
        pair_keywords = [
            'BTC', 'ETH', 'XRP', 'ADA', 'SOL', 'DOT', 'MATIC', 'BNB',
            'Bitcoin', 'Ethereum', 'Ripple', 'Cardano', 'Solana', 'Polkadot',
            'EUR/USD', 'GBP/USD', 'USD/JPY', 'AUD/USD', 'USD/CAD', 'NZD/USD',
            'EUR/GBP', 'EUR/JPY', 'GBP/JPY',
            'S&P', 'NASDAQ', 'Dow', 'FTSE', 'DAX', 'Nikkei',
            'Apple', 'Tesla', 'Amazon', 'Google', 'Microsoft',
            'crypto', 'forex', 'stock', 'equity', 'commodity'
        ]
        text_lower = cleaned.lower()
        contains_forbidden = any(kw.lower() in text_lower for kw in pair_keywords)
        contains_price   = re.search(r'\$?\d+[,.]?\d*\s*(k|K|m|M|b|B)?\b', cleaned)
        contains_percent = re.search(r'\d+\.?\d*%', cleaned)

        if contains_forbidden or contains_price or contains_percent:
            print(f"[AI] Rejected — contains specific pair/price: {cleaned[:50]}...")
            return None

        if cleaned and len(cleaned.strip()) > 15:
            word_count = len(cleaned.split())
            if 5 <= word_count <= 30:
                print(f"[ANALYSIS] Groq generated: {cleaned[:70]}... ({word_count} words)")
                return cleaned
            else:
                print(f"[AI] Rejected — wrong length: {word_count} words")

        return None

    except Exception as e:
        print(f"[GROQ ERROR] {e}")
        return None

def get_fallback_analysis() -> str:
    """Simple generic fallbacks — NO PAIR MENTIONS"""
    fallbacks = [
        "Pretty standard session, nothing special happening.",
        "Low energy across the board, just observing for now.",
        "Ranges are tightening up, could get interesting soon.",
        "Liquidity looks thin, not ideal for big moves.",
        "Holding patterns everywhere, no real conviction.",
        "Wicks are telling a story but price isn't following through.",
        "Clean levels are being respected, just no momentum yet.",
        "Feels like everyone is waiting for the same trigger.",
        "Structure looks decent, just missing the catalyst.",
        "Sellers showed up briefly but couldn't follow through.",
        "Buyers are stepping in at key zones, keeping things afloat.",
        "Typical pre-session drift, nothing to read into.",
        "Order flow is balanced, no clear edge either way.",
        "Compression building, usually leads to something eventually.",
        "Slow rotations within the range, textbook distribution.",
        "Watching for a flush before any real opportunity shows up.",
        "Dull session but the levels are clean for tomorrow.",
        "Not enough participation to trust any breakout right now.",
        "Market structure intact, just digesting the last move.",
        "Tight range day, saving energy for the real play."
    ]
    return random.choice(fallbacks)

async def get_random_greeting() -> str:
    """Return a completely safe, simple 1-2 line casual greeting or basic comment."""
    messages = [
        "Hey what's good",
        "Afternoon everyone",
        "Charts looking boring today ngl",
        "gm gm",
        "Just pulled up the screens",
        "Anything moving out there?",
        "Dead zone right now",
        "Barely any ticks on the tape",
        "Marked up my levels, now I wait",
        "Flat day so far",
        "Sitting this one out",
        "My edge isn't showing up today",
        "Discipline over everything",
        "London was a snooze, hoping NY delivers",
        "Might close the laptop early",
        "Hands off the buy button today",
        "Cash is a position too",
        "No reason to be aggressive here",
        "Hey guys",
        "Second coffee and still nothing lol",
        "Hope the week is treating you well",
        "Price feels like it wants to drop",
        "Chilling for the next couple hours",
        "Just ping ponging between levels",
        "Nothing convincing on the long side yet",
        "Anyone playing these swings?",
        "Zero exposure right now",
        "Going through my trade journal instead",
        "Pick a direction already",
        "Mixed signals everywhere",
        "Need a proper breakout before I care",
        "Happy I didn't chase that move earlier",
        "Best trade today is no trade",
        "Not much going on huh",
        "Curious how the 4h closes",
        "This chop will eat you alive if you let it",
        "Small size or no size on days like this",
        "Drawing lines on my chart, that's about it",
        "Slower than a Monday morning",
        "Need some real volume to push this",
        "This price action is putting me to sleep",
        "Gonna take a walk, screens aren't going anywhere",
        "Reminder: your plan exists for a reason",
        "Just waiting it out",
        "Whole market is in chill mode",
        "Sideways is the theme of the week apparently",
        "Slept through Asia session, didn't miss a thing",
        "Setups will come, not gonna force em",
        "Not vibing with this tape at all",
        "Hang in there everyone"
    ]
    return random.choice(messages)


# ==================== DISCORD SENDER ====================
class DiscordUserSender:
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
        self.safety = AntiLogoutManager()
        self.total_failures = 0
        self.total_success  = 0

    async def start(self) -> bool:
        if not USER_TOKEN:
            print("[ERROR] USER_TOKEN is not set!")
            print("Set it as an environment variable on Railway.")
            return False

        headers = {
            "Authorization":   USER_TOKEN,
            "User-Agent":      self.safety.get_user_agent(),
            "Accept":          "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Origin":          "https://discord.com",
            "Referer":         "https://discord.com/channels/@me",
            "DNT":             "1",
            "Connection":      "keep-alive",
            "Sec-Fetch-Dest":  "empty",
            "Sec-Fetch-Mode":  "cors",
            "Sec-Fetch-Site":  "same-origin",
            "TE":              "trailers"
        }
        connector = aiohttp.TCPConnector(limit=1, ttl_dns_cache=300, enable_cleanup_closed=True)
        timeout   = aiohttp.ClientTimeout(total=30, connect=15, sock_read=15)
        self.session = aiohttp.ClientSession(
            headers=headers,
            connector=connector,
            timeout=timeout,
            cookie_jar=aiohttp.CookieJar()
        )
        print(f"[SESSION] Started — 2.5-3 minute interval mode")
        print(f"[SETTINGS] {MAX_REQUESTS_PER_HOUR}/hour, {MIN_REQUEST_GAP}s min gap")
        return True

    async def verify_connection(self) -> bool:
        try:
            url = "https://discord.com/api/v9/users/@me"
            async with self.session.get(url) as r:
                if r.status == 200:
                    data = await r.json()
                    print(f"[VERIFY] Logged in as: {data.get('username', 'Unknown')}")
                    return True
                else:
                    print(f"[VERIFY] Failed: {r.status}")
                    return False
        except Exception as e:
            print(f"[VERIFY ERROR] {e}")
            return False

    async def send_text_message(self, text: str, channel_id: str = ANALYSIS_CHANNEL_ID, skip_safety: bool = False) -> Tuple[bool, str]:
        if not skip_safety:
            safe, reason = self.safety.check_request_safety()
            if not safe:
                await self.safety.cooldown(reason)
                return False, reason

        if not await self.verify_connection():
            print("[ERROR] Not logged in!")
            self.safety.record_failure()
            return False, "NOT_LOGGED_IN"

        await self.safety.pre_request_delay()
        url = f"https://discord.com/api/v9/channels/{channel_id}/messages"

        try:
            preview_len = min(60, len(text))
            print(f"[TEXT] Sending ({len(text)} chars) to {channel_id}: {text[:preview_len]}...")
            data = {"content": text, "tts": False, "flags": 0}
            headers = dict(self.session._default_headers)
            headers["User-Agent"] = self.safety.get_user_agent()

            async with self.session.post(url, json=data, headers=headers) as r:
                success, result = await self._handle_response(r)
                if success:
                    self.safety.record_success()
                    self.total_success += 1
                    await asyncio.sleep(random.uniform(1, 2))
                else:
                    self.safety.record_failure()
                    self.total_failures += 1
                return success, result

        except Exception as e:
            print(f"[SEND ERROR] {e}")
            self.safety.record_failure()
            self.total_failures += 1
            return False, f"ERROR:{str(e)}"

    async def send_message_with_image(self, text: str, image_path: str, channel_id: str = ANALYSIS_CHANNEL_ID) -> Tuple[bool, str]:
        safe, reason = self.safety.check_request_safety()
        if not safe:
            await self.safety.cooldown(reason)
            return False, reason

        if not await self.verify_connection():
            print("[ERROR] Not logged in!")
            self.safety.record_failure()
            return False, "NOT_LOGGED_IN"

        await self.safety.pre_request_delay()
        success, result = await self._try_send_with_image(text, image_path, channel_id, is_retry=False)

        if not success and ("400" in result or "JSON" in result or "IMAGE_ERROR" in result):
            print("[RETRY] Trying with sanitized filename...")
            temp_path = create_temp_screenshot(image_path)
            if temp_path:
                success, result = await self._try_send_with_image(text, temp_path, channel_id, is_retry=True)
                try:
                    if os.path.exists(temp_path):
                        os.remove(temp_path)
                except:
                    pass

        if success:
            self.safety.record_success()
            self.total_success += 1
            await asyncio.sleep(random.uniform(1, 2))
        else:
            self.safety.record_failure()
            self.total_failures += 1

        return success, result

    async def _try_send_with_image(self, text: str, image_path: str, channel_id: str, is_retry: bool) -> Tuple[bool, str]:
        url = f"https://discord.com/api/v9/channels/{channel_id}/messages"
        try:
            if not os.path.exists(image_path):
                print(f"[ERROR] Image not found: {image_path}")
                return False, "FILE_NOT_FOUND"

            with open(image_path, 'rb') as f:
                file_data = f.read()

            file_size_mb = len(file_data) / (1024 * 1024)
            if file_size_mb > 8:
                print(f"[ERROR] Image too large: {file_size_mb:.2f}MB > 8MB limit")
                return False, "IMAGE_TOO_LARGE"

            filename = os.path.basename(image_path)
            ext = filename.split('.')[-1].lower() if '.' in filename else 'jpg'
            if ext not in ['png', 'jpg', 'jpeg', 'gif', 'webp']:
                return False, "INVALID_EXTENSION"

            boundary = '----WebKitFormBoundary' + ''.join(random.choices('abcdefghijklmnopqrstuvwxyz0123456789', k=16))
            json_part = json.dumps({"content": text, "tts": False, "flags": 0})

            body = (
                f'--{boundary}\r\n'
                f'Content-Disposition: form-data; name="payload_json"\r\n'
                f'Content-Type: application/json\r\n'
                f'\r\n'
                f'{json_part}\r\n'
                f'--{boundary}\r\n'
                f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
                f'Content-Type: image/{ext}\r\n'
                f'\r\n'
            ).encode('utf-8') + file_data + f'\r\n--{boundary}--\r\n'.encode('utf-8')

            retry_msg = " (retry)" if is_retry else ""
            print(f"[IMAGE{retry_msg}] {filename} ({file_size_mb:.1f}MB)")

            headers = {
                "Authorization": USER_TOKEN,
                "Content-Type":  f"multipart/form-data; boundary={boundary}",
                "User-Agent":    self.safety.get_user_agent(),
                "Accept":        "*/*",
            }
            async with self.session.post(url, data=body, headers=headers) as r:
                return await self._handle_response(r)

        except Exception as e:
            print(f"[IMAGE SEND ERROR] {e}")
            return False, f"ERROR:{str(e)}"

    async def _handle_response(self, response) -> Tuple[bool, str]:
        try:
            response_text = await response.text()
            if response.status != 200:
                print(f"[RESPONSE {response.status}] {response_text[:200]}")
        except Exception as e:
            response_text = ""
            print(f"[RESPONSE ERROR] {e}")

        if response.status == 200:
            print("[SUCCESS] Message sent!")
            return True, "SUCCESS"
        elif response.status == 401:
            print("\n❌❌❌ CRITICAL: 401 - LOGGED OUT! ❌❌❌")
            return False, "LOGGED_OUT_401"
        elif response.status == 400:
            print(f"[ERROR] 400 Bad Request")
            if "rate limit" in response_text.lower():
                await self.safety.cooldown("RATE_LIMITED")
                return False, "RATE_LIMIT"
            return False, "BAD_REQUEST"
        elif response.status == 403:
            print("[ERROR] 403 - No permission to send in this channel")
            await self.safety.cooldown("failure")
            return False, "FORBIDDEN"
        elif response.status == 429:
            retry = int(response.headers.get('Retry-After', 15))
            print(f"[RATE LIMIT] Waiting {retry}s...")
            await asyncio.sleep(retry + random.uniform(5, 10))
            return False, "RATE_LIMITED"
        else:
            print(f"[ERROR] HTTP {response.status}")
            await self.safety.cooldown("failure")
            return False, f"HTTP_{response.status}"

    async def close(self):
        if self.session:
            await self.session.close()
        stats = self.safety.get_stats()
        print(f"\n[STATS] Success: {self.total_success}, Failures: {self.total_failures}")
        print(f"[STATS] Hourly: {stats['hourly_requests']}/{MAX_REQUESTS_PER_HOUR}")
        print(f"[STATS] Daily: {stats['daily_requests']}")

# ==================== MAIN BOT LOOP ====================
async def commentary_loop(sender: DiscordUserSender, use_images: bool):
    post_count = 0
    while True:
        post_count += 1
        current_time = datetime.now().strftime('%I:%M:%S %p')
        print(f"\n[#{post_count} COMMENTARY] {current_time}")
        print("-" * 40)

        try:
            stats = sender.safety.get_stats()
            remaining_hourly = MAX_REQUESTS_PER_HOUR - stats['hourly_requests']
            print(f"[STATS] This hour: {stats['hourly_requests']}/{MAX_REQUESTS_PER_HOUR} ({remaining_hourly} left)")

            screenshot = None
            if use_images:
                print("[1] Looking for screenshot...")
                screenshot = get_random_screenshot()
                if screenshot:
                    print(f"    Found: {os.path.basename(screenshot)}")
                else:
                    print("    No screenshots, switching to text-only mode")
                    use_images = False

            print("[2] Generating generic market commentary via Groq...")
            await asyncio.sleep(random.uniform(1, 2))
            analysis = await get_groq_analysis()

            if not analysis:
                analysis = get_fallback_analysis()
                print(f"    Fallback: {analysis}")
            else:
                print(f"    Groq AI: {analysis[:80]}...")

            print("[3] Sending message...")
            if screenshot and use_images:
                success, result = await sender.send_message_with_image(analysis, screenshot, ANALYSIS_CHANNEL_ID)
                if not success and ("BAD_REQUEST" in result or "400" in result):
                    use_images = False
                    print("[FALLBACK] Trying text-only...")
                    success, result = await sender.send_text_message(analysis, ANALYSIS_CHANNEL_ID)
            else:
                success, result = await sender.send_text_message(analysis, ANALYSIS_CHANNEL_ID)

            if success:
                print("    ✅ Success! Generic message sent")
            else:
                if "LOGGED_OUT" in result:
                    print("\n❌ ACCOUNT LOGGED OUT! Stopping commentary loop...")
                    break
                print(f"    ❌ Failed: {result}")

            base_wait = random.uniform(MIN_INTERVAL, MAX_INTERVAL)
            if random.random() < 0.15:
                variance = random.uniform(-30, 30)
                base_wait += variance
                direction = "Added" if variance > 0 else "Subtracted"
                print(f"[VARIANCE] {direction} {abs(variance):.0f} seconds")

            if base_wait < 120:
                base_wait = 120

            next_time = datetime.now() + timedelta(seconds=base_wait)
            wait_minutes = base_wait / 60
            print(f"\n[4] Next commentary post: {next_time.strftime('%I:%M %p')}")
            print(f"    Waiting {wait_minutes:.1f} minutes...")

            remaining = int(base_wait)
            last_update = 0
            while remaining > 0:
                if remaining <= 30 or (last_update - remaining) >= 30:
                    last_update = remaining
                await asyncio.sleep(1)
                remaining -= 1

            print("-" * 40)

        except Exception as e:
            print(f"\n[!] Commentary Loop Error: {e}")
            await asyncio.sleep(60)

async def advice_loop(sender: DiscordUserSender):
    post_count = 0
    if not ADVICE_CHANNEL_ID:
        print("[ADVICE] No ADVICE_CHANNEL_ID configured. Advice loop stopping.")
        return

    while True:
        post_count += 1
        current_time = datetime.now().strftime('%I:%M:%S %p')
        print(f"\n[#{post_count} ADVICE] {current_time}")
        print("-" * 40)

        try:
            advice = await get_random_greeting()
            print(f"    Selected Greeting: {advice}")

            print("[2] Sending advice message...")
            success, result = await sender.send_text_message(advice, ADVICE_CHANNEL_ID, skip_safety=True)

            if success:
                print("    ✅ Success! Trading advice sent")
            else:
                if "LOGGED_OUT" in result:
                    print("\n❌ ACCOUNT LOGGED OUT! Stopping advice loop...")
                    break
                print(f"    ❌ Failed: {result}")

            base_wait = random.uniform(ADVICE_MIN_INTERVAL, ADVICE_MAX_INTERVAL)
            next_time = datetime.now() + timedelta(seconds=base_wait)
            wait_minutes = base_wait / 60
            print(f"\n[3] Next advice post: {next_time.strftime('%I:%M %p')}")
            print(f"    Waiting {wait_minutes:.1f} minutes...")

            remaining = int(base_wait)
            while remaining > 0:
                await asyncio.sleep(1)
                remaining -= 1

            print("-" * 40)

        except Exception as e:
            print(f"\n[!] Advice Loop Error: {e}")
            await asyncio.sleep(60)

# ==================== MAIN BOT ENTRY ====================
async def main():
    print("\n" + "="*60)
    print("DISCORD BOT — COMMENTARY & TRADING ADVICE (Groq Edition)")
    print("="*60)
    print(f"Commentary Channel : {ANALYSIS_CHANNEL_ID}")
    print(f"Advice Channel     : {ADVICE_CHANNEL_ID}")
    print(f"Model              : {MODEL_NAME} via Groq")
    print("="*60)

    if not USER_TOKEN:
        print("\n[ERROR] USER_TOKEN is not set! Set it as an environment variable.")
        return

    if not GROQ_API_KEY:
        print("[WARNING] GROQ_API_KEY not set — will use fallback messages only (no AI).")

    sender = DiscordUserSender()
    if not await sender.start():
        return

    if not await sender.verify_connection():
        print("[ERROR] Cannot connect to Discord. Check your USER_TOKEN!")
        await sender.close()
        return

    use_images = bool(SCREENSHOT_FOLDER)
    session_start = datetime.now()

    print(f"\n[✓] Started at {session_start.strftime('%I:%M %p')}")
    print("[✓] Running concurrent commentary & advice loops")
    print("[✓] Press Ctrl+C to stop")
    print("-" * 60)

    try:
        # Run both tasks concurrently
        await asyncio.gather(
            commentary_loop(sender, use_images),
            advice_loop(sender)
        )
    except asyncio.CancelledError:
        pass
    except Exception as e:
        print(f"[!] Main loop fatal error: {e}")
    finally:
        await sender.close()

# ==================== ENTRY POINT ====================
if __name__ == "__main__":
    import sys

    # Non-interactive mode (Railway / cloud): just run main()
    if not sys.stdin.isatty():
        print("[CLOUD MODE] Auto-starting bot...")
        try:
            asyncio.run(main())
        except KeyboardInterrupt:
            print("\n[!] Stopped")
        except Exception as e:
            print(f"\n[!] Fatal error: {e}")

    # Interactive mode (local): show menu
    else:
        print("Discord Bot — GENERIC Market Analysis (Groq Edition)")
        print("=" * 50)
        print("\n⚡ 2.5-3 MINUTE MODE ⚡")
        print(f"• Messages every 2.5-3 minutes")
        print(f"• Up to {MAX_REQUESTS_PER_HOUR} messages per hour")
        print(f"• {MIN_REQUEST_GAP}s minimum gap between requests")
        print("\n🤖 AI: Groq cloud API (no local Ollama needed)")
        print(f"• Model: {MODEL_NAME}")
        print("\n🔒 GENERIC COMMENTARY ONLY")
        print("• No BTC/ETH/EUR/USD or specific pair mentions")
        print("\nSelect mode:")
        print("1. Run bot (normal operation)")
        print("2. Quick test (send 1 generic message now)")

        choice = input("\nEnter choice (1 or 2): ").strip()

        async def quick_test():
            sender = DiscordUserSender()
            if not await sender.start():
                return
            if not await sender.verify_connection():
                await sender.close()
                return
            msg = get_fallback_analysis()
            print(f"\nSending test: {msg}")
            success, result = await sender.send_text_message(msg)
            print("✅ Sent!" if success else f"❌ Failed: {result}")
            await sender.close()

        try:
            if choice == "2":
                asyncio.run(quick_test())
            else:
                asyncio.run(main())
        except KeyboardInterrupt:
            print("\n[!] Stopped by user")
        except Exception as e:
            print(f"\n[!] Fatal error: {e}")