from highrise import BaseBot, User, Position, Item

try:
    from highrise import Reaction as _HighriseReaction
except ImportError:
    _HighriseReaction = None


def resolve_reaction(name: str):
    """رشته‌ی ساده‌ی «heart»/«clap»/... رو به همون چیزی تبدیل می‌کنه که self.highrise.react()
    واقعاً قبول می‌کنه. ⚠️ صادقانه: مستنداتِ عمومیِ هایرایز مقادیرِ دقیقِ Reaction رو جایی
    لیست نکرده؛ این تابع چندتا حدسِ منطقی (رشته‌ی خام، اسمِ بزرگ تو enum) رو امتحان می‌کنه تا
    بیشترین شانس رو داشته باشه، ولی اگه بازم کار نکرد یعنی این حدس‌ها هم اشتباهن و باید مقدارِ
    واقعی از یه بات دیگه‌ی کارکن یا از خودِ PocketWorlds گرفته بشه."""
    if _HighriseReaction is not None:
        normalized = name.upper().replace("-", "_")
        for attr in (normalized, name.replace("-", "_"), name):
            if hasattr(_HighriseReaction, attr):
                return getattr(_HighriseReaction, attr)
    return name
from highrise.__main__ import BotDefinition
from asyncio import sleep, create_task, CancelledError
import asyncio
import os
import sys
import shutil
import json
import logging
from datetime import datetime, timedelta
import random
import aiohttp
import requests
import re
import urllib.parse
from collections import deque

# ============================= هوش مصنوعی (ChatGPT اصلی + g4f پشتیبان) =============================
# 🧠 اولویت با ChatGPT واقعیه (OpenAI API رسمی، نیاز به OPENAI_API_KEY داره).
# اگه کلید ست نشده باشه، خودکار میره سراغ g4f (رایگان، بدون کلید، ولی کیفیت/پایداری کمتر).
# نصب برای حالت پشتیبان: pip install -U g4f
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip()

try:
    import g4f
    G4F_AVAILABLE = True
except Exception as _g4f_import_error:
    g4f = None
    G4F_AVAILABLE = False
    logging.getLogger(__name__).warning(
        f"⚠️ کتابخونه‌ی g4f در دسترس نیست ({_g4f_import_error}). "
        f"اگه OPENAI_API_KEY هم ست نشده باشه، پرسیدن سوال از هوش مصنوعی کار نمی‌کنه."
    )

AI_SYSTEM_PROMPT = {
    "fa": (
        "تو دستیار هوش مصنوعی داخل چت یه بازی هستی. همیشه خیلی کوتاه، خودمونی و مستقیم جواب بده "
        "(حداکثر ۱ تا ۲ جمله‌ی کوتاه، بدون مقدمه‌چینی و بدون فهرست‌های طولانی)، مگر اینکه کاربر "
        "صراحتاً بخواد توضیح کامل بدی. همیشه فارسی جواب بده، مهم نیست کاربر با چه زبونی نوشته."
    ),
    "en": (
        "You are an AI assistant inside a game's chat. Always answer very briefly, casually and "
        "directly (max 1-2 short sentences, no preamble, no long lists), unless the user explicitly "
        "asks for a full explanation. Always answer in English, regardless of what language the user wrote in."
    ),
}
AI_MAX_TOKENS = 120  # سقف طول جواب -> جواب کوتاه می‌مونه


async def _ask_openai(prompt: str, lang: str) -> str | None:
    """تلاش برای گرفتن جواب از ChatGPT واقعی (OpenAI API رسمی). اگه کلید نباشه یا خطا بده None
    برمی‌گردونه تا فراخوان بره سراغ g4f."""
    if not OPENAI_API_KEY:
        return None

    def _sync_call():
        resp = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": OPENAI_MODEL,
                "messages": [
                    {"role": "system", "content": AI_SYSTEM_PROMPT.get(lang, AI_SYSTEM_PROMPT["fa"])},
                    {"role": "user", "content": prompt},
                ],
                "max_tokens": AI_MAX_TOKENS,
                "temperature": 0.7,
            },
            timeout=25,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip()

    try:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _sync_call)
    except Exception as e:
        logging.getLogger(__name__).error(f"خطا در تماس با OpenAI (ChatGPT رسمی): {e} — می‌رم سراغ g4f")
        return None


async def _ask_g4f(prompt: str, lang: str) -> str:
    if not G4F_AVAILABLE:
        return ("⚠️ هوش مصنوعی فعال نیست (نه OPENAI_API_KEY ست شده، نه g4f نصبه)."
                if lang == "fa" else
                "⚠️ AI isn't active right now (no OPENAI_API_KEY set, and g4f isn't installed).")

    def _sync_call():
        response = g4f.ChatCompletion.create(
            model=g4f.models.default,
            messages=[
                {"role": "system", "content": AI_SYSTEM_PROMPT.get(lang, AI_SYSTEM_PROMPT["fa"])},
                {"role": "user", "content": prompt},
            ],
        )
        if isinstance(response, str):
            return response
        try:
            return "".join(str(chunk) for chunk in response)
        except TypeError:
            return str(response)

    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, _sync_call)
        return (result or "").strip()
    except Exception as e:
        logging.getLogger(__name__).error(f"خطا در ask_ai (g4f): {e}")
        return (f"⚠️ خطا در گرفتن جواب از هوش مصنوعی: {e}" if lang == "fa"
                else f"⚠️ Error getting an AI response: {e}")


async def ask_ai(prompt: str, lang: str = "fa") -> str:
    """نقطه‌ی ورود واحد برای پرسیدن سوال: اول ChatGPT رسمی (اگه کلید ست شده)، وگرنه g4f.
    lang زبان بات (fa/en) رو مشخص می‌کنه — جواب همیشه به همون زبون برمی‌گرده، کوتاه هم نگه داشته میشه."""
    prompt = (prompt or "").strip()
    if not prompt:
        return "⚠️ یه سوال بنویس بعد از /" if lang == "fa" else "⚠️ Write a question after /"

    answer = await _ask_openai(prompt, lang)
    if answer:
        return _shorten(answer)

    answer = await _ask_g4f(prompt, lang)
    if answer:
        return _shorten(answer)
    return "🤖 جوابی نگرفتم، دوباره امتحان کن." if lang == "fa" else "🤖 Didn't get an answer, try again."


def _shorten(text: str, max_chars: int = 400) -> str:
    """حتی اگه مدل رعایت نکرد، تضمین می‌کنیم جواب خیلی طولانی نشه."""
    text = (text or "").strip()
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars].rsplit(" ", 1)[0]
    return cut + "…"

# تنظیم لاگینگ
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


# ============================= وب‌سرویس اسپیکر (چت هوشمند) =============================

def api_speaker(text: str, mode: str = None, restric: bool = False):
    """فراخوانی وب‌سرویس اسپیکر برای گرفتن پاسخ متنی هوشمند."""
    url = "https://l8pStudio.ir/apis-loop/api-speaker.php"
    payload = {"text": text}
    if mode:
        payload["mode"] = mode
    if restric:
        payload["restric"] = True
    try:
        response = requests.post(url, json=payload, timeout=15)
        if response.status_code == 200:
            data = response.json()
            if data["status"]:
                return data["data"]
    except Exception as e:
        logger.error(f"خطا در فراخوانی وب‌سرویس اسپیکر: {e}")
    return None


def extract_item_id_from_link(text: str) -> str:
    """از یه لینک high.rs (مثل https://high.rs/item?id=emote-scuba-dance&type=emote) فقط
    شناسه‌ی آیتم (emote-scuba-dance) رو بیرون می‌کشه. اگه ورودی از قبل خودِ آیدی خام باشه
    (بدون http)، همون رو بدون تغییر برمی‌گردونه."""
    text = (text or "").strip()
    if text.startswith("http://") or text.startswith("https://"):
        parsed = urllib.parse.urlparse(text)
        qs = urllib.parse.parse_qs(parsed.query)
        if "id" in qs and qs["id"]:
            return qs["id"][0]
        # اگه لینک به شکل query نبود، آخرین بخشِ مسیر رو امتحان کن
        return parsed.path.rstrip("/").rsplit("/", 1)[-1]
    return text


def serialize_outfit(outfit_items) -> list:
    """لیست آبجکت‌های Item رو به لیستی از دیکشنری قابل ذخیره در JSON تبدیل می‌کنه."""
    result = []
    for item in outfit_items:
        result.append({
            "type": getattr(item, "type", None),
            "amount": getattr(item, "amount", 1),
            "id": getattr(item, "id", None),
            "account_bound": getattr(item, "account_bound", False),
            "active_palette": getattr(item, "active_palette", None),
        })
    return result


_PERSIAN_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def to_persian_digits(number: int) -> str:
    return str(number).translate(_PERSIAN_DIGITS)


def deserialize_outfit(data: list):
    """دیکشنری ذخیره‌شده در کانفیگ رو دوباره به لیست آبجکت‌های Item تبدیل می‌کنه."""
    items = []
    for d in data:
        items.append(Item(
            type=d.get("type"),
            amount=d.get("amount", 1),
            id=d.get("id"),
            account_bound=d.get("account_bound", False),
            active_palette=d.get("active_palette"),
        ))
    return items

def extract_room_id_from_text(text: str) -> str:
    """هم لینکِ کامل (highrise.game/room/<id>/... یا high.rs/room/<id>) رو قبول می‌کنه، هم
    خودِ آیدیِ خام رو — مثلِ همون منطقی که تو پنلِ سایت واسه ساختِ بات استفاده میشه."""
    text = (text or "").strip()
    for marker in ("highrise.game/room/", "high.rs/room/"):
        if marker in text:
            try:
                after = text.split(marker, 1)[1]
                return after.split("/")[0].split("?")[0].strip()
            except Exception:
                return text
    return text


# تنظیمات پیش‌فرض
# 🔒 نکته‌ی حیاتی: هر ربات باید فایل تنظیماتِ خودش رو جدا داشته باشه، وگرنه وقتی چند ربات
# (برای روم‌های مختلف) هم‌زمان از همین یک فایل کد اجرا میشن، همه‌شون یک فایل تنظیمات
# مشترک رو می‌خوندن/می‌نوشتن و تنظیمات همدیگه (ادمین‌ها، ظاهر، رنک‌ها و ...) رو خراب می‌کردن.
# برای همین اسم فایل بر اساس ROOM_ID ساخته میشه تا هر ربات کاملاً مستقل باشه.
_room_id_for_config = os.getenv("ROOM_ID", "default")
CONFIG_FILE = f"bot_config_{_room_id_for_config}.json"

# 👕 ظاهر پیش‌فرض ربات (بر اساسِ ۸ اسکینِ واقعی‌ای که خودت از دو بات موجود صادر/آپلود کردی).
# پیش‌فرضِ کلی الان همون پریستِ شماره‌ی ۲ از فایلِ 6915952e ه (طبقِ درخواستِ خودت)، و هر ۸ تا
# اسکین هم به‌عنوانِ پریست‌های ۱ تا ۸ در دسترسن (با !item set 1 تا !item set 8).
DEFAULT_OUTFIT_ITEMS = [{"type": "clothing", "amount": 1, "id": "body-flesh", "account_bound": False, "active_palette": 36}, {"type": "clothing", "amount": 1, "id": "eyebrow-n_07", "account_bound": False, "active_palette": 0}, {"type": "clothing", "amount": 1, "id": "eye-n_basic2018woaheyes", "account_bound": False, "active_palette": 13}, {"type": "clothing", "amount": 1, "id": "nose-n_01", "account_bound": False, "active_palette": 0}, {"type": "clothing", "amount": 1, "id": "mouth-n_room22019sillymouth", "account_bound": False, "active_palette": 14}, {"type": "clothing", "amount": 1, "id": "freckle-n_basic2018freckle36", "account_bound": False, "active_palette": 0}, {"type": "clothing", "amount": 1, "id": "freckle-n_basic2018freckle33", "account_bound": False, "active_palette": 0}, {"type": "clothing", "amount": 1, "id": "watch-n_room32019blackwatch", "account_bound": False, "active_palette": 0}, {"type": "clothing", "amount": 1, "id": "shirt-n_mummyjacket", "account_bound": False, "active_palette": 0}, {"type": "clothing", "amount": 1, "id": "pants-n_mummypants", "account_bound": False, "active_palette": 0}, {"type": "clothing", "amount": 1, "id": "handbag-n_mummyplush", "account_bound": False, "active_palette": 0}, {"type": "clothing", "amount": 1, "id": "shoes-n_mummyheels", "account_bound": False, "active_palette": 0}, {"type": "clothing", "amount": 1, "id": "hair_front-n_malenew01", "account_bound": False, "active_palette": 17}, {"type": "clothing", "amount": 1, "id": "hair_back-n_malenew01", "account_bound": False, "active_palette": 17}, {"type": "clothing", "amount": 1, "id": "hat-n_mummyheadpiece_1", "account_bound": False, "active_palette": 0}, {"type": "clothing", "amount": 1, "id": "hat-n_mummyhat_3", "account_bound": False, "active_palette": 0}]

DEFAULT_OUTFIT_PRESETS = {
    "1": [{"type": "clothing", "amount": 1, "id": "body-flesh", "account_bound": False, "active_palette": 22}, {"type": "clothing", "amount": 1, "id": "eyebrow-n_12", "account_bound": False, "active_palette": 1}, {"type": "clothing", "amount": 1, "id": "hair_front-n_malenew09", "account_bound": False, "active_palette": 1}, {"type": "clothing", "amount": 1, "id": "hair_back-n_malenew09", "account_bound": False, "active_palette": 1}, {"type": "clothing", "amount": 1, "id": "eye-n_animecollection2018bishoneneyes", "account_bound": False, "active_palette": 7}, {"type": "clothing", "amount": 1, "id": "nose-n_01", "account_bound": False, "active_palette": 0}, {"type": "clothing", "amount": 1, "id": "shirt-n_gamerskypass2022ggshirt", "account_bound": False, "active_palette": 0}, {"type": "clothing", "amount": 1, "id": "shoes-n_chaseitems2024sneakersallwhite", "account_bound": True, "active_palette": 0}, {"type": "clothing", "amount": 1, "id": "bag-n_amethystdailyrewards2020amethystwings", "account_bound": False, "active_palette": 0}, {"type": "clothing", "amount": 1, "id": "bag-n_sapphiredailies2020sapphirestones", "account_bound": False, "active_palette": 0}, {"type": "clothing", "amount": 1, "id": "freckle-n_aprilfoolsinvisible2021hiddenface", "account_bound": False, "active_palette": 0}, {"type": "clothing", "amount": 1, "id": "mouth-n_amethystdailyrewards2020chainmouth", "account_bound": False, "active_palette": 0}, {"type": "clothing", "amount": 1, "id": "earrings-n_amethystdailyrewards2020amethystearrings", "account_bound": False, "active_palette": 0}, {"type": "clothing", "amount": 1, "id": "pants-n_highriseacademyudc2026set6yuppihrstudentpants", "account_bound": False, "active_palette": None}],
    "2": [{"type": "clothing", "amount": 1, "id": "body-flesh", "account_bound": False, "active_palette": 3}, {"type": "clothing", "amount": 1, "id": "nose-n_01", "account_bound": True, "active_palette": 0}, {"type": "clothing", "amount": 1, "id": "shirt-f_classicshirt_pink", "account_bound": False, "active_palette": 0}, {"type": "clothing", "amount": 1, "id": "skirt-n_2016falltanfloatyskirt", "account_bound": False, "active_palette": 0}, {"type": "clothing", "amount": 1, "id": "eye-n_basic2018heavymascera", "account_bound": True, "active_palette": 7}, {"type": "clothing", "amount": 1, "id": "hair_front-n_basic2018wavynobangs", "account_bound": True, "active_palette": 1}, {"type": "clothing", "amount": 1, "id": "hair_back-n_basic2018wavyshort", "account_bound": True, "active_palette": 1}, {"type": "clothing", "amount": 1, "id": "bag-n_SCSpring2018wildflowerbackpack", "account_bound": False, "active_palette": 0}, {"type": "clothing", "amount": 1, "id": "mouth-n_basic2018toothythinpeaked", "account_bound": True, "active_palette": -1}, {"type": "clothing", "amount": 1, "id": "shoes-n_whitedans", "account_bound": True, "active_palette": 0}, {"type": "clothing", "amount": 1, "id": "tattoo-n_authenticallyyouudc2024spookyimpcurvesnrolls", "account_bound": False, "active_palette": 0}, {"type": "clothing", "amount": 1, "id": "handbag-n_grad2018diploma", "account_bound": False, "active_palette": 0}, {"type": "clothing", "amount": 1, "id": "eyebrow-n_basic2018newbrows15", "account_bound": True, "active_palette": 1}],
    "3": [{"type": "clothing", "amount": 1, "id": "body-flesh", "account_bound": False, "active_palette": 48}, {"type": "clothing", "amount": 1, "id": "shoes-n_converse", "account_bound": False, "active_palette": 0}, {"type": "clothing", "amount": 1, "id": "hair_front-n_basic2018buzzcut", "account_bound": True, "active_palette": 25}, {"type": "clothing", "amount": 1, "id": "hair_back-n_basic2018buzzcut", "account_bound": True, "active_palette": 25}, {"type": "clothing", "amount": 1, "id": "pants-n_starteritems2019cuffedshortsblack", "account_bound": True, "active_palette": 0}, {"type": "clothing", "amount": 1, "id": "mouth-basic2018bunnyteeth", "account_bound": True, "active_palette": 38}, {"type": "clothing", "amount": 1, "id": "shoes-n_room22019tallsocks", "account_bound": True, "active_palette": 0}, {"type": "clothing", "amount": 1, "id": "eyebrow-n_10", "account_bound": False, "active_palette": 25}, {"type": "clothing", "amount": 1, "id": "eye-m_01b", "account_bound": True, "active_palette": 31}, {"type": "clothing", "amount": 1, "id": "shirt-n_tieteegreen", "account_bound": False, "active_palette": 0}, {"type": "clothing", "amount": 1, "id": "nose-n_01", "account_bound": True, "active_palette": 0}, {"type": "clothing", "amount": 1, "id": "freckle-n_basic2018freckle22", "account_bound": True, "active_palette": 0}, {"type": "clothing", "amount": 1, "id": "freckle-n_basic2018freckle28", "account_bound": True, "active_palette": 0}],
    "4": [{"type": "clothing", "amount": 1, "id": "body-flesh", "account_bound": False, "active_palette": 22}, {"type": "clothing", "amount": 1, "id": "eyebrow-n_12", "account_bound": False, "active_palette": 1}, {"type": "clothing", "amount": 1, "id": "hair_front-n_malenew09", "account_bound": False, "active_palette": 1}, {"type": "clothing", "amount": 1, "id": "hair_back-n_malenew09", "account_bound": False, "active_palette": 1}, {"type": "clothing", "amount": 1, "id": "eye-n_animecollection2018bishoneneyes", "account_bound": False, "active_palette": 7}, {"type": "clothing", "amount": 1, "id": "nose-n_01", "account_bound": False, "active_palette": 0}, {"type": "clothing", "amount": 1, "id": "shirt-n_gamerskypass2022ggshirt", "account_bound": False, "active_palette": 0}, {"type": "clothing", "amount": 1, "id": "pants-n_room12019rippedpantsblack", "account_bound": True, "active_palette": 0}, {"type": "clothing", "amount": 1, "id": "shoes-n_chaseitems2024sneakersallwhite", "account_bound": True, "active_palette": 0}, {"type": "clothing", "amount": 1, "id": "bag-n_amethystdailyrewards2020amethystwings", "account_bound": False, "active_palette": 0}, {"type": "clothing", "amount": 1, "id": "bag-n_sapphiredailies2020sapphirestones", "account_bound": False, "active_palette": 0}, {"type": "clothing", "amount": 1, "id": "freckle-n_aprilfoolsinvisible2021hiddenface", "account_bound": False, "active_palette": 0}, {"type": "clothing", "amount": 1, "id": "mouth-n_amethystdailyrewards2020chainmouth", "account_bound": False, "active_palette": 0}, {"type": "clothing", "amount": 1, "id": "earrings-n_amethystdailyrewards2020amethystearrings", "account_bound": False, "active_palette": 0}],
    "5": [{"type": "clothing", "amount": 1, "id": "body-flesh", "account_bound": False, "active_palette": 1}, {"type": "clothing", "amount": 1, "id": "eyebrow-n_07", "account_bound": False, "active_palette": 0}, {"type": "clothing", "amount": 1, "id": "eye-n_animecollection2018bishoneneyes", "account_bound": False, "active_palette": 15}, {"type": "clothing", "amount": 1, "id": "freckle-n_basic2018freckle22", "account_bound": False, "active_palette": 0}, {"type": "clothing", "amount": 1, "id": "pants-n_blackjoggerpants", "account_bound": False, "active_palette": 0}, {"type": "clothing", "amount": 1, "id": "mouth-n_aprilfoolsinvisible2020mouth", "account_bound": False, "active_palette": 22}, {"type": "clothing", "amount": 1, "id": "necklace-n_dailyquestoutfitnov2024chainnecklace", "account_bound": True, "active_palette": 0}, {"type": "clothing", "amount": 1, "id": "hat-n_lunarnewyearaltics2024dragonbuckethat", "account_bound": False, "active_palette": 0}, {"type": "clothing", "amount": 1, "id": "shirt-n_lunarnewyear2022tigersweater", "account_bound": False, "active_palette": 0}, {"type": "clothing", "amount": 1, "id": "nose-n_basic2018newnose20", "account_bound": True, "active_palette": 0}, {"type": "clothing", "amount": 1, "id": "handbag-n_room12019iphoneblack", "account_bound": False, "active_palette": 0}, {"type": "clothing", "amount": 1, "id": "hair_front-n_malenew19", "account_bound": True, "active_palette": 1}, {"type": "clothing", "amount": 1, "id": "hair_back-n_malenew19", "account_bound": True, "active_palette": 1}, {"type": "clothing", "amount": 1, "id": "shoes-n_room12019sneakersblack", "account_bound": True, "active_palette": 0}],
    "6": [{"type": "clothing", "amount": 1, "id": "freckle-n_basic2018freckle28", "account_bound": True, "active_palette": 0}, {"type": "clothing", "amount": 1, "id": "nose-n_01", "account_bound": True, "active_palette": 0}, {"type": "clothing", "amount": 1, "id": "freckle-n_basic2018freckle22", "account_bound": True, "active_palette": 0}, {"type": "clothing", "amount": 1, "id": "bag-n_amethystdailyrewards2020amethystwings", "account_bound": False, "active_palette": 0}, {"type": "clothing", "amount": 1, "id": "mouth-n_amethystdailyrewards2020chainmouth", "account_bound": False, "active_palette": 0}, {"type": "clothing", "amount": 1, "id": "bag-n_sapphiredailies2020sapphirestones", "account_bound": False, "active_palette": 0}, {"type": "clothing", "amount": 1, "id": "earrings-n_amethystdailyrewards2020amethystearrings", "account_bound": False, "active_palette": 0}, {"type": "clothing", "amount": 1, "id": "pants-n_starteritems2019cuffedjeansblack", "account_bound": False, "active_palette": 0}, {"type": "clothing", "amount": 1, "id": "shirt-m_suit_black", "account_bound": False, "active_palette": 0}, {"type": "clothing", "amount": 1, "id": "shoes-n_room12019bootsblack", "account_bound": False, "active_palette": 0}, {"type": "clothing", "amount": 1, "id": "eyebrow-n_02", "account_bound": False, "active_palette": 0}, {"type": "clothing", "amount": 1, "id": "hair_back-n_malenew23", "account_bound": False, "active_palette": 0}, {"type": "clothing", "amount": 1, "id": "hair_front-n_malenew23", "account_bound": False, "active_palette": 0}, {"type": "clothing", "amount": 1, "id": "body-flesh", "account_bound": False, "active_palette": 1}, {"type": "clothing", "amount": 1, "id": "freckle-n_aprilfoolsinvisible2021hiddenface", "account_bound": False, "active_palette": 0}, {"type": "clothing", "amount": 1, "id": "eye-n_animecollection2018bishoneneyes", "account_bound": False, "active_palette": 0}],
    "7": [{"type": "clothing", "amount": 1, "id": "body-flesh", "account_bound": False, "active_palette": 36}, {"type": "clothing", "amount": 1, "id": "eyebrow-n_07", "account_bound": False, "active_palette": 0}, {"type": "clothing", "amount": 1, "id": "eye-n_basic2018woaheyes", "account_bound": False, "active_palette": 13}, {"type": "clothing", "amount": 1, "id": "nose-n_01", "account_bound": False, "active_palette": 0}, {"type": "clothing", "amount": 1, "id": "mouth-n_room22019sillymouth", "account_bound": False, "active_palette": 14}, {"type": "clothing", "amount": 1, "id": "freckle-n_basic2018freckle36", "account_bound": False, "active_palette": 0}, {"type": "clothing", "amount": 1, "id": "freckle-n_basic2018freckle33", "account_bound": False, "active_palette": 0}, {"type": "clothing", "amount": 1, "id": "watch-n_room32019blackwatch", "account_bound": False, "active_palette": 0}, {"type": "clothing", "amount": 1, "id": "shirt-n_mummyjacket", "account_bound": False, "active_palette": 0}, {"type": "clothing", "amount": 1, "id": "pants-n_mummypants", "account_bound": False, "active_palette": 0}, {"type": "clothing", "amount": 1, "id": "handbag-n_mummyplush", "account_bound": False, "active_palette": 0}, {"type": "clothing", "amount": 1, "id": "shoes-n_mummyheels", "account_bound": False, "active_palette": 0}, {"type": "clothing", "amount": 1, "id": "hair_front-n_malenew01", "account_bound": False, "active_palette": 17}, {"type": "clothing", "amount": 1, "id": "hair_back-n_malenew01", "account_bound": False, "active_palette": 17}, {"type": "clothing", "amount": 1, "id": "hat-n_mummyheadpiece_1", "account_bound": False, "active_palette": 0}, {"type": "clothing", "amount": 1, "id": "hat-n_mummyhat_3", "account_bound": False, "active_palette": 0}],
    "8": [{"type": "clothing", "amount": 1, "id": "body-flesh", "account_bound": False, "active_palette": 48}, {"type": "clothing", "amount": 1, "id": "shoes-n_converse", "account_bound": False, "active_palette": 0}, {"type": "clothing", "amount": 1, "id": "hair_front-n_basic2018buzzcut", "account_bound": True, "active_palette": 25}, {"type": "clothing", "amount": 1, "id": "hair_back-n_basic2018buzzcut", "account_bound": True, "active_palette": 25}, {"type": "clothing", "amount": 1, "id": "pants-n_starteritems2019cuffedshortsblack", "account_bound": True, "active_palette": 0}, {"type": "clothing", "amount": 1, "id": "freckle-n_basic2018freckle28", "account_bound": True, "active_palette": 0}, {"type": "clothing", "amount": 1, "id": "mouth-basic2018bunnyteeth", "account_bound": True, "active_palette": 38}, {"type": "clothing", "amount": 1, "id": "shoes-n_room22019tallsocks", "account_bound": True, "active_palette": 0}, {"type": "clothing", "amount": 1, "id": "eyebrow-n_10", "account_bound": False, "active_palette": 25}, {"type": "clothing", "amount": 1, "id": "eye-m_01b", "account_bound": True, "active_palette": 31}, {"type": "clothing", "amount": 1, "id": "shirt-n_tieteegreen", "account_bound": False, "active_palette": 0}, {"type": "clothing", "amount": 1, "id": "nose-n_01", "account_bound": True, "active_palette": 0}, {"type": "clothing", "amount": 1, "id": "freckle-n_basic2018freckle22", "account_bound": True, "active_palette": 0}],
}

EN_DEFAULT_WELCOME = "<#00ffff> ✨ 🌟 Welcome {username} ❤️ Glad to ha<#ff99ff>ve you here! 🕺 Use Numbers (1-439)"
EN_DEFAULT_ANNOUNCEMENT = "Message @nukdum to rent this bot!"
AR_DEFAULT_WELCOME = "<#00ffff> ✨ 🌟 أهلاً {username} ❤️ سعداء بوجودك مع<#ff99ff>نا! 🕺 استخدم الأرقام (1-439)"
AR_DEFAULT_ANNOUNCEMENT = "راسل @nukdum لاستئجار هذا البوت!"

FA_DEFAULT_GOODBYE = "<#00ffff> 👋 {username} خداحافظ! خوشحال شدیم پیشمون بودی 💫"
EN_DEFAULT_GOODBYE = "<#00ffff> 👋 Bye {username}! It was great having you here 💫"
AR_DEFAULT_GOODBYE = "<#00ffff> 👋 مع السلامة {username}! سعدنا بوجودك معنا 💫"

# 🗣 معادل‌های فارسی/انگلیسیِ هرکدوم از این دسته‌ها — تا !item set eye 1 یا !item set چشم 1
# (نه فقط !item set eyes 1) هم کار کنه. هرچی به چپ نگاشته میشه به کلیدِ واقعیِ بالا.
STYLE_CATEGORY_ALIASES = {
    "eye": "eyes", "eyes": "eyes", "چشم": "eyes",
    "hair": "hair", "مو": "hair",
    "mouth": "mouth", "lip": "mouth", "lips": "mouth", "لب": "mouth",
    "eyebrow": "eyebrow", "eyebrows": "eyebrow", "ابرو": "eyebrow",
    "skin": "skin", "پوست": "skin",
    "nose": "nose", "دماغ": "nose", "بینی": "nose",
}
# دسته -> پیشوند واقعیِ آیدیِ هایرایز، برای پیدا کردن آیتمِ الانِ همون دسته وقتی فقط رنگ عوض میشه.
# ⚠️ طبق مستندات رسمیِ هایرایز (create.highrise.game/learn/bots/guides/change-bot-appearance):
# پیشوندِ واقعیِ چشم «eye» ه (نه «eyes»!) و پیشوندِ واقعیِ رنگِ پوست «body» ه (آیدیِ ثابتِ
# «body-flesh»، نه «skin»!) — این دقیقاً همون چیزی بود که باعث می‌شد !item set eye هیچ‌وقت
# آیتمِ فعلی رو پیدا نکنه و بگه «چیزی پوشیده نشده».
STYLE_CATEGORY_PREFIXES = {
    "eyes": "eye", "hair": "hair_front", "mouth": "mouth", "eyebrow": "eyebrow",
    "skin": "body", "nose": "nose",
}

# 🎒 دسته‌هایی که مطمئنیم تو خودِ هایرایز چندتایی/هم‌زمان قابلِ پوشیدنن (چندتا اکسسوری با هم)
# — این‌ها هیچ‌وقت با یه آیتمِ جدید حذف نمیشن، فقط اضافه میشن (دقیقاً مثلِ !item add).
# هر پیشوندِ دیگه‌ای که این‌جا نیست، «تک‌اسلاتی» فرض میشه (یعنی جایگزینِ نسخه‌ی قبلیِ خودش میشه).
MULTI_SLOT_ITEM_PREFIXES = {
    "necklace", "bag", "backpack", "purse", "handheld", "hand", "aura", "wings", "tail",
    "piercing", "freckles", "freckle", "blush", "mask",
}

# 🧍 این دسته‌ها طبق مستندات هایرایز تو *هر* درخواستِ set_outfit باید حتماً حاضر باشن، وگرنه
# سرور کلِ درخواست رو رد می‌کنه (حتی اگه فقط یه چیزِ دیگه رو عوض کرده باشی). برای همین موقعِ
# ساختنِ لیستِ نهایی، این‌ها رو از روی ظاهرِ واقعیِ الانِ بات نگه می‌داریم و هیچ‌وقت حذفشون
# نمی‌کنیم مگر اینکه خودِ کاربر صراحتاً همون دسته رو عوض کنه.
REQUIRED_OUTFIT_PREFIXES = {"body", "eye", "eyebrow", "nose", "mouth"}

# 🪙 دنومیناسیون‌های واقعیِ گلد بار تو هایرایز (برای تیپ کردن هر عدد دلخواه، با ترکیب این‌ها).
GOLD_BAR_VALUES = [
    (10000, "gold_bar_10k"), (5000, "gold_bar_5000"), (1000, "gold_bar_1k"),
    (500, "gold_bar_500"), (100, "gold_bar_100"), (50, "gold_bar_50"),
    (10, "gold_bar_10"), (5, "gold_bar_5"), (1, "gold_bar_1"),
]


def decompose_gold_amount(amount: int) -> list:
    """یه عدد دلخواه گلد رو با کمترین تعداد گلدبار ممکن می‌شکنه.
    مثال: 256 -> [(100,'gold_bar_100')x2, (50,'gold_bar_50')x1, (5,'gold_bar_5')x1, (1,'gold_bar_1')x1]"""
    remaining = amount
    plan = []
    for value, bar_name in GOLD_BAR_VALUES:
        count = remaining // value
        if count:
            plan.append((value, bar_name, count))
            remaining -= value * count
    return plan


DEFAULT_CONFIG = {
    "host_usernames": ["ahoora_king"],
    "owner_usernames": [],
    "manager_usernames": [],
    "admin_usernames": ["ahoora_king"],
    "vip_usernames": [],
    "banned_users": {},  # username -> until_iso (رشته) یا None (دائمی)
    "custom_ranks": {},
    "current_outfit": DEFAULT_OUTFIT_ITEMS,
    "outfit_presets": DEFAULT_OUTFIT_PRESETS,
    "discovered_emotes": {},
    "dance_enabled": True,
    "teleport_locations": {},
    "kill_position": None,  # {"x":.., "y":.., "z":..} - با !setkill از موقعیت خودِ ادمین ست میشه
    "language": "fa",
    "welcome_message": "<#00ffff> ✨ 🌟 𝐖𝐞𝐥𝐜𝐨𝐦𝐞 {username} ❤️ 𝐆𝐥𝐚𝐝 𝐭𝐨 𝐡𝐚<#ff99ff>𝐯𝐞 𝐲𝐨𝐮 𝐡𝐞𝐫𝐞!🕺 𝐔𝐬𝐞 𝐍𝐮𝐦𝐛𝐞𝐫𝐬 (𝟏-439)",
    "announcement_interval": 600,
    "announcement_message": "برای اجاره بات به آیدی @nukdumپیام دهید!",
    "theme_primary_color": "",  # رنگ اصلی پیام‌های ربات؛ خالی = تم پیش‌فرض (ff33ff)
    "theme_secondary_color": "",  # رنگ اسپیکر/لهجه‌ی دوم؛ خالی = تم پیش‌فرض (00ffff)
    "ai_room_enabled": False,  # !ai on/off -> آیا هوش مصنوعی با / تو چت عمومی روم هم جواب بده
    "auto_admins": [],  # یوزرنیم‌هایی که فقط با !admin on ادمین شدن (نه دستی) -> با !admin off برمی‌گردن
    "security_enabled": False,  # !security on/off -> آنتی‌اسپمِ خودکار (۵+ پیام تو ۸ ثانیه)
    "raidguard_enabled": False,  # !raidguard on/off -> ضدِ تبلیغِ لینک/دعوت به روم دیگه
    "warn_limit": 5,  # با چند اخطار، کاربر خودکار کیک میشه
    "bot_enabled": True,  # !botoff/!boton -> وقتی False باشه بات فقط به !boton جواب میده
    "welcome_messages": [],  # لیستِ پیام‌های خوش‌آمد (یکی تصادفی انتخاب میشه) — با welcome_message سینک میشه
    "welcome_enabled": True,  # !welcomeon/!welcomeoff
    "goodbye_message": FA_DEFAULT_GOODBYE,
    "goodbye_messages": [],  # لیستِ پیام‌های خداحافظی (یکی تصادفی انتخاب میشه) — دقیقاً مثلِ welcome_messages
    "goodbye_enabled": True,  # !goodbyeon/!goodbyeoff
    "user_marks": {},  # username -> {"x":.., "y":.., "z":..} - با !mark هر کاربر موقعیتِ شخصیِ خودش رو ذخیره می‌کنه
    "autotele_users": [],  # یوزرنیم‌هایی که !autotele on زدن — با فاصله‌ی زیاد خودکار به مارکِ خودشون تلپورت میشن
    "home_position": None,  # {"x":.., "y":.., "z":..} - محلِ استراحتِ بات، با !sethome
    "moderator_usernames": [],  # با !mod/!unmod -> دسترسیِ نظارتیِ محدود (نه کاملِ ادمین)
    "peak_population": {"count": 0, "at": None},  # رکوردِ بیشترین جمعیتِ هم‌زمان (برای !memories)
    "autohome_enabled": False,  # !ah/!autohome on/off -> با هر روشن‌شدن/ری‌استارتِ بات خودکار بره خونه
    "known_user_ids": {},  # username -> user_id (کشِ دائمی؛ برای !item set @user حتی وقتی الان آنلاین نیست)
}

# ============================= سیستمِ رتبه‌بندیِ یکپارچه (Host/Owner/Manager/Admin/Mod/VIP) =============================
# هر رتبه به یه کلیدِ لیست تو config وصله. سطح (level) هرچی بالاتر، قدرت بیشتر — برای تشخیصِ
# اینکه کی اجازه داره به کی رتبه بده/بگیره (!give) و برای مرتب‌سازیِ نمایش تو !listadd استفاده میشه.
RANK_DEFINITIONS = [
    {"key": "host", "config_key": "host_usernames", "level": 100,
     "fa": "هاست (Host)", "en": "Host", "ar": "هوست (Host)", "emoji": "👑",
     "aliases": ["host", "هاست"]},
    {"key": "owner", "config_key": "owner_usernames", "level": 90,
     "fa": "اونر (Owner)", "en": "Owner", "ar": "أونر (Owner)", "emoji": "🌟",
     "aliases": ["owner", "اونر", "مالک"]},
    {"key": "manager", "config_key": "manager_usernames", "level": 80,
     "fa": "منیجر (Manager)", "en": "Manager", "ar": "منجر (Manager)", "emoji": "🛠",
     "aliases": ["manager", "منیجر", "مدیر"]},
    {"key": "admin", "config_key": "admin_usernames", "level": 70,
     "fa": "ادمین (Admin)", "en": "Admin", "ar": "أدمن (Admin)", "emoji": "🛡",
     "aliases": ["admin", "ادمین", "ادمن"]},
    {"key": "mod", "config_key": "moderator_usernames", "level": 50,
     "fa": "مدراتور (Mod)", "en": "Mod", "ar": "مشرف (Mod)", "emoji": "🔧",
     "aliases": ["mod", "moderator", "مدراتور", "ماد"]},
    {"key": "vip", "config_key": "vip_usernames", "level": 10,
     "fa": "وی‌آی‌پی (VIP)", "en": "VIP", "ar": "في آي بي (VIP)", "emoji": "⭐",
     "aliases": ["vip", "وی‌ای‌پی", "ویپ"]},
]
RANK_BY_KEY = {r["key"]: r for r in RANK_DEFINITIONS}

# رتبه‌هایی که وقتی داده میشن، خودکار تو لیستِ ادمین‌ها هم قرار می‌گیرن (مثل رفتارِ قبلیِ Host).
RANKS_THAT_IMPLY_ADMIN = ("host", "owner", "manager")

# حداقل سطحِ لازم برای اینکه کسی بتونه هر رتبه رو بده/بگیره (به‌جز «host» که قانونِ اختصاصیِ
# خودش رو داره: فقط خودِ مالکِ اصلیِ بات). مثلاً برای دادنِ رتبه‌ی Admin، باید حداقل سطحِ
# Manager (۸۰) یا بالاتر (Owner/Host) داشته باشی.
RANK_GRANT_MIN_LEVEL = {
    "host": 100,     # فقط خودِ Host‌ها (هر Host می‌تونه به بقیه هم Host بده)
    "owner": 100,    # فقط Host
    "manager": 100,  # فقط Host
    "admin": 80,     # Manager به بالا
    "mod": 70,       # Admin به بالا
    "vip": 70,       # Admin به بالا
}

# ⏱️ فرمت مدت زمان برای !ban و !kick: 0 (دائمی)، عدد+s (ثانیه)، عدد+m (دقیقه)، عدد+h (ساعت)
_DURATION_RE = re.compile(r"^(\d+)\s*(s|m|h)$", re.IGNORECASE)


def parse_duration_arg(raw: str, lang: str = "fa"):
    """
    ورودی مثل '0' یا '30m' یا '2h' یا '90s'.
    خروجی: (seconds:int|None, error:str|None)
    seconds=None یعنی دائمی. اگه فرمت غلط باشه error پر میشه.
    """
    raw = (raw or "").strip().lower()
    if raw in ("", "0"):
        return None, None
    m = _DURATION_RE.match(raw)
    if not m:
        err = ("⚠️ فرمت تایم اشتباهه. مثال: 0 (دائمی)، 30m (دقیقه)، 2h (ساعت)، 90s (ثانیه)" if lang == "fa"
               else "⚠️ Wrong duration format. Example: 0 (permanent), 30m (minutes), 2h (hours), 90s (seconds)")
        return 0, err
    amount, unit = int(m.group(1)), m.group(2)
    multiplier = {"s": 1, "m": 60, "h": 3600}[unit]
    return amount * multiplier, None


def humanize_seconds_fa(seconds: int) -> str:
    if seconds <= 0:
        return "۰ ثانیه"
    days = seconds // 86400
    hours = (seconds % 86400) // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    parts = []
    if days:
        parts.append(f"{days} روز")
    if hours:
        parts.append(f"{hours} ساعت")
    if minutes:
        parts.append(f"{minutes} دقیقه")
    if secs and not days and not hours:
        parts.append(f"{secs} ثانیه")
    return " و ".join(parts) if parts else "کمتر از یک دقیقه"


def humanize_seconds_en(seconds: int) -> str:
    if seconds <= 0:
        return "0 seconds"
    days = seconds // 86400
    hours = (seconds % 86400) // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    parts = []
    if days:
        parts.append(f"{days} day{'s' if days != 1 else ''}")
    if hours:
        parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
    if minutes:
        parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
    if secs and not days and not hours:
        parts.append(f"{secs} second{'s' if secs != 1 else ''}")
    return " ".join(parts) if parts else "less than a minute"


def humanize_seconds_lang(seconds: int, lang: str) -> str:
    return humanize_seconds_fa(seconds) if lang == "fa" else humanize_seconds_en(seconds)


# ⏰ هشدار پایان اشتراک/رنت تو چت روم — از بزرگ به کوچیک بررسی میشه (۱ ساعت، ۱۵ دقیقه، ۵ دقیقه)
# ⏱️ فاصله بین پیام‌های !spam. روی حداقل ممکن گذاشته شده (سریع‌ترین حالت). اگه دیدی هایرایز
# پیام‌ها رو قطع/تاخیر می‌ندازه یا بات موقتاً میوت میشه، یعنی به rate-limit سرور خوردی —
# این عدد رو کمی بالا ببر (مثلاً 0.15 یا 0.3).
SPAM_DELAY_SECONDS = 0.05
AUTOTELE_DISTANCE_THRESHOLD = 6.0  # فاصله‌ای که ازش بیشتر بشه، !autotele کاربر رو خودکار به مارکش تلپورت می‌کنه

# ⏱️ فاصله‌ی چرخه‌ی سینک با پنل (چک کردن تغییرات سایت: ادمین، پیام خوش‌آمد، تم رنگی، بن‌ها).
# رو حداقل معقول گذاشته شده تا تغییرات تقریباً آنی اعمال بشن. این یه کوئری سبک روی sqlite محلیه،
# پس بار اضافه‌ای نداره؛ اگه چند صد بات هم‌زمان رو یه پنل ران باشن و فشار I/O دیسک زیاد شد، همینجا بالاش ببر.
PANEL_SYNC_INTERVAL_SECONDS = 1


EXPIRY_WARN_THRESHOLDS = [3600, 900, 300]
EXPIRY_WARN_MESSAGES = {
    "fa": {
        3600: "🔔 توجه: کمتر از ۱ ساعت به پایان اشتراک این ربات مونده! برای تمدید با مالک/ادمین هماهنگ کنید.",
        900: "⏰ توجه: کمتر از ۱۵ دقیقه به پایان اشتراک این ربات مونده!",
        300: "🚨 آخرین هشدار: کمتر از ۵ دقیقه به پایان اشتراک این ربات مونده، به‌زودی خاموش میشه!",
    },
    "en": {
        3600: "🔔 Notice: less than 1 hour left on this bot's subscription! Contact the owner/admin to renew.",
        900: "⏰ Notice: less than 15 minutes left on this bot's subscription!",
        300: "🚨 Final warning: less than 5 minutes left on this bot's subscription, it will shut down soon!",
    },
}

class AdvancedBot(BaseBot):
    def __init__(self):
        super().__init__()
        self.load_config()
        self.active_users = {}
        self.user_dances = {}
        self.dance_tasks = {}
        self.user_positions = {}
        self.user_scores = {}
        self.user_join_times = {}  # username -> datetime (ورود به روم این نشست بات، برای !info)
        self.bot_start_time = datetime.utcnow()  # زمان روشن شدن بات (برای !info)
        # 🎟 لاتاری: {"active": bool, "ticket_price": int, "entries": {username: {"username","user_id","amount"}}, "ends_at": datetime|None, "task": asyncio.Task|None}
        self.lottery = None
        self.user_id = None
        self.announcement_task = None
        self.score_update_task = None
        self.loopchat_task = None
        self.frozen_users = {}
        self.party_dances = {}
        self.speaker_enabled = True # وضعیت روشن/خاموش بودن قابلیت چت هوشمند (اسپیکر)
        self.speaker_mode = "rude"  # حالت لحن اسپیکر: polite (باادب) یا rude (بی‌ادب)
        self.following_username = None  # یوزرنیمی که ربات الان داره دنبالش می‌کنه (!fallow)
        self.muted_users = {}  # username -> دقیقه میوت (برای !mute)
        self.bot_position = None  # آخرین موقعیت شناخته‌شده‌ی خودِ ربات
        self.auto_walk_enabled = False  # وضعیت راه رفتن خودکار (!run)
        self.auto_walk_fast = False  # !run fast on/off -> راه رفتن سریع‌تر (هر ~۲ ثانیه به‌جای ۵-۹ ثانیه)
        self._expiry_warned = set()  # threshold هایی (ثانیه) که هشدار پایان اشتراکش قبلاً تو چت گفته شده
        self.auto_walk_task = None
        self.afk_users = set()  # یوزرنیم‌هایی که با !afk اعلام کردن که غایبن
        # 🛡 سیستم‌های جدیدِ نظارت: اخطار، زندان، لاگ اقدامات، آنتی‌اسپم، ضدِ تبلیغِ روم دیگه
        self.warn_counts = {}  # username -> تعداد اخطارهای فعلی (با ۵ تا خودکار کیک میشه)
        self.warn_reasons = {}  # username -> لیستِ آخرین دلیل‌ها (برای !warns)
        self.jailed_users = {}  # username -> asyncio.Task (حلقه‌ی نگه‌داشتن تو زندان، مثل frozen_users)
        self.mod_log = deque(maxlen=30)  # [(datetime, actor, action, target, extra)] برای !modlog
        self.spam_msg_times = {}  # username -> deque[datetime] (پنجره‌ی ۸ ثانیه‌ی آخر، برای !security)
        self.spam_warned_once = set()  # یوزرنیم‌هایی که یه‌بار برای اسپم اخطار گرفتن (دفعه‌ی بعد میوت میشن)
        self.raid_warned_once = set()  # یوزرنیم‌هایی که یه‌بار برای تبلیغِ روم دیگه اخطار گرفتن
        self.temp_vip_tasks = {}  # username -> asyncio.Task (تایمرِ انقضای !tempvip)
        self.temp_vip_expiry = {}  # username -> datetime (برای نمایشِ زمانِ باقی‌مونده تو !vip-list)
        self.visitors_today = set()  # یوزرنیم‌هایی که امروز واردِ روم شدن (برای !visitors)
        self.visitors_date = datetime.utcnow().date()  # تاریخِ همون شمارشی که بالاست؛ با تغییرِ روز صفر میشه
        self.active_quiz = None  # {"question":.., "answer":.., "started_by":..} یا None
        self.commands = {
            "!help": self.cmd_help,
            "!exthelp": self.cmd_help,
            "!راهنما": self.cmd_help,
            "!spam": self.cmd_spam,
            "!tele": self.cmd_tele,
            "!heart": self.cmd_heart,
            "!clap": self.cmd_clap,
            "!wink": self.cmd_wink,
            "!wave": self.cmd_wave,
            "!thumbs": self.cmd_thumbs,
            "!wallet": self.cmd_wallet,
            "!set": self.cmd_set,
            "!tip": self.cmd_tip,
            "!ban": self.cmd_ban,
            "!kick": self.cmd_kick,
            "!kill": self.cmd_kill,
            "!setkill": self.cmd_setkill,
            "!info": self.cmd_info,
            "!lottery": self.cmd_lottery,
            "!restart": self.cmd_restart,
            "!unban": self.cmd_unban,
            "!admin": self.cmd_admin_toggle,
            "!ai": self.cmd_ai_toggle,
            "!dancechain": self.cmd_dancechain,
            "!addtele": self.cmd_addtele,
            "!deltele": self.cmd_deltele,
            "!item set": self.cmd_set_item,
            "!item add": self.cmd_add_item,
            "!item search": self.cmd_item_search,
            "!welcome": self.cmd_welcome,
            "!addwelcome": self.cmd_welcome,
            "!addadmin": self.cmd_addadmin,
            "!removeadmin": self.cmd_removeadmin,
            "!addhost": self.cmd_addhost,
            "!removehost": self.cmd_removehost,
            "!listadd": self.cmd_listadd,
            "!give": self.cmd_give,
            "!freeze": self.cmd_freeze,
            "!unfreeze": self.cmd_unfreeze,
            # 🛡 نظارت: اخطار / زندان / لاگ / لیست‌ها / آنتی‌اسپم / ضدِ تبلیغ / گزارش
            "!warn": self.cmd_warn,
            "!warns": self.cmd_warns,
            "!clearwarn": self.cmd_clearwarn,
            "!jail": self.cmd_jail,
            "!unjail": self.cmd_unjail,
            "!mod-list": self.cmd_mod_list,
            "!muted": self.cmd_muted_list,
            "!modlog": self.cmd_modlog,
            "!security": self.cmd_security_toggle,
            "!raidguard": self.cmd_raidguard_toggle,
            "!report": self.cmd_report,
            "!welcomelist": self.cmd_welcomelist,
            "!delwelcome": self.cmd_delwelcome,
            "!welcomeon": self.cmd_welcome_on,
            "!welcomeoff": self.cmd_welcome_off,
            "!goodbye": self.cmd_goodbye,
            "!addgoodbye": self.cmd_goodbye,
            "!goodbyelist": self.cmd_goodbyelist,
            "!delgoodbye": self.cmd_delgoodbye,
            "!goodbyeon": self.cmd_goodbye_on,
            "!goodbyeoff": self.cmd_goodbye_off,
            "!mark": self.cmd_mark,
            "!autotele": self.cmd_autotele_toggle,
            "!language": self.cmd_language,
            "!botoff": self.cmd_bot_off,
            "!reactiontest": self.cmd_reaction_debug,
            "!boton": self.cmd_bot_on,
            "!dm": self.cmd_dm,
            "!sethome": self.cmd_sethome,
            "!home": self.cmd_home,
            "!delhome": self.cmd_delhome,
            "!mod": self.cmd_mod,
            "!unmod": self.cmd_unmod,
            "!vip-list": self.cmd_vip_list,
            "!vip-args": self.cmd_vip_args,
            "!tempvip": self.cmd_tempvip,
            "!untempvip": self.cmd_untempvip,
            "!summ": self.cmd_summ,
            "!quiz": self.cmd_quiz,
            "!top": self.cmd_top,
            "!visitors": self.cmd_visitors,
            "!memories": self.cmd_memories,
            "!countdown": self.cmd_countdown,
            "!schedule": self.cmd_schedule,
            "!stats": self.cmd_stats,
            "!down": self.cmd_down,
            "!move": self.cmd_move,
            "!ah": self.cmd_autohome_toggle,
            "!autohome": self.cmd_autohome_toggle,
            "!party": self.cmd_party,
            "!partys": self.cmd_partys,
            "!emotebot": self.cmd_emotebot,
            "!loop": self.cmd_loopchat,
            "!loops": self.cmd_loops,
            "!kiss": self.cmd_kiss,
            "!fight": self.cmd_fight,
            "!love": self.cmd_love,
            "!speaker": self.cmd_speaker,
            "!speakerm": self.cmd_speaker_mode,
            "!random": self.cmd_random,
            "!tp": self.cmd_tp,
            "!react": self.cmd_react,
            "!commands": self.cmd_commands,
            "!dances": self.cmd_dances,
            "!fallow": self.cmd_fallow,
            "!run": self.cmd_run,
            "!item save": self.cmd_save_item,
            "!mute": self.cmd_mute,
            "!unmute": self.cmd_unmute,
            "!mr": self.cmd_mr,
            "!gr": self.cmd_gr,
            "!dr": self.cmd_dr,
            "!emotescan": self.cmd_emotescan,
            "!punch": self.cmd_punch,
            "!dance": self.cmd_dance_toggle,
            "!afk": self.cmd_afk,
            "!lang": self.cmd_lang,
            "!emote": self.cmd_emote
        }
        self.emotes = {
            "1": "idle_zombie",
            "2": "idle_layingdown2",
            "3": "idle_layingdown",
            "4": "idle-sleep",
            "5": "idle-sad",
            "6": "idle-posh",
            "7": "idle-loop-tired",
            "8": "idle-loop-tapdance",
            "9": "idle-loop-sitfloor",
            "10": "idle-loop-shy",
            "11": "idle-loop-sad",
            "12": "idle-loop-happy",
            "13": "idle-loop-annoyed",
            "14": "idle-loop-aerobics",
            "15": "idle-lookup",
            "16": "idle-hero",
            "17": "idle-floorsleeping",
            "18": "idle-enthusiastic",
            "19": "idle-dance-swinging",
            "20": "idle-dance-headbobbing",
            "21": "idle-angry",
            "22": "emote-yes",
            "23": "emote-wings",
            "24": "emote-wave",
            "25": "emote-tired",
            "26": "emote-think",
            "27": "emote-theatrical",
            "28": "emote-tapdance",
            "29": "emote-superrun",
            "30": "emote-superpunch",
            "31": "emote-sumo",
            "32": "emote-suckthumb",
            "33": "emote-splitsdrop",
            "34": "emote-snowball",
            "35": "emote-snowangel",
            "36": "emote-shy",
            "37": "emote-secrethandshake",
            "38": "emote-sad",
            "39": "emote-ropepull",
            "40": "emote-roll",
            "41": "emote-rofl",
            "42": "emote-robot",
            "43": "emote-rainbow",
            "44": "emote-proposing",
            "45": "emote-peekaboo",
            "46": "emote-peace",
            "47": "emote-panic",
            "48": "emote-no",
            "49": "emote-ninjarun",
            "50": "emote-nightfever",
            "51": "emote-monster_fail",
            "52": "emote-model",
            "53": "emote-lust",
            "54": "emote-levelup",
            "55": "emote-laughing2",
            "56": "emote-laughing",
            "57": "emote-kiss",
            "58": "emote-kicking",
            "59": "emote-jumpb",
            "60": "emote-gravity",
            "61": "emote-judochop",
            "62": "emote-jetpack",
            "63": "emote-hugyourself",
            "64": "emote-hot",
            "65": "emote-hero",
            "66": "emote-hello",
            "67": "emote-headball",
            "68": "emote-harlemshake",
            "69": "emote-happy",
            "70": "emote-handstand",
            "71": "emote-greedy",
            "72": "emote-graceful",
            "73": "emote-gordonshuffle",
            "74": "emote-ghost-idle",
            "75": "emote-gangnam",
            "76": "emote-frollicking",
            "77": "emote-fainting",
            "78": "emote-fail2",
            "79": "emote-fail1",
            "80": "emote-exasperatedb",
            "81": "emote-exasperated",
            "82": "emote-elbowbump",
            "83": "emote-disco",
            "84": "emote-disappear",
            "85": "emote-deathdrop",
            "86": "emote-death2",
            "87": "emote-death",
            "88": "emote-dab",
            "89": "emote-curtsy",
            "90": "emote-confused",
            "91": "emote-cold",
            "92": "emote-charging",
            "93": "emote-bunnyhop",
            "94": "emote-bow",
            "95": "emote-boo",
            "96": "emote-baseball",
            "97": "emote-apart",
            "98": "emoji-thumbsup",
            "99": "emoji-there",
            "100": "emoji-sneeze",
            "101": "emoji-smirking",
            "102": "emoji-sick",
            "103": "emoji-scared",
            "104": "emoji-punch",
            "105": "emoji-pray",
            "106": "emoji-poop",
            "107": "emoji-naughty",
            "108": "emoji-mind-blown",
            "109": "emoji-lying",
            "110": "emoji-halo",
            "111": "emoji-hadoken",
            "112": "emoji-give-up",
            "113": "emoji-gagging",
            "114": "emoji-flex",
            "115": "emoji-dizzy",
            "116": "emoji-cursing",
            "117": "emoji-crying",
            "118": "emoji-clapping",
            "119": "emoji-celebrate",
            "120": "emoji-arrogance",
            "121": "emoji-angry",
            "122": "dance-voguehands",
            "123": "dance-tiktok8",
            "124": "dance-tiktok2",
            "125": "dance-spiritual",
            "126": "dance-smoothwalk",
            "127": "dance-singleladies",
            "128": "dance-shoppingcart",
            "129": "dance-russian",
            "130": "dance-robotic",
            "131": "dance-pennywise",
            "132": "dance-orangejustice",
            "133": "dance-metal",
            "134": "dance-martial-artist",
            "135": "dance-macarena",
            "136": "dance-handsup",
            "137": "dance-duckwalk",
            "138": "dance-breakdance",
            "139": "dance-blackpink",
            "140": "dance-aerobics",
            "141": "emote-hyped",
            "142": "dance-jinglebell",
            "143": "idle-nervous",
            "144": "idle-toilet",
            "145": "emote-attention",
            "146": "sit-open",
            "147": "emote-astronaut",
            "148": "dance-zombie",
            "149": "emoji-ghost",
            "150": "emote-hearteyes",
            "151": "emote-swordfight",
            "152": "emote-timejump",
            "153": "emote-snake",
            "154": "emote-heartfingers",
            "155": "emote-heartshape",
            "156": "emote-hug",
            "157": "emote-lagughing",
            "158": "emoji-eyeroll",
            "159": "emote-embarrassed",
            "160": "emote-float",
            "161": "emote-telekinesis",
            "162": "dance-sexy",
            "163": "emote-puppet",
            "164": "idle-fighter",
            "165": "dance-pinguin",
            "166": "dance-creepypuppet",
            "167": "emote-sleigh",
            "168": "emote-maniac",
            "169": "emote-energyball",
            "170": "idle_singing",
            "171": "emote-frog",
            "172": "emote-superpose",
            "173": "emote-cute",
            "174": "dance-tiktok9",
            "175": "dance-weird",
            "176": "dance-tiktok10",
            "177": "emote-pose7",
            "178": "emote-pose8",
            "179": "idle-dance-casual",
            "180": "emote-pose1",
            "181": "emote-pose3",
            "182": "emote-pose5",
            "183": "emote-cutey",
            "184": "emote-punkguitar",
            "185": "emote-zombierun",
            "186": "dance-jinglebell",
            "187": "emote-gravity",
            "188": "dance-icecream",
            "189": "dance-wrong",
            "190": "idle-uwu",
            "191": "idle-dance-tiktok4",
            "192": "emote-shy2",
            "193": "dance-anime",
            "194": "dance-kawai",
            "195": "idle-wild",
            "196": "emote-iceskating",
            "197": "emote-pose6",
            "198": "emote-celebrationstep",
            "199": "emote-creepycute",
            "200": "emote-frustrated",
            "201": "emote-pose10",
            "202": "sit-relaxed",
            "203": "emote-stargaze",
            "204": "emote-slap",
            "205": "emote-boxer",
            "206": "emote-headblowup",
            "207": "emote-kawaiigogo",
            "208": "emote-repose",
            "209": "idle-dance-tiktok7",
            "210": "emote-shrink",
            "211": "emote-pose9",
            "212": "emote-teleporting",
            "213": "dance-touch",
            "214": "idle-guitar",
            "215": "emote-gift",
            "216": "dance-employee",
            "217": "emote-kissing",
            "218": "dance-tiktok11",
            "219": "emote-cutesalute",
            "220": "emote-salute",
            "221": "idle-floorsleeping2",
            "222": "dance-floss",
            "223": "dance-tiktok11",
            "224": "dance-tiktok12",
            "225": "dance-tiktok13",
            "226": "emote-spiderman",
            "227": "dance-breakdance",
            "228": "dance-twerk",
            "229": "idle-space",
            "230": "sit-idle-cute",
            "231": "dance-true-heart",
            "232": "dance-griddy",
            "233": "dance-ballet",
            "234": "dance-freshprince",
            "235": "emote-idle-daydreaming",
            "236": "emote-graceful",
            "237": "dance-spiritual",
            "238": "dance-popularvibe",
            "239": "sit-idle-laidBack",
            "240": "dance-martial-artist",
            "241": "dance-swagbounce",
            "242": "emote-lust",
            "243": "dance-woah",
            "244": "dance-mine",
            "245": "emote-blowkisses",
            "246": "emote-hero",
            "247": "dance-shuffle",
            "248": "emote-knocking-screen",
            "249": "emote-alice-shrink",
            "250": "emote-threadexchange-star",
            "251": "dance-twerk",
            "252": "emote-meditate-idle",
            "301": "emote-adoringfans",
            "302": "emote-afk-idle",
            # 🆕 ایموت‌های جدید (طبق لینک‌های high.rs) — با عدد، اسم انگلیسی، اسم فارسی و شناسه‌ی خام قابل اجراست
            "303": "emote-sixseven",
            "sixseven": "emote-sixseven",
            "six seven": "emote-sixseven",
            "6ix9even": "emote-sixseven",
            "سیکس‌سون": "emote-sixseven",
            "سیکس سون": "emote-sixseven",
            "شصت‌وهفت": "emote-sixseven",
            "304": "emote-sixseven-noimg",
            "sixseven noimg": "emote-sixseven-noimg",
            "sixseve noimg": "emote-sixseven-noimg",
            "سیکس‌سون بدون‌عکس": "emote-sixseven-noimg",
            "سیکس سون بدون عکس": "emote-sixseven-noimg",
            "۳۰۳": "emote-sixseven",
            "۳۰۴": "emote-sixseven-noimg",
            "305": "emote-scuba-dance",
            "۳۰۵": "emote-scuba-dance",
            "scubadance": "emote-scuba-dance",
            "scuba dance": "emote-scuba-dance",
            "اسکوبا": "emote-scuba-dance",
            "دنس اسکوبا": "emote-scuba-dance",
            "306": "emote-modelwalk",
            "۳۰۶": "emote-modelwalk",
            "modelwalk": "emote-modelwalk",
            "model walk": "emote-modelwalk",
            "مدل واک": "emote-modelwalk",
            "راه رفتن مدلی": "emote-modelwalk",
            "307": "sit-idle-springSun",
            "۳۰۷": "sit-idle-springSun",
            "springsun": "sit-idle-springSun",
            "spring sun": "sit-idle-springSun",
            "نشستن بهاری": "sit-idle-springSun",
            "308": "emote-rainstruck-fail",
            "۳۰۸": "emote-rainstruck-fail",
            "rainstruck": "emote-rainstruck-fail",
            "rainstruck fail": "emote-rainstruck-fail",
            "رین‌استراک": "emote-rainstruck-fail",
            "۱": "idle_zombie",
            "۲": "idle_layingdown2",
            "۳": "idle_layingdown",
            "۴": "idle-sleep",
            "۵": "idle-sad",
            "۶": "idle-posh",
            "۷": "idle-loop-tired",
            "۸": "idle-loop-tapdance",
            "۹": "idle-loop-sitfloor",
            "۱۰": "idle-loop-shy",
            "۱۱": "idle-loop-sad",
            "۱۲": "idle-loop-happy",
            "۱۳": "idle-loop-annoyed",
            "۱۴": "idle-loop-aerobics",
            "۱۵": "idle-lookup",
            "۱۶": "idle-hero",
            "۱۷": "idle-floorsleeping",
            "۱۸": "idle-enthusiastic",
            "۱۹": "idle-dance-swinging",
            "۲۰": "idle-dance-headbobbing",
            "۲۱": "idle-angry",
            "۲۲": "emote-yes",
            "۲۳": "emote-wings",
            "۲۴": "emote-wave",
            "۲۵": "emote-tired",
            "۲۶": "emote-think",
            "۲۷": "emote-theatrical",
            "۲۸": "emote-tapdance",
            "۲۹": "emote-superrun",
            "۳۰": "emote-superpunch",
            "۳۱": "emote-sumo",
            "۳۲": "emote-suckthumb",
            "۳۳": "emote-splitsdrop",
            "۳۴": "emote-snowball",
            "۳۵": "emote-snowangel",
            "۳۶": "emote-shy",
            "۳۷": "emote-secrethandshake",
            "۳۸": "emote-sad",
            "۳۹": "emote-ropepull",
            "۴۰": "emote-roll",
            "۴۱": "emote-rofl",
            "۴۲": "emote-robot",
            "۴۳": "emote-rainbow",
            "۴۴": "emote-proposing",
            "۴۵": "emote-peekaboo",
            "۴۶": "emote-peace",
            "۴۷": "emote-panic",
            "۴۸": "emote-no",
            "۴۹": "emote-ninjarun",
            "۵۰": "emote-nightfever",
            "۵۱": "emote-monster_fail",
            "۵۲": "emote-model",
            "۵۳": "emote-lust",
            "۵۴": "emote-levelup",
            "۵۵": "emote-laughing2",
            "۵۶": "emote-laughing",
            "۵۷": "emote-kiss",
            "۵۸": "emote-kicking",
            "۵۹": "emote-jumpb",
            "۶۰": "emote-gravity",
            "۶۱": "emote-judochop",
            "۶۲": "emote-jetpack",
            "۶۳": "emote-hugyourself",
            "۶۴": "emote-hot",
            "۶۵": "emote-hero",
            "۶۶": "emote-hello",
            "۶۷": "emote-headball",
            "۶۸": "emote-harlemshake",
            "۶۹": "emote-happy",
            "۷۰": "emote-handstand",
            "۷۱": "emote-greedy",
            "۷۲": "emote-graceful",
            "۷۳": "emote-gordonshuffle",
            "۷۴": "emote-ghost-idle",
            "۷۵": "emote-gangnam",
            "۷۶": "emote-frollicking",
            "۷۷": "emote-fainting",
            "۷۸": "emote-fail2",
            "۷۹": "emote-fail1",
            "۸۰": "emote-exasperatedb",
            "۸۱": "emote-exasperated",
            "۸۲": "emote-elbowbump",
            "۸۳": "emote-disco",
            "۸۴": "emote-disappear",
            "۸۵": "emote-deathdrop",
            "۸۶": "emote-death2",
            "۸۷": "emote-death",
            "۸۸": "emote-dab",
            "۸۹": "emote-curtsy",
            "۹۰": "emote-confused",
            "۹۱": "emote-cold",
            "۹۲": "emote-charging",
            "۹۳": "emote-bunnyhop",
            "۹۴": "emote-bow",
            "۹۵": "emote-boo",
            "۹۶": "emote-baseball",
            "۹۷": "emote-apart",
            "۹۸": "emoji-thumbsup",
            "۹۹": "emoji-there",
            "۱۰۰": "emoji-sneeze",
            "۱۰۱": "emoji-smirking",
            "۱۰۲": "emoji-sick",
            "۱۰۳": "emoji-scared",
            "۱۰۴": "emoji-punch",
            "۱۰۵": "emoji-pray",
            "۱۰۶": "emoji-poop",
            "۱۰۷": "emoji-naughty",
            "۱۰۸": "emoji-mind-blown",
            "۱۰۹": "emoji-lying",
            "۱۱۰": "emoji-halo",
            "۱۱۱": "emoji-hadoken",
            "۱۱۲": "emoji-give-up",
            "۱۱۳": "emoji-gagging",
            "۱۱۴": "emoji-flex",
            "۱۱۵": "emoji-dizzy",
            "۱۱۶": "emoji-cursing",
            "۱۱۷": "emoji-crying",
            "۱۱۸": "emoji-clapping",
            "۱۱۹": "emoji-celebrate",
            "۱۲۰": "emoji-arrogance",
            "۱۲۱": "emoji-angry",
            "۱۲۲": "dance-voguehands",
            "۱۲۳": "dance-tiktok8",
            "۱۲۴": "dance-tiktok2",
            "۱۲۵": "dance-spiritual",
            "۱۲۶": "dance-smoothwalk",
            "۱۲۷": "dance-singleladies",
            "۱۲۸": "dance-shoppingcart",
            "۱۲۹": "dance-russian",
            "۱۳۰": "dance-robotic",
            "۱۳۱": "dance-pennywise",
            "۱۳۲": "dance-orangejustice",
            "۱۳۳": "dance-metal",
            "۱۳۴": "dance-martial-artist",
            "۱۳۵": "dance-macarena",
            "۱۳۶": "dance-handsup",
            "۱۳۷": "dance-duckwalk",
            "۱۳۸": "dance-breakdance",
            "۱۳۹": "dance-blackpink",
            "۱۴۰": "dance-aerobics",
            "۱۴۱": "emote-hyped",
            "۱۴۲": "dance-jinglebell",
            "۱۴۳": "idle-nervous",
            "۱۴۴": "idle-toilet",
            "۱۴۵": "emote-attention",
            "۱۴۶": "sit-open",
            "۱۴۷": "emote-astronaut",
            "۱۴۸": "dance-zombie",
            "۱۴۹": "emoji-ghost",
            "۱۵۰": "emote-hearteyes",
            "۱۵۱": "emote-swordfight",
            "۱۵۲": "emote-timejump",
            "۱۵۳": "emote-snake",
            "۱۵۴": "emote-heartfingers",
            "۱۵۵": "emote-heartshape",
            "۱۵۶": "emote-hug",
            "۱۵۷": "emote-lagughing",
            "۱۵۸": "emoji-eyeroll",
            "۱۵۹": "emote-embarrassed",
            "۱۶۰": "emote-float",
            "۱۶۱": "emote-telekinesis",
            "۱۶۲": "dance-sexy",
            "۱۶۳": "emote-puppet",
            "۱۶۴": "idle-fighter",
            "۱۶۵": "dance-pinguin",
            "۱۶۶": "dance-creepypuppet",
            "۱۶۷": "emote-sleigh",
            "۱۶۸": "emote-maniac",
            "۱۶۹": "emote-energyball",
            "۱۷۰": "idle_singing",
            "۱۷۱": "emote-frog",
            "۱۷۲": "emote-superpose",
            "۱۷۳": "emote-cute",
            "۱۷۴": "dance-tiktok9",
            "۱۷۵": "dance-weird",
            "۱۷۶": "dance-tiktok10",
            "۱۷۷": "emote-pose7",
            "۱۷۸": "emote-pose8",
            "۱۷۹": "idle-dance-casual",
            "۱۸۰": "emote-pose1",
            "۱۸۱": "emote-pose3",
            "۱۸۲": "emote-pose5",
            "۱۸۳": "emote-cutey",
            "۱۸۴": "emote-punkguitar",
            "۱۸۵": "emote-zombierun",
            "۱۸۶": "dance-jinglebell",
            "۱۸۷": "emote-gravity",
            "۱۸۸": "dance-icecream",
            "۱۸۹": "dance-wrong",
            "۱۹۰": "idle-uwu",
            "۱۹۱": "idle-dance-tiktok4",
            "۱۹۲": "emote-shy2",
            "۱۹۳": "dance-anime",
            "۱۹۴": "dance-kawai",
            "۱۹۵": "idle-wild",
            "۱۹۶": "emote-iceskating",
            "۱۹۷": "emote-pose6",
            "۱۹۸": "emote-celebrationstep",
            "۱۹۹": "emote-creepycute",
            "۲۰۰": "emote-frustrated",
            "۲۰۱": "emote-pose10",
            "۲۰۲": "sit-relaxed",
            "۲۰۳": "emote-stargaze",
            "۲۰۴": "emote-slap",
            "۲۰۵": "emote-boxer",
            "۲۰۶": "emote-headblowup",
            "۲۰۷": "emote-kawaiigogo",
            "۲۰۸": "emote-repose",
            "۲۰۹": "idle-dance-tiktok7",
            "۲۱۰": "emote-shrink",
            "۲۱۱": "emote-pose9",
            "۲۱۲": "emote-teleporting",
            "۲۱۳": "dance-touch",
            "۲۱۴": "idle-guitar",
            "۲۱۵": "emote-gift",
            "۲۱۶": "dance-employee",
            "۲۱۷": "emote-kissing",
            "۲۱۸": "dance-tiktok11",
            "۲۱۹": "emote-cutesalute",
            "۲۲۰": "emote-salute",
            "۲۲۱": "idle-floorsleeping2",
            "۲۲۲": "dance-floss",
            "۲۲۳": "dance-tiktok11",
            "۲۲۴": "dance-tiktok12",
            "۲۲۵": "dance-tiktok13",
            "۲۲۶": "emote-spiderman",
            "۲۲۷": "dance-breakdance",
            "۲۲۸": "dance-twerk",
            "۲۲۹": "idle-space",
            "۲۳۰": "sit-idle-cute",
            "۲۳۱": "dance-true-heart",
            "۲۳۲": "dance-griddy",
            "۲۳۳": "dance-ballet",
            "۲۳۴": "dance-freshprince",
            "۲۳۵": "emote-idle-daydreaming",
            "۲۳۶": "emote-graceful",
            "۲۳۷": "dance-spiritual",
            "۲۳۸": "dance-popularvibe",
            "۲۳۹": "sit-idle-laidBack",
            "۲۴۰": "dance-martial-artist",
            "۲۴۱": "dance-swagbounce",
            "۲۴۲": "emote-lust",
            "۲۴۳": "dance-woah",
            "۲۴۴": "dance-mine",
            "۲۴۵": "emote-blowkisses",
            "۲۴۶": "emote-hero",
            "۲۴۷": "dance-shuffle",
            "۲۴۸": "emote-knocking-screen",
            "۲۴۹": "emote-alice-shrink",
            "۲۵۰": "emote-threadexchange-star",
            "۲۵۱": "dance-twerk",
            "۲۵۲": "emote-meditate-idle",
            "۳۰۱": "emote-adoringfans",
            "۳۰۲": "emote-afk-idle",
            "zombie": "idle_zombie",
            "relaxed": "idle_layingdown2",
            "attentive": "idle_layingdown",
            "sleepy": "idle-sleep",
            "poutyFace": "idle-sad",
            "posh": "idle-posh",
            "tiredloop": "idle-loop-tired",
            "tapLoop": "idle-loop-tapdance",
            "sit": "idle-loop-sitfloor",
            "shy": "idle-loop-shy",
            "bummed": "idle-loop-sad",
            "chillin'": "idle-loop-happy",
            "annoyed": "idle-loop-annoyed",
            "loopaerobics": "idle-loop-aerobics",
            "ponder": "idle-lookup",
            "heropose": "idle-hero",
            "cozynap": "idle-floorsleeping",
            "enthused": "idle-enthusiastic",
            "boogieswing": "idle-dance-swinging",
            "feelthebeat": "idle-dance-headbobbing",
            "irritated": "idle-angry",
            "yes": "emote-yes",
            "ibelieveIcanfly": "emote-wings",
            "theWave": "emote-wave",
            "tired": "emote-tired",
            "think": "emote-think",
            "afk": "emote-afk-idle",
            "theatrical": "emote-theatrical",
            "tapdance": "emote-tapdance",
            "superrun": "emote-superrun",
            "superPunch": "emote-superpunch",
            "sumofight": "emote-sumo",
            "thumbSuck": "emote-suckthumb",
            "splitsdrop": "emote-splitsdrop",
            "snowballFight": "emote-snowball",
            "snowAngel": "emote-snowangel",
            "shyemote": "emote-shy",
            "secrehandshake": "emote-secrethandshake",
            "sad": "emote-sad",
            "adoringfans": "emote-adoringfans",
            "ropepull": "emote-ropepull",
            "roll": "emote-roll",
            "rofl": "emote-rofl",
            "robot": "emote-robot",
            "rainbow": "emote-rainbow",
            "proposing": "emote-proposing",
            "peekaboo": "emote-peekaboo",
            "peace": "emote-peace",
            "panic": "emote-panic",
            "no": "emote-no",
            "ninjarun": "emote-ninjarun",
            "nightfever": "emote-nightfever",
            "monsterfail": "emote-monster_fail",
            "model": "emote-model",
            "flirtywave": "emote-lust",
            "levelUp": "emote-levelup",
            "amused": "emote-laughing2",
            "laugh": "emote-laughing",
            "kiss": "emote-kiss",
            "superKick": "emote-kicking",
            "jump": "emote-jumpb",
            "gravity": "emote-gravity",
            "judochop": "emote-judochop",
            "imaginaryjetpack": "emote-jetpack",
            "hugyourself": "emote-hugyourself",
            "sweating": "emote-hot",
            "heroentrance": "emote-hero",
            "hello": "emote-hello",
            "headball": "emote-headball",
            "harlemShake": "emote-harlemshake",
            "happy": "emote-happy",
            "handstand": "emote-handstand",
            "greedyEmote": "emote-greedy",
            "graceful": "emote-graceful",
            "moonwalk": "emote-gordonshuffle",
            "ghostfloat": "emote-ghost-idle",
            "gangnamstyle": "emote-gangnam",
            "frolic": "emote-frollicking",
            "faint": "emote-fainting",
            "clumsy": "emote-fail2",
            "fall": "emote-fail1",
            "facePalm": "emote-exasperatedb",
            "exasperated": "emote-exasperated",
            "elbowBump": "emote-elbowbump",
            "disco": "emote-disco",
            "blastOff": "emote-disappear",
            "faintDrop": "emote-deathdrop",
            "collapse": "emote-death2",
            "revival": "emote-death",
            "dab": "emote-dab",
            "curtsy": "emote-curtsy",
            "confusion": "emote-confused",
            "cold": "emote-cold",
            "charging": "emote-charging",
            "bunnyHop": "emote-bunnyhop",
            "bow": "emote-bow",
            "boo": "emote-boo",
            "homerun": "emote-baseball",
            "fallingapart": "emote-apart",
            "thumbsup": "emoji-thumbsup",
            "point": "emoji-there",
            "sneeze": "emoji-sneeze",
            "smirk": "emoji-smirking",
            "sick": "emoji-sick",
            "gasp": "emoji-scared",
            "punch": "emoji-punch",
            "pray": "emoji-pray",
            "stinky": "emoji-poop",
            "naughty": "emoji-naughty",
            "mindBlown": "emoji-mind-blown",
            "lying": "emoji-lying",
            "levitate": "emoji-halo",
            "fireball Lunge": "emoji-hadoken",
            "giveup": "emoji-give-up",
            "tummy Ache": "emoji-gagging",
            "flex": "emoji-flex",
            "stunned": "emoji-dizzy",
            "cursing Emote": "emoji-cursing",
            "sob": "emoji-crying",
            "clap": "emoji-clapping",
            "raiseTheRoof": "emoji-celebrate",
            "arrogance": "emoji-arrogance",
            "angry": "emoji-angry",
            "VogueHands": "dance-voguehands",
            "SavageDance": "dance-tiktok8",
            "DontStartNow": "dance-tiktok2",
            "YogaFlow": "dance-spiritual",
            "Smoothwalk": "dance-smoothwalk",
            "RingonIt": "dance-singleladies",
            "Let's Go Shopping": "dance-shoppingcart",
            "russian Dance": "dance-russian",
            "tobotic": "dance-robotic",
            "penny's Dance": "dance-pennywise",
            "orange Juice Dance": "dance-orangejustice",
            "rockout": "dance-metal",
            "karate": "dance-martial-artist",
            "macarena": "dance-macarena",
            "handsintheair": "dance-handsup",
            "duckealk": "dance-duckwalk",
            "Breakdance": "dance-breakdance",
            "kpop": "dance-blackpink",
            "PushUps": "dance-aerobics",
            "Hyped": "emote-hyped",
            "Jinglebell": "dance-jinglebell",
            "Nervous": "idle-nervous",
            "Toilet": "idle-toilet",
            "Attention": "emote-attention",
            "laidback": "sit-open",
            "Astronaut": "emote-astronaut",
            "DanceZombie": "dance-zombie",
            "ghost": "emoji-ghost",
            "HeartEyes": "emote-hearteyes",
            "Swordfight": "emote-swordfight",
            "TimeJump": "emote-timejump",
            "Snake": "emote-snake",
            "HeartFingers": "emote-heartfingers",
            "Heart Shape": "emote-heartshape",
            "hug": "emote-hug",
            "Laugh": "emote-lagughing",
            "Eyeroll": "emoji-eyeroll",
            "Embarrassed": "emote-embarrassed",
            "float": "emote-float",
            "Telekinesis": "emote-telekinesis",
            "Sexydance": "dance-sexy",
            "Puppet": "emote-puppet",
            "Fighter idle": "idle-fighter",
            "Penguindance": "dance-pinguin",
            "Creepypuppet": "dance-creepypuppet",
            "Sleigh": "emote-sleigh",
            "Maniac": "emote-maniac",
            "EnergyBall": "emote-energyball",
            "Singing": "idle_singing",
            "Frog": "emote-frog",
            "Superpose": "emote-superpose",
            "Cute": "emote-cute",
            "TikTok9": "dance-tiktok9",
            "Weird": "dance-weird",
            "TikTok10": "dance-tiktok10",
            "pose7": "emote-pose7",
            "pose8": "emote-pose8",
            "casualDance": "idle-dance-casual",
            "pose1": "emote-pose1",
            "pose3": "emote-pose3",
            "pose5": "emote-pose5",
            "Cutey": "emote-cutey",
            "PunkGuitar": "emote-punkguitar",
            "zombieru": "emote-zombierun",
            "fashionista": "dance-jinglebell",
            "icecream": "dance-icecream",
            "wrong": "dance-wrong",
            "uwu": "idle-uwu",
            "TikTok4": "idle-dance-tiktok4",
            "advancedshy": "emote-shy2",
            "anime": "dance-anime",
            "kawaii": "dance-kawai",
            "Scritchy": "idle-wild",
            "iceskating": "emote-iceskating",
            "surpriseBig": "emote-pose6",
            "celebrationStep": "emote-celebrationstep",
            "creepycute": "emote-creepycute",
            "frustrated": "emote-frustrated",
            "pose10": "emote-pose10",
            "relaxedsit": "sit-relaxed",
            "stargazing": "emote-stargaze",
            "slap": "emote-slap",
            "boxer": "emote-boxer",
            "headBlowup": "emote-headblowup",
            "kawaiiGoGo": "emote-kawaiigogo",
            "repose": "emote-repose",
            "tiktok7": "idle-dance-tiktok7",
            "shrink": "emote-shrink",
            "ditzyPose": "emote-pose9",
            "teleporting": "emote-teleporting",
            "touch": "dance-touch",
            "airuitar": "idle-guitar",
            "thisIs For You": "emote-gift",
            "pushit": "dance-employee",
            "sweetSmooch": "emote-kissing",
            "tiktok11": "dance-tiktok11",
            "cutesalute": "emote-cutesalute",
            "relaxing": "idle-floorsleeping2",
            "attention": "emote-salute",
            "floss": "dance-floss",
            "rest": "sit-idle-cute",
            "twerk": "dance-twerk",
            "zenmode": "emote-meditate-idle",
            "aliceshrink": "emote-alice-shrink",
            "threadexchangestar": "emote-threadexchange-star",
            "253": "dance-hipshake",
            "۲۵۳": "dance-hipshake",
            "hipshake": "dance-hipshake",
            "254": "emote-stargazer",
            "۲۵۴": "emote-stargazer",
            "stargazer": "emote-stargazer",
            "255": "emote-launch",
            "۲۵۵": "emote-launch",
            "launch": "emote-launch",
            "256": "dance-cheerleader",
            "۲۵۶": "dance-cheerleader",
            "cheerleader": "dance-cheerleader",
            "257": "emote-collab-photo-right",
            "۲۵۷": "emote-collab-photo-right",
            "collabphoto": "emote-collab-photo-right",
            "258": "emote-hearteyes",
            "۲۵۸": "emote-hearteyes",
            "hearteyes": "emote-hearteyes",
            "259": "dance-hipshake",
            "۲۵۹": "dance-hipshake",
            "260": "dance-popularvibe",
            "۲۶۰": "dance-popularvibe",
            "popularvibe": "dance-popularvibe",
            "261": "emote-kissing",
            "۲۶۱": "emote-kissing",
            "kissing": "emote-kissing",
            "262": "emote-lust",
            "۲۶۲": "emote-lust",
            "lust": "emote-lust",
            "263": "emote-shrink",
            "۲۶۳": "emote-shrink",
            "264": "sit-open",
            "۲۶۴": "sit-open",
            "open": "sit-open",
            "265": "dance-touch",
            "۲۶۵": "dance-touch",
            "266": "dance-shuffle",
            "۲۶۶": "dance-shuffle",
            "shuffle": "dance-shuffle",
            "267": "idle-floorsleeping",
            "۲۶۷": "idle-floorsleeping",
            "floorsleeping": "idle-floorsleeping",
            "268": "sit-idle-laidBack",
            "۲۶۸": "sit-idle-laidBack",
            "idlelaidback": "sit-idle-laidBack",
            "269": "emote-ghost-idle",
            "۲۶۹": "emote-ghost-idle",
            "ghostidle": "emote-ghost-idle",
            "270": "dance-true-heart",
            "۲۷۰": "dance-true-heart",
            "trueheart": "dance-true-heart",
            "271": "dance-breakdance",
            "۲۷۱": "dance-breakdance",
            "breakdance": "dance-breakdance",
            "272": "emote-proposing",
            "۲۷۲": "emote-proposing",
            "273": "emote-stargazer",
            "۲۷۳": "emote-stargazer",
            "274": "dance-anime",
            "۲۷۴": "dance-anime",
            "275": "emote-disappear",
            "۲۷۵": "emote-disappear",
            "disappear": "emote-disappear",
            "276": "dance-spiritual",
            "۲۷۶": "dance-spiritual",
            "spiritual": "dance-spiritual",
            "277": "emote-bunnyhop",
            "۲۷۷": "emote-bunnyhop",
            "bunnyhop": "emote-bunnyhop",
            "278": "idle-space",
            "۲۷۸": "idle-space",
            "space": "idle-space",
            "279": "emoji-poop",
            "۲۷۹": "emoji-poop",
            "poop": "emoji-poop",
            "280": "emoji-mind-blown",
            "۲۸۰": "emoji-mind-blown",
            "mindblown": "emoji-mind-blown",
            "281": "emote-launch",
            "۲۸۱": "emote-launch",
            "282": "emoji-lying",
            "۲۸۲": "emoji-lying",
            "283": "emote-creepycute",
            "۲۸۳": "emote-creepycute",
            "284": "dance-martial-artist",
            "۲۸۴": "dance-martial-artist",
            "martialartist": "dance-martial-artist",
            "285": "emote-frog",
            "۲۸۵": "emote-frog",
            "frog": "emote-frog",
            "286": "emote-knocking-screen",
            "۲۸۶": "emote-knocking-screen",
            "knockingscreen": "emote-knocking-screen",
            "287": "dance-ballet",
            "۲۸۷": "dance-ballet",
            "ballet": "dance-ballet",
            "288": "dance-aerobics",
            "۲۸۸": "dance-aerobics",
            "aerobics": "dance-aerobics",
            "289": "emote-blowkisses",
            "۲۸۹": "emote-blowkisses",
            "blowkisses": "emote-blowkisses",
            "290": "idle-guitar",
            "۲۹۰": "idle-guitar",
            "guitar": "idle-guitar",
            "291": "dance-griddy",
            "۲۹۱": "dance-griddy",
            "griddy": "dance-griddy",
            "292": "emoji-cursing",
            "۲۹۲": "emoji-cursing",
            "cursing": "emoji-cursing",
            "293": "emote-teleporting",
            "۲۹۳": "emote-teleporting",
            "294": "dance-cheerleader",
            "۲۹۴": "dance-cheerleader",
            "295": "emote-charging",
            "۲۹۵": "emote-charging",
            "296": "emote-superrun",
            "۲۹۶": "emote-superrun",
            "297": "dance-robotic",
            "۲۹۷": "dance-robotic",
            "robotic": "dance-robotic",
            "298": "emote-snowangel",
            "۲۹۸": "emote-snowangel",
            "snowangel": "emote-snowangel",
            "299": "dance-wrong",
            "۲۹۹": "dance-wrong",
            "300": "emote-collab-photo-right",
            "۳۰۰": "emote-collab-photo-right",
            "collabphotoright": "emote-collab-photo-right",
            "309": "emote-sicklycute-sing-fast",
            "۳۰۹": "emote-sicklycute-sing-fast",
            "emotesicklycutesingfast": "emote-sicklycute-sing-fast",
            "310": "emote-sicklycute-sing-slow",
            "۳۱۰": "emote-sicklycute-sing-slow",
            "emotesicklycutesingslow": "emote-sicklycute-sing-slow",
            "311": "emote-fashionista",
            "۳۱۱": "emote-fashionista",
            "emotefashionista": "emote-fashionista",
            "312": "dance-touc",
            "۳۱۲": "dance-touc",
            "dancetouc": "dance-touc",
            "313": "idle_tough",
            "۳۱۳": "idle_tough",
            "idletough": "idle_tough",
            "314": "emote-fail3",
            "۳۱۴": "emote-fail3",
            "emotefail3": "emote-fail3",
            "315": "emote-theatrical-test",
            "۳۱۵": "emote-theatrical-test",
            "emotetheatricaltest": "emote-theatrical-test",
            "316": "run-vertical",
            "۳۱۶": "run-vertical",
            "runvertical": "run-vertical",
            "317": "emote-receive-disappointed",
            "۳۱۷": "emote-receive-disappointed",
            "emotereceivedisappointed": "emote-receive-disappointed",
            "318": "walk-vertical",
            "۳۱۸": "walk-vertical",
            "walkvertical": "walk-vertical",
            "319": "emote-confused2",
            "۳۱۹": "emote-confused2",
            "emoteconfused2": "emote-confused2",
            "320": "mining-mine",
            "۳۲۰": "mining-mine",
            "miningmine": "mining-mine",
            "321": "mining-success",
            "۳۲۱": "mining-success",
            "miningsuccess": "mining-success",
            "322": "mining-fail",
            "۳۲۲": "mining-fail",
            "miningfail": "mining-fail",
            "323": "fishing-pull",
            "۳۲۳": "fishing-pull",
            "fishingpull": "fishing-pull",
            "324": "fishing-idle",
            "۳۲۴": "fishing-idle",
            "fishingidle": "fishing-idle",
            "325": "fishing-cast",
            "۳۲۵": "fishing-cast",
            "fishingcast": "fishing-cast",
            "326": "fishing-pull-small",
            "۳۲۶": "fishing-pull-small",
            "fishingpullsmall": "fishing-pull-small",
            "327": "dance-fruity",
            "۳۲۷": "dance-fruity",
            "dancefruity": "dance-fruity",
            "328": "dance-tiktok14",
            "۳۲۸": "dance-tiktok14",
            "dancetiktok14": "dance-tiktok14",
            "329": "emote-looping",
            "۳۲۹": "emote-looping",
            "emotelooping": "emote-looping",
            "330": "idle-floating",
            "۳۳۰": "idle-floating",
            "idlefloating": "idle-floating",
            "331": "dance-wild",
            "۳۳۱": "dance-wild",
            "dancewild": "dance-wild",
            "332": "emote-howl",
            "۳۳۲": "emote-howl",
            "emotehowl": "emote-howl",
            "333": "idle-howl",
            "۳۳۳": "idle-howl",
            "idlehowl": "idle-howl",
            "334": "emote-trampoline",
            "۳۳۴": "emote-trampoline",
            "emotetrampoline": "emote-trampoline",
            "335": "emote-holding-hot-cocoa",
            "۳۳۵": "emote-holding-hot-cocoa",
            "emoteholdinghotcocoa": "emote-holding-hot-cocoa",
            "336": "emote-mittens",
            "۳۳۶": "emote-mittens",
            "emotemittens": "emote-mittens",
            "337": "emote-littlemonsters-dance",
            "۳۳۷": "emote-littlemonsters-dance",
            "emotelittlemonstersdance": "emote-littlemonsters-dance",
            "338": "emote-threadexchange-floating",
            "۳۳۸": "emote-threadexchange-floating",
            "emotethreadexchangefloating": "emote-threadexchange-floating",
            "339": "emote-jewelrise-vibing",
            "۳۳۹": "emote-jewelrise-vibing",
            "emotejewelrisevibing": "emote-jewelrise-vibing",
            "340": "stop",
            "۳۴۰": "stop",
            "stop": "stop",
            "341": "emote-pose-sit",
            "۳۴۱": "emote-pose-sit",
            "emoteposesit": "emote-pose-sit",
            "342": "emote-pose-stand1",
            "۳۴۲": "emote-pose-stand1",
            "emoteposestand1": "emote-pose-stand1",
            "343": "emote-pose-goth1",
            "۳۴۳": "emote-pose-goth1",
            "emoteposegoth1": "emote-pose-goth1",
            "344": "emote-pose-goth2",
            "۳۴۴": "emote-pose-goth2",
            "emoteposegoth2": "emote-pose-goth2",
            "345": "emote-pose-goth3",
            "۳۴۵": "emote-pose-goth3",
            "emoteposegoth3": "emote-pose-goth3",
            "346": "emote-bloomify-pose1",
            "۳۴۶": "emote-bloomify-pose1",
            "emotebloomifypose1": "emote-bloomify-pose1",
            "347": "emote-bloomify-pose2",
            "۳۴۷": "emote-bloomify-pose2",
            "emotebloomifypose2": "emote-bloomify-pose2",
            "348": "emote-bloomify-pose3",
            "۳۴۸": "emote-bloomify-pose3",
            "emotebloomifypose3": "emote-bloomify-pose3",
            "349": "emote-sugarbite-pose1",
            "۳۴۹": "emote-sugarbite-pose1",
            "emotesugarbitepose1": "emote-sugarbite-pose1",
            "350": "emote-sugarbite-pose2",
            "۳۵۰": "emote-sugarbite-pose2",
            "emotesugarbitepose2": "emote-sugarbite-pose2",
            "351": "emote-sugarbite-pose3",
            "۳۵۱": "emote-sugarbite-pose3",
            "emotesugarbitepose3": "emote-sugarbite-pose3",
            "352": "emote-punkandlaces-pose1",
            "۳۵۲": "emote-punkandlaces-pose1",
            "emotepunkandlacespose1": "emote-punkandlaces-pose1",
            "353": "emote-punkandlaces-pose2",
            "۳۵۳": "emote-punkandlaces-pose2",
            "emotepunkandlacespose2": "emote-punkandlaces-pose2",
            "354": "emote-punkandlaces-pose3",
            "۳۵۴": "emote-punkandlaces-pose3",
            "emotepunkandlacespose3": "emote-punkandlaces-pose3",
            "355": "emote-offdutyangels-backoff",
            "۳۵۵": "emote-offdutyangels-backoff",
            "emoteoffdutyangelsbackoff": "emote-offdutyangels-backoff",
            "356": "emote-offdutyangels-comehere",
            "۳۵۶": "emote-offdutyangels-comehere",
            "emoteoffdutyangelscomehere": "emote-offdutyangels-comehere",
            "357": "emote-ragdoll",
            "۳۵۷": "emote-ragdoll",
            "emoteragdoll": "emote-ragdoll",
            "358": "emote-kawaiipose",
            "۳۵۸": "emote-kawaiipose",
            "emotekawaiipose": "emote-kawaiipose",
            "359": "emote-collab-celebrate-right",
            "۳۵۹": "emote-collab-celebrate-right",
            "emotecollabcelebrateright": "emote-collab-celebrate-right",
            "360": "emote-collab-celebrate-left",
            "۳۶۰": "emote-collab-celebrate-left",
            "emotecollabcelebrateleft": "emote-collab-celebrate-left",
            "361": "emote-threadexchange-posing",
            "۳۶۱": "emote-threadexchange-posing",
            "emotethreadexchangeposing": "emote-threadexchange-posing",
            "362": "sit-idle-phone-text",
            "۳۶۲": "sit-idle-phone-text",
            "sitidlephonetext": "sit-idle-phone-text",
            "363": "idle-laying-phone-talking",
            "۳۶۳": "idle-laying-phone-talking",
            "idlelayingphonetalking": "idle-laying-phone-talking",
            "364": "emote-phone",
            "۳۶۴": "emote-phone",
            "emotephone": "emote-phone",
            "365": "idle-phone-talking",
            "۳۶۵": "idle-phone-talking",
            "idlephonetalking": "idle-phone-talking",
            "366": "idle-phone-camera",
            "۳۶۶": "idle-phone-camera",
            "idlephonecamera": "idle-phone-camera",
            "367": "dance-wait",
            "۳۶۷": "dance-wait",
            "dancewait": "dance-wait",
            "368": "emote-rifle",
            "۳۶۸": "emote-rifle",
            "emoterifle": "emote-rifle",
            "369": "emote-kissing-bound",
            "۳۶۹": "emote-kissing-bound",
            "emotekissingbound": "emote-kissing-bound",
            "370": "emote-celebrate",
            "۳۷۰": "emote-celebrate",
            "emotecelebrate": "emote-celebrate",
            "371": "emote-coolguy",
            "۳۷۱": "emote-coolguy",
            "emotecoolguy": "emote-coolguy",
            "372": "emote-rifle-throw",
            "۳۷۲": "emote-rifle-throw",
            "emoteriflethrow": "emote-rifle-throw",
            "373": "emote-swing-sneak-Idle",
            "۳۷۳": "emote-swing-sneak-Idle",
            "emoteswingsneakidle": "emote-swing-sneak-Idle",
            "374": "emote-swing-net-3",
            "۳۷۴": "emote-swing-net-3",
            "emoteswingnet3": "emote-swing-net-3",
            "375": "emote-swing-celebrate",
            "۳۷۵": "emote-swing-celebrate",
            "emoteswingcelebrate": "emote-swing-celebrate",
            "376": "emote-swing-net-2",
            "۳۷۶": "emote-swing-net-2",
            "emoteswingnet2": "emote-swing-net-2",
            "377": "emote-swing-net",
            "۳۷۷": "emote-swing-net",
            "emoteswingnet": "emote-swing-net",
            "378": "sit-idle-sleep",
            "۳۷۸": "sit-idle-sleep",
            "sitidlesleep": "sit-idle-sleep",
            "379": "emote-tune-accept",
            "۳۷۹": "emote-tune-accept",
            "emotetuneaccept": "emote-tune-accept",
            "380": "emote-yoga-treePose",
            "۳۸۰": "emote-yoga-treePose",
            "emoteyogatreepose": "emote-yoga-treePose",
            "381": "emote-yoga-warrior2",
            "۳۸۱": "emote-yoga-warrior2",
            "emoteyogawarrior2": "emote-yoga-warrior2",
            "382": "emote-yoga-warrior3",
            "۳۸۲": "emote-yoga-warrior3",
            "emoteyogawarrior3": "emote-yoga-warrior3",
            "383": "emote-pose-stand2",
            "۳۸۳": "emote-pose-stand2",
            "emoteposestand2": "emote-pose-stand2",
            "384": "dance-running-man",
            "۳۸۴": "dance-running-man",
            "dancerunningman": "dance-running-man",
            "385": "emote-yogaSurprise",
            "۳۸۵": "emote-yogaSurprise",
            "emoteyogasurprise": "emote-yogaSurprise",
            "386": "emote-rainstruck-success",
            "۳۸۶": "emote-rainstruck-success",
            "emoterainstrucksuccess": "emote-rainstruck-success",
            "387": "emote-outfit3",
            "۳۸۷": "emote-outfit3",
            "emoteoutfit3": "emote-outfit3",
            "388": "emote-pose13",
            "۳۸۸": "emote-pose13",
            "emotepose13": "emote-pose13",
            "389": "emote-outfit2",
            "۳۸۹": "emote-outfit2",
            "emoteoutfit2": "emote-outfit2",
            "390": "emote-pose12",
            "۳۹۰": "emote-pose12",
            "emotepose12": "emote-pose12",
            "391": "emote-pose11",
            "۳۹۱": "emote-pose11",
            "emotepose11": "emote-pose11",
            "392": "emote-collab-photo-left",
            "۳۹۲": "emote-collab-photo-left",
            "emotecollabphotoleft": "emote-collab-photo-left",
            "393": "emote-inside-out",
            "۳۹۳": "emote-inside-out",
            "emoteinsideout": "emote-inside-out",
            "394": "dance-anime3",
            "۳۹۴": "dance-anime3",
            "danceanime3": "dance-anime3",
            "395": "emote-armcannon",
            "۳۹۵": "emote-armcannon",
            "emotearmcannon": "emote-armcannon",
            "396": "profile-breakscreen",
            "۳۹۶": "profile-breakscreen",
            "profilebreakscreen": "profile-breakscreen",
            "397": "emote-cartwheel",
            "۳۹۷": "emote-cartwheel",
            "emotecartwheel": "emote-cartwheel",
            "398": "idle-cold",
            "۳۹۸": "idle-cold",
            "idlecold": "idle-cold",
            "399": "idle-crouched",
            "۳۹۹": "idle-crouched",
            "idlecrouched": "idle-crouched",
            "400": "emote-dinner",
            "۴۰۰": "emote-dinner",
            "emotedinner": "emote-dinner",
            "401": "emote-dramatic",
            "۴۰۱": "emote-dramatic",
            "emotedramatic": "emote-dramatic",
            "402": "emote-electrified",
            "۴۰۲": "emote-electrified",
            "emoteelectrified": "emote-electrified",
            "403": "emote-fading",
            "۴۰۳": "emote-fading",
            "emotefading": "emote-fading",
            "404": "emote-fireworks",
            "۴۰۴": "emote-fireworks",
            "emotefireworks": "emote-fireworks",
            "405": "emote-flirt",
            "۴۰۵": "emote-flirt",
            "emoteflirt": "emote-flirt",
            "406": "emote-receive-happy",
            "۴۰۶": "emote-receive-happy",
            "emotereceivehappy": "emote-receive-happy",
            "407": "emote-gooey",
            "۴۰۷": "emote-gooey",
            "emotegooey": "emote-gooey",
            "408": "emote-handwalk",
            "۴۰۸": "emote-handwalk",
            "emotehandwalk": "emote-handwalk",
            "409": "idle-headless",
            "۴۰۹": "idle-headless",
            "idleheadless": "idle-headless",
            "410": "dance-hiphop",
            "۴۱۰": "dance-hiphop",
            "dancehiphop": "dance-hiphop",
            "411": "emote-hopscotch",
            "۴۱۱": "emote-hopscotch",
            "emotehopscotch": "emote-hopscotch",
            "412": "idle-dance-tiktok6",
            "۴۱۲": "idle-dance-tiktok6",
            "idledancetiktok6": "idle-dance-tiktok6",
            "413": "hcc-jetpack",
            "۴۱۳": "hcc-jetpack",
            "hccjetpack": "hcc-jetpack",
            "414": "emote-juggling",
            "۴۱۴": "emote-juggling",
            "emotejuggling": "emote-juggling",
            "415": "dance-kid",
            "۴۱۵": "dance-kid",
            "dancekid": "dance-kid",
            "416": "emote-kissing-passionate",
            "۴۱۶": "emote-kissing-passionate",
            "emotekissingpassionate": "emote-kissing-passionate",
            "417": "emote-pose4",
            "۴۱۷": "emote-pose4",
            "emotepose4": "emote-pose4",
            "418": "emote-oops",
            "۴۱۸": "emote-oops",
            "emoteoops": "emote-oops",
            "419": "emote-opera",
            "۴۱۹": "emote-opera",
            "emoteopera": "emote-opera",
            "420": "emote-outfit",
            "۴۲۰": "emote-outfit",
            "emoteoutfit": "emote-outfit",
            "421": "emote-pose2",
            "۴۲۱": "emote-pose2",
            "emotepose2": "emote-pose2",
            "422": "emote-runhop",
            "۴۲۲": "emote-runhop",
            "emoterunhop": "emote-runhop",
            "423": "emote-sheephop",
            "۴۲۳": "emote-sheephop",
            "emotesheephop": "emote-sheephop",
            "424": "emote-shocked",
            "۴۲۴": "emote-shocked",
            "emoteshocked": "emote-shocked",
            "425": "emoji-shush",
            "۴۲۵": "emoji-shush",
            "emojishush": "emoji-shush",
            "426": "sit-chair",
            "۴۲۶": "sit-chair",
            "sitchair": "sit-chair",
            "427": "emote-surf",
            "۴۲۷": "emote-surf",
            "emotesurf": "emote-surf",
            "428": "emote-thief",
            "۴۲۸": "emote-thief",
            "emotethief": "emote-thief",
            "429": "dance-tiktok1",
            "۴۲۹": "dance-tiktok1",
            "dancetiktok1": "dance-tiktok1",
            "430": "dance-tiktok15",
            "۴۳۰": "dance-tiktok15",
            "dancetiktok15": "dance-tiktok15",
            "431": "dance-tiktok16",
            "۴۳۱": "dance-tiktok16",
            "dancetiktok16": "dance-tiktok16",
            "432": "dance-tiktok3",
            "۴۳۲": "dance-tiktok3",
            "dancetiktok3": "dance-tiktok3",
            "433": "dance-tiktok4",
            "۴۳۳": "dance-tiktok4",
            "dancetiktok4": "dance-tiktok4",
            "434": "dance-tiktok5",
            "۴۳۴": "dance-tiktok5",
            "dancetiktok5": "dance-tiktok5",
            "435": "emote-twitched",
            "۴۳۵": "emote-twitched",
            "emotetwitched": "emote-twitched",
            "436": "emote-thought",
            "۴۳۶": "emote-thought",
            "emotethought": "emote-thought",
            "437": "emote-wavey",
            "۴۳۷": "emote-wavey",
            "emotewavey": "emote-wavey",
            "438": "emote-hairssweep",
            "۴۳۸": "emote-hairssweep",
            "emotehairssweep": "emote-hairssweep",
            "439": "emote-collab-tea-left",
            "۴۳۹": "emote-collab-tea-left",
            "emotecollabtealeft": "emote-collab-tea-left",
        }

        # 🆕 دنس‌های کشف‌شده‌ی جدید (از طریق !emotescan) که قبلاً ذخیره شدن رو هم اضافه کن
        # تا کد شماره‌ای، کد فارسی و اسمشون بعد از هر بار روشن شدن ربات هم باقی بمونه.
        self.emotes.update(self.config.get("discovered_emotes", {}))

        self.emote_durations = {
            "idle_zombie": 28.75,
            "idle_layingdown2": 20.55,
            "idle_layingdown": 10.0,
            "idle-sleep": 22.62,
            "idle-sad": 24.38,
            "idle-posh": 21.85,
            "idle-loop-tired": 21.959,
            "idle-loop-tapdance": 6.26,
            "idle-loop-sitfloor": 22.32,
            "idle-loop-shy": 16.474,
            "idle-loop-sad": 6.05,
            "idle-loop-happy": 18.8,
            "idle-loop-annoyed": 17.06,
            "idle-loop-aerobics": 8.51,
            "idle-lookup": 22.34,
            "idle-hero": 20.88,
            "idle-floorsleeping": 10.0,
            "idle-enthusiastic": 15.94,
            "idle-dance-swinging": 20.0,
            "idle-dance-headbobbing": 25.37,
            "idle-angry": 25.43,
            "emote-yes": 1.5,
            "emote-wings": 13.13,
            "emote-wave": 2.69,
            "emote-tired": 4.61,
            "emote-think": 3.69,
            "emote-theatrical": 8.59,
            "emote-tapdance": 11.06,
            "emote-superrun": 6.27,
            "emote-superpunch": 3.75,
            "emote-sumo": 10.87,
            "emote-suckthumb": 4.19,
            "emote-splitsdrop": 4.47,
            "emote-snowball": 5.23,
            "emote-snowangel": 6.22,
            "emote-shy": 4.48,
            "emote-secrethandshake": 3.88,
            "emote-sad": 5.41,
            "emote-ropepull": 8.77,
            "emote-roll": 3.56,
            "emote-rofl": 6.31,
            "emote-robot": 7.61,
            "emote-rainbow": 2.81,
            "emote-proposing": 4.28,
            "emote-peekaboo": 3.63,
            "emote-peace": 5.76,
            "emote-panic": 2.85,
            "emote-no": 2.7,
            "emote-ninjarun": 4.75,
            "emote-nightfever": 5.49,
            "emote-monster_fail": 4.63,
            "emote-model": 6.49,
            "emote-lust": 4.66,
            "emote-levelup": 6.05,
            "emote-laughing2": 5.06,
            "emote-laughing": 2.69,
            "emote-kiss": 2.39,
            "emote-kicking": 4.87,
            "emote-jumpb": 3.58,
            "emote-gravity": 8.96,
            "emote-judochop": 2.43,
            "emote-jetpack": 16.76,
            "emote-hugyourself": 4.99,
            "emote-hot": 4.35,
            "emote-hero": 5.0,
            "emote-hello": 2.73,
            "emote-headball": 20.0,
            "emote-harlemshake": 13.56,
            "emote-happy": 3.48,
            "emote-handstand": 4.02,
            "emote-greedy": 4.64,
            "emote-graceful": 20.0,
            "emote-gordonshuffle": 8.05,
            "emote-ghost-idle": 18.57,
            "emote-gangnam": 7.28,
            "emote-frollicking": 3.7,
            "emote-fainting": 18.42,
            "emote-fail2": 6.48,
            "emote-fail1": 5.62,
            "emote-exasperatedb": 2.72,
            "emote-exasperated": 2.37,
            "emote-elbowbump": 3.8,
            "emote-disco": 5.37,
            "emote-disappear": 6.2,
            "emote-deathdrop": 3.76,
            "emote-death2": 4.86,
            "emote-death": 6.62,
            "emote-dab": 2.72,
            "emote-curtsy": 2.43,
            "emote-confused": 8.58,
            "emote-cold": 3.66,
            "emote-charging": 8.03,
            "emote-bunnyhop": 12.38,
            "emote-bow": 3.34,
            "emote-boo": 4.5,
            "emote-baseball": 7.25,
            "emote-apart": 4.81,
            "emoji-thumbsup": 2.7,
            "emoji-there": 2.06,
            "emoji-sneeze": 3.0,
            "emoji-smirking": 4.82,
            "emoji-sick": 5.07,
            "emoji-scared": 3.01,
            "emoji-punch": 1.76,
            "emoji-pray": 4.5,
            "emoji-poop": 4.8,
            "emoji-naughty": 4.28,
            "emoji-mind-blown": 2.4,
            "emoji-lying": 6.31,
            "emoji-halo": 5.84,
            "emoji-hadoken": 2.72,
            "emoji-give-up": 5.41,
            "emoji-gagging": 5.07,
            "emoji-flex": 20.0,
            "emoji-dizzy": 4.05,
            "emoji-cursing": 2.38,
            "emoji-crying": 3.7,
            "emoji-clapping": 2.16,
            "emoji-celebrate": 3.41,
            "emoji-arrogance": 6.87,
            "emoji-angry": 5.76,
            "dance-voguehands": 9.15,
            "dance-tiktok8": 10.94,
            "dance-tiktok2": 10.39,
            "dance-spiritual": 15.8,
            "dance-smoothwalk": 6.69,
            "dance-singleladies": 21.19,
            "dance-shoppingcart": 4.32,
            "dance-russian": 10.25,
            "dance-robotic": 20.0,
            "dance-pennywise": 0.37,
            "dance-orangejustice": 6.48,
            "dance-metal": 15.08,
            "dance-martial-artist": 13.28,
            "dance-macarena": 12.21,
            "dance-handsup": 22.28,
            "dance-duckwalk": 11.75,
            "dance-breakdance": 20.0,
            "dance-blackpink": 7.15,
            "dance-aerobics": 8.8,
            "emote-hyped": 7.49,
            "dance-jinglebell": 10.96,
            "idle-nervous": 21.71,
            "idle-toilet": 32.17,
            "emote-attention": 4.4,
            "sit-open": 15.0,
            "emote-astronaut": 13.79,
            "dance-zombie": 12.92,
            "emoji-ghost": 3.47,
            "emote-hearteyes": 4.03,
            "emote-swordfight": 5.91,
            "emote-timejump": 4.01,
            "emote-snake": 5.26,
            "emote-heartfingers": 4.0,
            "emote-heartshape": 6.23,
            "emote-hug": 3.1,
            "emote-lagughing": 15.0,
            "emoji-eyeroll": 3.02,
            "emote-embarrassed": 7.41,
            "emote-float": 9.0,
            "emote-telekinesis": 10.49,
            "dance-sexy": 12.31,
            "emote-puppet": 16.33,
            "idle-fighter": 17.19,
            "dance-pinguin": 11.58,
            "dance-creepypuppet": 6.42,
            "emote-sleigh": 11.33,
            "emote-maniac": 4.91,
            "emote-energyball": 7.58,
            "idle_singing": 10.26,
            "emote-frog": 14.55,
            "emote-superpose": 4.53,
            "emote-cute": 6.17,
            "dance-tiktok9": 11.89,
            "dance-weird": 21.56,
            "dance-tiktok10": 8.23,
            "emote-pose7": 4.66,
            "emote-pose8": 4.81,
            "idle-dance-casual": 9.08,
            "emote-pose1": 2.83,
            "emote-pose3": 5.11,
            "emote-pose5": 4.62,
            "emote-cutey": 3.26,
            "emote-punkguitar": 9.37,
            "emote-zombierun": 8.0,
            "dance-icecream": 14.77,
            "dance-wrong": 12.42,
            "idle-uwu": 24.76,
            "idle-dance-tiktok4": 15.5,
            "emote-shy2": 4.99,
            "dance-anime": 8.47,
            "dance-kawai": 10.29,
            "idle-wild": 26.42,
            "emote-iceskating": 7.3,
            "emote-pose6": 5.38,
            "emote-celebrationstep": 3.35,
            "emote-creepycute": 7.9,
            "emote-frustrated": 5.58,
            "emote-pose10": 3.99,
            "sit-relaxed": 28.89,
            "emote-stargaze": 1.13,
            "emote-slap": 1.3,
            "emote-boxer": 5.56,
            "emote-headblowup": 11.67,
            "emote-kawaiigogo": 10.0,
            "emote-repose": 1.12,
            "idle-dance-tiktok7": 12.96,
            "emote-shrink": 8.74,
            "emote-pose9": 4.58,
            "emote-teleporting": 11.77,
            "dance-touch": 15.0,
            "idle-guitar": 13.23,
            "emote-gift": 5.8,
            "dance-employee": 8.0,
            "emote-kissing": 5.0,
            "dance-tiktok11": 10.0,
            "dance-tiktok12": 14.85,
            "dance-tiktok13": 9.24,
            "emote-cutesalute": 2.76,
            "emote-salute": 2.71,
            "dance-floss": 20.5,
            "emote-dead": 6.0,
            "emote-alice-shrink": 15.0,
            "emote-threadexchange-star": 9.0,
            "idle-floorsleeping2": 16.25,
            "emote-afk-idle": 10.0,
            "emote-sicklycute-sing-fast": 11.0,
            "emote-sicklycute-sing-slow": 10.0,
            "emote-modelwalk": 10.0,
            "emote-fashionista": 5.61,
            "dance-touc": 12.0,
            "idle_tough": 26.9,
            "emote-fail3": 6.3,
            "emote-theatrical-test": 10.86,
            "run-vertical": 3.86,
            "emote-receive-disappointed": 5.4,
            "walk-vertical": 4.18,
            "emote-confused2": 7.1,
            "mining-mine": 3.0,
            "mining-success": 2.5,
            "mining-fail": 2.5,
            "fishing-pull": 1.0,
            "fishing-idle": 16.0,
            "fishing-cast": 1.5,
            "fishing-pull-small": 1.0,
            "dance-hipshake": 10.5,
            "dance-fruity": 16.5,
            "dance-cheerleader": 15.87,
            "dance-tiktok14": 9.1,
            "emote-looping": 9.0,
            "idle-floating": 26.3,
            "dance-wild": 13.48,
            "emote-howl": 4.75,
            "idle-howl": 30.0,
            "emote-trampoline": 4.26,
            "emote-launch": 8.0,
            "emote-stargazer": 6.7,
            "emote-holding-hot-cocoa": 3.87,
            "emote-mittens": 3.17,
            "emote-littlemonsters-dance": 15.0,
            "emote-threadexchange-floating": 14.0,
            "emote-jewelrise-vibing": 14.0,
            "stop": 0.0,
            "emote-pose-sit": 6.0,
            "emote-pose-stand1": 8.92,
            "emote-pose-goth1": 11.0,
            "emote-pose-goth2": 11.0,
            "emote-pose-goth3": 10.0,
            "emote-bloomify-pose1": 12.0,
            "emote-bloomify-pose2": 12.0,
            "emote-bloomify-pose3": 11.0,
            "emote-sugarbite-pose1": 11.0,
            "emote-sugarbite-pose2": 11.0,
            "emote-sugarbite-pose3": 11.0,
            "emote-punkandlaces-pose1": 1.8,
            "emote-punkandlaces-pose2": 1.8,
            "emote-punkandlaces-pose3": 1.9,
            "emote-offdutyangels-backoff": 5.0,
            "emote-offdutyangels-comehere": 6.0,
            "emote-spiderman": 8.82,
            "emote-idle-daydreaming": 14.0,
            "emote-ragdoll": 15.0,
            "emote-kawaiipose": 7.0,
            "emote-collab-celebrate-right": 5.88,
            "emote-collab-celebrate-left": 10.0,
            "sit-idle-cute": 15.5,
            "dance-true-heart": 20.0,
            "dance-swagbounce": 20.0,
            "dance-popularvibe": 20.0,
            "dance-freshprince": 20.0,
            "dance-ballet": 20.0,
            "sit-idle-laidBack": 20.0,
            "dance-twerk": 20.0,
            "dance-shuffle": 20.0,
            "dance-griddy": 20.0,
            "dance-mine": 20.0,
            "emote-knocking-screen": 20.0,
            "dance-woah": 20.0,
            "emote-blowkisses": 20.0,
            "emote-threadexchange-posing": 11.0,
            "sit-idle-springSun": 22.0,
            "sit-idle-phone-text": 10.0,
            "idle-laying-phone-talking": 10.0,
            "emote-phone": 10.0,
            "idle-phone-talking": 10.0,
            "idle-phone-camera": 20.0,
            "dance-wait": 10.0,
            "emote-rifle": 10.0,
            "emote-kissing-bound": 5.6,
            "emote-celebrate": 3.3,
            "emote-coolguy": 4.0,
            "emote-rifle-throw": 5.8,
            "emote-swing-sneak-Idle": 2.0,
            "emote-swing-net-3": 1.6,
            "emote-swing-celebrate": 1.2,
            "emote-swing-net-2": 1.3,
            "emote-swing-net": 1.2,
            "sit-idle-sleep": 15.0,
            "emote-tune-accept": 4.0,
            "emote-yoga-treePose": 2.2,
            "emote-yoga-warrior2": 5.8,
            "emote-yoga-warrior3": 6.0,
            "emote-pose-stand2": 5.2,
            "dance-running-man": 10.2,
            "emote-yogaSurprise": 16.0,
            "emote-rainstruck-fail": 11.0,
            "emote-rainstruck-success": 5.0,
            "emote-outfit3": 16.0,
            "emote-pose13": 20.0,
            "emote-outfit2": 20.0,
            "emote-pose12": 20.0,
            "emote-pose11": 20.0,
            "emote-meditate-idle": 15.0,
            "emote-collab-photo-left": 10.0,
            "emote-collab-photo-right": 10.0,
            "emote-collab-tea-left": 10.0,
            "emote-inside-out": 20.0,
            "emote-adoringfans": 10.0,
            "emote-sixseven": 10.0,
            "emote-sixseven-noimg": 10.0,
            "dance-anime3": 12.37,
            "emote-armcannon": 8.67,
            "profile-breakscreen": 10.7,
            "emote-cartwheel": 7.94,
            "idle-cold": 17.71,
            "idle-crouched": 28.27,
            "emote-dinner": 14.25,
            "emote-dramatic": 9.1,
            "emote-electrified": 5.29,
            "emote-fading": 14.05,
            "emote-fireworks": 13.15,
            "emote-flirt": 7.95,
            "emote-receive-happy": 5.94,
            "emote-gooey": 5.82,
            "emote-handwalk": 7.77,
            "idle-headless": 41.8,
            "dance-hiphop": 27.59,
            "emote-hopscotch": 5.84,
            "idle-dance-tiktok6": 9.73,
            "hcc-jetpack": 27.45,
            "emote-juggling": 5.83,
            "dance-kid": 10.3,
            "emote-kissing-passionate": 10.47,
            "emote-pose4": 6.08,
            "emote-oops": 8.02,
            "emote-opera": 5.76,
            "emote-outfit": 13.2,
            "emote-pose2": 7.2,
            "emote-runhop": 8.72,
            "emote-sheephop": 3.78,
            "emote-shocked": 5.59,
            "emoji-shush": 3.4,
            "sit-chair": 3.3,
            "idle-space": 37.78,
            "emote-surf": 19.01,
            "emote-thief": 6.89,
            "dance-tiktok1": 12.42,
            "dance-tiktok15": 16.11,
            "dance-tiktok16": 11.02,
            "dance-tiktok3": 10.4,
            "dance-tiktok4": 15.0,
            "dance-tiktok5": 12.2,
            "emote-twitched": 9.61,
            "emote-thought": 27.43,
            "emote-wavey": 12.6,
            "emote-scuba-dance": 10.0,
            "emote-hairssweep": 8.0,
        }

    def is_host(self, username: str) -> bool:
        """بررسی می‌کند که آیا کاربر رتبه Host (بالاترین سطح دسترسی، بالاتر از ادمین و VIP) دارد یا نه."""
        return username.lower() in [h.lower() for h in self.config.get("host_usernames", [])]

    def get_rank_level(self, username: str) -> int:
        """بالاترین سطحِ رتبه‌ای که این کاربر داره رو برمی‌گردونه (طبقِ RANK_DEFINITIONS).
        اگه هیچ رتبه‌ای نداشته باشه، ۰ برمی‌گرده."""
        username = (username or "").lower()
        level = 0
        for r in RANK_DEFINITIONS:
            members = [m.lower() for m in self.config.get(r["config_key"], [])]
            if username in members:
                level = max(level, r["level"])
        return level

    def resolve_rank(self, text: str):
        """یه رشته‌ی دلخواه (مثلِ «admin»، «ادمین»، «vip») رو به تعریفِ رتبه‌ی متناظرش تو
        RANK_DEFINITIONS تبدیل می‌کنه. اگه چیزی پیدا نشد None برمی‌گردونه."""
        text = (text or "").strip().lower()
        if not text:
            return None
        for r in RANK_DEFINITIONS:
            if text == r["key"] or text in [a.lower() for a in r["aliases"]]:
                return r
        return None

    def can_moderate(self, username: str) -> bool:
        """ادمین‌های کامل + ناظرهایی که با !mod اضافه شدن (سطحِ پایین‌تر، فقط برای دستوراتِ نظارتی
        مثلِ mute/kick/ban/freeze/warn/jail، نه دستوراتِ حساس‌تر مثلِ !restart یا !settoken)."""
        username = username.lower()
        return username in self.config["admin_usernames"] or username in [m.lower() for m in self.config.get("moderator_usernames", [])]

    # ============================= محرومیت (بن/کیک) با پشتیبانی از زمان =============================

    def is_banned(self, username: str) -> bool:
        """چک می‌کنه یوزر بن هست یا نه؛ اگه بن زمان‌دار منقضی شده باشه خودکار پاکش می‌کنه."""
        username = username.lower()
        banned = self.config.get("banned_users", {})
        if username not in banned:
            return False
        until_iso = banned[username]
        if until_iso is None:
            return True  # بن دائمی
        try:
            if datetime.utcnow() >= datetime.fromisoformat(until_iso):
                del banned[username]
                self.save_config()
                return False
            return True
        except ValueError:
            return True

    def ban_user(self, username: str, seconds: int | None):
        """seconds=None یعنی بن دائمی."""
        username = username.lower()
        until_iso = None if seconds is None else (datetime.utcnow() + timedelta(seconds=seconds)).isoformat()
        self.config.setdefault("banned_users", {})[username] = until_iso
        self.save_config()
        self.sync_ban_to_panel(username, "ban", until_iso)

    def unban_user(self, username: str) -> bool:
        username = username.lower()
        if username in self.config.get("banned_users", {}):
            del self.config["banned_users"][username]
            self.save_config()
            self.sync_ban_to_panel(username, "unban", None)
            return True
        return False

    def sync_ban_to_panel(self, username: str, kind: str, until_iso: str | None, reason: str = ""):
        """اگه ربات از طریق admin_panel.py ران شده باشه (PANEL_DB_PATH ست شده)، محدودیت رو
        تو دیتابیس مشترک پنل هم ثبت می‌کنه تا هم از چت هم از پنل قابل مدیریت بمونه.
        کاملاً best-effort و بی‌خطره: اگه پنل در دسترس نباشه فقط لاگ می‌کنه، ربات رو نمی‌ندازه."""
        panel_db = os.getenv("PANEL_DB_PATH")
        bot_id = os.getenv("PANEL_BOT_ID")
        if not panel_db or not bot_id or not os.path.exists(panel_db):
            return
        try:
            import sqlite3
            conn = sqlite3.connect(panel_db, timeout=5)
            try:
                if kind == "unban":
                    conn.execute("DELETE FROM bans WHERE bot_id = ? AND username = ?", (bot_id, username))
                else:
                    conn.execute(
                        "INSERT INTO bans (bot_id, username, kind, until_at, reason, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                        (bot_id, username, kind, until_iso, reason, datetime.utcnow().isoformat()),
                    )
                conn.commit()
            finally:
                conn.close()
        except Exception as e:
            logger.error(f"خطا در سینک محدودیت با پنل: {e}")

    def load_bans_from_panel(self):
        """موقع روشن شدن، محدودیت‌های ثبت‌شده از طریق پنل رو هم بخون تا با چت سینک باشه."""
        panel_db = os.getenv("PANEL_DB_PATH")
        bot_id = os.getenv("PANEL_BOT_ID")
        if not panel_db or not bot_id or not os.path.exists(panel_db):
            return
        try:
            import sqlite3
            conn = sqlite3.connect(panel_db, timeout=5)
            try:
                rows = conn.execute(
                    "SELECT username, until_at FROM bans WHERE bot_id = ? AND kind IN ('ban','kick')", (bot_id,)
                ).fetchall()
                for username, until_at in rows:
                    self.config.setdefault("banned_users", {})[username.lower()] = until_at
                if rows:
                    self.save_config()
            finally:
                conn.close()
        except Exception as e:
            logger.error(f"خطا در خوندن محدودیت‌های پنل: {e}")

    # ============================= حلقه‌ی دوره‌ای سینک با پنل =============================
    # هر PANEL_SYNC_INTERVAL_SECONDS (پیش‌فرض ۱ ثانیه): ۱) لیست بن رو کامل از جدول مشترک پنل می‌کشه
    # (چه از چت چه از پرتال ساب اضافه/حذف شده باشه، اینجا اعمال میشه) ۲) دستورهای صف‌شده از پرتال ساب
    # (افزودن/حذف ادمین، پیام خوش‌آمد، تم رنگی، !admin، اعلان) رو اجرا می‌کنه ۳) وضعیت فعلی
    # ربات رو برای نمایش تو پرتال ساب پس می‌فرسته ۴) هشدار انقضا میده.

    async def panel_sync_loop(self):
        panel_db = os.getenv("PANEL_DB_PATH")
        bot_id = os.getenv("PANEL_BOT_ID")
        if not panel_db or not bot_id:
            return  # این ربات مستقل از پنل ران شده، نیازی به سینک نیست
        while True:
            try:
                await self._panel_sync_once(panel_db, bot_id)
            except Exception as e:
                logger.error(f"خطا در چرخه‌ی سینک پنل: {e}")
            await sleep(PANEL_SYNC_INTERVAL_SECONDS)

    async def _panel_sync_once(self, panel_db, bot_id):
        import sqlite3
        conn = sqlite3.connect(panel_db, timeout=5)
        try:
            # ۱) بن‌ها رو کامل از پنل بازخوانی کن (جدول مشترک = منبع درستی)
            rows = conn.execute(
                "SELECT username, until_at FROM bans WHERE bot_id = ? AND kind IN ('ban','kick')", (bot_id,)
            ).fetchall()
            fresh_bans = {username.lower(): until_at for username, until_at in rows}
            if fresh_bans != self.config.get("banned_users", {}):
                self.config["banned_users"] = fresh_bans
                self.save_config()

            # ۲) دستورهای اجرانشده رو بردار و اجرا کن
            pending = conn.execute(
                "SELECT id, action, payload FROM bot_commands WHERE bot_id = ? AND applied = 0 ORDER BY id",
                (bot_id,),
            ).fetchall()
            for cmd_id, action, payload_raw in pending:
                try:
                    payload = json.loads(payload_raw or "{}")
                except Exception:
                    payload = {}
                await self._apply_panel_command(action, payload)
                conn.execute("UPDATE bot_commands SET applied = 1 WHERE id = ?", (cmd_id,))
            if pending:
                conn.commit()

            # ۳) وضعیت فعلی رو برای پرتال ساب پس بفرست
            extra_state = {
                "vip_usernames": self.config.get("vip_usernames", []),
                "teleport_locations": self.config.get("teleport_locations", {}),
                "custom_ranks": self.config.get("custom_ranks", {}),
                "speaker_enabled": self.speaker_enabled,
                "speaker_mode": self.speaker_mode,
                "dance_enabled": self.config.get("dance_enabled", True),
                "afk_users": sorted(self.afk_users),
                "follow_target": self.following_username,
                # 🗂 ثبت کامل وضعیت برای نمایش تو سایت (بخش «داده‌های کامل بات»)
                "current_outfit": self.config.get("current_outfit", []),
                "outfit_presets": list((self.config.get("outfit_presets") or {}).keys()),
                "language": self.config.get("language", "fa"),
                "auto_admins": self.config.get("auto_admins", []),
                "kill_position": self.config.get("kill_position"),
                "autoscan_dance_count": len(self.emotes),
                "active_user_count": len(self.active_users),
                "lottery_active": bool(self.lottery and self.lottery.get("active")),
            }
            conn.execute(
                "INSERT INTO bot_state (bot_id, admins, hosts, welcome_message, "
                "auto_admin_mode, theme_primary_color, theme_secondary_color, ai_room_enabled, extra_state, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(bot_id) DO UPDATE SET admins=excluded.admins, hosts=excluded.hosts, "
                "welcome_message=excluded.welcome_message, auto_admin_mode=excluded.auto_admin_mode, "
                "theme_primary_color=excluded.theme_primary_color, "
                "theme_secondary_color=excluded.theme_secondary_color, "
                "ai_room_enabled=excluded.ai_room_enabled, "
                "extra_state=excluded.extra_state, "
                "updated_at=excluded.updated_at",
                (
                    bot_id,
                    json.dumps(self.config.get("admin_usernames", []), ensure_ascii=False),
                    json.dumps(self.config.get("host_usernames", []), ensure_ascii=False),
                    self.config.get("welcome_message", ""),
                    int(bool(self.config.get("auto_admins"))),
                    self.config.get("theme_primary_color", ""),
                    self.config.get("theme_secondary_color", ""),
                    int(bool(self.config.get("ai_room_enabled"))),
                    json.dumps(extra_state, ensure_ascii=False),
                    datetime.utcnow().isoformat(),
                ),
            )
            conn.commit()

            # ۴) هشدار پایان اشتراک/رنت تو چت روم (یک ساعت، یک ربع و ۵ دقیقه‌ی آخر مونده)
            bot_row = conn.execute("SELECT status, expires_at FROM bots WHERE id = ?", (bot_id,)).fetchone()
            if bot_row and bot_row[0] == "running" and bot_row[1]:
                try:
                    expires_at = datetime.fromisoformat(bot_row[1])
                    remaining = (expires_at - datetime.utcnow()).total_seconds()
                    for threshold in EXPIRY_WARN_THRESHOLDS:
                        if 0 < remaining <= threshold and threshold not in self._expiry_warned:
                            self._expiry_warned.add(threshold)
                            _lang = self.config.get("language", "fa")
                            _lang = _lang if _lang in ("fa", "en") else "fa"
                            _fallback = (f"⏰ کمتر از {humanize_seconds_lang(threshold, _lang)} به پایان اشتراک این ربات مونده!"
                                         if _lang == "fa" else
                                         f"⏰ Less than {humanize_seconds_lang(threshold, _lang)} left on this bot's subscription!")
                            await self.chat(EXPIRY_WARN_MESSAGES.get(_lang, EXPIRY_WARN_MESSAGES["fa"]).get(threshold, _fallback))
                except ValueError:
                    pass
        finally:
            conn.close()

    async def _apply_panel_command(self, action, payload):
        username = (payload.get("username") or "").strip().lower()
        if action == "add_admin" and username:
            if username not in self.config["admin_usernames"]:
                self.config["admin_usernames"].append(username)
                self.save_config()
        elif action == "remove_admin" and username:
            if username in self.config["admin_usernames"]:
                self.config["admin_usernames"].remove(username)
                self.save_config()
        elif action == "add_host" and username:
            if username not in self.config["host_usernames"]:
                self.config["host_usernames"].append(username)
                self.save_config()
        elif action == "remove_host" and username:
            if username in self.config["host_usernames"]:
                self.config["host_usernames"].remove(username)
                self.save_config()
        elif action == "set_welcome":
            message = payload.get("message", "").strip()
            if message:
                self.config["welcome_message"] = message
                self.save_config()
        elif action == "set_theme":
            # payload: {"primary": "rrggbb"|"", "secondary": "rrggbb"|""} — "" یعنی برگشت به تم پیش‌فرض
            hex_re = re.compile(r"^[0-9a-fA-F]{6}$")
            primary = (payload.get("primary") or "").strip().lstrip("#")
            secondary = (payload.get("secondary") or "").strip().lstrip("#")
            if primary == "" or hex_re.match(primary):
                self.config["theme_primary_color"] = primary.lower()
            if secondary == "" or hex_re.match(secondary):
                self.config["theme_secondary_color"] = secondary.lower()
            self.save_config()
        elif action == "admin_sync_on":
            await self.apply_admin_sync("on")
        elif action == "admin_sync_off":
            await self.apply_admin_sync("off")
        elif action == "ai_on":
            self.config["ai_room_enabled"] = True
            self.save_config()
        elif action == "ai_off":
            self.config["ai_room_enabled"] = False
            self.save_config()
        elif action == "announce":
            message = payload.get("message", "").strip()
            if message:
                await self.chat(message)
        elif action == "add_vip" and username:
            if username not in self.config["vip_usernames"]:
                self.config["vip_usernames"].append(username)
                self.save_config()
        elif action == "remove_vip" and username:
            if username in self.config["vip_usernames"]:
                self.config["vip_usernames"].remove(username)
                self.save_config()
        elif action == "set_teleport_access":
            # payload: {"name": ..., "admin_only": bool, "restricted_rank": str|None}
            name = (payload.get("name") or "").strip().lower()
            if name and name in self.config["teleport_locations"]:
                self.config["teleport_locations"][name]["admin_only"] = bool(payload.get("admin_only"))
                rank = (payload.get("restricted_rank") or "").strip() or None
                self.config["teleport_locations"][name]["restricted_rank"] = rank if rank in self.config.get("custom_ranks", {}) else None
                self.save_config()
        elif action == "delete_teleport":
            name = (payload.get("name") or "").strip().lower()
            if name and name in self.config["teleport_locations"] and name not in ("vip", "vip1", "dj"):
                del self.config["teleport_locations"][name]
                self.save_config()
        elif action == "set_speaker":
            # payload: {"enabled": bool, "mode": "polite"|"rude"}
            if "enabled" in payload:
                self.speaker_enabled = bool(payload.get("enabled"))
            mode = payload.get("mode")
            if mode in ("polite", "rude"):
                self.speaker_mode = mode
        elif action == "set_dance_code":
            self.config["dance_enabled"] = bool(payload.get("enabled"))
            self.save_config()
        elif action == "follow_start" and username:
            self.following_username = username
        elif action == "follow_stop":
            self.following_username = None
        elif action == "set_style_item":
            links = payload.get("links") or {}
            palettes = payload.get("palettes") or {}
            for category in set(links.keys()) | set(palettes.keys()):
                link = links.get(category)
                palette = palettes.get(category)
                if category == "custom" and not link:
                    continue  # دسته‌ی آزاد بدون لینک قابل تشخیص نیست (نمی‌دونیم چیو رنگ کنیم)
                if link or (palette is not None and str(palette).strip() != ""):
                    await self.apply_style_item(None if category == "custom" else category, link or "-", palette)
        elif action == "add_accessory_items":
            for link in (payload.get("links") or []):
                if link:
                    await self.apply_add_item(link)
        else:
            logger.warning(f"دستور نامعتبر یا ناقص از پنل نادیده گرفته شد: {action} / {payload}")

    def load_config(self):
        """بارگذاری تنظیمات با چند لایه‌ی محافظتی، تا هیچ‌وقت یه خطای گذرا (فایل نصفه‌نوشته‌شده،
        کرش وسط ذخیره، دیسک پر و ...) باعث از دست رفتن کامل داده (ادمین‌ها، ظاهر، پریست‌ها،
        بن‌لیست و ...) نشه:
        ۱) اول فایل اصلی رو امتحان می‌کنیم.
        ۲) اگه خراب/ناقص بود، به‌جای پاک کردن همه‌چیز، از آخرین نسخه‌ی سالمِ پشتیبان (.bak) که
           خودمون هر بار قبل از overwrite کردن ذخیره می‌کنیم استفاده می‌کنیم.
        ۳) فقط اگه هیچ‌کدوم از این دو تا هم قابل‌خوندن نبودن، به تنظیمات پیش‌فرض برمی‌گردیم —
           آخرین راه‌حل، نه اولین."""
        loaded = self._load_config_file(CONFIG_FILE)
        if loaded is None:
            logger.error("فایل تنظیمات اصلی خراب/ناقص بود؛ تلاش برای بازیابی از نسخه‌ی پشتیبان (.bak)...")
            loaded = self._load_config_file(CONFIG_FILE + ".bak")
            if loaded is not None:
                logger.info("تنظیمات با موفقیت از نسخه‌ی پشتیبان بازیابی شد.")

        if loaded is not None:
            self.config = loaded
            # اضافه کردن کلیدهای جدید (مثل host_usernames) به تنظیمات قدیمی
            # که ممکنه از قبل روی سرور ذخیره شده باشن و این کلید رو نداشته باشن
            for key, value in DEFAULT_CONFIG.items():
                if key not in self.config:
                    self.config[key] = value.copy() if isinstance(value, (list, dict)) else value
            # 🔧 اصلاح فایل‌های تنظیماتِ قدیمی که از قبل current_outfit=null یا outfit_presets خالی/null
            # ذخیره کرده بودن (قبل از اضافه شدن قابلیت ظاهر پیش‌فرض) — این‌ها رو صریحاً پر می‌کنیم
            # چون حلقه‌ی بالا فقط کلیدهای کاملاً غایب رو اضافه می‌کنه، نه مقدار خالی/None موجود رو.
            if not self.config.get("current_outfit"):
                self.config["current_outfit"] = DEFAULT_OUTFIT_ITEMS
            if not isinstance(self.config.get("outfit_presets"), dict):
                self.config["outfit_presets"] = {}
            # 🎨 بک‌فیل: هر ۸ اسکینِ جدید رو، هرکدوم که هنوز تو این بات (چه قدیمی چه جدید) نبود
            # اضافه کن — بدونِ دست‌زدن به شماره‌ای که خودِ ادمین قبلاً چیزِ دیگه‌ای توش ذخیره کرده.
            for preset_num, preset_items in DEFAULT_OUTFIT_PRESETS.items():
                if preset_num not in self.config["outfit_presets"]:
                    self.config["outfit_presets"][preset_num] = preset_items
            # 🔄 مهاجرت فایل‌های قدیمی: قبلاً banned_users یه لیست ساده بود (فقط بن دائمی)،
            # الان دیکشنریه {username: until_iso یا None} تا زمان‌دار هم پشتیبانی بشه.
            if isinstance(self.config.get("banned_users"), list):
                self.config["banned_users"] = {u: None for u in self.config["banned_users"]}
            # 🔄 مهاجرت: قبلاً welcome_message یه رشته‌ی تکی بود. اگه welcome_messages (لیست) هنوز
            # خالیه، همون رشته‌ی قدیمی رو به‌عنوان اولین عضوِ لیست می‌ذاریم تا چیزی گم نشه.
            if not self.config.get("welcome_messages") and self.config.get("welcome_message"):
                self.config["welcome_messages"] = [self.config["welcome_message"]]
            # 🔄 مهاجرت: همونِ منطق برای goodbye_message/goodbye_messages
            if not self.config.get("goodbye_messages") and self.config.get("goodbye_message"):
                self.config["goodbye_messages"] = [self.config["goodbye_message"]]
            self.save_config()
            logger.info("تنظیمات با موفقیت بارگذاری شد.")
        else:
            logger.info("هیچ فایل تنظیماتِ قابل‌خوندنی (نه اصلی، نه پشتیبان) پیدا نشد؛ استفاده از تنظیمات پیش‌فرض...")
            self.config = DEFAULT_CONFIG.copy()
            self.config["welcome_messages"] = [self.config["welcome_message"]]
            self.config["goodbye_messages"] = [self.config["goodbye_message"]]
            # 🌐 اگه از سایت زبونِ دیگه‌ای (انگلیسی/عربی) برای این بات انتخاب شده (ساخت اولیه)،
            # پیام خوش‌آمد/خداحافظی پیش‌فرض هم همون زبون باشه، نه فارسی/میکس.
            _bot_lang_env = os.getenv("BOT_LANGUAGE", "").strip().lower()
            if _bot_lang_env == "en":
                self.config["language"] = "en"
                self.config["welcome_message"] = EN_DEFAULT_WELCOME
                self.config["welcome_messages"] = [EN_DEFAULT_WELCOME]
                self.config["goodbye_message"] = EN_DEFAULT_GOODBYE
                self.config["goodbye_messages"] = [EN_DEFAULT_GOODBYE]
                self.config["announcement_message"] = EN_DEFAULT_ANNOUNCEMENT
            elif _bot_lang_env == "ar":
                self.config["language"] = "ar"
                self.config["welcome_message"] = AR_DEFAULT_WELCOME
                self.config["welcome_messages"] = [AR_DEFAULT_WELCOME]
                self.config["goodbye_message"] = AR_DEFAULT_GOODBYE
                self.config["goodbye_messages"] = [AR_DEFAULT_GOODBYE]
                self.config["announcement_message"] = AR_DEFAULT_ANNOUNCEMENT
            self.save_config()

        # 🌐 زبان همیشه از انتخاب سایت پیروی می‌کنه (منبع اصلی تنظیمات همون پنله)، حتی برای
        # بات‌هایی که از قبل کانفیگ داشتن — اگه تو پنل عوضش کرده باشی، همینجا اعمال میشه.
        env_lang = os.getenv("BOT_LANGUAGE", "").strip().lower()
        if env_lang in ("fa", "en", "ar") and self.config.get("language") != env_lang:
            self.config["language"] = env_lang
            self.save_config()

        # 🛡️ همیشه مطمئن شو هاست‌ها + اونرها + منیجرها توی لیست ادمین‌ها هم هستن
        # (این رتبه‌ها به‌صورت خودکار تمام دسترسی‌های ادمین رو هم دارن)
        for rank_key in RANKS_THAT_IMPLY_ADMIN:
            for member in self.config.get(RANK_BY_KEY[rank_key]["config_key"], []):
                if member not in self.config["admin_usernames"]:
                    self.config["admin_usernames"].append(member)

    def _load_config_file(self, path):
        """یه فایل تنظیمات مشخص رو می‌خونه و اگه معتبر (JSON سالم و از نوع dict) بود
        برمی‌گردونه، وگرنه None (بدون هیچ throw ای به بیرون) — تا load_config بتونه
        بین فایل اصلی و پشتیبان امن سوییچ کنه."""
        try:
            if not os.path.exists(path):
                return None
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if not isinstance(data, dict) or not data:
                logger.error(f"محتوای {path} یه دیکشنری معتبر نیست (نوع: {type(data)}).")
                return None
            return data
        except json.JSONDecodeError as e:
            logger.error(f"خطا در ساختار JSON فایل {path}: {e}")
            return None
        except Exception as e:
            logger.error(f"خطا در خوندن فایل {path}: {e}")
            return None

    def save_config(self):
        """ذخیره‌ی اتمیک: اول رو یه فایل موقت می‌نویسیم و کامل flush/fsync می‌کنیم، بعد با
        os.replace (که رو سیستم‌عامل‌های واقعی اتمیکه) جایگزین فایل اصلی می‌کنیم. این یعنی اگه
        پروسه درست همون لحظه کرش کنه یا !restart بخوره، یا فایل قبلی کامل سرجاشه، یا فایل جدید
        کامل نوشته شده — هیچ‌وقت یه فایل نصفه‌نوشته‌شده/خراب رو دیسک نمی‌مونه. قبل از overwrite
        کردن، نسخه‌ی *قبلیِ* سالم رو هم به‌عنوان .bak نگه می‌داریم تا در صورت خرابیِ غیرمنتظره‌ی
        بعدی، بتونیم ازش بازیابی کنیم (رجوع کن به load_config)."""
        try:
            config_to_save = self.config.copy()
            config_to_save["host_usernames"] = list(config_to_save["host_usernames"])
            config_to_save["owner_usernames"] = list(config_to_save.get("owner_usernames", []))
            config_to_save["manager_usernames"] = list(config_to_save.get("manager_usernames", []))
            config_to_save["admin_usernames"] = list(config_to_save["admin_usernames"])
            config_to_save["moderator_usernames"] = list(config_to_save.get("moderator_usernames", []))
            config_to_save["vip_usernames"] = list(config_to_save["vip_usernames"])
            config_to_save["banned_users"] = dict(config_to_save["banned_users"])

            # قبل از هر چیز، اگه فایل اصلی از قبل وجود داره و سالمه، بذارش کنار به‌عنوان بکاپ
            if os.path.exists(CONFIG_FILE) and self._load_config_file(CONFIG_FILE) is not None:
                try:
                    shutil.copyfile(CONFIG_FILE, CONFIG_FILE + ".bak")
                except Exception as e:
                    logger.error(f"خطا در ساخت نسخه‌ی پشتیبان قبل از ذخیره: {e}")

            tmp_path = CONFIG_FILE + ".tmp"
            with open(tmp_path, 'w', encoding='utf-8') as f:
                json.dump(config_to_save, f, indent=4, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, CONFIG_FILE)
            logger.info("تنظیمات با موفقیت (و به‌صورت اتمیک) ذخیره شد.")
        except Exception as e:
            logger.error(f"خطا در ذخیره تنظیمات: {e}")

    async def chat(self, text: str, color: str = None):
        """جایگزین self.highrise.chat که خودکار رنگ اضافه می‌کنه.
        رنگ پیش‌فرض از تم انتخاب‌شده تو سایت میاد (theme_primary_color)؛ اگه ست نشده باشه
        همون تم اصلی <#ff33ff> استفاده میشه. پاسخ‌های اسپیکر جدا رنگ خودشون رو دارن."""
        default_color = f"<#{self.config['theme_primary_color']}>" if self.config.get("theme_primary_color") else "<#ff33ff>"
        color = color or default_color
        await self.highrise.chat(f"{color}{text}")

    def get_message(self, key, **kwargs):
        messages = {
            "fa": {
                "welcome": random.choice(self.config["welcome_messages"]) if self.config.get("welcome_messages") else self.config["welcome_message"],
                "goodbye": random.choice(self.config["goodbye_messages"]) if self.config.get("goodbye_messages") else self.config.get("goodbye_message", FA_DEFAULT_GOODBYE),
                "invalid_command": "❌ دستور نامعلوم! برای دیدن دستورات بات !help استفاده کنید یا به @ahoora_king پیام بدید.",
                "no_permission": "فقط ادمین‌ها می‌توانند از این دستور استفاده کنند!",
                "user_not_found": "کاربر {username} آنلاین نیست.",
                "invalid_format": "فرمت نادرست: {format}",
                "teleport_success": "@{username} به {location} تلپورت شد!",
                "teleport_error": "خطا در تلپورت: {error}",
                "heart_success": "{count} قلب بنفش به @{username} ارسال شد!",
                "heart_all_success": "{count} واکنش به {count} نفر ارسال شد!",
                "clap_success": "{count} clap به @{username} ارسال شد!",
                "wink_success": "{count} wink به @{username} ارسال شد!",
                "wave_success": "{count} wave به @{username} ارسال شد!",
                "thumbs_success": "{count} thumbs-up به @{username} ارسال شد!",
                "wallet_error": "خطا در دریافت موجودی: {error}",
                "tip_success": "{amount} گلد به @{username} ارسال شد.",
                "tip_all_success": "تیپ {amount} گلد به {count} نفر ارسال شد!",
                "ban_success": "@{username} بن شد!",
                "unban_success": "کاربر @{username} با موفقیت آنبن شد!",
                "unban_not_banned": "کاربر @{username} در لیست بن نیست.",
                "dancechain_success": "زنجیره رقص برای @{username} اجرا شد!",
                "addtele_success": "مکان {location} ذخیره شد!",
                "deltele_success": "مکان {location} با موفقیت حذف شد!",
                "deltele_not_found": "مکان {location} وجود ندارد!",
                "deltele_protected": "نمی‌توانید مکان پیش‌فرض {location} را حذف کنید!",
                "set_item_success": "ظاهر ربات به ایتم‌های @{username} تغییر کرد!",
                "listadd_empty": "هیچ ادمینی در لیست وجود ندارد.",
                "listadd_success": "لیست ادمین‌ها ({count} نفر):\n{admin_list}",
                "freeze_success": "کاربر @{username} فریز شد!",
                "unfreeze_success": "کاربر @{username} از حالت فریز آزاد شد!",
                "unfreeze_not_frozen": "کاربر @{username} فریز نشده است!",
                "party_success": "رقص شماره {dance_number} برای @{username} فعال شد!",
                "party_all_success": "رقص شماره {dance_number} برای {count} کاربر فعال شد!",
                "partys_success": "رقص اجباری برای @{username} متوقف شد!",
                "partys_not_dancing": "کاربر @{username} در حال رقص اجباری نیست!",
                "lang_changed": "✅ زبان ربات به فارسی تغییر کرد."
            },
            "en": {
                "welcome": random.choice(self.config["welcome_messages"]) if self.config.get("welcome_messages") else self.config["welcome_message"],
                "goodbye": random.choice(self.config["goodbye_messages"]) if self.config.get("goodbye_messages") else self.config.get("goodbye_message", EN_DEFAULT_GOODBYE),
                "invalid_command": "❌ Unknown command! Use !help to see commands or message @ahoora_king.",
                "no_permission": "Only admins can use this command!",
                "user_not_found": "User {username} is not online.",
                "invalid_format": "Invalid format: {format}",
                "teleport_success": "@{username} was teleported to {location}!",
                "teleport_error": "Teleport error: {error}",
                "heart_success": "{count} hearts sent to @{username}!",
                "heart_all_success": "{count} reactions sent to {count} people!",
                "clap_success": "{count} claps sent to @{username}!",
                "wink_success": "{count} winks sent to @{username}!",
                "wave_success": "{count} waves sent to @{username}!",
                "thumbs_success": "{count} thumbs-up sent to @{username}!",
                "wallet_error": "Error fetching wallet: {error}",
                "tip_success": "{amount} gold sent to @{username}.",
                "tip_all_success": "Tipped {amount} gold to {count} people!",
                "ban_success": "@{username} was banned!",
                "unban_success": "@{username} was successfully unbanned!",
                "unban_not_banned": "@{username} is not on the ban list.",
                "dancechain_success": "Dance chain executed for @{username}!",
                "addtele_success": "Location {location} saved!",
                "deltele_success": "Location {location} was successfully deleted!",
                "deltele_not_found": "Location {location} does not exist!",
                "deltele_protected": "You cannot delete the default location {location}!",
                "set_item_success": "Bot outfit changed to @{username}'s items!",
                "listadd_empty": "No admins in the list.",
                "listadd_success": "Admin list ({count} people):\n{admin_list}",
                "freeze_success": "@{username} has been frozen!",
                "unfreeze_success": "@{username} has been unfrozen!",
                "unfreeze_not_frozen": "@{username} is not frozen!",
                "party_success": "Dance #{dance_number} activated for @{username}!",
                "party_all_success": "Dance #{dance_number} activated for {count} users!",
                "partys_success": "Forced dance stopped for @{username}!",
                "partys_not_dancing": "@{username} is not currently forced-dancing!",
                "lang_changed": "✅ Bot language changed to English."
            },
            "ar": {
                "welcome": random.choice(self.config["welcome_messages"]) if self.config.get("welcome_messages") else self.config["welcome_message"],
                "goodbye": random.choice(self.config["goodbye_messages"]) if self.config.get("goodbye_messages") else self.config.get("goodbye_message", AR_DEFAULT_GOODBYE),
                "invalid_command": "❌ أمر غير معروف! استخدم !help لرؤية الأوامر أو راسل @ahoora_king.",
                "no_permission": "هذا الأمر مخصص للمشرفين فقط!",
                "user_not_found": "المستخدم {username} غير متصل الآن.",
                "invalid_format": "صيغة غير صحيحة: {format}",
                "teleport_success": "تم نقل @{username} إلى {location}!",
                "teleport_error": "خطأ في النقل: {error}",
                "heart_success": "تم إرسال {count} قلب إلى @{username}!",
                "heart_all_success": "تم إرسال {count} تفاعل إلى {count} شخص!",
                "clap_success": "تم إرسال {count} تصفيق إلى @{username}!",
                "wink_success": "تم إرسال {count} غمزة إلى @{username}!",
                "wave_success": "تم إرسال {count} تلويحة إلى @{username}!",
                "thumbs_success": "تم إرسال {count} إعجاب إلى @{username}!",
                "wallet_error": "خطأ في جلب الرصيد: {error}",
                "tip_success": "تم إرسال {amount} ذهب إلى @{username}.",
                "tip_all_success": "تم إرسال {amount} ذهب كإكرامية إلى {count} شخص!",
                "ban_success": "تم حظر @{username}!",
                "unban_success": "تم إلغاء حظر @{username} بنجاح!",
                "unban_not_banned": "@{username} ليس في قائمة الحظر.",
                "dancechain_success": "تم تنفيذ سلسلة الرقص لـ @{username}!",
                "addtele_success": "تم حفظ الموقع {location}!",
                "deltele_success": "تم حذف الموقع {location} بنجاح!",
                "deltele_not_found": "الموقع {location} غير موجود!",
                "deltele_protected": "لا يمكنك حذف الموقع الافتراضي {location}!",
                "set_item_success": "تم تغيير مظهر البوت إلى ملابس @{username}!",
                "listadd_empty": "لا توجد أي رتبة في القائمة.",
                "listadd_success": "قائمة المشرفين ({count} شخص):\n{admin_list}",
                "freeze_success": "تم تجميد @{username}!",
                "unfreeze_success": "تم إلغاء تجميد @{username}!",
                "unfreeze_not_frozen": "@{username} غير مجمّد!",
                "party_success": "تم تفعيل الرقصة رقم {dance_number} لـ @{username}!",
                "party_all_success": "تم تفعيل الرقصة رقم {dance_number} لـ {count} مستخدم!",
                "partys_success": "تم إيقاف الرقص الإجباري لـ @{username}!",
                "partys_not_dancing": "@{username} لا يرقص إجباريًا حاليًا!",
                "lang_changed": "✅ تم تغيير لغة البوت إلى العربية."
            }
        }
        lang = self.config.get("language", "fa")
        if lang not in messages:
            lang = "fa"
        lang_dict = messages[lang]
        if key not in lang_dict:
            # 🔄 اگه کلید تو زبونِ فعلی نبود (مثلاً یه پیامِ خیلی جدید که هنوز به این زبون ترجمه
            # نشده)، اول انگلیسی رو امتحان کن (چون بین‌المللی‌تره)، وگرنه فارسی (زبونِ اصلیِ بات).
            lang_dict = messages.get("en", {}) if key in messages.get("en", {}) else messages["fa"]
        return lang_dict[key].format(**kwargs)

    async def cmd_lang(self, user: User, parts: list):
        """!lang fa / !lang en / !lang ar -> تغییر زبان کامل ربات (اسپیکر جدا و همیشه فارسی می‌مونه)"""
        if user.username.lower() not in self.config["admin_usernames"]:
            await self.chat(self.get_message("no_permission"))
            return
        if len(parts) < 2 or parts[1].lower() not in ("fa", "en", "ar"):
            lang_now = self.config.get("language", "fa")
            usage = {
                "fa": "⚠️ فرمت: !lang fa یا !lang en یا !lang ar",
                "en": "⚠️ Usage: !lang fa | !lang en | !lang ar",
                "ar": "⚠️ الصيغة: !lang fa أو !lang en أو !lang ar",
            }
            await self.chat(usage.get(lang_now, usage["fa"]))
            return
        self.config["language"] = parts[1].lower()
        self.save_config()
        await self.chat(self.get_message("lang_changed"))

    async def cleanup_tasks(self):
        try:
            for username, task in self.dance_tasks.items():
                if not task.done():
                    task.cancel()
                try:
                    await task
                except CancelledError:
                    pass
            self.dance_tasks.clear()
            self.user_dances.clear()
            self.party_dances.clear()
            
            for username, task in self.frozen_users.items():
                if not task.done():
                    task.cancel()
                try:
                    await task
                except CancelledError:
                    pass
            self.frozen_users.clear()
            
            if self.announcement_task and not self.announcement_task.done():
                self.announcement_task.cancel()
                try:
                    await self.announcement_task
                except CancelledError:
                    pass
                self.announcement_task = None
            if self.score_update_task and not self.score_update_task.done():
                self.score_update_task.cancel()
                try:
                    await self.score_update_task
                except CancelledError:
                    pass
                self.score_update_task = None
            logger.info("همه وظایف ناهمزمان لغو شدند.")
        except Exception as e:
            logger.error(f"خطا در لغو وظایف: {e}")

    async def on_start(self, session_metadata):
        logger.info("ربات با موفقیت وصل شد.")
        self.user_id = getattr(session_metadata, "user_id", None)
        if not self.user_id:
            logger.error("شناسه ربات در session_metadata پیدا نشد.")
            await self.chat("خطا: شناسه ربات پیدا نشد." if self.config.get("language","fa") == "fa" else "Error: bot user ID not found.")
            return

        self.load_bans_from_panel()
        create_task(self.panel_sync_loop())
        await self.sync_room_users()

        # 👕 نکته: فعلاً اعمال خودکار ظاهر ذخیره‌شده روی استارت غیرفعاله (به‌درخواست خودت).
        # یعنی موقع روشن‌شدن/ری‌استارت، بات همون ظاهری که الان واقعاً پوشیده رو حفظ می‌کنه،
        # نه اینکه هر بار current_outfit ذخیره‌شده رو دوباره روش اعمال کنه. current_outfit همچنان
        # تو دیتا (کانفیگ/سایت) ثبت و به‌روز نگه داشته میشه، فقط خودکار روی بات اعمال نمیشه —
        # اعمالش هنوز با !item set/!item add دستی انجام میشه.

        self.announcement_task = create_task(self.announcement_loop())
        self.score_update_task = create_task(self.score_update_loop())
        self.emote_autoscan_task = create_task(self.emote_autoscan_loop())

        # 💃 دنس پیش‌فرض ربات: فلوس (Floss) - همیشه بدون وقفه اجرا میشه مگر با !emotebot عوض بشه
        # ⚠️ یه مکثِ کوتاه قبلش می‌ذاریم چون درست بعدِ اتصال، بات ممکنه هنوز کاملاً «اسپاون»
        # نشده باشه تو روم و اولین send_emote بی‌سروصدا رد بشه.
        await sleep(2.0)
        try:
            await self.set_bot_continuous_dance("dance-floss")
        except Exception as e:
            logger.error(f"خطا در اجرای دنس پیش‌فرض (floss): {e}")

        # 🏠 !ah/!autohome: اگه روشن باشه و خونه‌ای ست شده باشه، با هر وصل‌شدن/ری‌استارتِ
        # بات (چه دستیِ !restart، چه قطعیِ اتصال و اتصالِ مجدد) خودکار بره همون‌جا.
        if self.config.get("autohome_enabled", False) and self.config.get("home_position"):
            home = self.config["home_position"]
            try:
                await self.highrise.teleport(user_id=self.user_id, dest=Position(x=home["x"], y=home["y"], z=home["z"]))
                logger.info("autohome فعاله — بات خودکار به خونه تلپورت شد.")
            except Exception as e:
                logger.error(f"خطا در تلپورتِ autohome: {e}")

    async def cmd_autohome_toggle(self, user: User, parts: list):
        """!ah on/off یا !autohome on/off -> اگه روشن باشه، بات با هر وصل‌شدن/ری‌استارت خودکار
        میره به خونه‌ای که با !sethome ثبت کردی."""
        if user.username.lower() not in self.config["admin_usernames"]:
            await self.chat(self.get_message("no_permission"))
            return
        lang = self.config.get("language", "fa")
        if len(parts) != 2 or parts[1].lower() not in ("on", "off"):
            await self.chat("⚠️ استفاده کن از: !ah on یا !ah off" if lang == "fa" else "⚠️ Use: !ah on or !ah off")
            return
        enabled = parts[1].lower() == "on"
        if enabled and not self.config.get("home_position"):
            await self.chat(("⚠️ اول باید با !sethome یه خونه ثبت کنی، بعد !ah on رو بزن." if lang == "fa"
                              else "⚠️ Set a home first with !sethome, then turn on !ah."))
            return
        self.config["autohome_enabled"] = enabled
        self.save_config()
        await self.chat((f"🏠 autohome {'روشن' if enabled else 'خاموش'} شد." if lang == "fa"
                          else f"🏠 Autohome turned {'on' if enabled else 'off'}."))

    async def on_user_join(self, user: User, position: Position):
        username = user.username.lower()
        if user.id == self.user_id:
            return
        if self.is_banned(username):
            try:
                await self.highrise.moderate_room(user.id, "kick")
                logger.info(f"کاربر بن‌شده {user.username} به صورت خودکار کیک شد.")
            except Exception as e:
                logger.error(f"خطا در کیک کردن {user.username}: {e}")
            return
        self.active_users[username] = user
        self.user_positions[username] = position
        self.user_scores[username] = self.user_scores.get(username, 0) + 10
        self.user_join_times[username] = datetime.utcnow()

        # 🧠 کشِ دائمیِ username->id — تا !item set @user برای کسی که قبلاً دیده شده، حتی وقتی
        # الان آفلاینه هم کار کنه (چون هایرایز جستجوی عمومی با یوزرنیم نداره، فقط با آیدی).
        known_ids = self.config.setdefault("known_user_ids", {})
        if known_ids.get(username) != user.id:
            known_ids[username] = user.id
            self.save_config()

        # 📸 !visitors: شمارشِ بازدیدکنندگانِ یکتای امروز (با تغییرِ روز صفر میشه)
        today = datetime.utcnow().date()
        if today != self.visitors_date:
            self.visitors_date = today
            self.visitors_today = set()
        self.visitors_today.add(username)

        # 📸 !memories: رکوردِ بیشترین جمعیتِ هم‌زمان
        current_population = len(self.active_users)
        peak = self.config.setdefault("peak_population", {"count": 0, "at": None})
        if current_population > peak.get("count", 0):
            peak["count"] = current_population
            peak["at"] = datetime.utcnow().isoformat()
            self.save_config()

        if self.config.get("welcome_enabled", True):
            await self.chat(self.get_message("welcome", username=user.username))
        logger.info(f"کاربر {user.username} (ID: {user.id}) وارد روم شد. موقعیت: {position}")

    async def on_user_leave(self, user: User, position: Position | None = None):
        username = user.username.lower()
        self.active_users.pop(username, None)
        self.user_positions.pop(username, None)
        self.user_join_times.pop(username, None)
        if username in self.dance_tasks:
            self.dance_tasks[username].cancel()
            self.dance_tasks.pop(username, None)
            self.user_dances.pop(username, None)
            self.party_dances.pop(username, None)
        if username in self.frozen_users:
            self.frozen_users[username].cancel()
            self.frozen_users.pop(username, None)
        if self.config.get("goodbye_enabled", True):
            await self.chat(self.get_message("goodbye", username=user.username))
        logger.info(f"کاربر {user.username} (ID: {user.id}) از روم خارج شد. موقعیت: {position}")

    async def sync_room_users(self):
        try:
            room_users = await self.highrise.get_room_users()
            current_users = {user_data[0].username.lower(): user_data for user_data in room_users.content}
            
            for username in list(self.active_users.keys()):
                if username not in current_users:
                    self.active_users.pop(username, None)
                    self.user_positions.pop(username, None)
                    if username in self.dance_tasks:
                        self.dance_tasks[username].cancel()
                        self.dance_tasks.pop(username, None)
                    if username in self.frozen_users:
                        self.frozen_users[username].cancel()
                        self.frozen_users.pop(username, None)
                    logger.info(f"کاربر {username} از لیست‌ها حذف شد (همگام‌سازی).")
            
            for username, user_data in current_users.items():
                if user_data[0].id == self.user_id:
                    continue
                self.active_users[username] = user_data[0]
                self.user_positions[username] = user_data[1]
                self.user_join_times.setdefault(username, datetime.utcnow())
            
            logger.info(f"همگام‌سازی کاربران انجام شد. تعداد کاربران: {len(self.active_users)}. کاربران: {[user.username for user in self.active_users.values()]}")
            await self.chat((f"{len(self.active_users)} کاربر در روم شناسایی شدند." if self.config.get("language","fa") == "fa"
                              else f"{len(self.active_users)} users detected in the room."))
        except Exception as e:
            logger.error(f"خطا در همگام‌سازی کاربران: {e}", exc_info=True)
            await self.chat("خطا در شناسایی کاربران روم." if self.config.get("language","fa") == "fa" else "Error detecting room users.")

    async def announcement_loop(self):
        try:
            while True:
                await sleep(self.config["announcement_interval"])
                await self.chat(self.config["announcement_message"])
                logger.info("پیام اطلاع‌رسانی ارسال شد.")
        except CancelledError:
            logger.info("وظیفه اطلاع‌رسانی لغو شد.")
        except Exception as e:
            logger.error(f"خطا در حلقه اطلاع‌رسانی: {e}")

    async def score_update_loop(self):
        try:
            while True:
                await sleep(300)
                for username in self.active_users:
                    self.user_scores[username] = self.user_scores.get(username, 0) + 5
                logger.info("امتیازات کاربران به‌روزرسانی شد.")
        except CancelledError:
            logger.info("وظیفه به‌روزرسانی امتیازات لغو شد.")
        except Exception as e:
            logger.error(f"خطا در حلقه به‌روزرسانی امتیازات: {e}")

    async def on_user_move(self, user: User, position: Position):
        username = user.username.lower()
        self.user_positions[username] = position
        if username in self.config["admin_usernames"]:
            logger.info(f"ادمین {user.username} به موقعیت x={position.x}, y={position.y}, z={position.z} حرکت کرد.")
        if username in self.frozen_users:
            try:
                original_position = self.user_positions.get(username)
                if original_position:
                    await self.highrise.teleport(user_id=user.id, dest=original_position)
                    logger.info(f"کاربر {username} فریز شده به موقعیت اولیه x={original_position.x}, y={original_position.y}, z={original_position.z} بازگردانده شد.")
            except Exception as e:
                logger.error(f"خطا در بازگرداندن {username} به موقعیت فریز: {e}")

        # 🐾 دنبال کردن (!fallow) — اگه ربات داره این کاربر رو دنبال می‌کنه، با راه رفتن واقعی تعقیبش کن
        if self.following_username and username == self.following_username and user.id != self.user_id:
            try:
                await self.highrise.walk_to(position)
                self.bot_position = position
            except Exception as e:
                logger.error(f"خطا در دنبال کردن {username}: {e}")

        # 🧲 !autotele — اگه کاربر روشنش کرده باشه و فاصله‌اش از مارکِ شخصیِ خودش (!mark) زیاد بشه
        # (مثلاً داره می‌ره طبقه‌ی دیگه)، به‌جای اینکه راهِ طولانی رو پیاده بره، خودکار همون‌جا
        # تلپورت میشه به مارکش.
        if username in self.config.get("autotele_users", []) and user.id != self.user_id:
            mark = self.config.get("user_marks", {}).get(username)
            if mark:
                dx = position.x - mark["x"]
                dy = position.y - mark["y"]
                dz = position.z - mark["z"]
                distance = (dx * dx + dy * dy + dz * dz) ** 0.5
                if distance > AUTOTELE_DISTANCE_THRESHOLD:
                    try:
                        dest = Position(x=mark["x"], y=mark["y"], z=mark["z"])
                        await self.highrise.teleport(user_id=user.id, dest=dest)
                        logger.info(f"autotele: کاربر {username} با فاصله‌ی {distance:.1f} خودکار به مارکش تلپورت شد.")
                    except Exception as e:
                        logger.error(f"خطا در autotele برای {username}: {e}")

        if user.id == self.user_id:
            self.bot_position = position

    async def on_chat(self, user: User, message: str):
        username = user.username.lower()
        msg = message.strip()
        msg_lower = msg.lower()
        
        # بررسی اینکه آیا پیام خصوصیه یا عمومی
        # در Highrise، پیام‌های خصوصی معمولاً از طریق یک channel خاص میرن
        # ولی ما می‌تونیم با بررسی pattern شناختشون
        
        try:
            self.user_scores[username] = self.user_scores.get(username, 0) + 2
            lang = self.config.get("language", "fa")

            # 🛡 آنتی‌اسپم و ضدِ تبلیغِ رومِ دیگه (اگه با !security/!raidguard روشن شده باشن)
            await self._check_security_and_raidguard(user, msg)

            # 🎲 چک کردنِ جوابِ !quiz (فقط وقتی سوالی فعاله و پیام یه دستور نیست)
            if self.active_quiz and not msg_lower.startswith("!"):
                if msg.strip().lower() == self.active_quiz["answer"].strip().lower():
                    self.user_scores[username] = self.user_scores.get(username, 0) + 20
                    lang = self.config.get("language", "fa")
                    await self.chat((f"🎉 @{user.username} درست جواب داد: «{self.active_quiz['answer']}» — ۲۰ امتیاز گرفت!" if lang == "fa"
                                      else f"🎉 @{user.username} got it right: '{self.active_quiz['answer']}' — +20 points!"))
                    self.active_quiz = None

            if username in self.afk_users and msg_lower not in ["afk", "افک"]:
                self.afk_users.discard(username)
                await self.stop_dance(user)
                await self.chat((f"👋 @{user.username} برگشت (دیگه AFK نیست)." if lang == "fa"
                                  else f"👋 @{user.username} is back (no longer AFK)."))

            if msg_lower in ["afk", "افک"]:
                self.afk_users.add(username)
                if self.config.get("dance_enabled", True):
                    await self.start_dance(user, "emote-afk-idle")
                await self.chat((f"💤 @{user.username} غایب (AFK) شد." if lang == "fa"
                                  else f"💤 @{user.username} is now AFK."))
            elif msg_lower in self.emotes and self.config.get("dance_enabled", True):
                emote_name = self.emotes[msg_lower]
                await self.start_dance(user, emote_name)
                await self.chat((f"@{user.username} دنس با موفقیت اجرا شد ({emote_name})" if lang == "fa"
                                  else f"@{user.username} started dancing ({emote_name})"))
            elif msg_lower in ["stop", "استوپ", "0", "۰"]:
                await self.stop_dance(user)
            elif msg_lower in ["سازنده", "creature", "creator", "سازندت", "سازنده بات"]:
                await self.chat("👑 سازنده این بات: @ahoora_king 👑" if lang == "fa" else "👑 This bot's creator: @ahoora_king 👑")
            elif msg.startswith("+"):
                if self.speaker_enabled:
                    await self.handle_speaker_message(user, msg[1:])
                # اگه اسپیکر خاموش باشه، پیام‌های + بی‌صدا نادیده گرفته میشن
            elif msg.startswith("/") and self.config.get("ai_room_enabled", False):
                # 🧠 سوال از هوش مصنوعی تو چت عمومی روم (فقط وقتی !ai on زده شده باشه)
                question = msg[1:].strip()
                answer = await ask_ai(question, lang)
                await self.chat(f"🤖 @{user.username}: {answer}")
            elif msg_lower in self.config.get("teleport_locations", {}):
                loc = self.config["teleport_locations"][msg_lower]
                restricted_rank = loc.get("restricted_rank")
                if loc.get("admin_only", False) and username not in self.config["admin_usernames"]:
                    await self.chat((f"❌ مکان «{msg_lower}» فقط برای ادمین‌های ربات قابل استفاده‌ست." if lang == "fa"
                                      else f"❌ Location \"{msg_lower}\" is only usable by bot admins."))
                elif restricted_rank and username not in [m.lower() for m in self.config["custom_ranks"].get(restricted_rank, [])]:
                    await self.chat((f"❌ مکان «{msg_lower}» فقط برای اعضای رنک «{restricted_rank}» قابل استفاده‌ست." if lang == "fa"
                                      else f"❌ Location \"{msg_lower}\" is only usable by members of the \"{restricted_rank}\" rank."))
                else:
                    try:
                        dest = Position(x=loc["x"], y=loc["y"], z=loc["z"])
                        await self.highrise.teleport(user_id=user.id, dest=dest)
                        await self.chat((f"✅ @{user.username} به «{msg_lower}» تلپورت شد." if lang == "fa"
                                          else f"✅ @{user.username} teleported to \"{msg_lower}\"."))
                    except Exception as e:
                        await self.chat((f"خطا در تلپورت به «{msg_lower}»: {e}" if lang == "fa"
                                          else f"Error teleporting to \"{msg_lower}\": {e}"))
                        logger.error(f"خطا در تلپورت شورتکات {msg_lower}: {e}")
            elif msg_lower.startswith("!"):
                parts = msg.split()
                parts_lower = [p.lower() for p in parts]
                if len(parts_lower) >= 2 and parts_lower[0] == "!item":
                    cmd = f"!item {parts_lower[1]}"
                else:
                    cmd = parts_lower[0]
                if not self.config.get("bot_enabled", True) and cmd != "!boton":
                    # 🔇 وقتی با !botoff خاموش شده، فقط به !boton جواب میده — بقیه‌ی دستورات
                    # (حتی از ادمین) بی‌صدا نادیده گرفته میشن تا واقعاً "خاموش" باشه.
                    pass
                elif cmd in self.commands:
                    await self.commands[cmd](user, parts)
                # ⚠️ اگه دستور تو لیست خودِ این بات نبود، بی‌صدا نادیده می‌گیریم — چون ممکنه
                # مخصوص یه بات دیگه‌ای باشه که تو همین روم فعاله (دی‌جی/بلک‌جک)، نه اینکه غلط باشه.
        except Exception as e:
            logger.error(f"خطا در on_chat از {username}: {e}")

    async def on_message(self, user_id: str, conversation_id: str, is_new_conversation: bool) -> None:
        """⚠️ نکته‌ی مهم فنی: SDK هایرایز به‌جای متنِ پیام، فقط conversation_id رو می‌ده؛
        باید با self.highrise.get_messages(conversation_id) خودِ متن پیام رو جداگانه گرفت.
        نسخه‌ی قبلی این تابع فرض کرده بود که پارامتر دوم مستقیماً متن پیامه که اشتباه بود
        و باعث می‌شد !help/!commands/!dances تو پیوی هیچ‌وقت کار نکنن."""
        if user_id == self.user_id:
            return

        try:
            conversation = await self.highrise.get_messages(conversation_id)
            if not conversation.messages:
                return
            text = conversation.messages[0].content
        except Exception as e:
            logger.error(f"خطا در دریافت متن پیام پیوی (conversation_id={conversation_id}): {e}")
            return

        logger.info(f"📥 دایرکت مسیج جدید از کاربر [{user_id}]: {text}")
        text_clean = text.strip().lower()

        # 🧠 هوش مصنوعی تو پیوی: همیشه فعاله (بدون نیاز به !ai on)، کافیه پیام رو با / شروع کنی
        if text.strip().startswith("/"):
            question = text.strip()[1:].strip()
            lang = self.config.get("language", "fa")
            answer = await ask_ai(question, lang)
            try:
                await self.highrise.send_message(conversation_id, f"🤖 {answer}")
            except Exception as e:
                logger.error(f"خطا در ارسال جواب هوش مصنوعی در پیوی: {e}")
            return

        # 🆘 !help تو پیوی -> راهنمای دو دستور اصلی
        if text_clean == "!help":
            try:
                lang = self.config.get("language", "fa")
                if lang == "en":
                    help_text = (
                        "Hi! 👋 Use these commands to see bot info:\n\n"
                        "1: !commands  -> show the full command list\n"
                        "2: !dances  -> show all dance codes\n"
                        "3: /question  -> ask the AI anything (e.g. /how's the weather today)\n\n"
                        "Just send me these words in DM."
                    )
                else:
                    help_text = (
                        "سلام! 👋 برای دیدن اطلاعات ربات از این دستورات استفاده کن:\n\n"
                        "1: !commands  -> نمایش لیست کامل دستورات ربات\n"
                        "2: !dances  -> نمایش لیست کد تمام دنس‌ها\n"
                        "3: /سوالت  -> هر سوالی داری از هوش مصنوعی بپرس (مثلاً: /هوا امروز چطوره)\n\n"
                        "کافیه همین کلمه‌ها رو برام تو پیوی بفرستی."
                    )
                await self.highrise.send_message(conversation_id, help_text)
            except Exception as e:
                logger.error(f"خطا در ارسال راهنمای !help در پیوی: {e}")
            return

        # 📜 !commands تو پیوی
        if text_clean == "!commands":
            try:
                full_text = self.build_commands_text()
                for chunk in [full_text[i:i + 500] for i in range(0, len(full_text), 500)]:
                    await self.highrise.send_message(conversation_id, chunk)
            except Exception as e:
                logger.error(f"خطا در ارسال لیست دستورات در پیوی: {e}")
            return

        # 💃 !dances تو پیوی
        if text_clean == "!dances":
            try:
                full_text = self.build_dances_text()
                for chunk in [full_text[i:i + 500] for i in range(0, len(full_text), 500)]:
                    await self.highrise.send_message(conversation_id, chunk)
            except Exception as e:
                logger.error(f"خطا در ارسال لیست دنس‌ها در پیوی: {e}")
            return

        # 👑 متن تبلیغاتی و معرفی ویژگی‌های ربات به همراه اطلاعات رنت
        auto_reply = (
            "سلام عزیز! ❤️\n\n"
            "🤖 من یک ربات پیشرفته و فول امکانات برای مدیریت و ارتقای روم هستم!\n\n"
            "✨ **بخشی از قابلیت‌های خفن من:**\n"
            "🔹 دهها دنس جذاب و فعال با تکرار همیشگی و بدون حتی ۱ ثانیه تاخیر! 💃\n"
            "🔹 سیستم خوش‌آمدگویی هوشمند و خودکار به محض ورود پلیرها 🚪\n"
            "🔹 قابلیت رقص همگانی و پارتی خودکار برای کل اعضای روم 🕺\n"
            "🔹 امنیت بالا و مدیریت کامل ادمین‌ها و دستورات اختصاصی 🛠️\n"
            "🔹 میزبانی ۲۴ ساعته و آنلاین بدون قطعی روی سرورهای قدرتمند ⚡\n\n"
            "💬 برای دیدن لیست دستورات، برام بنویس !help\n\n"
            "🤝 **شرایط رنت (اجاره):**\n"
            "برای اجاره یا همان رنت این ربات فوق‌العاده برای روم خود، لطفاً همین الان به آیدی زیر پیام بدید:\n"
            "👉 @ahoora_king 👈"
        )

        try:
            await self.highrise.send_message(conversation_id, auto_reply)
        except Exception as e:
            logger.error(f"خطا در ارسال پاسخ خودکار دایرکت: {e}")

    async def on_tip(self, sender: User, receiver: User, tip):
        try:
            # بررسی ساختار شیء tip برای اطمینان از وجود ویژگی amount
            amount = getattr(tip, "amount", 0)
            lang = self.config.get("language", "fa")
            await self.chat((f"@{sender.username} {amount} گلد به @{receiver.username} داد!" if lang == "fa"
                              else f"@{sender.username} gave {amount} gold to @{receiver.username}!"))
            self.user_scores[sender.username.lower()] = self.user_scores.get(sender.username.lower(), 0) + amount
            logger.info(f"کاربر {sender.username} {amount} گلد به {receiver.username} تیپ داد.")

            # 🎟 اگه یه لاتاری فعاله و این تیپ به خودِ ربات بوده، به‌عنوان خرید بلیط حساب میشه
            if (
                self.lottery
                and self.lottery.get("active")
                and receiver.id == self.user_id
                and amount >= self.lottery["ticket_price"]
            ):
                uname = sender.username.lower()
                self.lottery["entries"].setdefault(uname, {"username": sender.username, "user_id": sender.id, "amount": 0})
                self.lottery["entries"][uname]["amount"] += amount
                await self.chat(
                    (f"🎟 @{sender.username} تو لاتاری شرکت کرد! (مجموع بلیط‌هاش: {self.lottery['entries'][uname]['amount']} گلد)"
                     if lang == "fa" else
                     f"🎟 @{sender.username} entered the lottery! (total tickets: {self.lottery['entries'][uname]['amount']} gold)")
                )

        except Exception as e:
            logger.error(f"خطا در پردازش تیپ از {sender.username} به {receiver.username}: {e}")
            await self.chat((f"خطا در پردازش تیپ از @{sender.username} به @{receiver.username}: {e}" if self.config.get("language", "fa") == "fa"
                              else f"Error processing tip from @{sender.username} to @{receiver.username}: {e}"))

    async def start_dance(self, user: User, emote: str):
        """🐛 دقیقاً همون باگی که تو دنسِ خودِ بات بود اینجا هم بود: اگه اولین send_emote به هر
        دلیلِ گذرایی خطا می‌داد، حلقه برای همیشه ساکت می‌مرد — ولی پیامِ «با موفقیت اجرا شد»
        از قبل (بلافاصله بعدِ create_task، بدونِ صبرکردن برای نتیجه‌ی واقعی) فرستاده می‌شد.
        الان حلقه هم مقاوم شده (دوباره تلاش می‌کنه)."""
        username = user.username.lower()
        await self.stop_dance(user)
        self.user_dances[username] = emote
        duration = self.emote_durations.get(emote, 15.0)
        sleep_time = duration

        async def dance_loop():
            consecutive_errors = 0
            try:
                while self.user_dances.get(username) == emote:
                    try:
                        await self.highrise.send_emote(emote, user.id)
                        consecutive_errors = 0
                        await sleep(sleep_time)
                    except CancelledError:
                        raise
                    except Exception as e:
                        consecutive_errors += 1
                        logger.error(f"خطا در حلقه رقص برای {username} (تلاشِ {consecutive_errors}): {e}")
                        if consecutive_errors >= 5:
                            logger.error(f"۵ بار پشتِ‌سرهم رقصِ {username} شکست خورد — حلقه متوقف شد.")
                            self.user_dances.pop(username, None)
                            return
                        await sleep(min(2.0 * consecutive_errors, 10.0))
            except CancelledError:
                logger.info(f"وظیفه رقص برای {username} لغو شد.")

        task = create_task(dance_loop())
        self.dance_tasks[username] = task
        logger.info(f"کاربر {username} شروع به رقص {emote} کرد.")

    async def stop_dance(self, user: User):
        username = user.username.lower()
        lang = self.config.get("language", "fa")
        if username in self.party_dances and self.party_dances[username][1]:
            await self.chat((f"@{username} نمی‌توانید رقص اجباری را متوقف کنید! فقط ادمین با !partys می‌تواند آن را متوقف کند." if lang == "fa"
                              else f"@{username} you can't stop a forced dance! Only an admin can stop it with !partys."))
            logger.info(f"کاربر {username} سعی کرد رقص اجباری را متوقف کند اما مجاز نیست.")
            return
        if username in self.dance_tasks:
            stopped_emote = self.user_dances.get(username, "نامشخص" if lang == "fa" else "unknown")
            self.user_dances.pop(username, None)
            self.party_dances.pop(username, None)
            self.dance_tasks[username].cancel()
            self.dance_tasks.pop(username, None)
            await self.chat((f"⏹️ @{user.username} دنس متوقف شد. (دنس قبلی: {stopped_emote})" if lang == "fa"
                              else f"⏹️ @{user.username} stopped dancing. (previous dance: {stopped_emote})"))
        else:
            await self.chat((f"@{user.username} تو الان دنسی در حال اجرا نداری." if lang == "fa"
                              else f"@{user.username} you're not dancing right now."))

    async def cmd_help(self, user: User, parts: list):
        lang = self.config.get("language", "fa")
        if lang not in ("fa", "en", "ar"):
            lang = "fa"
        if lang == "fa":
            help_text = (
                "دستورات ربات:\n"
                "1-6 - اجرای رقص\n"
                "stop - توقف رقص\n"
                "!help - نمایش راهنما\n"
                "!spam تعداد پیام - ارسال پیام اسپم\n"
                "!tele @username [vip|vip1|dj|مکان_سفارشی] - تلپورت کاربر\n"
                "!tele to @username - تلپورت به کاربر\n"
                "!tele me @username - تلپورت کاربر به ادمین\n"
                "!tele me all - تلپورت همه به ادمین\n"
                "!heart تعداد @username - ارسال قلب بنفش\n"
                "!heart all - قلب بنفش به همه\n"
                "!clap تعداد @username - ارسال clap\n"
                "!clap all - clap به همه\n"
                "!wink تعداد @username - ارسال wink\n"
                "!wink all - wink به همه\n"
                "!wave تعداد @username - ارسال wave\n"
                "!wave all - wave به همه\n"
                "!thumbs تعداد @username - ارسال thumbs-up\n"
                "!thumbs all - thumbs-up به همه\n"
                "!wallet - نمایش موجودی ربات\n"
                "!set - تلپورت ربات به ادمین\n"
                "!item set @username - تغییر ظاهر ربات به ایتم‌های کاربر\n"
                "!item set eye/hair/lip/eyebrow/skin شماره‌رنگ - فقط رنگِ همون بخش عوض میشه\n"
                "!item set eye/hair/lip/eyebrow/skin لینک [شماره‌رنگ] - جایگزینیِ همون بخش\n"
                "!item set لینک [شماره‌رنگ] - تعویضِ خودکار (بدونِ گفتنِ دسته) برای هرچیزِ دیگه‌ای\n"
                "!item add لینک - افزودنِ بگ/گردنبند/عینک و... بدونِ حذفِ چیزِ دیگه‌ای\n"
                "!tip <تعداد> all - تیپ به همه (هر عددی مجازه)\n"
                "!ban @username - بن کردن کاربر\n"
                "!kill @username - فرستادن به در روم (ادمین)\n"
                "!setkill - ثبت مقصد !kill از موقعیت خودت (ادمین)\n"
                "!info - اطلاعات روم\n"
                "!info @username - اطلاعات یک کاربر\n"
                "!lottery start قیمت دقیقه - شروع لاتاری (ادمین)\n"
                "!unban @username - آنبن کردن کاربر\n"
                "!dancechain - اجرای زنجیره رقص\n"
                "!addtele نام_مکان - ذخیره مکان جدید\n"
                "!deltele نام_مکان - حذف مکان تلپورت\n"
                "!welcome پیام - تنظیم پیام خوش‌آمدگویی\n"
                "!addadmin @username - افزودن ادمین (فقط Host)\n"
                "!removeadmin @username - حذف ادمین (فقط Host)\n"
                "!emotebot نام/شماره_دنس - تغییر دنس مداوم ربات (فقط ادمین)\n"
                "!loop پیام - تنظیم پیام تکرارشونده/اسپم ربات (فقط ادمین)\n"
                "!listadd - نمایش لیست همه رتبه‌ها (Host/Owner/Manager/Admin/Mod/VIP)\n"
                "!give رتبه @username - دادن رتبه (مثلا !give admin @user)\n"
                "!give -رتبه @username - گرفتن رتبه (مثلا !give -admin @user)\n"
                "!freeze @username - فریز کردن کاربر\n"
                "!unfreeze @username - آزاد کردن کاربر از فریز\n"
                "!party @username عدد - اجرای رقص اجباری برای کاربر\n"
                "!party all عدد - اجرای رقص برای همه\n"
                "!partys @username - توقف رقص اجباری کاربر\n"
                "!warn @username [دلیل] - ثبت اخطار (با ۵ اخطار خودکار کیک میشه)\n"
                "!warns @username - نمایش اخطارهای یه کاربر\n"
                "!clearwarn @username - پاک‌کردن اخطارهای یه کاربر\n"
                "!jail @username [دقیقه] - تبعید به زندان (اول !addtele jail بزن)\n"
                "!unjail @username - آزادکردن از زندان\n"
                "!mod-list - فهرست هاست‌ها و ادمین‌ها\n"
                "!muted - فهرست کاربرهای میوت‌شده\n"
                "!modlog - آخرین اقدامات نظارتی\n"
                "!security on/off - آنتی‌اسپمِ خودکار\n"
                "!raidguard on/off - ضدِ تبلیغِ رومِ دیگه\n"
                "!report @username [دلیل] - گزارشِ یه کاربر به ادمین‌های آنلاین\n"
                "!welcomelist - نمایشِ همه‌ی پیام‌های خوش‌آمد\n"
                "!delwelcome شماره - حذفِ یه پیامِ خوش‌آمد\n"
                "!welcomeon / !welcomeoff - روشن‌خاموش‌کردنِ کاملِ پیامِ خوش‌آمد\n"
                "!addgoodbye پیام - افزودنِ پیامِ خداحافظی (دقیقاً مثلِ !addwelcome)\n"
                "!goodbyelist / !delgoodbye شماره - نمایش/حذفِ پیام‌های خداحافظی\n"
                "!goodbyeon / !goodbyeoff - روشن‌خاموش‌کردنِ کاملِ پیامِ خداحافظی\n"
                "!mark - ذخیره‌ی موقعیتِ فعلیِ شما به‌عنوانِ مارکِ شخصی\n"
                "!autotele on/off - تلپورتِ خودکار به مارکِ خودتون وقتی فاصله زیاد بشه\n"
                "!language fa/en - تغییرِ زبانِ بات\n"
                "!botoff / !boton - خاموش‌روشن‌کردنِ کاملِ پاسخ‌گوییِ بات\n"
                "!dm @username متن - پیامِ خصوصی (ویسپر)\n"
                "!sethome / !home / !delhome - خونه‌ی بات\n"
                "!ah on/off یا !autohome on/off - رفتنِ خودکار به خونه با هر وصل‌شدن/ری‌استارت\n"
                "!mod @username / !unmod @username - افزودن یا حذف ناظر (دسترسیِ محدود)\n"
                "!vip-list - فهرستِ VIPها | !vip-args - مزایای VIP\n"
                "!tempvip @username دقیقه - VIPِ موقت | !untempvip @username - گرفتنِ زودهنگام\n"
                "!summ @username یا !summ all - احضارِ کاربر(ها) کنارِ خودت\n"
                "!quiz سوال | جواب - مسابقه‌ی امتیازی\n"
                "!top - جدولِ امتیازها\n"
                "!visitors - بازدیدکنندگانِ یکتای امروز\n"
                "!memories - رکوردِ بیشترین جمعیتِ هم‌زمان\n"
                "!countdown ثانیه [پیام] - شمارشِ معکوس\n"
                "!schedule دقیقه پیام - پیامِ زمان‌بندی‌شده (یه‌بار)\n"
                "!stats - آمارِ کلیِ روم\n"
                "!down - تلپورت به سطحِ زمین\n"
                "!move آیدیِ‌روم یا لینک - 🔒 فقط Host: انتقالِ کاملِ بات به یه روم دیگه\n\n"
                "📩 برای اطلاعات بیشتر به @ahoora_king پیام بدید!"
            )
        elif lang == "en":
            help_text = (
                "Bot commands:\n"
                "1-6 - perform a dance\n"
                "stop - stop dancing\n"
                "!help - show this help\n"
                "!spam <count> <message> - send a spam message\n"
                "!tele @username [vip|vip1|dj|custom_location] - teleport a user\n"
                "!tele to @username - teleport to a user\n"
                "!tele me @username - teleport a user to the admin\n"
                "!tele me all - teleport everyone to the admin\n"
                "!heart <count> @username - send purple hearts\n"
                "!heart all - send hearts to everyone\n"
                "!clap <count> @username - send claps\n"
                "!clap all - claps to everyone\n"
                "!wink <count> @username - send winks\n"
                "!wink all - winks to everyone\n"
                "!wave <count> @username - send waves\n"
                "!wave all - waves to everyone\n"
                "!thumbs <count> @username - send thumbs-up\n"
                "!thumbs all - thumbs-up to everyone\n"
                "!wallet - show the bot's gold balance\n"
                "!set - teleport the bot to the admin\n"
                "!item set @username - change the bot's outfit to that user's items\n"
                "!item set eye/hair/lip/eyebrow/skin <color_number> - just recolor that part\n"
                "!item set eye/hair/lip/eyebrow/skin <link> [color_number] - replace that part\n"
                "!item set <link> [color_number] - auto-detect category for anything else\n"
                "!item add <link> - add a bag/necklace/glasses/etc. without removing anything\n"
                "!tip <amount> all - tip everyone (any amount)\n"
                "!ban @username - ban a user\n"
                "!kill @username - send them to the door (admin)\n"
                "!setkill - set the !kill destination to your position (admin)\n"
                "!info - room info\n"
                "!info @username - info about a specific user\n"
                "!lottery start <price> <minutes> - start a lottery (admin)\n"
                "!unban @username - unban a user\n"
                "!dancechain - perform a dance chain\n"
                "!addtele <location_name> - save a new location\n"
                "!deltele <location_name> - delete a teleport location\n"
                "!welcome <message> - set the welcome message\n"
                "!addadmin @username - add an admin (Host only)\n"
                "!removeadmin @username - remove an admin (Host only)\n"
                "!emotebot <name/number> - set the bot's continuous dance (admin only)\n"
                "!loop <message> - set the bot's looping/spam message (admin only)\n"
                "!listadd - show every rank (Host/Owner/Manager/Admin/Mod/VIP) and its members\n"
                "!give <rank> @username - give a rank (e.g. !give admin @user)\n"
                "!give -<rank> @username - take a rank (e.g. !give -admin @user)\n"
                "!freeze @username - freeze a user\n"
                "!unfreeze @username - unfreeze a user\n"
                "!party @username <number> - force a dance on a user\n"
                "!party all <number> - force a dance on everyone\n"
                "!partys @username - stop a user's forced dance\n"
                "!warn @username [reason] - issue a warning (5 warnings = auto-kick)\n"
                "!warns @username - show a user's warnings\n"
                "!clearwarn @username - clear a user's warnings\n"
                "!jail @username [minutes] - send to jail (set spot first with !addtele jail)\n"
                "!unjail @username - release from jail\n"
                "!mod-list - list hosts and admins\n"
                "!muted - list currently muted users\n"
                "!modlog - recent moderation actions\n"
                "!security on/off - automatic anti-spam\n"
                "!raidguard on/off - block other-room advertising\n"
                "!report @username [reason] - report a user to online admins\n"
                "!welcomelist - show all welcome messages\n"
                "!delwelcome <number> - remove a welcome message\n"
                "!welcomeon / !welcomeoff - toggle the welcome message entirely\n"
                "!addgoodbye <message> - add a goodbye message (just like !addwelcome)\n"
                "!goodbyelist / !delgoodbye <number> - show/remove goodbye messages\n"
                "!goodbyeon / !goodbyeoff - toggle the goodbye message entirely\n"
                "!mark - save your current position as your personal mark\n"
                "!autotele on/off - auto-teleport to your mark when you get far from it\n"
                "!language fa/en - change the bot's language\n"
                "!botoff / !boton - toggle whether the bot responds at all\n"
                "!dm @username <text> - private message (whisper)\n"
                "!sethome / !home / !delhome - the bot's home spot\n"
                "!ah on/off or !autohome on/off - auto-go-home on every connect/restart\n"
                "!mod @username / !unmod @username - add or remove a moderator (limited access)\n"
                "!vip-list - list VIPs | !vip-args - show VIP perks\n"
                "!tempvip @username <minutes> - temporary VIP | !untempvip @username - remove early\n"
                "!summ @username or !summ all - summon user(s) to you\n"
                "!quiz question | answer - trivia contest\n"
                "!top - leaderboard\n"
                "!visitors - unique visitors today\n"
                "!memories - peak concurrent population record\n"
                "!countdown <seconds> [message] - countdown\n"
                "!schedule <minutes> <message> - one-time scheduled message\n"
                "!stats - room stats overview\n"
                "!down - teleport to ground level\n"
                "!move <room ID or link> - 🔒 Host only: move the whole bot to a different room\n\n"
                "📩 Message @ahoora_king for more info!"
            )
        elif lang == "ar":
            help_text = (
                "أوامر البوت:\n"
                "1-6 - تنفيذ رقصة\n"
                "stop - إيقاف الرقص\n"
                "!help - عرض هذه المساعدة\n"
                "!spam <عدد> <رسالة> - إرسال رسائل سبام\n"
                "!tele @username [vip|vip1|dj|موقع_مخصص] - نقل مستخدم\n"
                "!tele to @username - النقل إلى مستخدم\n"
                "!tele me @username - نقل مستخدم إليك\n"
                "!tele me all - نقل الجميع إليك\n"
                "!heart <عدد> @username - إرسال قلوب بنفسجية\n"
                "!heart all - قلوب للجميع\n"
                "!clap <عدد> @username - إرسال تصفيق\n"
                "!clap all - تصفيق للجميع\n"
                "!wink <عدد> @username - إرسال غمزات\n"
                "!wink all - غمزات للجميع\n"
                "!wave <عدد> @username - إرسال تلويحات\n"
                "!wave all - تلويحات للجميع\n"
                "!thumbs <عدد> @username - إرسال إعجاب\n"
                "!thumbs all - إعجاب للجميع\n"
                "!wallet - عرض رصيد البوت\n"
                "!set - نقل البوت إليك\n"
                "!item set @username - تغيير مظهر البوت إلى ملابس ذلك المستخدم\n"
                "!item set eye/hair/lip/eyebrow/skin <رقم_اللون> - تغيير لون ذلك الجزء فقط\n"
                "!item set eye/hair/lip/eyebrow/skin <رابط> [رقم_اللون] - استبدال ذلك الجزء\n"
                "!item set <رابط> [رقم_اللون] - استبدال تلقائي (بدون تحديد الفئة) لأي شيء آخر\n"
                "!item add <رابط> - إضافة حقيبة/قلادة/نظارة وغيرها دون حذف أي شيء\n"
                "!tip <مبلغ> all - إعطاء الجميع إكرامية (أي مبلغ)\n"
                "!ban @username - حظر مستخدم\n"
                "!kill @username - إرسال المستخدم إلى الباب (أدمن)\n"
                "!setkill - تعيين وجهة !kill من موقعك الحالي (أدمن)\n"
                "!info - معلومات الغرفة\n"
                "!info @username - معلومات عن مستخدم معيّن\n"
                "!lottery start <سعر> <دقائق> - بدء يانصيب (أدمن)\n"
                "!unban @username - إلغاء حظر مستخدم\n"
                "!dancechain - تنفيذ سلسلة رقص\n"
                "!addtele <اسم_الموقع> - حفظ موقع جديد\n"
                "!deltele <اسم_الموقع> - حذف موقع نقل\n"
                "!welcome <رسالة> - تعيين رسالة الترحيب\n"
                "!addadmin @username - إضافة أدمن (هوست فقط)\n"
                "!removeadmin @username - إزالة أدمن (هوست فقط)\n"
                "!emotebot <اسم/رقم_الرقصة> - تعيين الرقصة المستمرة للبوت (أدمن فقط)\n"
                "!loop <رسالة> - تعيين رسالة التكرار/السبام للبوت (أدمن فقط)\n"
                "!listadd - عرض كل رتبة وأعضائها\n"
                "!give <رتبة> @username - إعطاء رتبة (مثال: !give admin @user)\n"
                "!give -<رتبة> @username - سحب رتبة (مثال: !give -admin @user)\n"
                "!freeze @username - تجميد مستخدم\n"
                "!unfreeze @username - إلغاء تجميد مستخدم\n"
                "!party @username <رقم> - فرض رقصة على مستخدم\n"
                "!party all <رقم> - فرض رقصة على الجميع\n"
                "!partys @username - إيقاف الرقص الإجباري لمستخدم\n"
                "!warn @username [سبب] - تسجيل إنذار (5 إنذارات = طرد تلقائي)\n"
                "!warns @username - عرض إنذارات مستخدم\n"
                "!clearwarn @username - مسح إنذارات مستخدم\n"
                "!jail @username [دقائق] - إرسال إلى السجن (عيّن الموقع أولاً بـ !addtele jail)\n"
                "!unjail @username - الإفراج عن مستخدم\n"
                "!mod-list - قائمة الهوستات والأدمنز\n"
                "!muted - قائمة المستخدمين المكتومين حاليًا\n"
                "!modlog - آخر إجراءات الإشراف\n"
                "!security on/off - الحماية التلقائية من السبام\n"
                "!raidguard on/off - منع الإعلان عن غرف أخرى\n"
                "!report @username [سبب] - الإبلاغ عن مستخدم للأدمنز المتصلين\n"
                "!welcomelist - عرض كل رسائل الترحيب\n"
                "!delwelcome <رقم> - حذف رسالة ترحيب\n"
                "!welcomeon / !welcomeoff - تفعيل/إيقاف رسالة الترحيب بالكامل\n"
                "!addgoodbye <رسالة> - إضافة رسالة وداع (تمامًا مثل !addwelcome)\n"
                "!goodbyelist / !delgoodbye <رقم> - عرض/حذف رسائل الوداع\n"
                "!goodbyeon / !goodbyeoff - تفعيل/إيقاف رسالة الوداع بالكامل\n"
                "!mark - حفظ موقعك الحالي كعلامة شخصية\n"
                "!autotele on/off - النقل التلقائي إلى علامتك عند الابتعاد عنها\n"
                "!language fa/en/ar - تغيير لغة البوت\n"
                "!botoff / !boton - تفعيل/إيقاف استجابة البوت بالكامل\n"
                "!dm @username <نص> - رسالة خاصة (همس)\n"
                "!sethome / !home / !delhome - منزل البوت\n"
                "!ah on/off أو !autohome on/off - العودة التلقائية للمنزل عند كل اتصال/إعادة تشغيل\n"
                "!mod @username / !unmod @username - إضافة أو إزالة مشرف (صلاحيات محدودة)\n"
                "!vip-list - قائمة الـ VIP | !vip-args - مزايا الـ VIP\n"
                "!tempvip @username <دقائق> - VIP مؤقت | !untempvip @username - إزالة مبكرة\n"
                "!summ @username أو !summ all - استدعاء مستخدم/الجميع إليك\n"
                "!quiz سؤال | جواب - مسابقة\n"
                "!top - لوحة النقاط\n"
                "!visitors - الزوار الفريدون اليوم\n"
                "!memories - أعلى رقم للتواجد المتزامن\n"
                "!countdown <ثواني> [رسالة] - عد تنازلي\n"
                "!schedule <دقائق> <رسالة> - رسالة مجدولة (مرة واحدة)\n"
                "!stats - نظرة عامة على إحصائيات الغرفة\n"
                "!down - النقل إلى مستوى الأرض\n"
                "!move <معرف الغرفة أو رابطها> - 🔒 هوست فقط: نقل البوت بالكامل إلى غرفة أخرى\n\n"
                "📩 راسل @ahoora_king لمزيد من المعلومات!"
            )
        header = ("✨═══════ 📖 راهنمای کامل بات ═══════✨\n" if lang == "fa"
                  else "✨═══════ 📖 دليل البوت الكامل ═══════✨\n" if lang == "ar"
                  else "✨═══════ 📖 FULL BOT GUIDE ═══════✨\n")
        footer = ("\n✨═══════════════════════════✨" if lang == "fa"
                  else "\n✨═══════════════════════════✨")
        help_text = header + help_text + footer
        for chunk in [help_text[i:i+200] for i in range(0, len(help_text), 200)]:
            await self.chat(chunk)
        logger.info(f"راهنما توسط {user.username} درخواست شد.")

    async def cmd_spam(self, user: User, parts: list):
        if user.username.lower() not in self.config["admin_usernames"]:
            await self.chat(self.get_message("no_permission"))
            logger.info(f"کاربر {user.username} دسترسی لازم برای اجرای !spam را ندارد.")
            return
        lang = self.config.get("language", "fa")

        parts = [p.lower() for p in parts]
        if len(parts) < 2 or not parts[1].isdigit():
            await self.chat(self.get_message("invalid_format", format=("!spam تعداد پیام" if self.config.get("language","fa") == "fa" else "!spam <count> <message>")))
            logger.info(f"فرمت نادرست برای دستور !spam توسط {user.username} وارد شد.")
            return

        try:
            count = int(parts[1])
            default_msg = "اسپم آزمایشی!" if lang == "fa" else "Test spam!"
            spam_message = " ".join(parts[2:]) if len(parts) > 2 else default_msg
            if count < 1 or count > 100:
                await self.chat("تعداد پیام‌ها باید بین 1 تا 100 باشد." if lang == "fa" else "Message count must be between 1 and 100.")
                logger.info(f"تعداد پیام‌های نامعتبر ({count}) توسط {user.username} وارد شد.")
                return

            for _ in range(count):
                await self.chat(spam_message)
                await sleep(SPAM_DELAY_SECONDS)
            logger.info(f"{count} پیام اسپم توسط {user.username} ارسال شد: {spam_message}")
            await self.chat(f"{count} پیام اسپم ارسال شد!" if lang == "fa" else f"{count} spam messages sent!")
        except Exception as e:
            await self.chat((f"خطا در ارسال پیام اسپم: {str(e)}" if lang == "fa" else f"Error sending spam messages: {str(e)}"))
            logger.error(f"خطا در cmd_spam برای {user.username}: {str(e)}")

    async def cmd_tele(self, user: User, parts: list):
        if user.username.lower() not in self.config["admin_usernames"]:
            await self.chat(self.get_message("no_permission"))
            logger.info(f"کاربر {user.username} دسترسی لازم برای اجرای !tele را ندارد.")
            return
        lang = self.config.get("language", "fa")

        parts = [p.lower() for p in parts]
        
        if len(parts) == 3 and parts[1].startswith("@"):
            target_username = parts[1][1:].lower()
            location = parts[2]
            target_user = self.active_users.get(target_username)
            if not target_user:
                await self.chat(self.get_message("user_not_found", username=target_username))
                logger.info(f"کاربر هدف {target_username} توسط {user.username} پیدا نشد.")
                return
            if location not in self.config["teleport_locations"]:
                await self.chat((f"مکان {location} وجود ندارد!" if lang == "fa" else f"Location {location} doesn't exist!"))
                logger.info(f"مکان {location} توسط {user.username} برای تلپورت پیدا نشد.")
                return
            try:
                dest_data = self.config["teleport_locations"][location]
                dest = Position(x=dest_data["x"], y=dest_data["y"], z=dest_data["z"])
                await self.highrise.teleport(user_id=target_user.id, dest=dest)
                await self.chat(self.get_message("teleport_success", username=target_user.username, location=location.upper()))
                logger.info(f"کاربر {target_username} به {location} تلپورت شد.")
            except Exception as e:
                await self.chat(self.get_message("teleport_error", error=str(e)))
                logger.error(f"خطا در تلپورت {target_username} به {location}: {e}")

        elif len(parts) == 3 and parts[1] == "to" and parts[2].startswith("@"):
            target_username = parts[2][1:].lower()
            target_user = self.active_users.get(target_username)
            if not target_user:
                await self.chat(self.get_message("user_not_found", username=target_username))
                logger.info(f"کاربر هدف {target_username} توسط {user.username} پیدا نشد.")
                return
            try:
                position = self.user_positions.get(target_username)
                if position:
                    await self.highrise.teleport(user_id=user.id, dest=position)
                    await self.chat((f"@{user.username} به مکان @{target_user.username} تلپورت شد." if lang == "fa"
                                      else f"@{user.username} teleported to @{target_user.username}'s location."))
                    logger.info(f"کاربر {user.username} به مکان {target_username} تلپورت شد.")
                else:
                    await self.chat("موقعیت کاربر در دسترس نیست." if lang == "fa" else "User's position isn't available.")
                    logger.info(f"موقعیت {target_username} برای تلپورت {user.username} در دسترس نیست.")
            except Exception as e:
                await self.chat(self.get_message("teleport_error", error=str(e)))
                logger.error(f"خطا در تلپورت به {target_username}: {e}")

        elif len(parts) == 3 and parts[1] == "me" and parts[2].startswith("@"):
            target_username = parts[2][1:].lower()
            target_user = self.active_users.get(target_username)
            if not target_user:
                await self.chat(self.get_message("user_not_found", username=target_username))
                logger.info(f"کاربر هدف {target_username} توسط {user.username} پیدا نشد.")
                return
            try:
                position = self.user_positions.get(user.username.lower())
                if position:
                    await self.highrise.teleport(user_id=target_user.id, dest=position)
                    await self.chat((f"@{target_user.username} به مکان @{user.username} تلپورت شد." if lang == "fa"
                                      else f"@{target_user.username} teleported to @{user.username}'s location."))
                    logger.info(f"کاربر {target_username} به مکان {user.username} تلپورت شد.")
                else:
                    await self.chat("موقعیت شما در دسترس نیست." if lang == "fa" else "Your position isn't available.")
                    logger.info(f"موقعیت {user.username} برای تلپورت {target_username} در دسترس نیست.")
            except Exception as e:
                await self.chat(self.get_message("teleport_error", error=str(e)))
                logger.error(f"خطا در تلپورت {target_username} به {user.username}: {e}")

        elif len(parts) == 3 and parts[1] == "me" and parts[2] == "all":
            admin_position = self.user_positions.get(user.username.lower())
            if not admin_position:
                await self.chat("موقعیت شما در دسترس نیست." if self.config.get("language","fa") == "fa" else "Your position isn't available.")
                logger.info(f"موقعیت {user.username} برای تلپورت همه کاربران در دسترس نیست.")
                return
            try:
                successful_teleports = 0
                for username, target_user in self.active_users.items():
                    if target_user.id == user.id or target_user.id == self.user_id:
                        continue
                    if username not in self.active_users:
                        logger.info(f"کاربر {username} در حین تلپورت آفلاین شد.")
                        continue
                    try:
                        await self.highrise.teleport(user_id=target_user.id, dest=admin_position)
                        successful_teleports += 1
                        await sleep(0.5)
                    except Exception as e:
                        logger.error(f"خطا در تلپورت {username} به {user.username}: {e}")
                await self.chat((f"{successful_teleports} کاربر به مکان @{user.username} تلپورت شدند." if self.config.get("language","fa") == "fa"
                                  else f"{successful_teleports} users teleported to @{user.username}'s location."))
                logger.info(f"{successful_teleports} کاربر به مکان {user.username} تلپورت شدند.")
            except Exception as e:
                await self.chat(self.get_message("teleport_error", error=str(e)))
                logger.error(f"خطا در تلپورت همه کاربران به {user.username}: {e}")

        else:
            await self.chat(self.get_message("invalid_format", format=("!tele @username [مکان] یا !tele to @username یا !tele me @username یا !tele me all" if self.config.get("language","fa") == "fa"
                                                                              else "!tele @username [location] or !tele to @username or !tele me @username or !tele me all")))
            logger.info(f"فرمت نادرست برای دستور !tele توسط {user.username} وارد شد.")

    async def cmd_heart(self, user: User, parts: list):
        parts = [p.lower() for p in parts]
        lang = self.config.get("language", "fa")

        if parts[0] == "!heart" and len(parts) == 2 and parts[1] == "all":
            if user.username.lower() not in self.config["admin_usernames"]:
                await self.chat(self.get_message("no_permission"))
                return
            try:
                active_users = list(self.active_users.items())
                active_users_count = len([u for u in active_users if u[1].id != self.user_id])
                if active_users_count == 0:
                    await self.chat("هیچ کاربری در روم آنلاین نیست!" if lang == "fa" else "No users are online in the room!")
                    return
                reaction_id = resolve_reaction("heart")
                successful_hearts = 0
                for username, target_user in active_users:
                    if target_user.id == self.user_id:
                        continue
                    if username not in self.active_users:
                        logger.info(f"کاربر {username} در حین ارسال قلب آفلاین شد.")
                        continue
                    try:
                        await self.highrise.react(reaction_id, target_user.id)
                        successful_hearts += 1
                        await sleep(0.5)
                    except Exception as e:
                        await self.chat((f"خطا در ارسال قلب بنفش به @{target_user.username}: {e}" if lang == "fa"
                                          else f"Error sending heart to @{target_user.username}: {e}"))
                        logger.error(f"خطا در ارسال قلب به {target_user.username}: {e}")
                if successful_hearts > 0:
                    await self.chat(self.get_message("heart_all_success", count=successful_hearts))
                    logger.info(f"قلب بنفش به {successful_hearts} نفر ارسال شد.")
                else:
                    await self.chat("هیچ قلبی با موفقیت ارسال نشد." if lang == "fa" else "No hearts were sent successfully.")
            except Exception as e:
                await self.chat((f"خطا در اجرای دستور: {e}" if lang == "fa" else f"Error running command: {e}"))
                logger.error(f"خطا در ارسال قلب به همه: {e}")
            return

        if len(parts) != 3:
            await self.chat(self.get_message("invalid_format", format=("!heart تعداد @username یا !heart all" if self.config.get("language","fa") == "fa" else "!heart <count> @username or !heart all")))
            return

        try:
            count = int(parts[1])
            if count < 1 or count > 100:
                await self.chat((f"@{user.username}: تعداد باید بین 1 تا 100 باشد." if lang == "fa"
                                  else f"@{user.username}: count must be between 1 and 100."))
                return
        except ValueError:
            await self.chat((f"@{user.username}: عدد نامعتبر است." if lang == "fa" else f"@{user.username}: invalid number."))
            return

        target_username = parts[2].lstrip('@').lower()
        target_user = next((u for u in self.active_users.values() if u.username.lower() == target_username), None)

        if not target_user:
            await self.chat(self.get_message("user_not_found", username=target_username))
            return

        try:
            reaction_id = resolve_reaction("heart")
            for _ in range(count):
                if target_user.username.lower() not in self.active_users:
                    await self.chat((f"کاربر @{target_user.username} آفلاین شد و قلب ارسال نشد." if lang == "fa"
                                      else f"@{target_user.username} went offline, hearts stopped."))
                    logger.info(f"کاربر {target_user.username} در حین ارسال قلب آفلاین شد.")
                    return
                await self.highrise.react(reaction_id, target_user.id)
                await sleep(0.5)
            await self.chat(self.get_message("heart_success", count=count, username=target_user.username))
            logger.info(f"{count} قلب بنفش به {target_user.username} ارسال شد.")
        except Exception as e:
            await self.chat((f"خطا در ارسال قلب بنفش: {e}" if lang == "fa" else f"Error sending hearts: {e}"))
            logger.error(f"خطا در ارسال قلب به {target_username}: {e}")

    async def cmd_clap(self, user: User, parts: list):
        parts = [p.lower() for p in parts]
        lang = self.config.get("language", "fa")

        if parts[0] == "!clap" and len(parts) == 2 and parts[1] == "all":
            if user.username.lower() not in self.config["admin_usernames"]:
                await self.chat(self.get_message("no_permission"))
                return
            try:
                active_users = list(self.active_users.items())
                active_users_count = len([u for u in active_users if u[1].id != self.user_id])
                if active_users_count == 0:
                    await self.chat("هیچ کاربری در روم آنلاین نیست!" if lang == "fa" else "No users are online in the room!")
                    return
                reaction_id = resolve_reaction("clap")
                successful_reactions = 0
                for username, target_user in active_users:
                    if target_user.id == self.user_id:
                        continue
                    if username not in self.active_users:
                        logger.info(f"کاربر {username} در حین ارسال clap آفلاین شد.")
                        continue
                    try:
                        await self.highrise.react(reaction_id, target_user.id)
                        successful_reactions += 1
                        await sleep(0.5)
                    except Exception as e:
                        await self.chat((f"خطا در ارسال clap به @{target_user.username}: {e}" if lang == "fa"
                                          else f"Error sending clap to @{target_user.username}: {e}"))
                        logger.error(f"خطا در ارسال clap به {target_user.username}: {e}")
                if successful_reactions > 0:
                    await self.chat(self.get_message("heart_all_success", count=successful_reactions))
                    logger.info(f"Clap به {successful_reactions} نفر ارسال شد.")
                else:
                    await self.chat("هیچ clap با موفقیت ارسال نشد." if lang == "fa" else "No claps were sent successfully.")
            except Exception as e:
                await self.chat((f"خطا در اجرای دستور: {e}" if lang == "fa" else f"Error running command: {e}"))
                logger.error(f"خطا در ارسال clap به همه: {e}")
            return

        if len(parts) != 3:
            await self.chat(self.get_message("invalid_format", format=("!clap تعداد @username یا !clap all" if self.config.get("language","fa") == "fa" else "!clap <count> @username or !clap all")))
            return

        try:
            count = int(parts[1])
            if count < 1 or count > 100:
                await self.chat((f"@{user.username}: تعداد باید بین 1 تا 100 باشد." if lang == "fa"
                                  else f"@{user.username}: count must be between 1 and 100."))
                return
        except ValueError:
            await self.chat((f"@{user.username}: عدد نامعتبر است." if lang == "fa" else f"@{user.username}: invalid number."))
            return

        target_username = parts[2].lstrip('@').lower()
        target_user = next((u for u in self.active_users.values() if u.username.lower() == target_username), None)

        if not target_user:
            await self.chat(self.get_message("user_not_found", username=target_username))
            return

        try:
            reaction_id = resolve_reaction("clap")
            for _ in range(count):
                if target_user.username.lower() not in self.active_users:
                    await self.chat((f"کاربر @{target_user.username} آفلاین شد و clap ارسال نشد." if lang == "fa"
                                      else f"@{target_user.username} went offline, claps stopped."))
                    logger.info(f"کاربر {target_user.username} در حین ارسال clap آفلاین شد.")
                    return
                await self.highrise.react(reaction_id, target_user.id)
                await sleep(0.5)
            await self.chat(self.get_message("clap_success", count=count, username=target_user.username))
            logger.info(f"{count} clap به {target_user.username} ارسال شد.")
        except Exception as e:
            await self.chat((f"خطا در ارسال clap: {e}" if lang == "fa" else f"Error sending claps: {e}"))
            logger.error(f"خطا در ارسال clap به {target_username}: {e}")

    async def cmd_wink(self, user: User, parts: list):
        parts = [p.lower() for p in parts]
        lang = self.config.get("language", "fa")

        if parts[0] == "!wink" and len(parts) == 2 and parts[1] == "all":
            if user.username.lower() not in self.config["admin_usernames"]:
                await self.chat(self.get_message("no_permission"))
                return
            try:
                active_users = list(self.active_users.items())
                active_users_count = len([u for u in active_users if u[1].id != self.user_id])
                if active_users_count == 0:
                    await self.chat("هیچ کاربری در روم آنلاین نیست!" if lang == "fa" else "No users are online in the room!")
                    return
                reaction_id = resolve_reaction("wink")
                successful_reactions = 0
                for username, target_user in active_users:
                    if target_user.id == self.user_id:
                        continue
                    if username not in self.active_users:
                        logger.info(f"کاربر {username} در حین ارسال wink آفلاین شد.")
                        continue
                    try:
                        await self.highrise.react(reaction_id, target_user.id)
                        successful_reactions += 1
                        await sleep(0.5)
                    except Exception as e:
                        await self.chat((f"خطا در ارسال wink به @{target_user.username}: {e}" if lang == "fa"
                                          else f"Error sending wink to @{target_user.username}: {e}"))
                        logger.error(f"خطا در ارسال wink به {target_user.username}: {e}")
                if successful_reactions > 0:
                    await self.chat(self.get_message("heart_all_success", count=successful_reactions))
                    logger.info(f"Wink به {successful_reactions} نفر ارسال شد.")
                else:
                    await self.chat("هیچ wink با موفقیت ارسال نشد." if lang == "fa" else "No winks were sent successfully.")
            except Exception as e:
                await self.chat((f"خطا در اجرای دستور: {e}" if lang == "fa" else f"Error running command: {e}"))
                logger.error(f"خطا در ارسال wink به همه: {e}")
            return

        if len(parts) != 3:
            await self.chat(self.get_message("invalid_format", format=("!wink تعداد @username یا !wink all" if self.config.get("language","fa") == "fa" else "!wink <count> @username or !wink all")))
            return

        try:
            count = int(parts[1])
            if count < 1 or count > 100:
                await self.chat((f"@{user.username}: تعداد باید بین 1 تا 100 باشد." if lang == "fa"
                                  else f"@{user.username}: count must be between 1 and 100."))
                return
        except ValueError:
            await self.chat((f"@{user.username}: عدد نامعتبر است." if lang == "fa" else f"@{user.username}: invalid number."))
            return

        target_username = parts[2].lstrip('@').lower()
        target_user = next((u for u in self.active_users.values() if u.username.lower() == target_username), None)

        if not target_user:
            await self.chat(self.get_message("user_not_found", username=target_username))
            return

        try:
            reaction_id = resolve_reaction("wink")
            for _ in range(count):
                if target_user.username.lower() not in self.active_users:
                    await self.chat((f"کاربر @{target_user.username} آفلاین شد و wink ارسال نشد." if lang == "fa"
                                      else f"@{target_user.username} went offline, winks stopped."))
                    logger.info(f"کاربر {target_user.username} در حین ارسال wink آفلاین شد.")
                    return
                await self.highrise.react(reaction_id, target_user.id)
                await sleep(0.5)
            await self.chat(self.get_message("wink_success", count=count, username=target_user.username))
            logger.info(f"{count} wink به {target_user.username} ارسال شد.")
        except Exception as e:
            await self.chat((f"خطا در ارسال wink: {e}" if lang == "fa" else f"Error sending winks: {e}"))
            logger.error(f"خطا در ارسال wink به {target_username}: {e}")

    async def cmd_wave(self, user: User, parts: list):
        parts = [p.lower() for p in parts]
        lang = self.config.get("language", "fa")

        if parts[0] == "!wave" and len(parts) == 2 and parts[1] == "all":
            if user.username.lower() not in self.config["admin_usernames"]:
                await self.chat(self.get_message("no_permission"))
                return
            try:
                active_users = list(self.active_users.items())
                active_users_count = len([u for u in active_users if u[1].id != self.user_id])
                if active_users_count == 0:
                    await self.chat("هیچ کاربری در روم آنلاین نیست!" if lang == "fa" else "No users are online in the room!")
                    return
                reaction_id = resolve_reaction("wave")
                successful_reactions = 0
                for username, target_user in active_users:
                    if target_user.id == self.user_id:
                        continue
                    if username not in self.active_users:
                        logger.info(f"کاربر {username} در حین ارسال wave آفلاین شد.")
                        continue
                    try:
                        await self.highrise.react(reaction_id, target_user.id)
                        successful_reactions += 1
                        await sleep(0.5)
                    except Exception as e:
                        await self.chat((f"خطا در ارسال wave به @{target_user.username}: {e}" if lang == "fa"
                                          else f"Error sending wave to @{target_user.username}: {e}"))
                        logger.error(f"خطا در ارسال wave به {target_user.username}: {e}")
                if successful_reactions > 0:
                    await self.chat(self.get_message("heart_all_success", count=successful_reactions))
                    logger.info(f"Wave به {successful_reactions} نفر ارسال شد.")
                else:
                    await self.chat("هیچ wave با موفقیت ارسال نشد." if lang == "fa" else "No waves were sent successfully.")
            except Exception as e:
                await self.chat((f"خطا در اجرای دستور: {e}" if lang == "fa" else f"Error running command: {e}"))
                logger.error(f"خطا در ارسال wave به همه: {e}")
            return

        if len(parts) != 3:
            await self.chat(self.get_message("invalid_format", format=("!wave تعداد @username یا !wave all" if self.config.get("language","fa") == "fa" else "!wave <count> @username or !wave all")))
            return

        try:
            count = int(parts[1])
            if count < 1 or count > 100:
                await self.chat((f"@{user.username}: تعداد باید بین 1 تا 100 باشد." if lang == "fa"
                                  else f"@{user.username}: count must be between 1 and 100."))
                return
        except ValueError:
            await self.chat((f"@{user.username}: عدد نامعتبر است." if lang == "fa" else f"@{user.username}: invalid number."))
            return

        target_username = parts[2].lstrip('@').lower()
        target_user = next((u for u in self.active_users.values() if u.username.lower() == target_username), None)

        if not target_user:
            await self.chat(self.get_message("user_not_found", username=target_username))
            return

        try:
            reaction_id = resolve_reaction("wave")
            for _ in range(count):
                if target_user.username.lower() not in self.active_users:
                    await self.chat((f"کاربر @{target_user.username} آفلاین شد و wave ارسال نشد." if lang == "fa"
                                      else f"@{target_user.username} went offline, waves stopped."))
                    logger.info(f"کاربر {target_user.username} در حین ارسال wave آفلاین شد.")
                    return
                await self.highrise.react(reaction_id, target_user.id)
                await sleep(0.5)
            await self.chat(self.get_message("wave_success", count=count, username=target_user.username))
            logger.info(f"{count} wave به {target_user.username} ارسال شد.")
        except Exception as e:
            await self.chat((f"خطا در ارسال wave: {e}" if lang == "fa" else f"Error sending waves: {e}"))
            logger.error(f"خطا در ارسال wave به {target_username}: {e}")

    async def cmd_thumbs(self, user: User, parts: list):
        parts = [p.lower() for p in parts]
        lang = self.config.get("language", "fa")

        if parts[0] == "!thumbs" and len(parts) == 2 and parts[1] == "all":
            if user.username.lower() not in self.config["admin_usernames"]:
                await self.chat(self.get_message("no_permission"))
                return
            try:
                active_users = list(self.active_users.items())
                active_users_count = len([u for u in active_users if u[1].id != self.user_id])
                if active_users_count == 0:
                    await self.chat("هیچ کاربری در روم آنلاین نیست!" if lang == "fa" else "No users are online in the room!")
                    return
                reaction_id = resolve_reaction("thumbs-up")
                successful_reactions = 0
                for username, target_user in active_users:
                    if target_user.id == self.user_id:
                        continue
                    if username not in self.active_users:
                        logger.info(f"کاربر {username} در حین ارسال thumbs-up آفلاین شد.")
                        continue
                    try:
                        await self.highrise.react(reaction_id, target_user.id)
                        successful_reactions += 1
                        await sleep(0.5)
                    except Exception as e:
                        await self.chat((f"خطا در ارسال thumbs-up به @{target_user.username}: {e}" if lang == "fa"
                                          else f"Error sending thumbs-up to @{target_user.username}: {e}"))
                        logger.error(f"خطا در ارسال thumbs-up به {target_user.username}: {e}")
                if successful_reactions > 0:
                    await self.chat(self.get_message("heart_all_success", count=successful_reactions))
                    logger.info(f"Thumbs-up به {successful_reactions} نفر ارسال شد.")
                else:
                    await self.chat("هیچ thumbs-up با موفقیت ارسال نشد." if lang == "fa" else "No thumbs-up were sent successfully.")
            except Exception as e:
                await self.chat((f"خطا در اجرای دستور: {e}" if lang == "fa" else f"Error running command: {e}"))
                logger.error(f"خطا در ارسال thumbs-up به همه: {e}")
            return

        if len(parts) != 3:
            await self.chat(self.get_message("invalid_format", format=("!thumbs تعداد @username یا !thumbs all" if self.config.get("language","fa") == "fa" else "!thumbs <count> @username or !thumbs all")))
            return

        try:
            count = int(parts[1])
            if count < 1 or count > 100:
                await self.chat((f"@{user.username}: تعداد باید بین 1 تا 100 باشد." if lang == "fa"
                                  else f"@{user.username}: count must be between 1 and 100."))
                return
        except ValueError:
            await self.chat((f"@{user.username}: عدد نامعتبر است." if lang == "fa" else f"@{user.username}: invalid number."))
            return

        target_username = parts[2].lstrip('@').lower()
        target_user = next((u for u in self.active_users.values() if u.username.lower() == target_username), None)

        if not target_user:
            await self.chat(self.get_message("user_not_found", username=target_username))
            return

        try:
            reaction_id = resolve_reaction("thumbs-up")
            for _ in range(count):
                if target_user.username.lower() not in self.active_users:
                    await self.chat((f"کاربر @{target_user.username} آفلاین شد و thumbs-up ارسال نشد." if lang == "fa"
                                      else f"@{target_user.username} went offline, thumbs-up stopped."))
                    logger.info(f"کاربر {target_user.username} در حین ارسال thumbs-up آفلاین شد.")
                    return
                await self.highrise.react(reaction_id, target_user.id)
                await sleep(0.5)
            await self.chat(self.get_message("thumbs_success", count=count, username=target_user.username))
            logger.info(f"{count} thumbs-up به {target_user.username} ارسال شد.")
        except Exception as e:
            await self.chat((f"خطا در ارسال thumbs-up: {e}" if lang == "fa" else f"Error sending thumbs-up: {e}"))
            logger.error(f"خطا در ارسال thumbs-up به {target_username}: {e}")

    async def cmd_wallet(self, user: User, parts: list):
        if user.username.lower() not in self.config["admin_usernames"]:
            await self.chat(self.get_message("no_permission"))
            return

        try:
            wallet = await self.highrise.get_wallet()
            gold_amount = 0
            if hasattr(wallet, "content") and isinstance(wallet.content, list):
                for item in wallet.content:
                    if hasattr(item, "type") and item.type == "gold" and hasattr(item, "amount"):
                        gold_amount = item.amount
                        break
            else:
                logger.error("ساختار wallet ناشناخته است.")
                await self.chat("خطا: ساختار پاسخ wallet ناشناخته است." if self.config.get("language","fa") == "fa" else "Error: unrecognized wallet response structure.")
                return
            
            await self.chat((f"موجودی گلد ربات: {gold_amount} گلد" if self.config.get("language","fa") == "fa" else f"Bot gold balance: {gold_amount} gold"))
            logger.info(f"موجودی ربات: {gold_amount} گلد")
        except Exception as e:
            await self.chat(self.get_message("wallet_error", error=str(e)))
            logger.error(f"خطا در دریافت موجودی: {e}")

    async def cmd_tip(self, user: User, parts: list):
        if user.username.lower() not in self.config["admin_usernames"]:
            await self.chat(self.get_message("no_permission"))
            return
        lang = self.config.get("language", "fa")

        parts_lower = [p.lower() for p in parts]
        if len(parts_lower) < 3 or not parts_lower[1].isdigit():
            await self.chat(self.get_message(
                "invalid_format",
                format=("!tip تعداد all | !tip تعداد @username | !tip تعداد random عدد_نفرات (هر عددی مجازه، مثلاً 256)" if lang == "fa"
                        else "!tip <amount> all | !tip <amount> @username | !tip <amount> random <count> (any amount, e.g. 256)")
            ))
            return

        try:
            tip_amount = int(parts_lower[1])
            if tip_amount <= 0:
                await self.chat("⚠️ مقدار گلد باید بیشتر از صفر باشه." if lang == "fa" else "⚠️ Gold amount must be greater than zero.")
                return

            tip_plan = decompose_gold_amount(tip_amount)  # [(value, bar_name, count), ...]

            all_active = [u for u in self.active_users.values() if u.id != self.user_id]

            # 🎯 تعیین لیست هدف بر اساس حالت: all / @username / random عدد
            if parts_lower[2] == "all":
                target_users = all_active
            elif parts_lower[2] == "random":
                if len(parts_lower) < 4 or not parts_lower[3].isdigit():
                    await self.chat("⚠️ فرمت اشتباه! استفاده کن از: !tip تعداد random عدد_نفرات" if lang == "fa"
                                     else "⚠️ Wrong format! Use: !tip amount random number_of_people")
                    return
                n = int(parts_lower[3])
                if n < 1:
                    await self.chat("⚠️ تعداد نفرات باید حداقل 1 باشد." if lang == "fa"
                                     else "⚠️ Number of people must be at least 1.")
                    return
                target_users = random.sample(all_active, min(n, len(all_active)))
            elif parts_lower[2].startswith("@"):
                target_username = parts_lower[2][1:]
                target_user = self.active_users.get(target_username)
                if not target_user:
                    await self.chat(self.get_message("user_not_found", username=target_username))
                    return
                target_users = [target_user]
            else:
                await self.chat("⚠️ فرمت اشتباه! استفاده کن از: !tip تعداد all | !tip تعداد @username | !tip تعداد random عدد_نفرات" if lang == "fa"
                                 else "⚠️ Wrong format! Use: !tip amount all | !tip amount @username | !tip amount random number_of_people")
                return

            if not target_users:
                await self.chat("هیچ کاربری برای تیپ پیدا نشد!" if lang == "fa" else "No users found to tip!")
                return

            wallet = await self.highrise.get_wallet()
            gold_amount = 0
            if hasattr(wallet, "content") and isinstance(wallet.content, list):
                for item in wallet.content:
                    if hasattr(item, "type") and item.type == "gold" and hasattr(item, "amount"):
                        gold_amount = item.amount
                        break
            else:
                logger.error("ساختار wallet ناشناخته است.")
                await self.chat("خطا: ساختار پاسخ wallet ناشناخته است." if lang == "fa"
                                 else "Error: unknown wallet response structure.")
                return

            total_needed = tip_amount * len(target_users)

            if gold_amount < total_needed:
                shortfall = total_needed - gold_amount
                await self.chat(
                    (f"⚠️ موجودی ربات ({gold_amount} گلد) کافی نیست. برای تیپ {tip_amount} گلد به {len(target_users)} نفر، "
                     f"{total_needed} گلد لازمه — یعنی {shortfall} گلد دیگه کم داری."
                     if lang == "fa" else
                     f"⚠️ Bot balance ({gold_amount} gold) isn't enough. Tipping {tip_amount} gold to {len(target_users)} people "
                     f"needs {total_needed} gold — you're short by {shortfall} gold.")
                )
                return

            successful_tips = 0
            for target_user in target_users:
                if target_user.username.lower() not in self.active_users:
                    logger.info(f"کاربر {target_user.username} در حین ارسال تیپ آفلاین شد.")
                    continue
                try:
                    # هر تیپ ممکنه چند گلدبار پشت سر هم لازم داشته باشه (مثلاً 256 = 100+100+50+5+1)
                    for value, bar_name, count in tip_plan:
                        for _ in range(count):
                            response = await self.highrise.tip_user(target_user.id, bar_name)
                            if hasattr(response, "error"):
                                raise Exception(f"خطای API: {response.error}")
                            await sleep(0.3)
                    successful_tips += 1
                    await self.chat(self.get_message("tip_success", amount=tip_amount, username=target_user.username))
                    logger.info(f"ارسال {tip_amount} گلد به {target_user.username} موفقیت‌آمیز بود.")
                    await sleep(1.0)
                except Exception as e:
                    await self.chat((f"خطا در تیپ به @{target_user.username}: {e}" if lang == "fa"
                                      else f"Error tipping @{target_user.username}: {e}"))
                    logger.error(f"خطا در تیپ به {target_user.username}: {e}")

            if successful_tips > 0:
                await self.chat(self.get_message("tip_all_success", amount=tip_amount, count=successful_tips))
            else:
                await self.chat("هیچ تیپی با موفقیت ارسال نشد." if lang == "fa" else "No tips were sent successfully.")

            wallet = await self.highrise.get_wallet()
            gold_amount = 0
            if hasattr(wallet, "content") and isinstance(wallet.content, list):
                for item in wallet.content:
                    if hasattr(item, "type") and item.type == "gold" and hasattr(item, "amount"):
                        gold_amount = item.amount
                        break
            await self.chat((f"موجودی جدید ربات: {gold_amount} گلد" if lang == "fa"
                              else f"New bot balance: {gold_amount} gold"))
            logger.info(f"موجودی جدید ربات: {gold_amount} گلد")

        except Exception as e:
            await self.chat((f"خطای ناشناخته: {e}" if self.config.get("language","fa") == "fa" else f"Unknown error: {e}"))
            logger.error(f"خطا در cmd_tip: {e}")

    async def cmd_set(self, user: User, parts: list):
        # ⚠️ اگه بعد از !set یه آرگومان اضافه باشه (مثل "21" یا "dj")، یعنی این دستور
        # مخصوص یه بات دیگه‌ست (بلک‌جک یا دی‌جی) که تو همین روم فعاله، نه بات معمولی.
        # پس کاملاً بی‌صدا نادیده‌اش می‌گیریم تا نه خطا بده و نه جابه‌جا بشه.
        if len(parts) > 1:
            return
        if user.username.lower() not in self.config["admin_usernames"]:
            await self.chat(self.get_message("no_permission"))
            return

        pos = self.user_positions.get(user.username.lower())
        if not pos:
            await self.chat((f"@{user.username}: موقعیت شما مشخص نیست." if self.config.get("language","fa") == "fa" else f"@{user.username}: your position isn't known."))
            return
        try:
            await self.highrise.teleport(user_id=self.user_id, dest=pos)
            await self.chat((f"ربات به موقعیت @{user.username} منتقل شد." if self.config.get("language","fa") == "fa" else f"Bot teleported to @{user.username}'s location."))
            logger.info(f"ربات به موقعیت {user.username} تلپورت شد.")
        except Exception as e:
            await self.chat((f"خطا در تلپورت ربات: {e}" if self.config.get("language","fa") == "fa" else f"Error teleporting bot: {e}"))
            logger.error(f"خطا در cmd_set: {e}")

    async def cmd_ban(self, user: User, parts: list):
        """!ban @username [تایم] -> کاربر رو محروم می‌کنه (از الان به بعد با ورود خودکار کیک میشه).
        تایم اختیاریه: 0 یا خالی = دائمی، 30m/2h/90s = زمان‌دار."""
        if not self.can_moderate(user.username):
            await self.chat(self.get_message("no_permission"))
            return
        if len(parts) not in (2, 3) or not parts[1].startswith("@"):
            await self.chat(self.get_message("invalid_format", format=("!ban @username [تایم دلخواه مثل 30m/2h/0]" if self.config.get("language","fa") == "fa" else "!ban @username [duration like 30m/2h/0]")))
            return

        target_username = parts[1][1:].lower()
        duration_raw = parts[2] if len(parts) == 3 else "0"
        seconds, err = parse_duration_arg(duration_raw, lang=self.config.get("language", "fa"))
        if err:
            await self.chat(err)
            return

        self.ban_user(target_username, seconds)

        target_user = self.active_users.get(target_username)
        if target_user:
            try:
                await self.highrise.moderate_room(target_user.id, "kick")
            except Exception as e:
                logger.error(f"خطا در کیک فوری بعد از بن {target_username}: {e}")

        self._log_mod_action(user.username, "ban", target_username, duration_raw)

        lang = self.config.get("language", "fa")
        if lang == "fa":
            duration_text = "برای همیشه" if seconds is None else f"به مدت {humanize_seconds_fa(seconds)}"
            await self.chat(f"⛔ @{target_username} {duration_text} بن شد.")
        else:
            duration_text = "forever" if seconds is None else f"for {humanize_seconds_en(seconds)}"
            await self.chat(f"⛔ @{target_username} was banned {duration_text}.")
        logger.info(f"کاربر {target_username} توسط {user.username} بن شد. ({duration_raw})")

    async def cmd_kick(self, user: User, parts: list):
        """!kick @username [تایم] ->
        بدون تایم: فقط همین الان از روم کیک میشه (بن نمیشه، می‌تونه دوباره بیاد تو).
        تایم = 0: بن دائمی (مثل !ban).
        تایم = عدد (30m/2h/90s): تا اون مدت بن میشه، بعدش خودکار آزاد میشه."""
        if not self.can_moderate(user.username):
            await self.chat(self.get_message("no_permission"))
            return
        lang = self.config.get("language", "fa")
        if len(parts) not in (2, 3) or not parts[1].startswith("@"):
            await self.chat(self.get_message("invalid_format", format=(
                "!kick @username [تایم دلخواه: خالی=فقط کیک، 0=دائمی، 30m/2h=زمان‌دار]" if lang == "fa"
                else "!kick @username [optional duration: empty=kick only, 0=permanent, 30m/2h=timed]"
            )))
            return

        target_username = parts[1][1:].lower()
        target_user = self.active_users.get(target_username)

        if len(parts) == 2:
            # بدون تایم -> فقط یه کیک ساده، بدون ثبت محرومیت
            if not target_user:
                await self.chat(self.get_message("user_not_found", username=target_username))
                return
            try:
                await self.highrise.moderate_room(target_user.id, "kick")
                self._log_mod_action(user.username, "kick", target_username)
                await self.chat((f"👢 @{target_username} از روم کیک شد." if lang == "fa"
                                  else f"👢 @{target_username} was kicked from the room."))
                logger.info(f"کاربر {target_username} توسط {user.username} فقط کیک شد (بدون بن).")
            except Exception as e:
                await self.chat((f"خطا در کیک کردن: {e}" if lang == "fa" else f"Error kicking user: {e}"))
                logger.error(f"خطا در cmd_kick (بدون تایم) برای {target_username}: {e}")
            return

        duration_raw = parts[2]
        seconds, err = parse_duration_arg(duration_raw, lang=lang)
        if err:
            await self.chat(err)
            return

        self.ban_user(target_username, seconds)
        if target_user:
            try:
                await self.highrise.moderate_room(target_user.id, "kick")
            except Exception as e:
                logger.error(f"خطا در کیک فوری بعد از !kick {target_username}: {e}")

        if lang == "fa":
            duration_text = "برای همیشه" if seconds is None else f"به مدت {humanize_seconds_fa(seconds)}"
            await self.chat(f"👢⛔ @{target_username} کیک و {duration_text} بن شد.")
        else:
            duration_text = "forever" if seconds is None else f"for {humanize_seconds_en(seconds)}"
            await self.chat(f"👢⛔ @{target_username} was kicked and banned {duration_text}.")
        logger.info(f"کاربر {target_username} توسط {user.username} کیک+بن شد. ({duration_raw})")

    async def cmd_setkill(self, user: User, parts: list):
        """!setkill -> موقعیت فعلیِ خودِ ادمین رو به‌عنوان مقصد !kill (معمولاً دم در روم) ذخیره می‌کنه."""
        if user.username.lower() not in self.config["admin_usernames"]:
            await self.chat(self.get_message("no_permission"))
            return
        lang = self.config.get("language", "fa")
        pos = self.user_positions.get(user.username.lower())
        if not pos:
            await self.chat("⚠️ موقعیت شما مشخص نیست، یه تکون بخور و دوباره امتحان کن." if lang == "fa"
                             else "⚠️ Can't detect your position — move a bit and try again.")
            return
        self.config["kill_position"] = {"x": pos.x, "y": pos.y, "z": pos.z}
        self.save_config()
        await self.chat("💀 مقصدِ !kill همینجا ثبت شد." if lang == "fa" else "💀 The !kill destination has been set to here.")

    async def cmd_kill(self, user: User, parts: list):
        """!kill @username -> کاربر رو به مقصد ثبت‌شده با !setkill (معمولاً دم در روم) تلپورت می‌کنه.
        اگه هنوز !setkill زده نشده باشه، از یه مختصات پیش‌فرض نزدیک به مبدأ استفاده می‌کنه."""
        if user.username.lower() not in self.config["admin_usernames"]:
            await self.chat(self.get_message("no_permission"))
            return
        lang = self.config.get("language", "fa")
        if len(parts) != 2 or not parts[1].startswith("@"):
            await self.chat(self.get_message("invalid_format", format=("!kill @username" if lang == "fa" else "!kill @username")))
            return

        target_username = parts[1][1:].lower()
        target_user = self.active_users.get(target_username)
        if not target_user:
            await self.chat(self.get_message("user_not_found", username=target_username))
            return

        kill_pos = self.config.get("kill_position") or {"x": 0.0, "y": 0.0, "z": 0.0}
        try:
            dest = Position(x=kill_pos["x"], y=kill_pos["y"], z=kill_pos["z"])
            await self.highrise.teleport(user_id=target_user.id, dest=dest)
            await self.chat((f"🔪 @{target_username} به در روم فرستاده شد." if lang == "fa"
                              else f"🔪 @{target_username} was sent to the door."))
            logger.info(f"کاربر {target_username} توسط {user.username} با !kill تلپورت شد.")
        except Exception as e:
            await self.chat(self.get_message("teleport_error", error=str(e)))
            logger.error(f"خطا در cmd_kill برای {target_username}: {e}")

    async def cmd_info(self, user: User, parts: list):
        """!info -> اطلاعات کلی روم (تعداد کاربر، تعداد در حال رقص و ...) |
        !info @username -> اطلاعات یک کاربر خاص (رنک، مدت حضور تو این نشست، وضعیت فعلی).
        ⚠️ تعداد فالوور، سن اکانت و کل زمان بازی‌شده (playtime) از طریق API عمومی بات هایرایز
        در دسترس نیست، برای همین اینجا نشون داده نمیشه (که عدد ساختگی/غلط نده)."""
        lang = self.config.get("language", "fa")

        if len(parts) >= 2 and parts[1].startswith("@"):
            target_username = parts[1][1:].lower()
            target_user = self.active_users.get(target_username)
            if not target_user:
                await self.chat(self.get_message("user_not_found", username=target_username))
                return

            if target_username in self.config.get("host_usernames", []):
                rank = "هاست (Host)" if lang == "fa" else "Host"
            elif target_username in self.config["admin_usernames"]:
                rank = "ادمین (Admin)" if lang == "fa" else "Admin"
            elif target_username in self.config.get("vip_usernames", []):
                rank = "VIP"
            else:
                rank = "کاربر عادی" if lang == "fa" else "Regular user"

            join_time = self.user_join_times.get(target_username)
            session_text = humanize_seconds_lang(int((datetime.utcnow() - join_time).total_seconds()), lang) if join_time else ("نامشخص" if lang == "fa" else "unknown")
            dancing = target_username in self.user_dances or target_username in self.party_dances
            afk = target_username in self.afk_users
            frozen = target_username in self.frozen_users

            if lang == "fa":
                lines = [
                    f"ℹ️ اطلاعات @{target_user.username}:",
                    f"رنک: {rank}",
                    f"مدت حضور تو این نشست: {session_text}",
                    f"وضعیت: {'در حال رقص' if dancing else 'در حال رقص نیست'}{'، AFK' if afk else ''}{'، فریز شده' if frozen else ''}",
                    "⚠️ تعداد فالوور، سن اکانت و کل زمان بازی از طریق بات در دسترس نیست.",
                ]
            else:
                lines = [
                    f"ℹ️ Info for @{target_user.username}:",
                    f"Rank: {rank}",
                    f"Time in room this session: {session_text}",
                    f"Status: {'dancing' if dancing else 'not dancing'}{', AFK' if afk else ''}{', frozen' if frozen else ''}",
                    "⚠️ Follower count, account age, and total playtime aren't available through the bot API.",
                ]
            await self.chat("\n".join(lines))
            return

        total_users = len(self.active_users)
        dancing_count = len(set(self.user_dances.keys()) | set(self.party_dances.keys()))
        afk_count = len(self.afk_users)
        admin_count = len(self.config["admin_usernames"])
        uptime_text = humanize_seconds_lang(int((datetime.utcnow() - self.bot_start_time).total_seconds()), lang)

        if lang == "fa":
            lines = [
                "ℹ️ اطلاعات روم:",
                f"تعداد کاربر: {total_users}",
                f"در حال رقص: {dancing_count}",
                f"AFK: {afk_count}",
                f"ادمین/هاست ربات: {admin_count}",
                f"زبان بات: {'فارسی' if self.config.get('language','fa')=='fa' else 'English'}",
                f"مدت روشن بودن بات: {uptime_text}",
            ]
        else:
            lines = [
                "ℹ️ Room info:",
                f"Users: {total_users}",
                f"Dancing: {dancing_count}",
                f"AFK: {afk_count}",
                f"Bot admins/hosts: {admin_count}",
                f"Bot language: {'Persian' if self.config.get('language','fa')=='fa' else 'English'}",
                f"Bot uptime: {uptime_text}",
            ]
        await self.chat("\n".join(lines))

    async def cmd_lottery(self, user: User, parts: list):
        """!lottery start قیمت_بلیط دقیقه -> شروع لاتاری (ادمین)
        !lottery status -> وضعیت لاتاری الان
        !lottery draw -> برنده رو مشخص و کل جایزه رو بهش تیپ می‌کنه (ادمین)
        !lottery cancel -> لغو و برگردوندن بلیط‌ها به همه (ادمین)
        ورود به لاتاری: کافیه کاربر به خودِ ربات دقیقاً به اندازه‌ی قیمت بلیط (یا بیشتر) گلد واقعی تیپ کنه."""
        lang = self.config.get("language", "fa")
        sub = parts[1].lower() if len(parts) >= 2 else ""

        if sub == "start":
            if user.username.lower() not in self.config["admin_usernames"]:
                await self.chat(self.get_message("no_permission"))
                return
            if self.lottery and self.lottery.get("active"):
                await self.chat("⚠️ یه لاتاری از قبل فعاله. اول با !lottery cancel یا !lottery draw تمومش کن." if lang == "fa"
                                 else "⚠️ A lottery is already running. Finish it first with !lottery cancel or !lottery draw.")
                return
            if len(parts) != 4 or not parts[2].isdigit() or not parts[3].isdigit():
                await self.chat(self.get_message("invalid_format", format=("!lottery start قیمت_بلیط دقیقه" if lang == "fa" else "!lottery start <ticket_price> <minutes>")))
                return
            ticket_price = int(parts[2])
            minutes = int(parts[3])
            if ticket_price <= 0 or minutes <= 0:
                await self.chat("⚠️ قیمت بلیط و مدت زمان باید بیشتر از صفر باشن." if lang == "fa" else "⚠️ Ticket price and duration must be greater than zero.")
                return

            self.lottery = {
                "active": True, "ticket_price": ticket_price, "entries": {},
                "ends_at": datetime.utcnow() + timedelta(minutes=minutes),
            }

            async def auto_draw_after_delay():
                await sleep(minutes * 60)
                if self.lottery and self.lottery.get("active"):
                    await self._draw_lottery(announce_no_entries=True)

            self.lottery["task"] = create_task(auto_draw_after_delay())

            await self.chat(
                (f"🎉 لاتاری شروع شد! قیمت هر بلیط: {ticket_price} گلد — برای شرکت، همین مقدار (یا بیشتر) به ربات تیپ کن.\n"
                 f"⏰ قرعه‌کشی خودکار تا {minutes} دقیقه‌ی دیگه، یا با !lottery draw زودتر انجامش بده."
                 if lang == "fa" else
                 f"🎉 The lottery has started! Ticket price: {ticket_price} gold — tip the bot that amount (or more) to enter.\n"
                 f"⏰ Auto-draw in {minutes} minutes, or run !lottery draw to do it sooner.")
            )
            return

        if sub == "status":
            if not self.lottery or not self.lottery.get("active"):
                await self.chat("📭 الان هیچ لاتاری فعالی نیست." if lang == "fa" else "📭 No lottery is currently active.")
                return
            entries = self.lottery["entries"]
            pot = sum(e["amount"] for e in entries.values())
            remaining = max(0, int((self.lottery["ends_at"] - datetime.utcnow()).total_seconds()))
            await self.chat(
                (f"🎟 لاتاری فعال — قیمت بلیط: {self.lottery['ticket_price']} گلد | شرکت‌کننده: {len(entries)} نفر | "
                 f"جایزه‌ی فعلی: {pot} گلد | زمان باقی‌مونده: {humanize_seconds_lang(remaining, lang)}"
                 if lang == "fa" else
                 f"🎟 Lottery active — ticket price: {self.lottery['ticket_price']} gold | entrants: {len(entries)} | "
                 f"current pot: {pot} gold | time left: {humanize_seconds_lang(remaining, lang)}")
            )
            return

        if sub == "draw":
            if user.username.lower() not in self.config["admin_usernames"]:
                await self.chat(self.get_message("no_permission"))
                return
            if not self.lottery or not self.lottery.get("active"):
                await self.chat("📭 الان هیچ لاتاری فعالی نیست." if lang == "fa" else "📭 No lottery is currently active.")
                return
            await self._draw_lottery(announce_no_entries=True)
            return

        if sub == "cancel":
            if user.username.lower() not in self.config["admin_usernames"]:
                await self.chat(self.get_message("no_permission"))
                return
            if not self.lottery or not self.lottery.get("active"):
                await self.chat("📭 الان هیچ لاتاری فعالی نیست." if lang == "fa" else "📭 No lottery is currently active.")
                return
            await self.chat("↩️ در حال برگردوندن بلیط‌ها به همه‌ی شرکت‌کننده‌ها..." if lang == "fa" else "↩️ Refunding tickets to all entrants...")
            await self._refund_lottery_entries()
            if self.lottery.get("task"):
                self.lottery["task"].cancel()
            self.lottery["active"] = False
            await self.chat("🛑 لاتاری لغو شد و بلیط‌ها برگردونده شدن." if lang == "fa" else "🛑 The lottery was cancelled and tickets were refunded.")
            return

        await self.chat(self.get_message("invalid_format", format=("!lottery start قیمت_بلیط دقیقه | !lottery status | !lottery draw | !lottery cancel" if lang == "fa" else "!lottery start <ticket_price> <minutes> | !lottery status | !lottery draw | !lottery cancel")))

    async def _refund_lottery_entries(self):
        """هر بلیطی که یه کاربر خریده رو (با همون ترکیب گلدبار) بهش پس می‌ده."""
        if not self.lottery:
            return
        for entry in self.lottery["entries"].values():
            try:
                for value, bar_name, count in decompose_gold_amount(entry["amount"]):
                    for _ in range(count):
                        await self.highrise.tip_user(entry["user_id"], bar_name)
                        await sleep(0.3)
            except Exception as e:
                logger.error(f"خطا در برگردوندن بلیط لاتاری به {entry['username']}: {e}")

    async def _draw_lottery(self, announce_no_entries: bool = False):
        lang = self.config.get("language", "fa")
        if not self.lottery or not self.lottery.get("active"):
            return
        entries = list(self.lottery["entries"].values())
        self.lottery["active"] = False
        if self.lottery.get("task"):
            self.lottery["task"].cancel()

        if not entries:
            if announce_no_entries:
                await self.chat("📭 لاتاری تموم شد ولی هیچکس شرکت نکرده بود." if lang == "fa" else "📭 The lottery ended but no one entered.")
            return

        pot = sum(e["amount"] for e in entries)
        weighted_pool = []
        for e in entries:
            weighted_pool.extend([e] * max(1, e["amount"] // self.lottery["ticket_price"]))
        winner = random.choice(weighted_pool)

        await self.chat(
            (f"🎉🎉 قرعه‌کشی لاتاری تموم شد! برنده: @{winner['username']} با جایزه‌ی {pot} گلد! تبریک 🎊"
             if lang == "fa" else
             f"🎉🎉 The lottery draw is complete! Winner: @{winner['username']} with a prize of {pot} gold! Congrats 🎊")
        )
        try:
            for value, bar_name, count in decompose_gold_amount(pot):
                for _ in range(count):
                    await self.highrise.tip_user(winner["user_id"], bar_name)
                    await sleep(0.3)
        except Exception as e:
            logger.error(f"خطا در پرداخت جایزه‌ی لاتاری به {winner['username']}: {e}")
            await self.chat((f"⚠️ خطا در پرداخت خودکار جایزه: {e} — لطفاً دستی پیگیری کن." if lang == "fa"
                              else f"⚠️ Error auto-paying the prize: {e} — please follow up manually."))

    async def cmd_unban(self, user: User, parts: list):
        if not self.can_moderate(user.username):
            await self.chat(self.get_message("no_permission"))
            logger.info(f"کاربر {user.username} دسترسی لازم برای اجرای !unban را ندارد.")
            return

        parts = [p.lower() for p in parts]
        if len(parts) != 2 or not parts[1].startswith("@"):
            await self.chat(self.get_message("invalid_format", format="!unban @username"))
            logger.info(f"فرمت نادرست برای دستور !unban توسط {user.username} وارد شد.")
            return

        target_username = parts[1][1:].lower()
        if not self.unban_user(target_username):
            await self.chat(self.get_message("unban_not_banned", username=target_username))
            logger.info(f"کاربر {target_username} توسط {user.username} برای آنبن درخواست شد، اما در لیست بن نیست.")
            return

        await self.chat(self.get_message("unban_success", username=target_username))
        logger.info(f"کاربر {target_username} توسط {user.username} آنبن شد.")
        self._log_mod_action(user.username, "unban", target_username)

    async def _detect_room_admin_usernames(self):
        """تلاش می‌کنه لیست یوزرنیم‌هایی که تو خودِ هایرایز (نه ربات) نقش ادمین/مدیر روم دارن رو
        در بیاره. چون این نسخه از highrise-bot-sdk تو بقیه‌ی فایل هیچ‌جا از فیلد پرمیشن/مدیر
        استفاده نکرده، این تابع چند اسم رایج رو امتحان می‌کنه و اگه هیچ‌کدوم جواب نداد، None
        برمی‌گردونه (یعنی «نمی‌تونم تشخیص بدم»، نه «هیچ ادمینی نیست»)."""
        try:
            room_users = await self.highrise.get_room_users()
        except Exception as e:
            logger.error(f"خطا در گرفتن لیست کاربران روم برای تشخیص ادمین: {e}")
            return None

        found_any_signal = False
        admins = []
        for user_data in room_users.content:
            u = user_data[0]
            if u.id == self.user_id:
                continue
            is_admin = None
            for attr in ("moderator", "is_moderator", "is_admin"):
                val = getattr(u, attr, None)
                if val is not None:
                    is_admin = bool(val)
                    found_any_signal = True
                    break
            if is_admin is None:
                perms = getattr(u, "permissions", None)
                if perms is not None:
                    for attr in ("moderator", "is_moderator"):
                        val = getattr(perms, attr, None)
                        if val is not None:
                            is_admin = bool(val)
                            found_any_signal = True
                            break
            if is_admin:
                admins.append(u.username.lower())

        if not found_any_signal:
            return None
        return admins

    async def apply_admin_sync(self, mode: str) -> str:
        """هسته‌ی مشترک !admin on/off — هم از چت هم از دستورات صف‌شده‌ی پنل صدا زده میشه."""
        if mode == "on":
            detected = await self._detect_room_admin_usernames()
            if detected is None:
                return (
                    "⚠️ این نسخه از SDK هایرایز اطلاعات ادمین‌بودن کاربرها رو در اختیار ربات نمی‌ذاره، "
                    "پس نمی‌تونم خودکار تشخیص بدم کیا تو خودِ روم ادمینن. دستی با !addadmin @username اضافه‌شون کن."
                )
            newly_added = [u for u in detected if u not in self.config["admin_usernames"]]
            for u in newly_added:
                self.config["admin_usernames"].append(u)
            for u in newly_added:
                if u not in self.config["auto_admins"]:
                    self.config["auto_admins"].append(u)
            self.save_config()
            if newly_added:
                return f"✅ {len(newly_added)} نفر از ادمین‌های روم، ادمین ربات هم شدن: " + ", ".join(f"@{u}" for u in newly_added)
            return "ℹ️ همه‌ی ادمین‌های روم از قبل ادمین ربات هم بودن."
        else:  # off
            removed = list(self.config.get("auto_admins", []))
            for u in removed:
                if u in self.config["admin_usernames"]:
                    self.config["admin_usernames"].remove(u)
            self.config["auto_admins"] = []
            self.save_config()
            if removed:
                return f"✅ {len(removed)} ادمینی که فقط با !admin on اضافه شده بودن حذف شدن (ادمین‌های دستی می‌مونن)."
            return "ℹ️ کسی از این طریق ادمین نشده بود، چیزی حذف نشد."

    async def cmd_admin_toggle(self, user: User, parts: list):
        """!admin on / !admin off -> سینک خودکار ادمین‌های خودِ روم با ادمین‌های ربات.
        فقط هاست می‌تونه بزنه چون قدرتش بالاست (می‌تونه چند نفر رو یهو ادمین کنه)."""
        if not self.is_host(user.username):
            await self.chat(self.get_message("no_permission"))
            return
        if len(parts) < 2 or parts[1].lower() not in ("on", "off"):
            await self.chat("⚠️ فرمت اشتباه! استفاده کن از: !admin on یا !admin off" if self.config.get("language","fa") == "fa" else "⚠️ Wrong format! Use: !admin on or !admin off")
            return
        result = await self.apply_admin_sync(parts[1].lower())
        await self.chat(result)

    async def cmd_restart(self, user: User, parts: list):
        """!restart -> ری‌استارت کامل بات (فقط ادمین/هاست). پروسه‌ی بات کاملاً بسته میشه و
        (اگه از طریق admin_panel.py ران شده باشه) خودکار ظرف چند ثانیه دوباره روشن میشه —
        وضعیت (کانفیگ، ادمین‌ها، ظاهر و...) از رو فایل تنظیمات دوباره لود میشه، انگار تازه استارت شده."""
        lang = self.config.get("language", "fa")
        if user.username.lower() not in self.config["admin_usernames"] and not self.is_host(user.username):
            await self.chat(self.get_message("no_permission"))
            return
        await self.chat("🔄 در حال ری‌استارت... چند ثانیه دیگه برمی‌گردم." if lang == "fa" else "🔄 Restarting... I'll be back in a few seconds.")
        logger.info(f"ری‌استارت با دستور !restart توسط {user.username} درخواست شد.")
        await sleep(1.0)  # فرصت برای رسیدن پیام بالا به چت قبل از بسته شدن پروسه
        os._exit(0)

    async def cmd_ai_toggle(self, user: User, parts: list):
        """!ai on / !ai off -> فعال یا غیرفعال کردن پاسخ‌دهی هوش مصنوعی با / تو چت عمومی روم.
        تو پیوی همیشه فعاله، این دستور فقط رو چت روم اثر داره."""
        if user.username.lower() not in self.config["admin_usernames"]:
            await self.chat(self.get_message("no_permission"))
            return
        lang = self.config.get("language", "fa")
        if len(parts) < 2 or parts[1].lower() not in ("on", "off"):
            await self.chat("⚠️ فرمت اشتباه! استفاده کن از: !ai on یا !ai off" if lang == "fa"
                             else "⚠️ Wrong format! Use: !ai on or !ai off")
            return
        self.config["ai_room_enabled"] = (parts[1].lower() == "on")
        self.save_config()
        if self.config["ai_room_enabled"]:
            await self.chat("🤖 هوش مصنوعی تو چت روم فعال شد. کافیه پیام رو با / شروع کنی." if lang == "fa"
                             else "🤖 AI is now active in room chat. Just start your message with /")
        else:
            await self.chat("🤖 هوش مصنوعی تو چت روم خاموش شد (فقط تو پیوی کار می‌کنه)." if lang == "fa"
                             else "🤖 AI turned off in room chat (still works in DMs).")

    async def cmd_dancechain(self, user: User, parts: list):
        dance_list = ["dance-tiktok8", "dance-blackpink", "dance-tiktok2"]
        for emote in dance_list:
            await self.highrise.send_emote(emote, user.id)
            await sleep(self.emote_durations.get(emote, 15.0))
        await self.chat(self.get_message("dancechain_success", username=user.username))
        logger.info(f"زنجیره رقص برای {user.username} اجرا شد.")

    async def cmd_addtele(self, user: User, parts: list):
        """!addtele نام_مکان [admin|نام_رنک] -> اگه admin بذاری فقط ادمین‌ها، اگه اسم یه رنک دلخواه بذاری فقط اعضای اون رنک،
        وگرنه (بدون هیچی) همه می‌تونن با گفتن اسم مکان تو چت به اونجا برن."""
        if user.username.lower() not in self.config["admin_usernames"] and not self.is_host(user.username):
            await self.chat(self.get_message("no_permission"))
            return
        lang = self.config.get("language", "fa")
        if len(parts) not in (2, 3):
            await self.chat(self.get_message("invalid_format", format=(
                "!addtele نام_مکان [admin|نام_رنک]" if lang == "fa" else "!addtele <location_name> [admin|rank_name]"
            )))
            return

        location_name = parts[1].lower()
        restriction = parts[2] if len(parts) == 3 else None
        admin_only = False
        restricted_rank = None

        if restriction:
            if restriction.lower() == "admin":
                admin_only = True
            elif restriction in self.config["custom_ranks"]:
                restricted_rank = restriction
            else:
                await self.chat((f"⚠️ رنک «{restriction}» وجود نداره. اول با !MR بسازش، یا بنویس admin." if lang == "fa"
                                  else f"⚠️ Rank \"{restriction}\" doesn't exist. Create it first with !MR, or type admin."))
                return

        pos = self.user_positions.get(user.username.lower())
        if not pos:
            await self.chat("موقعیت شما مشخص نیست!" if lang == "fa" else "Your position isn't known!")
            return
        self.config["teleport_locations"][location_name] = {
            "x": pos.x, "y": pos.y, "z": pos.z,
            "admin_only": admin_only,
            "restricted_rank": restricted_rank,
        }
        self.save_config()
        if lang == "fa":
            if admin_only:
                access_text = "فقط ادمین‌های ربات"
            elif restricted_rank:
                access_text = f"فقط اعضای رنک «{restricted_rank}»"
            else:
                access_text = "همه"
            await self.chat(f"✅ مکان «{location_name}» ذخیره شد. (دسترسی: {access_text})\nحالا کافیه اسم «{location_name}» رو تو چت بگی تا بری اونجا.")
        else:
            if admin_only:
                access_text = "bot admins only"
            elif restricted_rank:
                access_text = f"only members of rank \"{restricted_rank}\""
            else:
                access_text = "everyone"
            await self.chat(f"✅ Location \"{location_name}\" saved. (Access: {access_text})\nJust type \"{location_name}\" in chat to go there.")
        logger.info(f"مکان {location_name} توسط {user.username} اضافه شد. (admin_only={admin_only}, rank={restricted_rank})")

    async def cmd_deltele(self, user: User, parts: list):
        if user.username.lower() not in self.config["admin_usernames"]:
            await self.chat(self.get_message("no_permission"))
            logger.info(f"کاربر {user.username} دسترسی لازم برای اجرای !deltele را ندارد.")
            return

        parts = [p.lower() for p in parts]
        if len(parts) != 2:
            await self.chat(self.get_message("invalid_format", format=("!deltele نام_مکان" if self.config.get("language","fa") == "fa" else "!deltele <location_name>")))
            logger.info(f"فرمت نادرست برای دستور !deltele توسط {user.username} وارد شد.")
            return

        location_name = parts[1]
        if location_name in ["vip", "vip1", "dj"]:
            await self.chat(self.get_message("deltele_protected", location=location_name))
            logger.info(f"کاربر {user.username} سعی کرد مکان پیش‌فرض {location_name} را حذف کند.")
            return

        if location_name not in self.config["teleport_locations"]:
            await self.chat(self.get_message("deltele_not_found", location=location_name))
            logger.info(f"مکان {location_name} توسط {user.username} برای حذف درخواست شد، اما وجود ندارد.")
            return

        try:
            del self.config["teleport_locations"][location_name]
            self.save_config()
            await self.chat(self.get_message("deltele_success", location=location_name))
            logger.info(f"مکان {location_name} توسط {user.username} حذف شد.")
        except Exception as e:
            await self.chat((f"خطا در حذف مکان {location_name}: {str(e)}" if self.config.get("language", "fa") == "fa"
                              else f"Error deleting location {location_name}: {str(e)}"))
            logger.error(f"خطا در cmd_deltele برای {location_name}: {str(e)}")

    async def apply_style_item(self, category, link_or_id: str, palette=None) -> str:
        """یه آیتم رو با آیتم داده‌شده (لینک یا آیدی خام) عوض می‌کنه. نیازی به گفتن «نوع/دسته»
        نیست — دسته‌ی واقعی از روی پیشوند خودِ آیدیِ آیتم (eye-، hair_front-، pants-، shoes-،
        و غیره) خودکار تشخیص داده میشه. آیتم قبلیِ همون دسته حذف و آیتم جدید اضافه میشه.
        اگه هایرایز آیتم رو رد کنه (مثلاً چون قفله و بات مالکش نیست)، خطای واقعی سرور رو
        برمی‌گردونیم — نمی‌تونیم به‌جاش خودکار یه جایگزین حدس بزنیم چون به کاتالوگ کامل و
        وضعیت قفل‌بودنِ هر آیتم دسترسی نداریم.

        رنگ/palette: خیلی از آیتم‌های هایرایز چند رنگ (پالت) مختلف دارن که با همون آیدیِ آیتم
        ولی یه ایندکسِ رنگ (active_palette، معمولاً 0 و بالاتر) انتخاب میشن. برای فقط عوض کردن
        رنگِ آیتمی که الان پوشیدی، کافیه دوباره همون لینک رو با یه شماره‌رنگ جدید بدی."""
        lang = self.config.get("language", "fa")
        current = await self.get_live_outfit()

        # حالت «فقط رنگ»: لینک خالی یا "-" یعنی همون آیتمِ الان بمونه، فقط رنگش عوض بشه
        # (فقط وقتی category صریحاً داده شده باشه؛ تو حالت خودکار این مسیر استفاده نمیشه)
        if category and (not link_or_id or link_or_id.strip() in ("-", "same", "همون")):
            target_prefix = STYLE_CATEGORY_PREFIXES.get(category, category)
            existing = next((it for it in current if (it.get("id") or "").split("-", 1)[0] == target_prefix), None)
            if not existing:
                return ("⚠️ الان هیچ آیتمی تو این دسته پوشیده نشده که رنگش عوض بشه — اول یه لینک آیتم بده."
                        if lang == "fa" else
                        "⚠️ Nothing is currently worn in this category to recolor — provide an item link first.")
            item_id = existing["id"]
            filtered = [it for it in current if it is not existing]
        else:
            item_id = extract_item_id_from_link(link_or_id)
            if not item_id:
                return "⚠️ لینک/آیدی آیتم نامعتبره." if lang == "fa" else "⚠️ Invalid item link/id."
            new_prefix = item_id.split("-", 1)[0]
            if new_prefix in MULTI_SLOT_ITEM_PREFIXES:
                # 🎒 دسته‌هایی مثل بگ/گردنبند/عینک که هایرایز اجازه‌ی چندتاییِ هم‌زمان رو میده —
                # هیچی حذف نمیشه، فقط اضافه میشه (دقیقاً مثل !item add).
                filtered = list(current)
            else:
                filtered = [it for it in current if (it.get("id") or "").split("-", 1)[0] != new_prefix]
            category = category or new_prefix

        palette_value = None
        if palette is not None and str(palette).strip() != "":
            try:
                palette_value = int(palette)
            except (TypeError, ValueError):
                return ("⚠️ شماره‌ی رنگ باید یه عدد باشه (مثلاً 0، 1، 2 ...)." if lang == "fa"
                        else "⚠️ The color number must be an integer (e.g. 0, 1, 2 ...).")

        filtered.append({"type": "clothing", "amount": 1, "id": item_id, "account_bound": False, "active_palette": palette_value})

        try:
            await self.highrise.set_outfit(deserialize_outfit(filtered))
            self.config["current_outfit"] = filtered
            self.save_config()
            logger.info(f"استایل دسته‌ی {category} به {item_id} (رنگ: {palette_value}) تغییر کرد.")
            if palette_value is not None:
                return (f"✅ آیتم «{item_id}» با رنگ شماره‌ی {palette_value} اعمال شد." if lang == "fa"
                        else f"✅ Item \"{item_id}\" applied with color #{palette_value}.")
            return (f"✅ آیتم «{item_id}» اعمال شد." if lang == "fa" else f"✅ Item \"{item_id}\" applied.")
        except Exception as e:
            logger.error(f"خطا در اعمال استایل ({category}={item_id}): {e}")
            return ((f"❌ هایرایز این آیتم رو قبول نکرد (احتمالاً قفله یا بات مالکش نیست): {e}") if lang == "fa"
                     else (f"❌ Highrise rejected this item (it may be locked or the bot doesn't own it): {e}"))

    async def get_live_outfit(self) -> list:
        """ظاهرِ *واقعیِ الانِ* بات رو مستقیم از هایرایز می‌پرسه (نه از روی کشِ محلی/کانفیگ).
        🐛 قبلاً از کشِ محلیِ self.config["current_outfit"] استفاده می‌شد که ممکنه با واقعیت
        جفت‌وجور نباشه؛ وقتی اون لیست قدیمی/نادرست بود، هایرایز کلِ درخواستِ set_outfit رو
        بی‌سروصدا (بدونِ اکسپشن) رد می‌کرد — برای همین کد فکر می‌کرد موفق بوده ولی تو بازی
        هیچی عوض نمی‌شد. الان همیشه اول ظاهرِ واقعی رو می‌گیریم.
        ⚠️ خودِ مستنداتِ هایرایز هم ناهماهنگن: چنج‌لاگِ قدیمیِ SDK اسمِ متد رو get_outfit()
        نوشته، ولی راهنمای فعلیِ سایتشون get_my_outfit() می‌گه — احتمالاً بین نسخه‌ها عوض شده.
        برای اینکه به نسخه‌ی SDKِ نصب‌شده روی سیستمِ تو حساس نباشیم، هر دو اسم رو امتحان
        می‌کنیم و هرکدوم واقعاً روی self.highrise وجود داشت همونو صدا می‌زنیم."""
        method = getattr(self.highrise, "get_my_outfit", None) or getattr(self.highrise, "get_outfit", None)
        if not method:
            logger.error("نه get_my_outfit نه get_outfit روی self.highrise پیدا نشد — SDK رو آپدیت کن.")
            return list(self.config.get("current_outfit") or DEFAULT_OUTFIT_ITEMS)
        try:
            outfit_response = await method()
            outfit_list = getattr(outfit_response, "outfit", outfit_response)
            if outfit_list:
                return serialize_outfit(outfit_list)
        except Exception as e:
            logger.error(f"خطا در گرفتنِ ظاهرِ واقعیِ بات با {method.__name__}(): {e}")
        return list(self.config.get("current_outfit") or DEFAULT_OUTFIT_ITEMS)

    async def apply_add_item(self, link_or_id: str) -> str:
        """یه آیتم رو فقط اضافه می‌کنه، بدون حذف هیچ آیتم دیگه‌ای — برای اکسسوری‌هایی مثل بگ،
        عینک، گردنبند و... که قرار نیست جای چیز دیگه‌ای رو بگیرن. هیچ محدودیت تعدادی از طرف
        ما اعمال نمیشه؛ تنها محدودیت واقعی، محدودیت اسلات‌های ظاهرِ خودِ هایرایزه که کنترلش
        دست ما نیست (اگه هایرایز رد کنه، خطای واقعیش رو نشون میدیم)."""
        lang = self.config.get("language", "fa")
        item_id = extract_item_id_from_link(link_or_id)
        if not item_id:
            return "⚠️ لینک/آیدی آیتم نامعتبره." if lang == "fa" else "⚠️ Invalid item link/id."

        current = await self.get_live_outfit()
        current.append({"type": "clothing", "amount": 1, "id": item_id, "account_bound": False, "active_palette": None})

        try:
            await self.highrise.set_outfit(deserialize_outfit(current))
            self.config["current_outfit"] = current
            self.save_config()
            logger.info(f"آیتم {item_id} بدون حذف چیزی اضافه شد.")
            return (f"✅ آیتم «{item_id}» اضافه شد (بدون حذف چیز دیگه‌ای)." if lang == "fa"
                     else f"✅ Item \"{item_id}\" added (nothing else was removed).")
        except Exception as e:
            logger.error(f"خطا در افزودن آیتم {item_id}: {e}")
            return ((f"❌ هایرایز این آیتم رو قبول نکرد (احتمالاً قفله، بات مالکش نیست، یا اسلات‌های ظاهر پره): {e}") if lang == "fa"
                     else (f"❌ Highrise rejected this item (it may be locked, not owned by the bot, or outfit slots are full): {e}"))

    async def cmd_add_item(self, user: User, parts: list):
        """!item add <لینک/آیدی> -> افزودن یه آیتم (معمولاً اکسسوری) بدون حذف هیچ چیز دیگه‌ای، بدون محدودیت تعداد."""
        if user.username.lower() not in self.config["admin_usernames"]:
            await self.chat(self.get_message("no_permission"))
            return
        lang = self.config.get("language", "fa")
        if len(parts) != 3:
            await self.chat(self.get_message("invalid_format", format=("!item add لینک/آیدی" if lang == "fa" else "!item add <link/id>")))
            return
        result = await self.apply_add_item(parts[2])
        await self.chat(result)

    async def cmd_item_search(self, user: User, parts: list):
        """!item search <کلمه‌کلیدی> -> جستجوی واقعی تو کاتالوگ هایرایز (نه یه لیست دستی/حدسی) و
        نمایش چند آیتم واقعی که اسمشون به کلمه‌کلیدی می‌خوره، همراه با آیدیِ آماده برای استفاده
        مستقیم تو !item set. این یعنی دیگه لازم نیست از بیرون لینک پیدا کنی — مستقیم از همینجا
        جستجو کن و همون‌جا هم اعمالش کن."""
        if user.username.lower() not in self.config["admin_usernames"]:
            await self.chat(self.get_message("no_permission"))
            return
        lang = self.config.get("language", "fa")
        if len(parts) < 3:
            await self.chat(self.get_message("invalid_format", format=("!item search کلمه‌کلیدی" if lang == "fa" else "!item search <keyword>")))
            return

        keyword = " ".join(parts[2:]).strip().lower().replace(" ", "")
        try:
            response = await self.webapi.get_items()
            items_list = getattr(response, "items", None) or (response if isinstance(response, list) else [])
        except Exception as e:
            logger.error(f"خطا در جستجوی کاتالوگ ({keyword}): {e}")
            await self.chat((f"❌ خطا در ارتباط با کاتالوگ هایرایز: {e}" if lang == "fa"
                              else f"❌ Error reaching the Highrise catalog: {e}"))
            return

        matches = []
        for it in items_list:
            item_id = getattr(it, "id", None) or (it.get("id") if isinstance(it, dict) else None)
            item_type = getattr(it, "item_type", None) or getattr(it, "type", None) or (
                it.get("item_type") if isinstance(it, dict) else None
            )
            if not item_id:
                continue
            # جستجوی آیتم‌های ظاهری (نه دنس/اموت که !dances/!emotescan مسئولشونه)
            is_emote_like = item_id.startswith(("dance-", "emote-", "idle-")) or (item_type and "emote" in str(item_type).lower())
            if is_emote_like:
                continue
            if keyword in item_id.lower().replace(" ", ""):
                matches.append(item_id)

        if not matches:
            await self.chat((f"⚠️ چیزی برای «{keyword}» تو کاتالوگ پیدا نشد." if lang == "fa"
                              else f"⚠️ Nothing found for \"{keyword}\" in the catalog."))
            return

        matches = matches[:10]
        if lang == "fa":
            lines = [f"🔎 {len(matches)} نتیجه برای «{keyword}» (برای اعمال: !item set <آیدی>):"]
        else:
            lines = [f"🔎 {len(matches)} results for \"{keyword}\" (to apply: !item set <id>):"]
        lines.extend(f"• {m}" for m in matches)
        await self.chat("\n".join(lines))

    async def cmd_set_item(self, user: User, parts: list):
        """!item set @username -> کپی ظاهر یک کاربر (حتی اگه الان تو روم نباشه ولی قبلاً یه بار دیده باشیمش) |
        !item set شماره -> اعمال یک اسکین ذخیره‌شده (پریست) |
        !item set eye/hair/lip/eyebrow/skin شماره‌رنگ -> فقط رنگِ همون بخش رو عوض می‌کنه |
        !item set eye/hair/lip/eyebrow/skin <لینک> [شماره‌رنگ] -> جایگزینیِ همون بخش با آیتمِ جدید |
        !item set <لینک/آیدی> [شماره‌رنگ] -> تعویض خودکار (بدونِ گفتنِ دسته) برای هر چیزِ دیگه‌ای
        (شلوار/کفش/لباس/کلاه/...) |
        !item add <لینک/آیدی> -> افزودن یه آیتم بدون حذف هیچ‌چیزی (برای اکسسوری‌هایی مثل بگ/گردنبند/عینک که
        قرار نیست جایگزین چیز دیگه‌ای بشن، بدون محدودیت تعداد)"""
        if user.username.lower() not in self.config["admin_usernames"]:
            await self.chat(self.get_message("no_permission"))
            logger.info(f"کاربر {user.username} دسترسی لازم برای اجرای !item set را ندارد.")
            return
        lang = self.config.get("language", "fa")
        fmt_error = ("!item set @username یا !item set شماره یا !item set eye/hair/lip/eyebrow/skin [لینک] شماره‌رنگ یا !item set <لینک> [شماره‌رنگ]"
                     if lang == "fa" else
                     "!item set @username or !item set <number> or !item set eye/hair/lip/eyebrow/skin [link] [color] or !item set <link> [color]")

        if len(parts) not in (3, 4, 5):
            await self.chat(self.get_message("invalid_format", format=fmt_error))
            return

        target_spec = parts[2]

        # حالت صفرم: !item set eye/hair/lip/eyebrow/skin [لینک] [شماره‌رنگ] -> یه دسته‌ی
        # شناخته‌شده‌ی صورت. یا فقط یه عدد (= فقط رنگِ همینی که الان پوشیده عوض بشه)، یا یه
        # لینک/آیدی (با شماره‌رنگِ اختیاری بعدش).
        category_key = STYLE_CATEGORY_ALIASES.get(target_spec.lower())
        if category_key:
            category = STYLE_CATEGORY_PREFIXES[category_key]
            if len(parts) == 3:
                await self.chat(("⚠️ یا یه شماره‌رنگ بده (مثلاً !item set eye 1) یا یه لینک/آیدی." if lang == "fa"
                                  else "⚠️ Give either a color number (e.g. !item set eye 1) or a link/id."))
                return
            arg3 = parts[3]
            if arg3.isdigit() and len(parts) == 4:
                # فقط رنگ عوض بشه، آیتمِ فعلیِ همون دسته دست‌نخورده بمونه
                result = await self.apply_style_item(category, "-", arg3)
            else:
                # یه آیتمِ جدید برای همین دسته، با شماره‌رنگِ اختیاری
                palette = parts[4] if len(parts) == 5 else None
                result = await self.apply_style_item(category, arg3, palette)
            await self.chat(result)
            return

        # حالت سوم: !item set <لینک/آیدی> [شماره‌رنگ] -> تشخیص خودکار دسته از روی خودِ لینک،
        # بدون نیاز به گفتن نوع. هر چیزی که با @ شروع نشه و کاملاً عدد هم نباشه، لینک/آیدی حساب میشه.
        if not target_spec.startswith("@") and not target_spec.isdigit():
            if len(parts) not in (3, 4):
                await self.chat(self.get_message("invalid_format", format=fmt_error))
                return
            palette = parts[3] if len(parts) == 4 else None
            result = await self.apply_style_item(None, target_spec, palette)
            await self.chat(result)
            return

        if len(parts) != 3:
            await self.chat(self.get_message("invalid_format", format=fmt_error))
            return

        # حالت اول: !item set 1 / !item set 2 ... -> اعمال یک اسکین ذخیره‌شده (پریست)
        if target_spec.isdigit():
            preset = self.config["outfit_presets"].get(target_spec)
            if not preset:
                await self.chat((f"⚠️ پریست شماره {target_spec} هنوز ذخیره نشده. اول با !item save {target_spec} یه ظاهر رو ذخیره کن." if lang == "fa"
                                  else f"⚠️ Preset #{target_spec} hasn't been saved yet. First save a look with !item save {target_spec}."))
                return
            try:
                outfit_items = deserialize_outfit(preset)
                await self.highrise.set_outfit(outfit_items)
                self.config["current_outfit"] = preset
                self.save_config()
                await self.chat((f"✅ ظاهر ربات به پریست شماره {target_spec} تغییر کرد." if lang == "fa"
                                  else f"✅ Bot's look changed to preset #{target_spec}."))
                logger.info(f"ظاهر ربات به پریست {target_spec} تغییر کرد توسط {user.username}.")
            except Exception as e:
                await self.chat((f"خطا در اعمال پریست: {e}" if lang == "fa" else f"Error applying preset: {e}"))
                logger.error(f"خطا در اعمال پریست {target_spec}: {e}")
            return

        # حالت دوم: !item set @username -> کپی کردن ظاهر یک کاربر (آنلاین یا قبلاً دیده‌شده)
        if not target_spec.startswith("@"):
            await self.chat(self.get_message("invalid_format", format=fmt_error))
            return

        target_username = target_spec[1:].lower()
        target_user = self.active_users.get(target_username)
        target_user_id = target_user.id if target_user else self.config.get("known_user_ids", {}).get(target_username)

        if not target_user_id:
            await self.chat((f"⚠️ @{target_username} پیدا نشد — این بات فقط کسایی که *قبلاً حداقل یه بار* "
                              f"تو همین روم دیده رو می‌تونه کپی کنه (چون هایرایز جستجوی عمومی با یوزرنیم نداره)."
                              if lang == "fa" else
                              f"⚠️ @{target_username} not found — this bot can only copy someone it has *seen in this room at least once before* "
                              f"(Highrise has no public username search)."))
            logger.info(f"کاربر هدف {target_username} توسط {user.username} پیدا نشد (نه آنلاین، نه تو کش).")
            return

        try:
            outfit_response = await self.highrise.get_user_outfit(target_user_id)
            if not hasattr(outfit_response, "outfit") or not outfit_response.outfit:
                await self.chat((f"خطا: اطلاعات ظاهر برای @{target_username} در دسترس نیست." if lang == "fa"
                                  else f"Error: outfit data for @{target_username} isn't available."))
                logger.error(f"اطلاعات ظاهر برای {target_username} در دسترس نیست.")
                return

            outfit_items = outfit_response.outfit
            await self.highrise.set_outfit(outfit_items)

            # ذخیره‌ی خودکار ظاهر جدید تا بعد از ری‌استارت ربات هم حفظ بشه
            self.config["current_outfit"] = serialize_outfit(outfit_items)
            self.save_config()

            await self.chat(self.get_message("set_item_success", username=target_username))
            logger.info(f"ظاهر ربات به ایتم‌های {target_username} تغییر کرد: {outfit_items}")
        except Exception as e:
            err_text = str(e)
            if "lock" in err_text.lower() or "permission" in err_text.lower() or "forbidden" in err_text.lower():
                await self.chat((f"❌ هایرایز کپی‌کردنِ ظاهرِ @{target_username} رو رد کرد — احتمالاً خودش تو تنظیماتِ "
                                  f"اکانتش کپی‌شدنِ ظاهرش رو غیرفعال کرده. این یه محدودیتِ عمدیِ خودِ هایرایزه که "
                                  f"دورش نمی‌زنیم." if lang == "fa" else
                                  f"❌ Highrise rejected copying @{target_username}'s look — they've likely disabled "
                                  f"outfit copying in their account settings. That's an intentional Highrise "
                                  f"protection we won't bypass."))
            else:
                await self.chat((f"خطا در تغییر ظاهر ربات: {err_text}" if lang == "fa" else f"Error changing bot's look: {err_text}"))
            logger.error(f"خطا در cmd_set_item برای {target_username}: {err_text}")

    async def cmd_save_item(self, user: User, parts: list):
        """!item save شماره -> ذخیره‌ی ظاهر فعلیِ ربات به‌عنوان یک پریست قابل استفاده با !item set شماره"""
        if user.username.lower() not in self.config["admin_usernames"]:
            await self.chat(self.get_message("no_permission"))
            return
        lang = self.config.get("language", "fa")

        if len(parts) != 3 or not parts[2].isdigit():
            await self.chat("⚠️ فرمت اشتباه! استفاده کن از: !item save شماره (مثلاً !item save 1)" if lang == "fa"
                             else "⚠️ Wrong format! Use: !item save number (e.g. !item save 1)")
            return

        slot = parts[2]
        try:
            outfit_items = await self.get_live_outfit()
            if not outfit_items:
                await self.chat("⚠️ نتونستم ظاهر فعلی ربات رو بخونم." if lang == "fa" else "⚠️ Couldn't read the bot's current look.")
                return

            self.config["outfit_presets"][slot] = outfit_items
            self.save_config()
            await self.chat((f"✅ ظاهر فعلی ربات به‌عنوان پریست شماره {slot} ذخیره شد. حالا هرکسی می‌تونه با !item set {slot} روش سوییچ کنه." if lang == "fa"
                              else f"✅ Bot's current look saved as preset #{slot}. Anyone can now switch to it with !item set {slot}."))
            logger.info(f"{user.username} ظاهر فعلی ربات رو تو پریست {slot} ذخیره کرد.")
        except Exception as e:
            await self.chat((f"خطا در ذخیره‌ی پریست: {e}" if lang == "fa" else f"Error saving preset: {e}"))
            logger.error(f"خطا در cmd_save_item برای اسلات {slot}: {e}")

    async def cmd_run(self, user: User, parts: list):
        """!run on / !run off -> روشن یا خاموش کردن راه رفتن خودکار ربات دور روم (مثل یک کاراکتر واقعی) |
        !run fast on / !run fast off -> راه رفتنِ سریع‌تر (هر ~۲ ثانیه به‌جای ۵ تا ۹ ثانیه)"""
        if user.username.lower() not in self.config["admin_usernames"]:
            await self.chat(self.get_message("no_permission"))
            return
        lang = self.config.get("language", "fa")

        if len(parts) >= 3 and parts[1].lower() == "fast" and parts[2].lower() in ("on", "off"):
            self.auto_walk_fast = parts[2].lower() == "on"
            await self.chat((f"⚡ راه رفتنِ سریع {'روشن' if self.auto_walk_fast else 'خاموش'} شد." if lang == "fa"
                              else f"⚡ Fast walking turned {'on' if self.auto_walk_fast else 'off'}."))
            return

        if len(parts) < 2 or parts[1].lower() not in ("on", "off"):
            await self.chat("⚠️ فرمت اشتباه! استفاده کن از: !run on یا !run off یا !run fast on/off" if lang == "fa"
                             else "⚠️ Wrong format! Use: !run on, !run off, or !run fast on/off")
            return

        if parts[1].lower() == "on":
            if self.auto_walk_enabled:
                await self.chat("⚠️ راه رفتن خودکار از قبل روشنه." if lang == "fa" else "⚠️ Auto-walk is already on.")
                return
            self.auto_walk_enabled = True
            self.auto_walk_task = create_task(self.auto_walk_loop())
            await self.chat("🚶 راه رفتن خودکار ربات روشن شد." if lang == "fa" else "🚶 Bot auto-walk turned on.")
        else:
            self.auto_walk_enabled = False
            if self.auto_walk_task and not self.auto_walk_task.done():
                self.auto_walk_task.cancel()
            await self.chat("🛑 راه رفتن خودکار ربات خاموش شد." if lang == "fa" else "🛑 Bot auto-walk turned off.")

    async def auto_walk_loop(self):
        """هر چند ثانیه یک‌بار، ربات به یک نقطه‌ی نزدیک تصادفی راه می‌ره تا شبیه یک کاراکتر واقعی رفتار کنه.
        با !run fast on فاصله‌ی بینِ حرکت‌ها کوتاه‌تر میشه (~۲ ثانیه به‌جای ۵ تا ۹ ثانیه)."""
        try:
            while self.auto_walk_enabled:
                base = self.bot_position or Position(x=0.0, y=0.0, z=0.0)
                dest = Position(
                    x=base.x + random.uniform(-2.0, 2.0),
                    y=base.y,
                    z=base.z + random.uniform(-2.0, 2.0),
                )
                try:
                    await self.highrise.walk_to(dest)
                    self.bot_position = dest
                except Exception as e:
                    logger.error(f"خطا در راه رفتن خودکار: {e}")
                if self.auto_walk_fast:
                    await sleep(random.uniform(1.5, 2.5))
                else:
                    await sleep(random.uniform(5.0, 9.0))
        except CancelledError:
            logger.info("راه رفتن خودکار متوقف شد.")

    async def cmd_welcome(self, user: User, parts: list):
        """!welcome پیام -> یه پیامِ خوش‌آمدِ جدید به لیست اضافه می‌کنه (وقتی چندتا باشه، هر بار یکی
        تصادفی انتخاب میشه). لیستِ کامل: !welcomelist — حذف: !delwelcome <شماره>."""
        if user.username.lower() not in self.config["admin_usernames"]:
            await self.chat(self.get_message("no_permission"))
            logger.info(f"کاربر {user.username} دسترسی لازم برای اجرای !welcome را ندارد.")
            return

        parts = parts[:1] + ([" ".join(parts[1:])] if len(parts) > 1 else [])
        if len(parts) < 2:
            await self.chat(self.get_message("invalid_format", format=("!welcome پیام" if self.config.get("language","fa") == "fa" else "!welcome <message>")))
            logger.info(f"فرمت نادرست برای دستور !welcome توسط {user.username} وارد شد.")
            return

        welcome_message = parts[1]
        self.config.setdefault("welcome_messages", []).append(welcome_message)
        self.config["welcome_message"] = welcome_message  # برای سازگاری با پنلِ سایت (که همین یکی رو نشون می‌ده)
        self.save_config()
        count = len(self.config["welcome_messages"])
        await self.chat((f"✅ پیامِ خوش‌آمدِ جدید اضافه شد (الان {count} تا داری؛ هر بار یکی تصادفی انتخاب میشه)." if self.config.get("language","fa") == "fa"
                          else f"✅ New welcome message added (you now have {count}; one is picked at random each time)."))
        logger.info(f"پیام خوش‌آمدگویی جدید توسط {user.username} اضافه شد: '{welcome_message}'")

    async def cmd_welcomelist(self, user: User, parts: list):
        if user.username.lower() not in self.config["admin_usernames"]:
            await self.chat(self.get_message("no_permission"))
            return
        lang = self.config.get("language", "fa")
        messages = self.config.get("welcome_messages", [])
        if not messages:
            await self.chat("📭 هیچ پیامِ خوش‌آمدی ثبت نشده." if lang == "fa" else "📭 No welcome messages set.")
            return
        lines = [f"{i+1}. {m}" for i, m in enumerate(messages)]
        text = "📋 پیام‌های خوش‌آمد:\n" + "\n".join(lines) if lang == "fa" else "📋 Welcome messages:\n" + "\n".join(lines)
        for chunk in [text[i:i+200] for i in range(0, len(text), 200)]:
            await self.chat(chunk)

    async def cmd_delwelcome(self, user: User, parts: list):
        if user.username.lower() not in self.config["admin_usernames"]:
            await self.chat(self.get_message("no_permission"))
            return
        lang = self.config.get("language", "fa")
        if len(parts) != 2 or not parts[1].isdigit():
            await self.chat("⚠️ استفاده کن از: !delwelcome شماره (شماره رو از !welcomelist بگیر)" if lang == "fa"
                             else "⚠️ Use: !delwelcome <number> (get the number from !welcomelist)")
            return
        idx = int(parts[1]) - 1
        messages = self.config.get("welcome_messages", [])
        if idx < 0 or idx >= len(messages):
            await self.chat("⚠️ همچین شماره‌ای وجود نداره." if lang == "fa" else "⚠️ That number doesn't exist.")
            return
        removed = messages.pop(idx)
        self.config["welcome_message"] = messages[0] if messages else ""
        self.save_config()
        await self.chat((f"🗑 حذف شد: {removed}" if lang == "fa" else f"🗑 Removed: {removed}"))

    async def cmd_welcome_on(self, user: User, parts: list):
        await self._set_welcome_enabled(user, True)

    async def cmd_welcome_off(self, user: User, parts: list):
        await self._set_welcome_enabled(user, False)

    async def _set_welcome_enabled(self, user: User, enabled: bool):
        if user.username.lower() not in self.config["admin_usernames"]:
            await self.chat(self.get_message("no_permission"))
            return
        lang = self.config.get("language", "fa")
        self.config["welcome_enabled"] = enabled
        self.save_config()
        await self.chat((f"👋 پیامِ خوش‌آمد {'روشن' if enabled else 'خاموش'} شد." if lang == "fa"
                          else f"👋 Welcome message turned {'on' if enabled else 'off'}."))

    async def cmd_goodbye(self, user: User, parts: list):
        """!goodbye پیام / !addgoodbye پیام -> یه پیامِ خداحافظیِ جدید به لیست اضافه می‌کنه
        (دقیقاً مثلِ !welcome/!addwelcome) — وقتی چندتا باشه، هر بار یکی تصادفی انتخاب میشه.
        لیستِ کامل: !goodbyelist — حذف: !delgoodbye <شماره>."""
        if user.username.lower() not in self.config["admin_usernames"]:
            await self.chat(self.get_message("no_permission"))
            logger.info(f"کاربر {user.username} دسترسی لازم برای اجرای !goodbye را ندارد.")
            return

        lang = self.config.get("language", "fa")
        parts = parts[:1] + ([" ".join(parts[1:])] if len(parts) > 1 else [])
        if len(parts) < 2:
            usage = {
                "fa": "!goodbye پیام یا !addgoodbye پیام",
                "en": "!goodbye <message> or !addgoodbye <message>",
                "ar": "!goodbye رسالة أو !addgoodbye رسالة",
            }.get(lang, "!goodbye <message>")
            await self.chat(self.get_message("invalid_format", format=usage))
            logger.info(f"فرمت نادرست برای دستور !goodbye توسط {user.username} وارد شد.")
            return

        goodbye_message = parts[1]
        self.config.setdefault("goodbye_messages", []).append(goodbye_message)
        self.config["goodbye_message"] = goodbye_message  # برای سازگاری با پنلِ سایت
        self.save_config()
        count = len(self.config["goodbye_messages"])
        await self.chat({
            "fa": f"✅ پیامِ خداحافظیِ جدید اضافه شد (الان {count} تا داری؛ هر بار یکی تصادفی انتخاب میشه).",
            "en": f"✅ New goodbye message added (you now have {count}; one is picked at random each time).",
            "ar": f"✅ تمت إضافة رسالة وداع جديدة (لديك الآن {count}؛ يتم اختيار واحدة عشوائيًا في كل مرة).",
        }.get(lang))
        logger.info(f"پیام خداحافظی جدید توسط {user.username} اضافه شد: '{goodbye_message}'")

    async def cmd_goodbyelist(self, user: User, parts: list):
        if user.username.lower() not in self.config["admin_usernames"]:
            await self.chat(self.get_message("no_permission"))
            return
        lang = self.config.get("language", "fa")
        messages = self.config.get("goodbye_messages", [])
        if not messages:
            await self.chat({
                "fa": "📭 هیچ پیامِ خداحافظی‌ای ثبت نشده.",
                "en": "📭 No goodbye messages set.",
                "ar": "📭 لا توجد أي رسالة وداع مسجّلة.",
            }.get(lang))
            return
        lines = [f"{i+1}. {m}" for i, m in enumerate(messages)]
        header = {"fa": "📋 پیام‌های خداحافظی:\n", "en": "📋 Goodbye messages:\n", "ar": "📋 رسائل الوداع:\n"}.get(lang)
        text = header + "\n".join(lines)
        for chunk in [text[i:i+200] for i in range(0, len(text), 200)]:
            await self.chat(chunk)

    async def cmd_delgoodbye(self, user: User, parts: list):
        if user.username.lower() not in self.config["admin_usernames"]:
            await self.chat(self.get_message("no_permission"))
            return
        lang = self.config.get("language", "fa")
        if len(parts) != 2 or not parts[1].isdigit():
            await self.chat({
                "fa": "⚠️ استفاده کن از: !delgoodbye شماره (شماره رو از !goodbyelist بگیر)",
                "en": "⚠️ Use: !delgoodbye <number> (get the number from !goodbyelist)",
                "ar": "⚠️ استخدم: !delgoodbye رقم (احصل على الرقم من !goodbyelist)",
            }.get(lang))
            return
        idx = int(parts[1]) - 1
        messages = self.config.get("goodbye_messages", [])
        if idx < 0 or idx >= len(messages):
            await self.chat({
                "fa": "⚠️ همچین شماره‌ای وجود نداره.",
                "en": "⚠️ That number doesn't exist.",
                "ar": "⚠️ هذا الرقم غير موجود.",
            }.get(lang))
            return
        removed = messages.pop(idx)
        self.config["goodbye_message"] = messages[0] if messages else ""
        self.save_config()
        await self.chat({
            "fa": f"🗑 حذف شد: {removed}",
            "en": f"🗑 Removed: {removed}",
            "ar": f"🗑 تم الحذف: {removed}",
        }.get(lang))

    async def cmd_goodbye_on(self, user: User, parts: list):
        await self._set_goodbye_enabled(user, True)

    async def cmd_goodbye_off(self, user: User, parts: list):
        await self._set_goodbye_enabled(user, False)

    async def _set_goodbye_enabled(self, user: User, enabled: bool):
        if user.username.lower() not in self.config["admin_usernames"]:
            await self.chat(self.get_message("no_permission"))
            return
        lang = self.config.get("language", "fa")
        self.config["goodbye_enabled"] = enabled
        self.save_config()
        await self.chat({
            "fa": f"👋 پیامِ خداحافظی {'روشن' if enabled else 'خاموش'} شد.",
            "en": f"👋 Goodbye message turned {'on' if enabled else 'off'}.",
            "ar": f"👋 تم {'تفعيل' if enabled else 'إيقاف'} رسالة الوداع.",
        }.get(lang))

    async def cmd_mark(self, user: User, parts: list):
        """!mark -> موقعیتِ فعلیِ کاربر رو به‌عنوانِ مارکِ شخصیِ خودش ذخیره می‌کنه (برای !autotele)."""
        lang = self.config.get("language", "fa")
        username = user.username.lower()
        pos = self.user_positions.get(username)
        if not pos:
            await self.chat({
                "fa": "⚠️ موقعیتِ شما مشخص نیست، یه لحظه تکون بخور و دوباره امتحان کن.",
                "en": "⚠️ Your position isn't known — move a bit and try again.",
                "ar": "⚠️ موقعك غير معروف، تحرك قليلاً وحاول مرة أخرى.",
            }.get(lang))
            return
        self.config.setdefault("user_marks", {})[username] = {"x": pos.x, "y": pos.y, "z": pos.z}
        self.save_config()
        await self.chat({
            "fa": "📍 همین‌جا به‌عنوان مارکِ شخصیِ شما ذخیره شد. حالا !autotele on رو بزن.",
            "en": "📍 This spot was saved as your personal mark. Now run !autotele on.",
            "ar": "📍 تم حفظ هذا المكان كعلامتك الشخصية. الآن استخدم !autotele on.",
        }.get(lang))
        logger.info(f"کاربر {user.username} موقعیتِ خودش رو با !mark ذخیره کرد: x={pos.x}, y={pos.y}, z={pos.z}")

    async def cmd_autotele_toggle(self, user: User, parts: list):
        """!autotele on/off -> وقتی روشنه، اگه فاصله‌ی کاربر از مارکِ شخصیِ خودش (!mark) زیاد بشه
        (مثلاً می‌خواد بره طبقه‌ی دیگه)، به‌جای راه‌رفتنِ دستی، خودکار همون‌جا تلپورت میشه."""
        lang = self.config.get("language", "fa")
        username = user.username.lower()
        if len(parts) != 2 or parts[1].lower() not in ("on", "off"):
            await self.chat({
                "fa": "⚠️ استفاده کن از: !autotele on یا !autotele off",
                "en": "⚠️ Use: !autotele on or !autotele off",
                "ar": "⚠️ استخدم: !autotele on أو !autotele off",
            }.get(lang))
            return

        enabled = parts[1].lower() == "on"
        autotele_users = set(self.config.setdefault("autotele_users", []))

        if enabled:
            if username not in self.config.get("user_marks", {}):
                await self.chat({
                    "fa": "⚠️ اول برو همون‌جایی که می‌خوای وایسا و !mark رو بزن، بعد !autotele on.",
                    "en": "⚠️ First stand where you want and run !mark, then !autotele on.",
                    "ar": "⚠️ أولاً قف في المكان الذي تريده واستخدم !mark، ثم !autotele on.",
                }.get(lang))
                return
            autotele_users.add(username)
        else:
            autotele_users.discard(username)

        self.config["autotele_users"] = list(autotele_users)
        self.save_config()
        await self.chat({
            "fa": f"🧲 autotele برای شما {'روشن' if enabled else 'خاموش'} شد.",
            "en": f"🧲 autotele turned {'on' if enabled else 'off'} for you.",
            "ar": f"🧲 تم {'تفعيل' if enabled else 'إيقاف'} autotele لك.",
        }.get(lang))
        logger.info(f"کاربر {user.username} autotele را {'روشن' if enabled else 'خاموش'} کرد.")

    async def cmd_language(self, user: User, parts: list):
        """!language fa / !language en / !language ar -> تغییرِ زبانِ بات.
        ⚠️ نکته: زبانِ پیش‌فرض از تنظیماتِ سایت میاد و فقط موقعِ روشن‌شدنِ بات خونده میشه؛
        یعنی این دستور فوراً اعمال میشه ولی اگه از سایت هم زبونِ دیگه‌ای ست کرده باشی، با
        !restart یا روشنِ بعدیِ بات دوباره از سایت می‌خونه. برای تغییرِ دائمی، از سایت استفاده کن."""
        if user.username.lower() not in self.config["admin_usernames"]:
            await self.chat(self.get_message("no_permission"))
            return
        if len(parts) != 2 or parts[1].lower() not in ("fa", "en", "ar"):
            lang_now = self.config.get("language", "fa")
            usage = {
                "fa": "⚠️ استفاده کن از: !language fa یا !language en یا !language ar",
                "en": "⚠️ Use: !language fa or !language en or !language ar",
                "ar": "⚠️ استخدم: !language fa أو !language en أو !language ar",
            }
            await self.chat(usage.get(lang_now, usage["fa"]))
            return
        self.config["language"] = parts[1].lower()
        self.save_config()
        await self.chat(self.get_message("lang_changed"))

    async def cmd_reaction_debug(self, user: User, parts: list):
        """!reactiontest @username -> فقط برای تشخیصِ باگِ !heart/!clap/... : هرچی از Reaction
        تو SDK پیدا کنه رو تو چت لیست می‌کنه، و نتیجه‌ی واقعیِ ارسال (خطا یا نه) رو هم می‌گه.
        اینو یه‌بار بزن و کل خروجیش رو برام بفرست تا مقدارِ درستِ Reaction رو دقیق بفهمیم."""
        if not (user.username.lower() in self.config["admin_usernames"] or self.is_host(user.username)):
            await self.chat(self.get_message("no_permission"))
            return
        if len(parts) != 2 or not parts[1].startswith("@"):
            await self.chat("⚠️ استفاده کن از: !reactiontest @username")
            return
        target_username = parts[1][1:].lower()
        target_user = self.active_users.get(target_username)
        if not target_user:
            await self.chat(self.get_message("user_not_found", username=target_username))
            return

        if _HighriseReaction is None:
            await self.chat("⚠️ اصلاً Reaction از highrise قابل import نیست — یعنی این نسخه از SDK همچین چیزی نداره.")
        else:
            members = [a for a in dir(_HighriseReaction) if not a.startswith("_")]
            text = "📋 اعضای Reaction تو SDK: " + ", ".join(members[:40])
            for chunk in [text[i:i+200] for i in range(0, len(text), 200)]:
                await self.chat(chunk)

        for raw_name in ("heart", "clap", "wink", "wave", "thumbs-up"):
            resolved = resolve_reaction(raw_name)
            await self.chat(f"🔎 {raw_name} -> {resolved!r} (type: {type(resolved).__name__})")

        try:
            await self.highrise.react(resolve_reaction("heart"), target_user.id)
            await self.chat("✅ react() برای heart بدون اکسپشن اجرا شد (یعنی سرور رد نکرده).")
        except Exception as e:
            await self.chat(f"❌ react() برای heart اکسپشن داد: {type(e).__name__}: {e}")

    async def cmd_bot_off(self, user: User, parts: list):
        if user.username.lower() not in self.config["admin_usernames"]:
            await self.chat(self.get_message("no_permission"))
            return
        lang = self.config.get("language", "fa")
        self.config["bot_enabled"] = False
        self.save_config()
        await self.chat(("🔇 بات خاموش شد — فقط به !boton جواب می‌ده تا دوباره روشنش کنی." if lang == "fa"
                          else "🔇 Bot turned off — it will only respond to !boton to turn back on."))

    async def cmd_bot_on(self, user: User, parts: list):
        if user.username.lower() not in self.config["admin_usernames"]:
            await self.chat(self.get_message("no_permission"))
            return
        lang = self.config.get("language", "fa")
        self.config["bot_enabled"] = True
        self.save_config()
        await self.chat("🔊 بات دوباره روشن شد." if lang == "fa" else "🔊 Bot is back on.")

    async def cmd_dm(self, user: User, parts: list):
        """!dm @username متن -> پیامِ خصوصی می‌فرسته.
        ⚠️ صادقانه: SDK هایرایز فقط اجازه‌ی ارسال به یه «مکالمه‌ی موجود» رو می‌ده، نه شروعِ
        مکالمه‌ی جدید با هرکسی. برای همین این دستور در واقع از send_whisper استفاده می‌کنه —
        یعنی پیام فقط وقتی که کاربر هدف هنوز تو همین روم حاضره قابل‌دیدنه، نه یه پیامِ اینباکسِ
        همیشگی که هر وقت آنلاین شد ببینه."""
        if user.username.lower() not in self.config["admin_usernames"]:
            await self.chat(self.get_message("no_permission"))
            return
        lang = self.config.get("language", "fa")
        if len(parts) < 3 or not parts[1].startswith("@"):
            await self.chat("⚠️ فرمت اشتباه! استفاده کن از: !dm @username متن" if lang == "fa"
                             else "⚠️ Wrong format! Use: !dm @username <text>")
            return
        target_username = parts[1][1:].lower()
        target_user = self.active_users.get(target_username)
        if not target_user:
            await self.chat(self.get_message("user_not_found", username=target_username))
            return
        text = " ".join(parts[2:])
        try:
            await self.highrise.send_whisper(target_user.id, f"💌 پیامِ خصوصی از @{user.username}: {text}" if lang == "fa"
                                              else f"💌 Private message from @{user.username}: {text}")
            await self.chat((f"✅ پیام به @{target_username} فرستاده شد (به‌صورتِ ویسپر، فقط خودش می‌بینه)." if lang == "fa"
                              else f"✅ Message sent to @{target_username} (as a whisper, only they can see it)."))
        except Exception as e:
            await self.chat((f"خطا در فرستادنِ پیام: {e}" if lang == "fa" else f"Error sending message: {e}"))
            logger.error(f"خطا در cmd_dm برای {target_username}: {e}")

    async def cmd_sethome(self, user: User, parts: list):
        """!sethome -> موقعیتِ فعلیِ ادمین رو به‌عنوانِ «خونه‌ی بات» ذخیره می‌کنه."""
        if user.username.lower() not in self.config["admin_usernames"]:
            await self.chat(self.get_message("no_permission"))
            return
        lang = self.config.get("language", "fa")
        pos = self.user_positions.get(user.username.lower())
        if not pos:
            await self.chat("موقعیت شما مشخص نیست!" if lang == "fa" else "Your position isn't known!")
            return
        self.config["home_position"] = {"x": pos.x, "y": pos.y, "z": pos.z}
        self.save_config()
        await self.chat("🏠 خونه‌ی بات همین‌جا ثبت شد." if lang == "fa" else "🏠 Bot's home was set to your current spot.")

    async def cmd_home(self, user: User, parts: list):
        """!home -> بات رو به خونه‌ی ثبت‌شده تلپورت می‌کنه."""
        if user.username.lower() not in self.config["admin_usernames"]:
            await self.chat(self.get_message("no_permission"))
            return
        lang = self.config.get("language", "fa")
        home = self.config.get("home_position")
        if not home:
            await self.chat(("⚠️ هنوز خونه‌ای ثبت نشده — اول برو همون‌جا وایسا و بزن !sethome." if lang == "fa"
                              else "⚠️ No home is set yet — stand where you want and run !sethome."))
            return
        try:
            await self.highrise.teleport(user_id=self.user_id, dest=Position(x=home["x"], y=home["y"], z=home["z"]))
            await self.chat("🏠 بات به خونه برگشت." if lang == "fa" else "🏠 Bot returned home.")
        except Exception as e:
            await self.chat((f"خطا در تلپورت به خونه: {e}" if lang == "fa" else f"Error teleporting home: {e}"))
            logger.error(f"خطا در cmd_home: {e}")

    async def cmd_delhome(self, user: User, parts: list):
        if user.username.lower() not in self.config["admin_usernames"]:
            await self.chat(self.get_message("no_permission"))
            return
        lang = self.config.get("language", "fa")
        self.config["home_position"] = None
        self.save_config()
        await self.chat("🗑 خونه‌ی بات پاک شد." if lang == "fa" else "🗑 Bot's home was cleared.")

    async def cmd_mod(self, user: User, parts: list):
        """!mod @username -> اضافه‌کردنِ یه ناظر (دسترسیِ محدودتر از ادمینِ کامل — فقط
        دستوراتِ نظارتی مثلِ mute/kick/ban/freeze/warn/jail، نه !restart یا !settoken)."""
        lang = self.config.get("language", "fa")
        if not self.is_host(user.username) and user.username.lower() not in self.config["admin_usernames"]:
            await self.chat(self.get_message("no_permission"))
            return
        if len(parts) != 2 or not parts[1].startswith("@"):
            await self.chat("⚠️ فرمت اشتباه! استفاده کن از: !mod @username" if lang == "fa"
                             else "⚠️ Wrong format! Use: !mod @username")
            return
        target_username = parts[1][1:].lower()
        if target_username in self.config.get("moderator_usernames", []):
            await self.chat((f"@{target_username} از قبل ناظره." if lang == "fa" else f"@{target_username} is already a moderator."))
            return
        self.config.setdefault("moderator_usernames", []).append(target_username)
        self.save_config()
        await self.chat((f"🛡 @{target_username} ناظر شد (دسترسیِ نظارتیِ محدود)." if lang == "fa"
                          else f"🛡 @{target_username} is now a moderator (limited moderation access)."))

    async def cmd_unmod(self, user: User, parts: list):
        lang = self.config.get("language", "fa")
        if not self.is_host(user.username) and user.username.lower() not in self.config["admin_usernames"]:
            await self.chat(self.get_message("no_permission"))
            return
        if len(parts) != 2 or not parts[1].startswith("@"):
            await self.chat("⚠️ فرمت اشتباه! استفاده کن از: !unmod @username" if lang == "fa"
                             else "⚠️ Wrong format! Use: !unmod @username")
            return
        target_username = parts[1][1:].lower()
        if target_username not in self.config.get("moderator_usernames", []):
            await self.chat((f"@{target_username} ناظر نیست." if lang == "fa" else f"@{target_username} isn't a moderator."))
            return
        self.config["moderator_usernames"].remove(target_username)
        self.save_config()
        await self.chat((f"🛡 @{target_username} دیگه ناظر نیست." if lang == "fa" else f"🛡 @{target_username} is no longer a moderator."))

    async def cmd_vip_list(self, user: User, parts: list):
        """!vip-list -> فهرستِ VIPهای دائمی و موقت (با زمانِ باقی‌مونده‌ی موقت‌ها)."""
        lang = self.config.get("language", "fa")
        vips = self.config.get("vip_usernames", [])
        if not vips:
            await self.chat("👑 الان هیچ VIP ای نیست." if lang == "fa" else "👑 There are no VIPs right now.")
            return
        lines = []
        for v in vips:
            if v in self.temp_vip_expiry:
                remaining = (self.temp_vip_expiry[v] - datetime.utcnow()).total_seconds()
                remaining_text = humanize_seconds_fa(int(remaining)) if lang == "fa" else humanize_seconds_en(int(remaining))
                lines.append(f"@{v} (موقت — {remaining_text} مونده)" if lang == "fa" else f"@{v} (temp — {remaining_text} left)")
            else:
                lines.append(f"@{v} (دائمی)" if lang == "fa" else f"@{v} (permanent)")
        text = ("👑 لیستِ VIP:\n" if lang == "fa" else "👑 VIP list:\n") + "\n".join(lines)
        for chunk in [text[i:i+200] for i in range(0, len(text), 200)]:
            await self.chat(chunk)

    async def cmd_vip_args(self, user: User, parts: list):
        """!vip-args -> نمایشِ مزایای VIP (متنِ ثابت — خودت می‌تونی متنش رو عوض کنی)."""
        lang = self.config.get("language", "fa")
        text = (
            "⭐ مزایای VIP:\n"
            "• دسترسی به مکان‌های اختصاصیِ VIP (با !vip / !vip1)\n"
            "• نشانِ VIP تو !info\n"
            "• اولویت تو رویدادها و قرعه‌کشی‌ها (اگه ادمین فعال کرده باشه)"
            if lang == "fa" else
            "⭐ VIP perks:\n"
            "• Access to VIP-only spots (!vip / !vip1)\n"
            "• VIP badge shown in !info\n"
            "• Priority in events/lotteries (if enabled by the admin)"
        )
        await self.chat(text)

    async def cmd_tempvip(self, user: User, parts: list):
        """!tempvip @username دقیقه -> VIPِ موقت می‌ده که با تمومِ زمان خودکار برداشته میشه."""
        if user.username.lower() not in self.config["admin_usernames"]:
            await self.chat(self.get_message("no_permission"))
            return
        lang = self.config.get("language", "fa")
        if len(parts) != 3 or not parts[1].startswith("@") or not parts[2].isdigit():
            await self.chat("⚠️ فرمت اشتباه! استفاده کن از: !tempvip @username دقیقه" if lang == "fa"
                             else "⚠️ Wrong format! Use: !tempvip @username <minutes>")
            return
        target_username = parts[1][1:].lower()
        minutes = int(parts[2])
        if target_username in self.config.get("vip_usernames", []) and target_username not in self.temp_vip_expiry:
            await self.chat((f"@{target_username} از قبل VIPِ دائمیه — نیازی به تمپ‌وی‌آی‌پی نداره." if lang == "fa"
                              else f"@{target_username} is already a permanent VIP — no need for temp VIP."))
            return

        old_task = self.temp_vip_tasks.pop(target_username, None)
        if old_task:
            old_task.cancel()
        if target_username not in self.config["vip_usernames"]:
            self.config["vip_usernames"].append(target_username)
        self.temp_vip_expiry[target_username] = datetime.utcnow() + timedelta(minutes=minutes)
        self.save_config()

        async def expire_loop():
            try:
                await sleep(minutes * 60)
                if target_username in self.config["vip_usernames"]:
                    self.config["vip_usernames"].remove(target_username)
                    self.save_config()
                self.temp_vip_expiry.pop(target_username, None)
                self.temp_vip_tasks.pop(target_username, None)
                await self.chat((f"⏰ VIPِ موقتِ @{target_username} تموم شد." if lang == "fa"
                                  else f"⏰ @{target_username}'s temporary VIP has expired."))
            except CancelledError:
                pass
            except Exception as e:
                logger.error(f"خطا در حلقه‌ی انقضای tempvip برای {target_username}: {e}")

        self.temp_vip_tasks[target_username] = create_task(expire_loop())
        await self.chat((f"⭐ @{target_username} برای {minutes} دقیقه VIP شد." if lang == "fa"
                          else f"⭐ @{target_username} is VIP for {minutes} minutes."))

    async def cmd_untempvip(self, user: User, parts: list):
        """!untempvip @username -> زودتر از موعد VIPِ موقت رو می‌گیره."""
        if user.username.lower() not in self.config["admin_usernames"]:
            await self.chat(self.get_message("no_permission"))
            return
        lang = self.config.get("language", "fa")
        if len(parts) != 2 or not parts[1].startswith("@"):
            await self.chat("⚠️ فرمت اشتباه! استفاده کن از: !untempvip @username" if lang == "fa"
                             else "⚠️ Wrong format! Use: !untempvip @username")
            return
        target_username = parts[1][1:].lower()
        if target_username not in self.temp_vip_expiry:
            await self.chat((f"@{target_username} VIPِ موقتِ فعالی نداره." if lang == "fa"
                              else f"@{target_username} doesn't have an active temp VIP."))
            return
        task = self.temp_vip_tasks.pop(target_username, None)
        if task:
            task.cancel()
        self.temp_vip_expiry.pop(target_username, None)
        if target_username in self.config["vip_usernames"]:
            self.config["vip_usernames"].remove(target_username)
            self.save_config()
        await self.chat((f"⭐ VIPِ موقتِ @{target_username} زودتر گرفته شد." if lang == "fa"
                          else f"⭐ @{target_username}'s temp VIP was removed early."))

    async def cmd_summ(self, user: User, parts: list):
        """!summ @username -> اون کاربر رو کنارِ خودت میاره | !summ all -> همه رو کنارِ خودت جمع می‌کنه."""
        if user.username.lower() not in self.config["admin_usernames"]:
            await self.chat(self.get_message("no_permission"))
            return
        lang = self.config.get("language", "fa")
        if len(parts) != 2:
            await self.chat("⚠️ فرمت اشتباه! استفاده کن از: !summ @username یا !summ all" if lang == "fa"
                             else "⚠️ Wrong format! Use: !summ @username or !summ all")
            return

        position = self.user_positions.get(user.username.lower())
        if not position:
            await self.chat("موقعیت شما مشخص نیست!" if lang == "fa" else "Your position isn't known!")
            return

        if parts[1].lower() == "all":
            count = 0
            for uname, target_user in list(self.active_users.items()):
                if uname == user.username.lower():
                    continue
                try:
                    await self.highrise.teleport(user_id=target_user.id, dest=position)
                    count += 1
                except Exception as e:
                    logger.error(f"خطا در احضارِ {uname}: {e}")
            await self.chat((f"📣 {count} نفر کنارِ @{user.username} احضار شدن." if lang == "fa"
                              else f"📣 {count} people were summoned to @{user.username}."))
            return

        if not parts[1].startswith("@"):
            await self.chat("⚠️ فرمت اشتباه! استفاده کن از: !summ @username یا !summ all" if lang == "fa"
                             else "⚠️ Wrong format! Use: !summ @username or !summ all")
            return
        target_username = parts[1][1:].lower()
        target_user = self.active_users.get(target_username)
        if not target_user:
            await self.chat(self.get_message("user_not_found", username=target_username))
            return
        try:
            await self.highrise.teleport(user_id=target_user.id, dest=position)
            await self.chat((f"📣 @{target_username} کنارِ @{user.username} احضار شد." if lang == "fa"
                              else f"📣 @{target_username} was summoned to @{user.username}."))
        except Exception as e:
            await self.chat(self.get_message("teleport_error", error=str(e)))
            logger.error(f"خطا در احضارِ {target_username}: {e}")

    async def cmd_quiz(self, user: User, parts: list):
        """!quiz سوال | جواب -> یه مسابقه‌ی امتیازیِ ساده شروع می‌کنه؛ اولین کسی که تو چت
        دقیقاً همون جواب رو بنویسه (بدونِ ! جلوش) ۲۰ امتیاز می‌گیره."""
        if user.username.lower() not in self.config["admin_usernames"]:
            await self.chat(self.get_message("no_permission"))
            return
        lang = self.config.get("language", "fa")
        raw = " ".join(parts[1:])
        if "|" not in raw:
            await self.chat("⚠️ استفاده کن از: !quiz سوال | جواب" if lang == "fa"
                             else "⚠️ Use: !quiz question | answer")
            return
        if self.active_quiz:
            await self.chat("⚠️ یه مسابقه از قبل فعاله." if lang == "fa" else "⚠️ A quiz is already active.")
            return
        question, answer = raw.split("|", 1)
        question, answer = question.strip(), answer.strip()
        if not question or not answer:
            await self.chat("⚠️ استفاده کن از: !quiz سوال | جواب" if lang == "fa"
                             else "⚠️ Use: !quiz question | answer")
            return
        self.active_quiz = {"question": question, "answer": answer, "started_by": user.username}
        await self.chat((f"🎲 مسابقه: {question}\n(هر کی جواب رو بدونه، همینجا تو چت بنویسه!)" if lang == "fa"
                          else f"🎲 Quiz: {question}\n(Whoever knows it, just type it in chat!)"))

    async def cmd_top(self, user: User, parts: list):
        """!top -> جدولِ امتیازهای فعلیِ کاربرها (۵ نفرِ اول)."""
        lang = self.config.get("language", "fa")
        if not self.user_scores:
            await self.chat("🏆 هنوز هیچ امتیازی ثبت نشده." if lang == "fa" else "🏆 No scores yet.")
            return
        top5 = sorted(self.user_scores.items(), key=lambda kv: kv[1], reverse=True)[:5]
        medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
        lines = [f"{medals[i]} @{name}: {score}" for i, (name, score) in enumerate(top5)]
        text = ("🏆 جدولِ امتیازها:\n" if lang == "fa" else "🏆 Leaderboard:\n") + "\n".join(lines)
        await self.chat(text)

    async def cmd_visitors(self, user: User, parts: list):
        """!visitors -> تعدادِ بازدیدکنندگانِ یکتای امروز (از وقتی بات روشن بوده)."""
        lang = self.config.get("language", "fa")
        today = datetime.utcnow().date()
        if today != self.visitors_date:
            self.visitors_date = today
            self.visitors_today = set()
        count = len(self.visitors_today)
        await self.chat((f"📸 امروز {count} بازدیدکننده‌ی یکتا داشتیم (فقط از وقتی بات روشن بوده)." if lang == "fa"
                          else f"📸 {count} unique visitors today (only counted while the bot has been running)."))

    async def cmd_memories(self, user: User, parts: list):
        """!memories -> رکوردِ بیشترین جمعیتِ هم‌زمانِ روم (از وقتی بات دارهٔ اون رکورد رو نگه می‌داره)."""
        lang = self.config.get("language", "fa")
        peak = self.config.get("peak_population", {"count": 0, "at": None})
        if not peak.get("count"):
            await self.chat("📸 هنوز رکوردی ثبت نشده." if lang == "fa" else "📸 No record yet.")
            return
        at = peak.get("at")
        try:
            at_text = datetime.fromisoformat(at).strftime("%Y-%m-%d %H:%M UTC") if at else "؟"
        except Exception:
            at_text = at or "؟"
        await self.chat((f"📸 رکوردِ بیشترین جمعیتِ هم‌زمان: {peak['count']} نفر (در {at_text})" if lang == "fa"
                          else f"📸 Peak concurrent population: {peak['count']} people (at {at_text})"))

    async def cmd_countdown(self, user: User, parts: list):
        """!countdown [ثانیه] [پیام] -> شمارشِ معکوس تو چت، هر ثانیه یا هر چند ثانیه یه بار
        (برای شمارش‌های طولانی هر ۵ ثانیه، تا اسپم نشه)، بعدش پیامِ پایانی."""
        if user.username.lower() not in self.config["admin_usernames"]:
            await self.chat(self.get_message("no_permission"))
            return
        lang = self.config.get("language", "fa")
        if len(parts) < 2 or not parts[1].isdigit():
            await self.chat("⚠️ استفاده کن از: !countdown ثانیه [پیام]" if lang == "fa"
                             else "⚠️ Use: !countdown <seconds> [message]")
            return
        seconds = int(parts[1])
        final_message = " ".join(parts[2:]) or ("شروع!" if lang == "fa" else "Go!")
        if seconds <= 0 or seconds > 3600:
            await self.chat("⚠️ عدد باید بین ۱ تا ۳۶۰۰ ثانیه باشه." if lang == "fa" else "⚠️ Must be between 1 and 3600 seconds.")
            return

        async def countdown_loop():
            try:
                remaining = seconds
                step = 5 if seconds > 15 else 1
                while remaining > 0:
                    if remaining <= 3 or remaining % step == 0:
                        await self.chat(f"⏳ {remaining}...")
                    await sleep(min(step, remaining))
                    remaining -= min(step, remaining)
                await self.chat(f"🎉 {final_message}")
            except CancelledError:
                pass

        create_task(countdown_loop())
        await self.chat((f"⏳ شمارشِ معکوسِ {seconds} ثانیه‌ای شروع شد." if lang == "fa"
                          else f"⏳ {seconds}-second countdown started."))

    async def cmd_schedule(self, user: User, parts: list):
        """!schedule دقیقه پیام -> بعدِ اون مدت، یه‌بار همون پیام رو تو چت می‌فرسته (برخلافِ
        !loop که تکرارشونده‌ست، این فقط یه‌بار اجرا میشه)."""
        if user.username.lower() not in self.config["admin_usernames"]:
            await self.chat(self.get_message("no_permission"))
            return
        lang = self.config.get("language", "fa")
        if len(parts) < 3 or not parts[1].isdigit():
            await self.chat("⚠️ استفاده کن از: !schedule دقیقه پیام" if lang == "fa"
                             else "⚠️ Use: !schedule <minutes> <message>")
            return
        minutes = int(parts[1])
        message = " ".join(parts[2:])

        async def schedule_loop():
            try:
                await sleep(minutes * 60)
                await self.chat(f"📅 {message}")
            except CancelledError:
                pass

        create_task(schedule_loop())
        await self.chat((f"📅 پیام برای {minutes} دقیقه‌ی دیگه زمان‌بندی شد." if lang == "fa"
                          else f"📅 Message scheduled for {minutes} minutes from now."))

    async def cmd_stats(self, user: User, parts: list):
        """!stats -> یه خلاصه‌ی کلی: جمعیتِ الان، بازدیدکنندگانِ امروز، رکوردِ جمعیت، نفرِ اولِ جدول."""
        lang = self.config.get("language", "fa")
        today = datetime.utcnow().date()
        if today != self.visitors_date:
            self.visitors_date = today
            self.visitors_today = set()
        peak = self.config.get("peak_population", {"count": 0, "at": None})
        top_user = max(self.user_scores.items(), key=lambda kv: kv[1], default=None)
        top_text = f"@{top_user[0]} ({top_user[1]})" if top_user else "-"

        if lang == "fa":
            lines = [
                "📊 آمار کلی روم:",
                f"جمعیتِ الان: {len(self.active_users)}",
                f"بازدیدکنندگانِ امروز: {len(self.visitors_today)}",
                f"رکوردِ بیشترین جمعیتِ هم‌زمان: {peak.get('count', 0)}",
                f"نفرِ اولِ جدولِ امتیازها: {top_text}",
            ]
        else:
            lines = [
                "📊 Room stats:",
                f"Current population: {len(self.active_users)}",
                f"Visitors today: {len(self.visitors_today)}",
                f"Peak concurrent population: {peak.get('count', 0)}",
                f"Top scorer: {top_text}",
            ]
        await self.chat("\n".join(lines))

    async def cmd_down(self, user: User, parts: list):
        """!down -> تلپورتِ خودت به همون x/z فعلی ولی y=0 (سطحِ زمین)."""
        lang = self.config.get("language", "fa")
        position = self.user_positions.get(user.username.lower())
        if not position:
            await self.chat("موقعیت شما مشخص نیست!" if lang == "fa" else "Your position isn't known!")
            return
        try:
            dest = Position(x=position.x, y=0, z=position.z)
            await self.highrise.teleport(user_id=user.id, dest=dest)
        except Exception as e:
            await self.chat(self.get_message("teleport_error", error=str(e)))
            logger.error(f"خطا در !down برای {user.username}: {e}")

    async def cmd_move(self, user: User, parts: list):
        """!move <آیدی روم یا لینکِ کامل> -> خودِ بات رو کاملاً به یه روم دیگه منتقل می‌کنه.

        ⚠️ صادقانه، این یه تلپورتِ ساده نیست — SDKِ عمومیِ هایرایز راهی برای «سوییچ‌کردنِ»
        یه سشنِ زنده به رومِ دیگه نداره. برای همین این دستور کارِ زیر رو می‌کنه:
          ۱. متغیرِ محیطیِ ROOM_ID رو با آیدیِ جدید عوض می‌کنه
          ۲. کلِ پردازشِ پایتون رو با os.execve (جایگزینیِ کاملِ خودِ پردازش، نه اجرای یه
             پردازشِ جدیدِ جدا) دوباره از اول اجرا می‌کنه — یعنی همون PID می‌مونه، نیازی به
             هیچ ناظرِ بیرونی (systemd/پنل و...) نداره، خودش خودشو ری‌استارت می‌کنه
          ۳. بعدِ ری‌استارت، بات با همون API_TOKEN ولی تو رومِ جدید وصل میشه

        نیازمندی‌ها:
          • همون توکنِ API باید تو رومِ مقصد هم دسترسیِ کافی (مالک یا Designer) داشته باشه،
            وگرنه اتصال رد میشه
          • بعدِ !move، تنظیماتِ این بات (ادمین‌ها، ظاهر، رنک‌ها و...) از اول شروع میشه — چون
            فایلِ تنظیمات بر اساسِ ROOM_ID جداست؛ اگه قبلاً تو اون روم بوده، همون تنظیماتِ
            قبلیش رو برمی‌داره (فایلش هنوز رو دیسکه)
        """
        lang = self.config.get("language", "fa")
        if not self.is_host(user.username):
            await self.chat("فقط Host می‌تواند از این دستور استفاده کند!" if lang == "fa" else "Only a Host can use this command!")
            return
        if len(parts) < 2:
            await self.chat("⚠️ استفاده کن از: !move آیدیِ‌روم یا لینکِ‌کامل" if lang == "fa"
                             else "⚠️ Use: !move <room ID or full link>")
            return

        new_room_id = extract_room_id_from_text(" ".join(parts[1:]))
        if not new_room_id:
            await self.chat("⚠️ آیدی/لینکِ رومِ معتبر نفرستادی." if lang == "fa" else "⚠️ That's not a valid room ID/link.")
            return

        await self.chat((f"🚚 در حالِ جابه‌جاییِ بات به رومِ جدید ({new_room_id})... چند ثانیه دیگه اینجا خاموش میشه و اونجا روشن میشه." if lang == "fa"
                          else f"🚚 Moving the bot to a new room ({new_room_id})... it'll go offline here and come back there in a few seconds."))
        logger.info(f"{user.username} با !move درخواستِ جابه‌جاییِ بات به روم {new_room_id} رو داد.")
        await sleep(1.0)

        new_env = os.environ.copy()
        new_env["ROOM_ID"] = new_room_id
        try:
            os.execve(sys.executable, [sys.executable] + sys.argv, new_env)
        except Exception as e:
            logger.error(f"خطا در os.execve برای !move: {e}")
            await self.chat((f"❌ جابه‌جایی شکست خورد: {e} — خودت دستی ROOM_ID رو عوض کن و بات رو ری‌استارت کن." if lang == "fa"
                              else f"❌ Move failed: {e} — set ROOM_ID manually and restart the bot yourself."))

    async def cmd_addadmin(self, user: User, parts: list):
        lang = self.config.get("language", "fa")
        if not self.is_host(user.username):
            await self.chat("فقط Host می‌تواند از این دستور استفاده کند!" if lang == "fa" else "Only a Host can use this command!")
            logger.info(f"کاربر {user.username} سعی کرد !addadmin را اجرا کند اما دسترسی ندارد.")
            return

        parts = [p.lower() for p in parts]
        if len(parts) != 2 or not parts[1].startswith("@"):
            await self.chat(self.get_message("invalid_format", format="!addadmin @username"))
            logger.info(f"فرمت نادرست برای دستور !addadmin توسط {user.username} وارد شد.")
            return

        target_username = parts[1][1:].lower()
        if target_username in self.config["admin_usernames"]:
            await self.chat((f"کاربر @{target_username} قبلاً ادمین است!" if lang == "fa"
                              else f"@{target_username} is already an admin!"))
            logger.info(f"کاربر {target_username} توسط {user.username} برای افزودن به ادمین‌ها درخواست شد، اما قبلاً ادمین است.")
            return

        try:
            self.config["admin_usernames"].append(target_username)
            self.save_config()
            await self.chat((f"کاربر @{target_username} با موفقیت به ادمین‌ها اضافه شد!" if lang == "fa"
                              else f"@{target_username} was successfully added as an admin!"))
            logger.info(f"کاربر {target_username} توسط {user.username} به ادمین‌ها اضافه شد.")
        except Exception as e:
            await self.chat((f"خطا در افزودن ادمین @{target_username}: {str(e)}" if lang == "fa"
                              else f"Error adding admin @{target_username}: {str(e)}"))
            logger.error(f"خطا در cmd_addadmin برای {target_username}: {str(e)}")

    async def cmd_removeadmin(self, user: User, parts: list):
        lang = self.config.get("language", "fa")
        if not self.is_host(user.username):
            await self.chat("فقط Host می‌تواند از این دستور استفاده کند!" if lang == "fa" else "Only a Host can use this command!")
            logger.info(f"کاربر {user.username} سعی کرد !removeadmin را اجرا کند اما دسترسی ندارد.")
            return

        parts = [p.lower() for p in parts]
        if len(parts) != 2 or not parts[1].startswith("@"):
            await self.chat(self.get_message("invalid_format", format="!removeadmin @username"))
            logger.info(f"فرمت نادرست برای دستور !removeadmin توسط {user.username} وارد شد.")
            return

        target_username = parts[1][1:].lower()
        if target_username not in self.config["admin_usernames"]:
            await self.chat((f"کاربر @{target_username} در لیست ادمین‌ها نیست!" if lang == "fa"
                              else f"@{target_username} isn't in the admin list!"))
            logger.info(f"کاربر {target_username} توسط {user.username} برای حذف از ادمین‌ها درخواست شد، اما در لیست نیست.")
            return

        if self.is_host(target_username):
            await self.chat((f"❌ @{target_username} رتبه Host دارد و نمی‌توان او را از ادمین‌ها حذف کرد!" if lang == "fa"
                              else f"❌ @{target_username} has Host rank and can't be removed from admins!"))
            logger.info(f"تلاش برای حذف Host {target_username} از ادمین‌ها توسط {user.username} رد شد.")
            return

        if target_username == "bad_qoq":
            await self.chat("نمی‌توانید bad_qoq را از ادمین‌ها حذف کنید!" if lang == "fa" else "You can't remove bad_qoq from admins!")
            logger.info(f"تلاش برای حذف bad_qoq از ادمین‌ها توسط {user.username} رد شد.")
            return

        try:
            self.config["admin_usernames"].remove(target_username)
            self.save_config()
            await self.chat((f"کاربر @{target_username} با موفقیت از ادمین‌ها حذف شد!" if lang == "fa"
                              else f"@{target_username} was successfully removed from admins!"))
            logger.info(f"کاربر {target_username} توسط {user.username} از ادمین‌ها حذف شد.")
        except Exception as e:
            await self.chat((f"خطا در حذف ادمین @{target_username}: {str(e)}" if lang == "fa"
                              else f"Error removing admin @{target_username}: {str(e)}"))
            logger.error(f"خطا در cmd_removeadmin برای {target_username}: {str(e)}")

    async def cmd_addhost(self, user: User, parts: list):
        """👑 هر کسی که خودش Host باشه می‌تونه رتبه Host به بقیه هم بده (نه فقط مالک اصلی)."""
        lang = self.config.get("language", "fa")
        if not self.is_host(user.username):
            await self.chat("❌ دسترسی غیرمجاز! فقط Host می‌تواند از این دستور استفاده کند." if lang == "fa" else "❌ Unauthorized! Only a Host can use this command.")
            logger.info(f"کاربر {user.username} سعی کرد !addhost را اجرا کند اما دسترسی ندارد.")
            return

        parts = [p.lower() for p in parts]
        if len(parts) != 2 or not parts[1].startswith("@"):
            await self.chat(self.get_message("invalid_format", format="!addhost @username"))
            logger.info(f"فرمت نادرست برای دستور !addhost توسط {user.username} وارد شد.")
            return

        target_username = parts[1][1:].lower()
        if target_username in self.config["host_usernames"]:
            await self.chat(f"کاربر @{target_username} از قبل Host است!" if lang == "fa" else f"@{target_username} is already a Host!")
            return

        try:
            self.config["host_usernames"].append(target_username)
            if target_username not in self.config["admin_usernames"]:
                self.config["admin_usernames"].append(target_username)
            self.save_config()
            await self.chat((f"👑 کاربر @{target_username} با موفقیت Host شد!" if lang == "fa"
                              else f"👑 @{target_username} is now a Host!"))
            logger.info(f"کاربر {target_username} توسط {user.username} به Host تبدیل شد.")
        except Exception as e:
            await self.chat((f"خطا در افزودن Host @{target_username}: {str(e)}" if lang == "fa"
                              else f"Error adding Host @{target_username}: {str(e)}"))
            logger.error(f"خطا در cmd_addhost برای {target_username}: {str(e)}")

    async def cmd_removehost(self, user: User, parts: list):
        """👑 هر کسی که خودش Host باشه می‌تونه رتبه Host رو از بقیه بگیره (نه فقط مالک اصلی)."""
        lang = self.config.get("language", "fa")
        if not self.is_host(user.username):
            await self.chat("❌ دسترسی غیرمجاز! فقط Host می‌تواند از این دستور استفاده کند." if lang == "fa" else "❌ Unauthorized! Only a Host can use this command.")
            logger.info(f"کاربر {user.username} سعی کرد !removehost را اجرا کند اما دسترسی ندارد.")
            return

        parts = [p.lower() for p in parts]
        if len(parts) != 2 or not parts[1].startswith("@"):
            await self.chat(self.get_message("invalid_format", format="!removehost @username"))
            logger.info(f"فرمت نادرست برای دستور !removehost توسط {user.username} وارد شد.")
            return

        target_username = parts[1][1:].lower()
        if target_username not in self.config["host_usernames"]:
            await self.chat(f"کاربر @{target_username} در لیست Host‌ها نیست!" if lang == "fa" else f"@{target_username} isn't in the Host list!")
            return

        if len(self.config["host_usernames"]) <= 1:
            await self.chat("❌ نمی‌توان آخرین Host را حذف کرد!" if lang == "fa" else "❌ Can't remove the last Host!")
            logger.info(f"تلاش برای حذف آخرین Host ({target_username}) توسط {user.username} رد شد.")
            return

        try:
            self.config["host_usernames"].remove(target_username)
            self.save_config()
            await self.chat((f"کاربر @{target_username} از رتبه Host حذف شد." if lang == "fa"
                              else f"@{target_username} was removed from Host rank."))
            logger.info(f"کاربر {target_username} توسط {user.username} از Host حذف شد.")
        except Exception as e:
            await self.chat((f"خطا در حذف Host @{target_username}: {str(e)}" if lang == "fa"
                              else f"Error removing Host @{target_username}: {str(e)}"))
            logger.error(f"خطا در cmd_removehost برای {target_username}: {str(e)}")

    async def cmd_listadd(self, user: User, parts: list):
        """!listadd -> برای هر رتبه‌ای که حداقل یه عضو داره، یه بلوکِ جدا نشون می‌ده:
        اسمِ رتبه، بعد هر یوزرنیم تو خطِ خودش (@username)، بعد یه خطِ جداکننده.
        رتبه‌های خالی اصلاً نشون داده نمیشن."""
        lang = self.config.get("language", "fa")
        if user.username.lower() not in self.config["admin_usernames"]:
            await self.chat(self.get_message("no_permission"))
            logger.info(f"کاربر {user.username} دسترسی لازم برای اجرای !listadd را ندارد.")
            return

        try:
            total = 0
            blocks = []
            for r in RANK_DEFINITIONS:
                members = self.config.get(r["config_key"], [])
                if not members:
                    continue
                total += len(members)
                name = r.get(lang, r["en"])
                block_lines = [f"{r['emoji']} {name}:"]
                block_lines.extend(f"@{m}" for m in members)
                block_lines.append("__________")
                blocks.append("\n".join(block_lines))

            if total == 0:
                await self.chat(self.get_message("listadd_empty"))
                logger.info(f"لیست رتبه‌ها خالی است. درخواست توسط {user.username}.")
                return

            text = "\n".join(blocks)
            for chunk in [text[i:i + 300] for i in range(0, len(text), 300)]:
                await self.chat(chunk)
            logger.info(f"لیست رتبه‌ها توسط {user.username} درخواست شد.")
        except Exception as e:
            await self.chat({
                "fa": f"خطا در نمایش لیست رتبه‌ها: {str(e)}",
                "en": f"Error showing rank list: {str(e)}",
                "ar": f"خطأ في عرض قائمة الرتب: {str(e)}",
            }.get(lang))
            logger.error(f"خطا در cmd_listadd: {str(e)}")

    async def cmd_give(self, user: User, parts: list):
        """!give [رتبه] @username -> دادنِ یکی از رتبه‌های ثابتِ بات (Owner/Manager/Admin/Mod/VIP/Host).
        !give -[رتبه] @username (یا !give - [رتبه] @username) -> گرفتنِ همون رتبه.
        برای رتبه‌های دلخواه/سفارشی همچنان از !MR / !GR / !DR استفاده کن."""
        lang = self.config.get("language", "fa")
        granter = user.username.lower()

        usage = ("⚠️ فرمت اشتباه! استفاده کن از:\n"
                  "!give [رتبه] @username -> دادنِ رتبه\n"
                  "!give -[رتبه] @username -> گرفتنِ رتبه\n"
                  "رتبه‌های معتبر: " + " / ".join(r["en"] for r in RANK_DEFINITIONS)
                  if lang == "fa" else
                  "⚠️ Wrong format! Use:\n"
                  "!give [rank] @username -> give the rank\n"
                  "!give -[rank] @username -> take the rank\n"
                  "Valid ranks: " + " / ".join(r["en"] for r in RANK_DEFINITIONS))

        args = parts[1:]
        at_args = [p for p in args if p.startswith("@")]
        other_args = [p for p in args if not p.startswith("@")]
        if not at_args or not other_args:
            await self.chat(usage)
            return

        target_username = at_args[-1][1:].lower()
        rank_spec = " ".join(other_args).strip()
        remove = rank_spec.startswith("-")
        if remove:
            rank_spec = rank_spec[1:].strip()

        rank = self.resolve_rank(rank_spec)
        if rank is None:
            await self.chat(usage)
            return

        # 👑 برای دادن/گرفتنِ هر رتبه (رتبه‌ی Host هم شاملش میشه) باید حداقل سطحِ لازم رو داشته باشی؛
        # طبقِ RANK_GRANT_MIN_LEVEL، برای Host خودت باید Host باشی (یعنی هر Host می‌تونه به بقیه هم Host بده).
        min_level = RANK_GRANT_MIN_LEVEL.get(rank["key"], 70)
        if self.get_rank_level(granter) < min_level:
            needed = next((rr["en"] for rr in RANK_DEFINITIONS if rr["level"] == min_level), "?")
            await self.chat((f"❌ برای مدیریتِ رتبه‌ی {rank['fa']} حداقل باید {needed} باشی!" if lang == "fa"
                              else f"❌ You need to be at least {needed} to manage the {rank['en']} rank!"))
            logger.info(f"کاربر {user.username} سعی کرد رتبه {rank['key']} را با !give تغییر دهد اما سطح کافی ندارد.")
            return

        members = self.config.setdefault(rank["config_key"], [])

        if remove:
            if target_username not in members:
                await self.chat((f"⚠️ @{target_username} این رتبه رو نداره!" if lang == "fa"
                                  else f"⚠️ @{target_username} doesn't have this rank!"))
                return
            if rank["key"] == "host" and len(members) <= 1:
                await self.chat("❌ نمی‌توان آخرین Host را حذف کرد!" if lang == "fa" else "❌ Can't remove the last Host!")
                return
            try:
                members.remove(target_username)
                self.save_config()
                await self.chat((f"➖ رتبه‌ی {rank['fa']} از @{target_username} گرفته شد." if lang == "fa"
                                  else f"➖ {rank['en']} rank was taken from @{target_username}."))
                logger.info(f"کاربر {target_username} توسط {user.username} از رتبه {rank['key']} حذف شد.")
            except Exception as e:
                await self.chat((f"خطا در گرفتنِ رتبه: {str(e)}" if lang == "fa" else f"Error removing rank: {str(e)}"))
                logger.error(f"خطا در cmd_give (remove) برای {target_username}: {str(e)}")
        else:
            if target_username in members:
                await self.chat((f"⚠️ @{target_username} از قبل این رتبه رو داره!" if lang == "fa"
                                  else f"⚠️ @{target_username} already has this rank!"))
                return
            try:
                members.append(target_username)
                if rank["key"] in RANKS_THAT_IMPLY_ADMIN and target_username not in self.config["admin_usernames"]:
                    self.config["admin_usernames"].append(target_username)
                self.save_config()
                await self.chat((f"{rank['emoji']} رتبه‌ی {rank['fa']} به @{target_username} داده شد!" if lang == "fa"
                                  else f"{rank['emoji']} {rank['en']} rank was given to @{target_username}!"))
                logger.info(f"کاربر {target_username} توسط {user.username} رتبه {rank['key']} گرفت.")
            except Exception as e:
                await self.chat((f"خطا در دادنِ رتبه: {str(e)}" if lang == "fa" else f"Error giving rank: {str(e)}"))
                logger.error(f"خطا در cmd_give (add) برای {target_username}: {str(e)}")

    async def cmd_freeze(self, user: User, parts: list):
        if not self.can_moderate(user.username):
            await self.chat(self.get_message("no_permission"))
            logger.info(f"کاربر {user.username} دسترسی لازم برای اجرای !freeze را ندارد.")
            return
        lang = self.config.get("language", "fa")

        parts = [p.lower() for p in parts]
        if len(parts) != 2 or not parts[1].startswith("@"):
            await self.chat(self.get_message("invalid_format", format="!freeze @username"))
            logger.info(f"فرمت نادرست برای دستور !freeze توسط {user.username} وارد شد.")
            return

        target_username = parts[1][1:].lower()
        target_user = self.active_users.get(target_username)
        if not target_user:
            await self.chat(self.get_message("user_not_found", username=target_username))
            logger.info(f"کاربر هدف {target_username} توسط {user.username} پیدا نشد.")
            return

        if target_username in self.frozen_users:
            await self.chat((f"کاربر @{target_username} قبلاً فریز شده است." if lang == "fa"
                              else f"@{target_username} is already frozen."))
            logger.info(f"کاربر {target_username} توسط {user.username} برای فریز درخواست شد، اما قبلاً فریز شده است.")
            return

        position = self.user_positions.get(target_username)
        if not position:
            await self.chat((f"موقعیت @{target_username} در دسترس نیست." if lang == "fa"
                              else f"@{target_username}'s position isn't available."))
            logger.info(f"موقعیت {target_username} برای فریز توسط {user.username} در دسترس نیست.")
            return

        async def freeze_loop():
            try:
                while target_username in self.frozen_users:
                    if target_username not in self.active_users:
                        self.frozen_users.pop(target_username, None)
                        logger.info(f"کاربر {target_username} آفلاین شد، فریز لغو شد.")
                        break
                    await self.highrise.teleport(user_id=target_user.id, dest=position)
                    await sleep(1.0)
            except CancelledError:
                logger.info(f"وظیفه فریز برای {target_username} لغو شد.")
            except Exception as e:
                logger.error(f"خطا در حلقه فریز برای {target_username}: {e}")

        task = create_task(freeze_loop())
        self.frozen_users[target_username] = task
        self._log_mod_action(user.username, "freeze", target_username)
        await self.chat(self.get_message("freeze_success", username=target_username))
        logger.info(f"کاربر {target_username} توسط {user.username} فریز شد.")

    async def cmd_unfreeze(self, user: User, parts: list):
        if not self.can_moderate(user.username):
            await self.chat(self.get_message("no_permission"))
            logger.info(f"کاربر {user.username} دسترسی لازم برای اجرای !unfreeze را ندارد.")
            return
        lang = self.config.get("language", "fa")

        parts = [p.lower() for p in parts]
        if len(parts) != 2 or not parts[1].startswith("@"):
            await self.chat(self.get_message("invalid_format", format="!unfreeze @username"))
            logger.info(f"فرمت نادرست برای دستور !unfreeze توسط {user.username} وارد شد.")
            return

        target_username = parts[1][1:].lower()
        if target_username not in self.frozen_users:
            await self.chat(self.get_message("unfreeze_not_frozen", username=target_username))
            logger.info(f"کاربر {target_username} توسط {user.username} برای آنفریز درخواست شد، اما فریز نشده است.")
            return

        try:
            task = self.frozen_users.pop(target_username)
            task.cancel()
            await task
            self._log_mod_action(user.username, "unfreeze", target_username)
            await self.chat(self.get_message("unfreeze_success", username=target_username))
            logger.info(f"کاربر {target_username} توسط {user.username} از حالت فریز آزاد شد.")
        except Exception as e:
            await self.chat((f"خطا در آزاد کردن @{target_username}: {str(e)}" if lang == "fa"
                              else f"Error unfreezing @{target_username}: {str(e)}"))
            logger.error(f"خطا در cmd_unfreeze برای {target_username}: {str(e)}")

    def _log_mod_action(self, actor: str, action: str, target: str = "", extra: str = ""):
        """یه خط به !modlog اضافه می‌کنه — فقط حافظه‌ست (با ری‌استارت بات پاک میشه)، برای
        لاگِ دائمی از لاگ‌فایلِ خودِ سرور (logger.info) استفاده کن."""
        self.mod_log.append((datetime.utcnow(), actor, action, target, extra))

    async def cmd_warn(self, user: User, parts: list):
        """!warn @username [دلیل] -> یه اخطار ثبت می‌کنه؛ با رسیدن به warn_limit (پیش‌فرض ۵) خودکار کیک میشه."""
        if not self.can_moderate(user.username):
            await self.chat(self.get_message("no_permission"))
            return
        lang = self.config.get("language", "fa")
        if len(parts) < 2 or not parts[1].startswith("@"):
            await self.chat("⚠️ فرمت اشتباه! استفاده کن از: !warn @username [دلیل]" if lang == "fa"
                             else "⚠️ Wrong format! Use: !warn @username [reason]")
            return

        target_username = parts[1][1:].lower()
        target_user = self.active_users.get(target_username)
        if not target_user:
            await self.chat(self.get_message("user_not_found", username=target_username))
            return

        reason = " ".join(parts[2:]).strip() or ("بدون دلیل" if lang == "fa" else "no reason given")
        self.warn_counts[target_username] = self.warn_counts.get(target_username, 0) + 1
        self.warn_reasons.setdefault(target_username, []).append(reason)
        self.warn_reasons[target_username] = self.warn_reasons[target_username][-5:]
        count = self.warn_counts[target_username]
        limit = self.config.get("warn_limit", 5)
        self._log_mod_action(user.username, "warn", target_username, f"{reason} ({count}/{limit})")

        await self.chat((f"⚠️ @{target_username} اخطار گرفت ({count}/{limit}) — دلیل: {reason}" if lang == "fa"
                          else f"⚠️ @{target_username} was warned ({count}/{limit}) — reason: {reason}"))
        logger.info(f"{user.username} به {target_username} اخطار داد ({count}/{limit}): {reason}")

        if count >= limit:
            try:
                await self.highrise.moderate_room(target_user.id, "kick")
                self.warn_counts[target_username] = 0
                self.warn_reasons.pop(target_username, None)
                self._log_mod_action(user.username, "auto-kick (warn limit)", target_username)
                await self.chat((f"👢 @{target_username} به‌خاطرِ رسیدن به {limit} اخطار خودکار کیک شد." if lang == "fa"
                                  else f"👢 @{target_username} was auto-kicked for reaching {limit} warnings."))
            except Exception as e:
                logger.error(f"خطا در کیکِ خودکارِ {target_username} بعد از اخطارها: {e}")

    async def cmd_warns(self, user: User, parts: list):
        """!warns @username -> نمایش تعداد و آخرین دلیل‌های اخطارهای یه کاربر."""
        if not self.can_moderate(user.username):
            await self.chat(self.get_message("no_permission"))
            return
        lang = self.config.get("language", "fa")
        if len(parts) != 2 or not parts[1].startswith("@"):
            await self.chat("⚠️ فرمت اشتباه! استفاده کن از: !warns @username" if lang == "fa"
                             else "⚠️ Wrong format! Use: !warns @username")
            return
        target_username = parts[1][1:].lower()
        count = self.warn_counts.get(target_username, 0)
        limit = self.config.get("warn_limit", 5)
        reasons = self.warn_reasons.get(target_username, [])
        if count == 0:
            await self.chat((f"✅ @{target_username} هیچ اخطاری نداره." if lang == "fa"
                              else f"✅ @{target_username} has no warnings."))
            return
        reasons_text = " | ".join(reasons) if reasons else "-"
        await self.chat((f"⚠️ @{target_username}: {count}/{limit} اخطار — آخرین دلیل‌ها: {reasons_text}" if lang == "fa"
                          else f"⚠️ @{target_username}: {count}/{limit} warnings — recent reasons: {reasons_text}"))

    async def cmd_clearwarn(self, user: User, parts: list):
        """!clearwarn @username -> پاک‌کردنِ کاملِ اخطارهای یه کاربر."""
        if not self.can_moderate(user.username):
            await self.chat(self.get_message("no_permission"))
            return
        lang = self.config.get("language", "fa")
        if len(parts) != 2 or not parts[1].startswith("@"):
            await self.chat("⚠️ فرمت اشتباه! استفاده کن از: !clearwarn @username" if lang == "fa"
                             else "⚠️ Wrong format! Use: !clearwarn @username")
            return
        target_username = parts[1][1:].lower()
        self.warn_counts.pop(target_username, None)
        self.warn_reasons.pop(target_username, None)
        self._log_mod_action(user.username, "clearwarn", target_username)
        await self.chat((f"🧹 اخطارهای @{target_username} پاک شد." if lang == "fa"
                          else f"🧹 @{target_username}'s warnings were cleared."))

    async def cmd_jail(self, user: User, parts: list):
        """!jail @username [دقیقه] -> کاربر رو مدام تلپورت می‌کنه به مکانِ «jail» (با !addtele jail ست کن).
        بدونِ دقیقه: تا !unjail دستی، تو زندان می‌مونه."""
        if not self.can_moderate(user.username):
            await self.chat(self.get_message("no_permission"))
            return
        lang = self.config.get("language", "fa")
        if len(parts) < 2 or not parts[1].startswith("@"):
            await self.chat("⚠️ فرمت اشتباه! استفاده کن از: !jail @username [دقیقه]" if lang == "fa"
                             else "⚠️ Wrong format! Use: !jail @username [minutes]")
            return

        jail_loc = self.config.get("teleport_locations", {}).get("jail")
        if not jail_loc:
            await self.chat(("⚠️ اول باید مکانِ زندان رو تنظیم کنی — برو همون‌جا وایسا و بزن: !addtele jail" if lang == "fa"
                              else "⚠️ You need to set the jail spot first — stand there and run: !addtele jail"))
            return

        target_username = parts[1][1:].lower()
        target_user = self.active_users.get(target_username)
        if not target_user:
            await self.chat(self.get_message("user_not_found", username=target_username))
            return
        if target_username in self.jailed_users:
            await self.chat((f"@{target_username} از قبل تو زندانه." if lang == "fa" else f"@{target_username} is already jailed."))
            return

        minutes = None
        if len(parts) >= 3:
            try:
                minutes = int(parts[2])
            except ValueError:
                await self.chat("⚠️ دقیقه باید عدد باشه." if lang == "fa" else "⚠️ Minutes must be a number.")
                return

        dest = Position(x=jail_loc["x"], y=jail_loc["y"], z=jail_loc["z"])

        async def jail_loop():
            try:
                elapsed = 0
                while target_username in self.jailed_users:
                    if target_username not in self.active_users:
                        self.jailed_users.pop(target_username, None)
                        break
                    await self.highrise.teleport(user_id=target_user.id, dest=dest)
                    await sleep(1.0)
                    elapsed += 1
                    if minutes is not None and elapsed >= minutes * 60:
                        self.jailed_users.pop(target_username, None)
                        await self.chat((f"🔓 @{target_username} از زندان آزاد شد (اتمامِ زمان)." if lang == "fa"
                                          else f"🔓 @{target_username} was released from jail (time's up)."))
                        break
            except CancelledError:
                pass
            except Exception as e:
                logger.error(f"خطا در حلقه‌ی زندان برای {target_username}: {e}")

        task = create_task(jail_loop())
        self.jailed_users[target_username] = task
        self._log_mod_action(user.username, "jail", target_username, f"{minutes} min" if minutes else "manual")
        time_text = f"{minutes} دقیقه" if minutes else "تا !unjail دستی"
        time_text_en = f"{minutes} minutes" if minutes else "until manually released"
        await self.chat((f"🔒 @{target_username} تبعید شد به زندان ({time_text})." if lang == "fa"
                          else f"🔒 @{target_username} was sent to jail ({time_text_en})."))

    async def cmd_unjail(self, user: User, parts: list):
        if not self.can_moderate(user.username):
            await self.chat(self.get_message("no_permission"))
            return
        lang = self.config.get("language", "fa")
        if len(parts) != 2 or not parts[1].startswith("@"):
            await self.chat("⚠️ فرمت اشتباه! استفاده کن از: !unjail @username" if lang == "fa"
                             else "⚠️ Wrong format! Use: !unjail @username")
            return
        target_username = parts[1][1:].lower()
        task = self.jailed_users.pop(target_username, None)
        if not task:
            await self.chat((f"@{target_username} تو زندان نیست." if lang == "fa" else f"@{target_username} isn't jailed."))
            return
        task.cancel()
        self._log_mod_action(user.username, "unjail", target_username)
        await self.chat((f"🔓 @{target_username} از زندان آزاد شد." if lang == "fa" else f"🔓 @{target_username} was released from jail."))

    async def cmd_mod_list(self, user: User, parts: list):
        """!mod-list -> فهرستِ هاست‌ها و ادمین‌های بات."""
        lang = self.config.get("language", "fa")
        hosts = self.config.get("host_usernames", [])
        admins = [a for a in self.config.get("admin_usernames", []) if a not in hosts]
        hosts_text = ", ".join(f"@{h}" for h in hosts) or "-"
        admins_text = ", ".join(f"@{a}" for a in admins) or "-"
        await self.chat((f"👑 هاست‌ها: {hosts_text}\n🛡 ادمین‌ها: {admins_text}" if lang == "fa"
                          else f"👑 Hosts: {hosts_text}\n🛡 Admins: {admins_text}"))

    async def cmd_muted_list(self, user: User, parts: list):
        """!muted -> فهرستِ کاربرهایی که این نشستِ بات میوت شدن."""
        lang = self.config.get("language", "fa")
        if not self.muted_users:
            await self.chat("🔇 الان هیچ‌کس میوت نیست." if lang == "fa" else "🔇 No one is currently muted.")
            return
        # ⚠️ این عددها همون مدتِ اولیه‌ای هستن که با !mute ست شده، نه زمانِ باقی‌مونده‌ی واقعی —
        # چون خودِ بات تایمرِ دقیق برای پایانِ میوت نگه نمی‌داره (SDK هایرایز خودش هندل می‌کنه).
        lines = [f"@{u} ({m} دقیقه)" for u, m in self.muted_users.items()]
        await self.chat(("🔇 میوت‌شده‌ها: " + ", ".join(lines)) if lang == "fa"
                         else ("🔇 Muted: " + ", ".join(lines)))

    async def cmd_modlog(self, user: User, parts: list):
        """!modlog -> ۱۰ اقدامِ نظارتیِ آخر (بن/کیک/میوت/زندان/اخطار...) از همین نشستِ بات."""
        if not self.can_moderate(user.username):
            await self.chat(self.get_message("no_permission"))
            return
        lang = self.config.get("language", "fa")
        if not self.mod_log:
            await self.chat("📋 هنوز هیچ اقدامی ثبت نشده." if lang == "fa" else "📋 No actions logged yet.")
            return
        lines = []
        for ts, actor, action, target, extra in list(self.mod_log)[-10:]:
            time_str = ts.strftime("%H:%M")
            piece = f"[{time_str}] {actor} → {action}"
            if target:
                piece += f" @{target}"
            if extra:
                piece += f" ({extra})"
            lines.append(piece)
        await self.chat(("📋 آخرین اقدامات نظارتی:\n" + "\n".join(lines)) if lang == "fa"
                         else ("📋 Recent moderation actions:\n" + "\n".join(lines)))

    async def cmd_security_toggle(self, user: User, parts: list):
        """!security on/off -> آنتی‌اسپمِ خودکار (۵+ پیام تو ۸ ثانیه: بارِ اول اخطار، بارِ بعد میوت)."""
        if not self.can_moderate(user.username):
            await self.chat(self.get_message("no_permission"))
            return
        lang = self.config.get("language", "fa")
        if len(parts) != 2 or parts[1].lower() not in ("on", "off"):
            await self.chat("⚠️ استفاده کن از: !security on یا !security off" if lang == "fa"
                             else "⚠️ Use: !security on or !security off")
            return
        enabled = parts[1].lower() == "on"
        self.config["security_enabled"] = enabled
        self.save_config()
        await self.chat((f"🛡 آنتی‌اسپم {'روشن' if enabled else 'خاموش'} شد." if lang == "fa"
                          else f"🛡 Anti-spam turned {'on' if enabled else 'off'}."))

    async def cmd_raidguard_toggle(self, user: User, parts: list):
        """!raidguard on/off -> ضدِ تبلیغِ لینک/دعوتِ رومِ دیگه (بارِ اول اخطار، بارِ بعد میوت)."""
        if not self.can_moderate(user.username):
            await self.chat(self.get_message("no_permission"))
            return
        lang = self.config.get("language", "fa")
        if len(parts) != 2 or parts[1].lower() not in ("on", "off"):
            await self.chat("⚠️ استفاده کن از: !raidguard on یا !raidguard off" if lang == "fa"
                             else "⚠️ Use: !raidguard on or !raidguard off")
            return
        enabled = parts[1].lower() == "on"
        self.config["raidguard_enabled"] = enabled
        self.save_config()
        await self.chat((f"🚧 محافظِ ضدِ تبلیغ {'روشن' if enabled else 'خاموش'} شد." if lang == "fa"
                          else f"🚧 Raid guard turned {'on' if enabled else 'off'}."))

    async def cmd_report(self, user: User, parts: list):
        """!report @username [دلیل] -> گزارشِ یه کاربر به همه‌ی ادمین‌های آنلاینِ روم (تو چت)."""
        lang = self.config.get("language", "fa")
        if len(parts) < 2 or not parts[1].startswith("@"):
            await self.chat("⚠️ فرمت اشتباه! استفاده کن از: !report @username [دلیل]" if lang == "fa"
                             else "⚠️ Wrong format! Use: !report @username [reason]")
            return
        target_username = parts[1][1:].lower()
        reason = " ".join(parts[2:]).strip() or ("بدون دلیل" if lang == "fa" else "no reason given")
        self._log_mod_action(user.username, "report", target_username, reason)

        online_admins = [a for a in self.config.get("admin_usernames", []) if a in self.active_users]
        mention = " ".join(f"@{a}" for a in online_admins)
        await self.chat((f"🚨 گزارش از {user.username} علیهِ @{target_username}: {reason} {mention}".strip() if lang == "fa"
                          else f"🚨 Report from {user.username} against @{target_username}: {reason} {mention}".strip()))
        logger.info(f"گزارش: {user.username} از {target_username} گزارش کرد — {reason}")

    async def _check_security_and_raidguard(self, user: User, msg: str) -> None:
        """تو on_chat، قبل از هر پردازشِ دیگه‌ای صدا زده میشه. ادمین/هاست معافن.
        دفعه‌ی اول = فقط اخطارِ متنی (بدون افزایشِ !warn count)، دفعه‌ی بعد = میوتِ خودکار."""
        username = user.username.lower()
        if username in self.config.get("admin_usernames", []):
            return
        lang = self.config.get("language", "fa")

        # 🛡 آنتی‌اسپم: بیش از ۵ پیام تو ۸ ثانیه
        if self.config.get("security_enabled", False):
            now = datetime.utcnow()
            window = self.spam_msg_times.setdefault(username, deque())
            window.append(now)
            while window and (now - window[0]).total_seconds() > 8:
                window.popleft()
            if len(window) > 5:
                window.clear()
                if username not in self.spam_warned_once:
                    self.spam_warned_once.add(username)
                    self._log_mod_action("security", "spam-warn", username)
                    await self.chat((f"⚠️ @{user.username} آروم‌تر پیام بده — دفعه‌ی بعد میوت میشی." if lang == "fa"
                                      else f"⚠️ @{user.username} slow down — you'll be muted next time."))
                else:
                    try:
                        await self.highrise.moderate_room(user.id, "mute", 5 * 60)
                        self.muted_users[username] = 5
                        self._log_mod_action("security", "auto-mute (spam)", username)
                        await self.chat((f"🔇 @{user.username} به‌خاطرِ اسپم ۵ دقیقه میوت شد." if lang == "fa"
                                          else f"🔇 @{user.username} was muted for 5 minutes for spamming."))
                    except Exception as e:
                        logger.error(f"خطا در میوتِ خودکارِ اسپم برای {username}: {e}")
                return  # از چک راهنمای تبلیغ صرف‌نظر کن، همین یه اخطار/میوت کافیه

        # 🚧 ضدِ تبلیغِ رومِ دیگه
        if self.config.get("raidguard_enabled", False):
            msg_lower = msg.lower()
            raid_signals = ("highrise.game/room/", "high.rs/room/", "بریم روم من", "بیا روم من", "come to my room")
            if any(sig in msg_lower for sig in raid_signals):
                if username not in self.raid_warned_once:
                    self.raid_warned_once.add(username)
                    self._log_mod_action("raidguard", "raid-warn", username)
                    await self.chat((f"⚠️ @{user.username} تبلیغِ روم دیگه اینجا ممنوعه — دفعه‌ی بعد میوت میشی." if lang == "fa"
                                      else f"⚠️ @{user.username} advertising other rooms isn't allowed here — you'll be muted next time."))
                else:
                    try:
                        await self.highrise.moderate_room(user.id, "mute", 5 * 60)
                        self.muted_users[username] = 5
                        self._log_mod_action("raidguard", "auto-mute (raid)", username)
                        await self.chat((f"🔇 @{user.username} به‌خاطرِ تبلیغِ روم دیگه ۵ دقیقه میوت شد." if lang == "fa"
                                          else f"🔇 @{user.username} was muted for 5 minutes for advertising."))
                    except Exception as e:
                        logger.error(f"خطا در میوتِ خودکارِ raidguard برای {username}: {e}")

    async def cmd_party(self, user: User, parts: list):
        if user.username.lower() not in self.config["admin_usernames"]:
            await self.chat(self.get_message("no_permission"))
            logger.info(f"کاربر {user.username} دسترسی لازم برای اجرای !party را ندارد.")
            return
        lang = self.config.get("language", "fa")

        parts = [p.lower() for p in parts]
        if len(parts) != 3 or (not parts[1].startswith("@") and parts[1] != "all") or not parts[2].isdigit():
            await self.chat(self.get_message("invalid_format", format=("!party @username عدد یا !party all عدد" if self.config.get("language","fa") == "fa" else "!party @username <number> or !party all <number>")))
            logger.info(f"فرمت نادرست برای دستور !party توسط {user.username} وارد شد.")
            return

        dance_number = parts[2]
        if dance_number not in self.emotes:
            await self.chat((f"رقص شماره {dance_number} وجود ندارد!" if lang == "fa" else f"Dance #{dance_number} doesn't exist!"))
            logger.info(f"رقص شماره {dance_number} توسط {user.username} نامعتبر است.")
            return

        emote = self.emotes[dance_number]
        duration = self.emote_durations.get(emote, 15.0)

        if parts[1] == "all":
            try:
                successful_dances = 0
                for username, target_user in self.active_users.items():
                    if target_user.id == self.user_id:
                        continue
                    if username not in self.active_users:
                        logger.info(f"کاربر {username} در حین اجرای رقص آفلاین شد.")
                        continue
                    await self.stop_dance(target_user)  # توقف رقص قبلی
                    self.party_dances[username] = (emote, False)  # False نشان‌دهنده رقص قابل توقف توسط کاربر
                    async def dance_loop(username=username, target_user=target_user):
                        # توجه: username و target_user به عنوان مقدار پیش‌فرض پاس داده شدن
                        # تا هر تسک مقدار مخصوص به خودش رو نگه داره، نه مقدار مشترک حلقه بیرونی
                        # (جلوگیری از باگ late-binding closure در پایتون)
                        try:
                            while username in self.party_dances and self.party_dances[username][0] == emote:
                                if username not in self.active_users:
                                    self.party_dances.pop(username, None)
                                    logger.info(f"کاربر {username} آفلاین شد، رقص متوقف شد.")
                                    break
                                await self.highrise.send_emote(emote, target_user.id)
                                await sleep(duration)
                        except CancelledError:
                            logger.info(f"وظیفه رقص برای {username} لغو شد.")
                        except Exception as e:
                            logger.error(f"خطا در حلقه رقص برای {username}: {e}")
                    task = create_task(dance_loop())
                    self.dance_tasks[username] = task
                    successful_dances += 1
                    await sleep(0.5)
                await self.chat(self.get_message("party_all_success", dance_number=dance_number, count=successful_dances))
                logger.info(f"رقص شماره {dance_number} برای {successful_dances} کاربر توسط {user.username} فعال شد.")
            except Exception as e:
                await self.chat((f"خطا در اجرای رقص برای همه: {str(e)}" if lang == "fa" else f"Error running dance for everyone: {str(e)}"))
                logger.error(f"خطا در cmd_party all: {str(e)}")
        else:
            target_username = parts[1][1:].lower()
            target_user = self.active_users.get(target_username)
            if not target_user:
                await self.chat(self.get_message("user_not_found", username=target_username))
                logger.info(f"کاربر هدف {target_username} توسط {user.username} پیدا نشد.")
                return
            try:
                await self.stop_dance(target_user)  # توقف رقص قبلی
                self.party_dances[target_username] = (emote, True)  # True نشان‌دهنده رقص غیرقابل توقف توسط کاربر
                async def dance_loop():
                    try:
                        while target_username in self.party_dances and self.party_dances[target_username][0] == emote:
                            if target_username not in self.active_users:
                                self.party_dances.pop(target_username, None)
                                logger.info(f"کاربر {target_username} آفلاین شد، رقص متوقف شد.")
                                break
                            await self.highrise.send_emote(emote, target_user.id)
                            await sleep(duration)
                    except CancelledError:
                        logger.info(f"وظیفه رقص برای {target_username} لغو شد.")
                    except Exception as e:
                        logger.error(f"خطا در حلقه رقص برای {target_username}: {e}")
                task = create_task(dance_loop())
                self.dance_tasks[target_username] = task
                await self.chat(self.get_message("party_success", dance_number=dance_number, username=target_username))
                logger.info(f"رقص شماره {dance_number} برای {target_username} توسط {user.username} فعال شد.")
            except Exception as e:
                await self.chat((f"خطا در اجرای رقص برای @{target_username}: {str(e)}" if lang == "fa"
                                  else f"Error running dance for @{target_username}: {str(e)}"))
                logger.error(f"خطا در cmd_party برای {target_username}: {str(e)}")

    async def cmd_partys(self, user: User, parts: list):
        if user.username.lower() not in self.config["admin_usernames"]:
            await self.chat(self.get_message("no_permission"))
            logger.info(f"کاربر {user.username} دسترسی لازم برای اجرای !partys را ندارد.")
            return

        parts = [p.lower() for p in parts]
        if len(parts) != 2 or not parts[1].startswith("@"):
            await self.chat(self.get_message("invalid_format", format="!partys @username"))
            logger.info(f"فرمت نادرست برای دستور !partys توسط {user.username} وارد شد.")
            return

        target_username = parts[1][1:].lower()
        if target_username not in self.party_dances:
            await self.chat(self.get_message("partys_not_dancing", username=target_username))
            logger.info(f"کاربر {target_username} توسط {user.username} برای توقف رقص درخواست شد، اما در حال رقص اجباری نیست.")
            return

        try:
            await self.stop_dance(self.active_users[target_username])
            self.party_dances.pop(target_username, None)
            await self.chat(self.get_message("partys_success", username=target_username))
            logger.info(f"رقص اجباری برای {target_username} توسط {user.username} متوقف شد.")
        except Exception as e:
            await self.chat((f"خطا در توقف رقص برای @{target_username}: {str(e)}" if self.config.get("language","fa") == "fa" else f"Error stopping dance for @{target_username}: {str(e)}"))
            logger.error(f"خطا در cmd_partys برای {target_username}: {str(e)}")

    async def cmd_loopchat(self, user: User, parts: list):
        admins_lower = [admin.lower() for admin in self.config.get("admin_usernames", [])]
        lang = self.config.get("language", "fa")
        if user.username.lower() not in admins_lower:
            await self.chat("❌ این دستور مخصوص ادمین‌های ربات است!" if lang == "fa" else "❌ This command is for bot admins only!")
            return

        if len(parts) < 2:
            await self.chat("⚠️ فرمت اشتباه! فرمت صحیح: !loop [تایم به ثانیه (حداقل 3)] پیام شما" if lang == "fa"
                             else "⚠️ Wrong format! Correct format: !loop [interval in seconds (min 3)] your message")
            return

        # اگه اولین آرگومان بعد از !loopchat یه عدد معتبر (>=3) باشه، به‌عنوان تایم تکرار در نظر گرفته میشه
        interval = 10.0
        message_parts = parts[1:]
        if parts[1].isdigit():
            requested_interval = int(parts[1])
            if requested_interval < 3:
                await self.chat("⚠️ تایم تکرار باید حداقل 3 ثانیه باشد." if lang == "fa" else "⚠️ Interval must be at least 3 seconds.")
                return
            interval = float(requested_interval)
            message_parts = parts[2:]

        if not message_parts:
            await self.chat("⚠️ فرمت اشتباه! فرمت صحیح: !loop [تایم به ثانیه (حداقل 3)] پیام شما" if lang == "fa"
                             else "⚠️ Wrong format! Correct format: !loop [interval in seconds (min 3)] your message")
            return

        # تمام متن باقی‌مانده رو به‌عنوان پیام تکرارشونده در نظر بگیر
        loop_message = " ".join(message_parts)
        
        # اگر loopchat فعلاً در حال اجراست، آن را لغو کن
        if hasattr(self, 'loopchat_task') and self.loopchat_task:
            self.loopchat_task.cancel()
        
        await self.chat((f"✅ حالت تکرار فعال شد! (هر {int(interval)} ثانیه) پیام: {loop_message}" if lang == "fa"
                          else f"✅ Loop mode activated! (every {int(interval)}s) Message: {loop_message}"))
        logger.info(f"loopchat فعال شد توسط {user.username} با تایم {interval} ثانیه: {loop_message}")
        
        # شروع حلقه ارسال پیام
        async def loopchat_loop():
            try:
                while True:
                    await self.chat(loop_message)
                    await sleep(interval)
            except CancelledError:
                logger.info("loopchat لغو شد.")
            except Exception as e:
                logger.error(f"خطا در loopchat: {e}")
        
        self.loopchat_task = create_task(loopchat_loop())

    async def cmd_speaker(self, user: User, parts: list):
        """!speaker on / !speaker off — روشن یا خاموش کردن قابلیت چت هوشمند (اسپیکر)."""
        admins_lower = [admin.lower() for admin in self.config.get("admin_usernames", [])]
        lang = self.config.get("language", "fa")
        if user.username.lower() not in admins_lower and not self.is_host(user.username):
            await self.chat("❌ این دستور مخصوص ادمین‌ها و هاست‌های ربات است!" if lang == "fa"
                             else "❌ This command is for bot admins and hosts only!")
            return

        if len(parts) < 2 or parts[1].lower() not in ("on", "off"):
            await self.chat("⚠️ فرمت اشتباه! استفاده کن از: !speaker on یا !speaker off" if lang == "fa"
                             else "⚠️ Wrong format! Use: !speaker on or !speaker off")
            return

        if parts[1].lower() == "on":
            self.speaker_enabled = True
            await self.chat("🗣️ اسپیکر روشن شد! حالا برای صحبت با ربات، اول جمله رو با + شروع کن." if lang == "fa"
                             else "🗣️ Speaker is on! Start your sentence with + to talk to the bot.")
        else:
            self.speaker_enabled = False
            await self.chat("🔇 اسپیکر خاموش شد." if lang == "fa" else "🔇 Speaker turned off.")

    async def cmd_speaker_mode(self, user: User, parts: list):
        """!speakerm — لحن اسپیکر رو بین باادب (polite) و بی‌ادب (rude) عوض می‌کنه."""
        admins_lower = [admin.lower() for admin in self.config.get("admin_usernames", [])]
        lang = self.config.get("language", "fa")
        if user.username.lower() not in admins_lower and not self.is_host(user.username):
            await self.chat("❌ این دستور مخصوص ادمین‌ها و هاست‌های ربات است!" if lang == "fa"
                             else "❌ This command is for bot admins and hosts only!")
            return

        self.speaker_mode = "rude" if self.speaker_mode == "polite" else "polite"
        if lang == "fa":
            label = "بی‌ادب 😈" if self.speaker_mode == "rude" else "باادب 😇"
        else:
            label = "rude 😈" if self.speaker_mode == "rude" else "polite 😇"
        await self.chat((f"🗣️ لحن اسپیکر عوض شد: {label}" if lang == "fa" else f"🗣️ Speaker tone changed: {label}"))

    async def handle_speaker_message(self, user: User, spoken_text: str):
        """پیام کاربر (بعد از حذف +) رو به موتور هوش مصنوعی می‌فرسته و پاسخ رو تو چت روم می‌گه.
        برای بات فارسی از وب‌سرویس اسپیکر (که فقط فارسی جواب میده) استفاده می‌کنیم؛
        برای بات انگلیسی حتماً از ask_ai (که واقعاً انگلیسی جواب میده) استفاده می‌کنیم تا
        هیچ کلمه‌ی فارسی‌ای تو نسخه‌ی انگلیسی درز نکنه."""
        spoken_text = spoken_text.strip()
        if not spoken_text:
            return
        lang = self.config.get("language", "fa")
        secondary_color = f"<#{self.config['theme_secondary_color']}>" if self.config.get("theme_secondary_color") else "<#00ffff>"
        try:
            if lang == "en":
                # api_speaker سرویس خارجیه که کنترلی روی زبون جوابش نداریم -> فقط برای فارسی استفاده میشه.
                tone_hint = " Reply rudely and sarcastically." if self.speaker_mode == "rude" else " Reply politely and kindly."
                answer = await ask_ai(spoken_text + tone_hint, lang="en")
            else:
                # چون api_speaker با requests (sync) نوشته شده، تو یه ترد جدا اجراش می‌کنیم
                # تا event loop اصلی ربات مسدود (block) نشه.
                answer = await asyncio.to_thread(api_speaker, spoken_text, self.speaker_mode)
            if answer:
                await self.chat(f"@{user.username} {answer}", color=secondary_color)
            else:
                await self.chat((f"⚠️ @{user.username} اسپیکر الان جواب نداد، دوباره امتحان کن." if lang == "fa"
                                  else f"⚠️ @{user.username} the speaker didn't respond, try again."), color=secondary_color)
        except Exception as e:
            logger.error(f"خطا در handle_speaker_message برای {user.username}: {e}")
            await self.chat("⚠️ خطا در ارتباط با سرویس اسپیکر." if lang == "fa" else "⚠️ Error connecting to the speaker service.",
                             color="<#00ffff>")

    async def cmd_loops(self, user: User, parts: list):
        """!loops -> قطع کردن پیام تکرارشونده‌ی فعلی (!loop)"""
        admins_lower = [admin.lower() for admin in self.config.get("admin_usernames", [])]
        lang = self.config.get("language", "fa")
        if user.username.lower() not in admins_lower:
            await self.chat("❌ این دستور مخصوص ادمین‌های ربات است!" if lang == "fa" else "❌ This command is for bot admins only!")
            return

        if hasattr(self, 'loopchat_task') and self.loopchat_task and not self.loopchat_task.done():
            self.loopchat_task.cancel()
            self.loopchat_task = None
            await self.chat("🛑 پیام تکرارشونده قطع شد." if lang == "fa" else "🛑 The looping message was stopped.")
        else:
            await self.chat("⚠️ الان هیچ پیام تکرارشونده‌ای فعال نیست." if lang == "fa" else "⚠️ There's no looping message active right now.")

    async def cmd_love(self, user: User, parts: list):
        """!love @user1 @user2 -> درصد عشق تصادفی (ثابت برای همون دو نفر) بین دو کاربر"""
        lang = self.config.get("language", "fa")
        if len(parts) != 3 or not parts[1].startswith("@") or not parts[2].startswith("@"):
            await self.chat("⚠️ فرمت اشتباه! استفاده کن از: !love @user1 @user2" if lang == "fa"
                             else "⚠️ Wrong format! Use: !love @user1 @user2")
            return

        name1 = parts[1][1:].lower()
        name2 = parts[2][1:].lower()

        # درصد بر اساس ترکیب دو اسم ثابت می‌مونه (هربار یکسان درمیاد، نه کاملاً رندوم هر بار)
        seed_str = "".join(sorted([name1, name2]))
        rng = random.Random(seed_str)
        percent = rng.randint(1, 100)

        bar_filled = "❤️" * (percent // 10)
        bar_empty = "🤍" * (10 - percent // 10)

        await self.chat((f"💘 عشق‌سنج: @{parts[1][1:]} + @{parts[2][1:]} = {percent}%\n{bar_filled}{bar_empty}" if lang == "fa"
                          else f"💘 Love meter: @{parts[1][1:]} + @{parts[2][1:]} = {percent}%\n{bar_filled}{bar_empty}"))

    async def cmd_kiss(self, user: User, parts: list):
        """!kiss @user1 @user2 -> ایموت واقعی sweet kiss (emote-kissing) روی هر دو کاربر پلی میشه؛ نه ری‌اکشن، نه دنس تکرارشونده."""
        lang = self.config.get("language", "fa")
        if len(parts) != 3 or not parts[1].startswith("@") or not parts[2].startswith("@"):
            await self.chat("⚠️ فرمت اشتباه! استفاده کن از: !kiss @user1 @user2" if lang == "fa"
                             else "⚠️ Wrong format! Use: !kiss @user1 @user2")
            return

        u1 = self.active_users.get(parts[1][1:].lower())
        u2 = self.active_users.get(parts[2][1:].lower())
        if not u1 or not u2:
            await self.chat("⚠️ یکی از دو کاربر تو روم پیدا نشد." if lang == "fa" else "⚠️ One of the two users wasn't found in the room.")
            return

        kiss_emote = self.emotes.get("sweetSmooch", "emote-kissing")
        try:
            await self.highrise.send_emote(kiss_emote, u1.id)
            await self.highrise.send_emote(kiss_emote, u2.id)
            await self.chat((f"💋 @{u1.username} و @{u2.username} همدیگه رو بوسیدن!" if lang == "fa"
                              else f"💋 @{u1.username} and @{u2.username} kissed each other!"))
        except Exception as e:
            await self.chat((f"خطا در اجرای ایموت بوسه: {e}" if lang == "fa" else f"Error running kiss emote: {e}"))
            logger.error(f"خطا در cmd_kiss: {e}")

    async def cmd_punch(self, user: User, parts: list):
        """!punch @username -> فرستنده مشت می‌زنه و کاربر هدف واقعاً میفته زمین (fainting)"""
        lang = self.config.get("language", "fa")
        if len(parts) != 2 or not parts[1].startswith("@"):
            await self.chat("⚠️ فرمت اشتباه! استفاده کن از: !punch @username" if lang == "fa"
                             else "⚠️ Wrong format! Use: !punch @username")
            return

        target_username = parts[1][1:].lower()
        target_user = self.active_users.get(target_username)
        if not target_user:
            await self.chat(self.get_message("user_not_found", username=target_username))
            return

        if target_user.id == user.id:
            await self.chat("⚠️ نمی‌تونی خودتو مشت بزنی!" if lang == "fa" else "⚠️ You can't punch yourself!")
            return

        punch_emote = self.emotes.get("punch", "emote-punch")
        fall_emote = self.emotes.get("faint", "emote-fainting")
        try:
            await self.highrise.send_emote(punch_emote, user.id)
            await sleep(0.6)
            await self.highrise.send_emote(fall_emote, target_user.id)
            await self.chat((f"👊 @{user.username} یک مشت محکم به @{target_user.username} زد و انداختش زمین!" if lang == "fa"
                              else f"👊 @{user.username} landed a hard punch on @{target_user.username} and knocked them down!"))
        except Exception as e:
            await self.chat((f"خطا در اجرای مشت: {e}" if lang == "fa" else f"Error running punch: {e}"))
            logger.error(f"خطا در cmd_punch: {e}")

    async def cmd_dance_toggle(self, user: User, parts: list):
        """!dance on / !dance off -> فعال یا غیرفعال کردن کامل قابلیت اجرای دنس با کد عددی/اسم (پیش‌فرض: روشن)"""
        if user.username.lower() not in self.config["admin_usernames"]:
            await self.chat(self.get_message("no_permission"))
            return
        lang = self.config.get("language", "fa")

        if len(parts) < 2 or parts[1].lower() not in ("on", "off"):
            await self.chat("⚠️ فرمت اشتباه! استفاده کن از: !dance on یا !dance off" if lang == "fa"
                             else "⚠️ Wrong format! Use: !dance on or !dance off")
            return

        self.config["dance_enabled"] = (parts[1].lower() == "on")
        self.save_config()
        state_text = "روشن ✅" if self.config["dance_enabled"] else "خاموش ⛔️"
        await self.chat((f"💃 قابلیت اجرای دنس با کد الان {state_text} شد." if self.config.get("language","fa") == "fa" else f"💃 Code-triggered dancing is now {state_text}."))

    async def cmd_afk(self, user: User, parts: list):
        """!afk -> نمایش لیست کاربرهایی که الان AFK هستن (خودِ AFK شدن با تایپ afk انجام میشه)"""
        if not self.afk_users:
            await self.chat("😊 الان هیچکس AFK نیست." if self.config.get("language","fa") == "fa" else "😊 No one is AFK right now.")
            return
        names = "، ".join(f"@{u}" for u in self.afk_users)
        await self.chat((f"💤 کاربرهای AFK: {names}" if self.config.get("language","fa") == "fa" else f"💤 AFK users: {names}"))

    async def cmd_emote(self, user: User, parts: list):
        """!emote [name] یا !emote [لینک آیتم] -> اجرای هر دنس/ایموتی با اسم دقیق یا لینک high.rs، حتی اگه تو لیست !dances نباشه."""
        if len(parts) < 2:
            await self.chat("⚠️ Usage: !emote [name] or !emote [item link]")
            return
        raw = " ".join(parts[1:]).strip()

        # حالت ۱: یه لینک high.rs/item?id=... داده (استخراج مستقیم شناسه‌ی واقعی آیتم)
        link_match = re.search(r"high\.rs/item\?id=([A-Za-z0-9_.\-]+)", raw)
        if link_match:
            emote_id = link_match.group(1)
        else:
            # حالت ۲: اسم دقیق (alias تو self.emotes) یا خودِ شناسه‌ی خام
            key = raw.lower()
            emote_id = self.emotes.get(key, raw)

        try:
            await self.start_dance(user, emote_id)
            await self.chat(f"✅ @{user.username} emote: {emote_id}")
        except Exception as e:
            await self.chat(f"❌ Error running emote: {e}")
            logger.error(f"خطا در cmd_emote برای {emote_id}: {e}")

    async def cmd_fight(self, user: User, parts: list):
        """!fight @username -> یک دعوای متنی واقعی بین فرستنده و کاربر هدف، با ری‌اکشن واقعی برای برنده (بدون دنس/ایموت/ایموجی)."""
        lang = self.config.get("language", "fa")
        if len(parts) != 2 or not parts[1].startswith("@"):
            await self.chat("⚠️ فرمت اشتباه! استفاده کن از: !fight @username" if lang == "fa"
                             else "⚠️ Wrong format! Use: !fight @username")
            return

        target_username = parts[1][1:].lower()
        target_user = self.active_users.get(target_username)
        if not target_user:
            await self.chat(self.get_message("user_not_found", username=target_username))
            return

        if target_user.id == user.id:
            await self.chat("⚠️ نمی‌تونی با خودت دعوا کنی!" if lang == "fa" else "⚠️ You can't fight yourself!")
            return

        winner, loser = random.sample([user, target_user], 2)
        await self.chat((f"⚔️ دعوای @{user.username} و @{target_user.username} شروع شد..." if lang == "fa"
                          else f"⚔️ A fight between @{user.username} and @{target_user.username} has begun..."))
        await sleep(1.5)

        try:
            await self.highrise.react("thumbs", winner.id)
            await sleep(0.4)
            await self.highrise.react("heart", loser.id)
        except Exception as e:
            logger.error(f"خطا در ری‌اکشن !fight: {e}")

        await self.chat((f"🏆 @{winner.username} برنده‌ی دعوا شد! (@{loser.username} بازنده شد)" if lang == "fa"
                          else f"🏆 @{winner.username} won the fight! (@{loser.username} lost)"))

    async def cmd_random(self, user: User, parts: list):
        """!random -> تاس (عدد ۱ تا ۶) | !random گزینه1 گزینه2 ... -> گردونه بین گزینه‌ها"""
        lang = self.config.get("language", "fa")
        if len(parts) == 1:
            result = random.randint(1, 6)
            await self.chat((f"🎲 @{user.username} تاس انداخت و عدد {result} اومد!" if lang == "fa"
                              else f"🎲 @{user.username} rolled the dice and got {result}!"))
            logger.info(f"{user.username} تاس انداخت: {result}")
            return

        options = parts[1:]
        winner = random.choice(options)
        await self.chat((f"🎡 گردونه چرخید... و رو «{winner}» ایستاد! (درخواست @{user.username})" if lang == "fa"
                          else f"🎡 The wheel spun... and landed on \"{winner}\"! (requested by @{user.username})"))
        logger.info(f"گردونه {user.username} با گزینه‌های {options} -> {winner}")

    async def cmd_tp(self, user: User, parts: list):
        """!tp all X Y Z یا !tp @username X Y Z -> تلپورت به مختصات دقیق"""
        if user.username.lower() not in self.config["admin_usernames"]:
            await self.chat(self.get_message("no_permission"))
            return
        lang = self.config.get("language", "fa")

        if len(parts) != 5:
            await self.chat("⚠️ فرمت اشتباه! استفاده کن از: !tp all X Y Z یا !tp @username X Y Z" if lang == "fa"
                             else "⚠️ Wrong format! Use: !tp all X Y Z or !tp @username X Y Z")
            return

        target_spec = parts[1]
        try:
            x, y, z = float(parts[2]), float(parts[3]), float(parts[4])
        except ValueError:
            await self.chat("⚠️ مختصات X, Y, Z باید عدد باشن." if lang == "fa" else "⚠️ X, Y, Z coordinates must be numbers.")
            return

        dest = Position(x=x, y=y, z=z)

        if target_spec.lower() == "all":
            successful = 0
            for username, target_user in list(self.active_users.items()):
                if target_user.id == self.user_id:
                    continue
                try:
                    await self.highrise.teleport(user_id=target_user.id, dest=dest)
                    successful += 1
                    await sleep(0.3)
                except Exception as e:
                    logger.error(f"خطا در تلپورت {username} به مختصات دلخواه: {e}")
            await self.chat((f"✅ {successful} کاربر به مختصات ({x}, {y}, {z}) تلپورت شدند." if lang == "fa"
                              else f"✅ {successful} users teleported to ({x}, {y}, {z})."))
        elif target_spec.startswith("@"):
            target_username = target_spec[1:].lower()
            target_user = self.active_users.get(target_username)
            if not target_user:
                await self.chat(self.get_message("user_not_found", username=target_username))
                return
            try:
                await self.highrise.teleport(user_id=target_user.id, dest=dest)
                await self.chat((f"✅ @{target_user.username} به مختصات ({x}, {y}, {z}) تلپورت شد." if lang == "fa"
                                  else f"✅ @{target_user.username} teleported to ({x}, {y}, {z})."))
            except Exception as e:
                await self.chat(self.get_message("teleport_error", error=str(e)))
                logger.error(f"خطا در تلپورت {target_username}: {e}")
        else:
            await self.chat("⚠️ فرمت اشتباه! استفاده کن از: !tp all X Y Z یا !tp @username X Y Z" if lang == "fa"
                             else "⚠️ Wrong format! Use: !tp all X Y Z or !tp @username X Y Z")

    async def cmd_react(self, user: User, parts: list):
        """!react نوع تعداد @username یا !react نوع all -> ارسال هر نوع واکنشی (heart, clap, wave, wink, thumbs, ...)"""
        lang = self.config.get("language", "fa")
        if len(parts) < 3:
            await self.chat("⚠️ فرمت اشتباه! استفاده کن از: !react نوع تعداد @username یا !react نوع all" if lang == "fa"
                             else "⚠️ Wrong format! Use: !react type count @username or !react type all")
            return

        reaction_type = parts[1].lower()

        if parts[2].lower() == "all":
            if user.username.lower() not in self.config["admin_usernames"]:
                await self.chat(self.get_message("no_permission"))
                return
            successful = 0
            for username, target_user in list(self.active_users.items()):
                if target_user.id == self.user_id:
                    continue
                try:
                    await self.highrise.react(reaction_type, target_user.id)
                    successful += 1
                    await sleep(0.5)
                except Exception as e:
                    logger.error(f"خطا در ارسال واکنش {reaction_type} به {username}: {e}")
            await self.chat((f"✅ واکنش «{reaction_type}» به {successful} نفر ارسال شد." if lang == "fa"
                              else f"✅ Sent \"{reaction_type}\" reaction to {successful} people."))
            return

        if len(parts) != 4:
            await self.chat("⚠️ فرمت اشتباه! استفاده کن از: !react نوع تعداد @username" if lang == "fa"
                             else "⚠️ Wrong format! Use: !react type count @username")
            return

        try:
            count = int(parts[2])
            if count < 1 or count > 100:
                await self.chat("⚠️ تعداد باید بین 1 تا 100 باشد." if lang == "fa" else "⚠️ Count must be between 1 and 100.")
                return
        except ValueError:
            await self.chat("⚠️ عدد نامعتبر است." if lang == "fa" else "⚠️ Invalid number.")
            return

        target_username = parts[3].lstrip('@').lower()
        target_user = self.active_users.get(target_username)
        if not target_user:
            await self.chat(self.get_message("user_not_found", username=target_username))
            return

        try:
            for _ in range(count):
                await self.highrise.react(reaction_type, target_user.id)
                await sleep(0.5)
            await self.chat((f"✅ واکنش «{reaction_type}» ({count} بار) به @{target_user.username} ارسال شد." if lang == "fa"
                              else f"✅ Sent \"{reaction_type}\" reaction ({count}x) to @{target_user.username}."))
        except Exception as e:
            await self.chat((f"خطا در ارسال واکنش: {e}" if lang == "fa" else f"Error sending reaction: {e}"))
            logger.error(f"خطا در ارسال واکنش {reaction_type} به {target_username}: {e}")

    def build_commands_text(self) -> str:
        return (
            "📜 لیست کامل دستورات ربات:\n\n"
            "1-248 - اجرای رقص با کد عددی (لیست کامل: !dances)\n"
            "stop - توقف رقص\n"
            "!help - نمایش راهنما\n"
            "!commands - نمایش همین لیست دستورات\n"
            "!dances - نمایش لیست کد تمام دنس‌ها\n"
            "!spam تعداد پیام - ارسال پیام اسپم (ادمین)\n"
            "!tele @username [vip|vip1|dj|مکان_سفارشی] - تلپورت به مکان ذخیره‌شده (ادمین)\n"
            "!tele to @username / !tele me @username / !tele me all - تلپورت بین کاربران (ادمین)\n"
            "!tp all X Y Z / !tp @username X Y Z - تلپورت به مختصات دقیق (ادمین)\n"
            "!fallow @username - ربات دنبال کاربر راه می‌افته (واقعی، با قدم زدن)، دوباره بزن تا متوقف بشه (ادمین/هاست)\n"
            "!run on / !run off - راه رفتن خودکار ربات دور روم مثل یک کاراکتر واقعی (ادمین)\n"
            "!heart تعداد @username / !heart all - ارسال قلب بنفش\n"
            "!clap تعداد @username / !clap all - ارسال clap\n"
            "!wink تعداد @username / !wink all - ارسال wink\n"
            "!wave تعداد @username / !wave all - ارسال wave\n"
            "!thumbs تعداد @username / !thumbs all - ارسال thumbs-up\n"
            "!react نوع تعداد @username / !react نوع all - ارسال هر نوع واکنش دلخواه\n"
            "!random - انداختن تاس (عدد 1 تا 6)\n"
            "!random گزینه1 گزینه2 ... - گردونه شانس بین گزینه‌ها\n"
            "!mute @username [دقیقه] - میوت کردن کاربر (ادمین)\n"
            "!unmute @username - آنمیوت کردن کاربر (ادمین)\n"
            "!wallet - نمایش موجودی ربات\n"
            "!set - تلپورت ربات به ادمین\n"
            "!item set @username - تغییر ظاهر ربات به ایتم‌های یک کاربر (ذخیره خودکار میشه)\n"
            "!item set شماره - اعمال یک اسکین ذخیره‌شده (پریست)\n"
            "!item save شماره - ذخیره‌ی ظاهر فعلی ربات به‌عنوان یک پریست (ادمین)\n"
            "!tip تعداد all / !tip تعداد @username / !tip تعداد random عدد_نفرات - تیپ گلد\n"
            "!ban @username [تایم دلخواه: 0=دائمی، 30m، 2h، 90s] - محروم کردن کاربر (ادمین)\n"
            "!kick @username [تایم دلخواه] - بدون تایم فقط کیک؛ با 0 بن دائمی؛ با عدد بن زمان‌دار (ادمین)\n"
            "!unban @username - آنبن کردن کاربر (ادمین)\n"
            "!admin on / !admin off - سینک خودکار ادمین‌های روم با ادمین‌های ربات (فقط هاست)\n"
            "!ai on / !ai off - روشن/خاموش کردن هوش مصنوعی تو چت روم (تو پیوی همیشه فعاله) (ادمین)\n"
            "/سوال - پرسیدن سوال از هوش مصنوعی؛ جواب کوتاه؛ تو پیوی همیشه، تو روم فقط با !ai on\n"
            "!dancechain - اجرای زنجیره رقص\n"
            "!dance on / !dance off - فعال/غیرفعال کردن کامل اجرای دنس با کد (پیش‌فرض: روشن) (ادمین)\n"
            "!kiss @user1 @user2 - اجرای ایموت واقعی بوسیدن (smooch) روی هر دو کاربر\n"
            "!punch @username - مشت زدن؛ کاربر هدف واقعاً میفته زمین\n"
            "!love @user1 @user2 - نمایش درصد عشق‌سنج بین دو کاربر\n"
            "!afk - نمایش لیست کاربرهای AFK (خودِ AFK شدن با تایپ afk انجام میشه)\n"
            "!addtele نام_مکان [admin|نام_رنک] - ذخیره مکان فعلی؛ با گفتن اسمش تو چت میری اونجا (admin=فقط ادمین‌ها, نام_رنک=فقط اون رنک, بدون هیچی=عمومی)\n"
            "!lang fa / !lang en - تغییر کامل زبان ربات (ادمین)\n"
            "!emote [اسم یا لینک آیتم] - اجرای هر دنس/ایموتی، حتی خارج از لیست !dances\n"
            "!deltele نام_مکان - حذف مکان (ادمین)\n"
            "!welcome پیام - تنظیم پیام خوش‌آمدگویی (ادمین)\n"
            "!addadmin @username / !removeadmin @username - مدیریت ادمین‌ها (فقط Host)\n"
            "!addhost @username / !removehost @username - مدیریت هاست‌ها (فقط Host)\n"
            "!give رتبه @username / !give -رتبه @username - دادن/گرفتن رتبه (Owner/Manager/Admin/Mod/VIP/Host، بسته به سطح خودت)\n"
            "!emotebot نام/شماره_دنس - تغییر دنس مداوم ربات (ادمین)\n"
            "!loop [تایم ثانیه >=3] پیام - تنظیم پیام تکرارشونده ربات (ادمین)\n"
            "!loops - قطع کردن پیام تکرارشونده‌ی فعلی (ادمین)\n"
            "!listadd - نمایش لیست همه رتبه‌ها (Host/Owner/Manager/Admin/Mod/VIP)\n"
            "!freeze @username / !unfreeze @username - فریز کردن/آزادسازی کاربر (ادمین)\n"
            "!party @username عدد / !party all عدد - اجرای رقص اجباری (ادمین)\n"
            "!partys @username - توقف رقص اجباری کاربر (ادمین)\n"
            "!speaker on / !speaker off - روشن و خاموش کردن چت هوشمند (ادمین/هاست)\n"
            "!speakerm - تغییر لحن اسپیکر بین باادب/بی‌ادب (ادمین/هاست)\n"
            "+متن - صحبت با اسپیکر (وقتی روشن باشه)\n"
            "!MR نام_رنک - ساخت رنک دلخواه (ادمین)\n"
            "!GR نام_رنک @username - دادن/گرفتن رنک از کاربر (ادمین)\n"
            "!DR نام_رنک - حذف رنک دلخواه (ادمین)\n"
            "!emotescan - اسکن کاتالوگ هایرایز و افزودن خودکار دنس‌های واقعی جدید، بدون هیچ محدودیتی (ادمین)\n\n"
            "📩 برای اطلاعات بیشتر به @ahoora_king پیام بدید!"
        )

    def build_dances_text(self) -> str:
        """لیستِ دنس‌ها با شماره‌ی کنارش (همون شماره‌ای که با !botdance/!party و... استفاده میشه)
        + اسمِ تمیزِ انگلیسیِ همون دنس."""
        # برای هر emote واقعی (مثلاً "idle-loop-happy")، هم شماره‌ش رو پیدا کن هم کوتاه‌ترین
        # اسمِ انگلیسیِ تمیزش رو (بدونِ کدِ فارسی/رشته‌ی خامِ دیگه).
        value_to_number = {}
        value_to_name = {}
        for key, value in self.emotes.items():
            if key.isdigit():
                value_to_number.setdefault(value, key)
                continue
            if all('۰' <= c <= '۹' for c in key):
                continue
            if not re.fullmatch(r"[A-Za-z]+", key):
                continue
            if value not in value_to_name or len(key) < len(value_to_name[value]):
                value_to_name[value] = key

        rows = []
        for value, number in value_to_number.items():
            name = value_to_name.get(value, value)
            rows.append((int(number), name))
        rows.sort(key=lambda r: r[0])

        lines = ["💃 لیستِ دنس‌ها (شماره - اسم):\n"]
        lines.extend(f"{num} - {name}" for num, name in rows)
        return "\n".join(lines)

    async def cmd_commands(self, user: User, parts: list):
        text = self.build_commands_text()
        for chunk in [text[i:i + 200] for i in range(0, len(text), 200)]:
            await self.chat(chunk)
        logger.info(f"لیست دستورات توسط {user.username} درخواست شد.")

    async def cmd_dances(self, user: User, parts: list):
        """!dances -> لیستِ دنس‌ها با شماره‌ی کنارش، تو چتِ عمومی."""
        text = self.build_dances_text()
        for chunk in [text[i:i + 200] for i in range(0, len(text), 200)]:
            await self.chat(chunk)
        logger.info(f"لیست دنس‌ها توسط {user.username} درخواست شد.")

    async def cmd_fallow(self, user: User, parts: list):
        """!fallow @username -> ربات شروع به دنبال کردن (راه رفتن پشت سر) کاربر می‌کنه؛ دوباره زدن همون یوزر متوقفش می‌کنه."""
        admins_lower = [admin.lower() for admin in self.config.get("admin_usernames", [])]
        if user.username.lower() not in admins_lower and not self.is_host(user.username):
            await self.chat("❌ این دستور مخصوص ادمین\u200cها و هاست\u200cهای ربات است!" if self.config.get("language","fa") == "fa" else "❌ This command is only for bot admins and hosts!")
            return

        if len(parts) < 2 or not parts[1].startswith("@"):
            if self.following_username:
                self.following_username = None
                await self.chat("🛑 ربات دنبال کردن رو متوقف کرد." if self.config.get("language","fa") == "fa" else "🛑 The bot stopped following.")
            else:
                await self.chat("⚠️ فرمت اشتباه! استفاده کن از: !fallow @username" if self.config.get("language","fa") == "fa" else "⚠️ Wrong format! Use: !fallow @username")
            return

        target_username = parts[1][1:].lower()

        if self.following_username == target_username:
            self.following_username = None
            await self.chat((f"🛑 ربات دیگه دنبال @{target_username} نمیره." if self.config.get("language","fa") == "fa" else f"🛑 The bot no longer follows @{target_username}."))
            return

        target_user = self.active_users.get(target_username)
        if not target_user:
            await self.chat(self.get_message("user_not_found", username=target_username))
            return

        self.following_username = target_username
        await self.chat((f"🐾 ربات از الان دنبال @{target_user.username} می\u200cره!" if self.config.get("language","fa") == "fa" else f"🐾 The bot is now following @{target_user.username}!"))

        position = self.user_positions.get(target_username)
        if position:
            try:
                await self.highrise.walk_to(position)
                self.bot_position = position
            except Exception as e:
                logger.error(f"خطا در حرکت اولیه هنگام فالو کردن {target_username}: {e}")

    async def cmd_mute(self, user: User, parts: list):
        """!mute @username [دقیقه] -> میوت کردن کاربر"""
        if not self.can_moderate(user.username):
            await self.chat(self.get_message("no_permission"))
            return
        lang = self.config.get("language", "fa")

        if len(parts) < 2 or not parts[1].startswith("@"):
            await self.chat("⚠️ فرمت اشتباه! استفاده کن از: !mute @username [دقیقه]" if lang == "fa"
                             else "⚠️ Wrong format! Use: !mute @username [minutes]")
            return

        target_username = parts[1][1:].lower()
        target_user = self.active_users.get(target_username)
        if not target_user:
            await self.chat(self.get_message("user_not_found", username=target_username))
            return

        minutes = 5
        if len(parts) >= 3:
            try:
                minutes = int(parts[2])
            except ValueError:
                await self.chat("⚠️ زمان باید یک عدد (به دقیقه) باشد." if lang == "fa" else "⚠️ Duration must be a number (in minutes).")
                return

        try:
            # نکته: واحد دقیق پارامتر action_length در SDK هایرایز مستند نشده؛
            # اینجا به‌عنوان ثانیه فرستاده میشه. اگه رفتار واقعی فرق داشت، این عدد رو تنظیم کن.
            await self.highrise.moderate_room(target_user.id, "mute", minutes * 60)
            self.muted_users[target_username] = minutes
            self._log_mod_action(user.username, "mute", target_username, f"{minutes} min")
            await self.chat((f"🔇 @{target_user.username} به مدت {minutes} دقیقه میوت شد." if lang == "fa"
                              else f"🔇 @{target_user.username} was muted for {minutes} minutes."))
            logger.info(f"{user.username} کاربر {target_username} رو برای {minutes} دقیقه میوت کرد.")
        except Exception as e:
            await self.chat((f"خطا در میوت کردن: {e}" if lang == "fa" else f"Error muting user: {e}"))
            logger.error(f"خطا در میوت {target_username}: {e}")

    async def cmd_unmute(self, user: User, parts: list):
        if not self.can_moderate(user.username):
            await self.chat(self.get_message("no_permission"))
            return
        lang = self.config.get("language", "fa")

        if len(parts) < 2 or not parts[1].startswith("@"):
            await self.chat("⚠️ فرمت اشتباه! استفاده کن از: !unmute @username" if lang == "fa"
                             else "⚠️ Wrong format! Use: !unmute @username")
            return

        target_username = parts[1][1:].lower()
        target_user = self.active_users.get(target_username)
        if not target_user:
            await self.chat(self.get_message("user_not_found", username=target_username))
            return

        try:
            await self.highrise.moderate_room(target_user.id, "unmute")
            self.muted_users.pop(target_username, None)
            self._log_mod_action(user.username, "unmute", target_username)
            await self.chat(f"🔊 @{target_user.username} آنمیوت شد." if lang == "fa" else f"🔊 @{target_user.username} was unmuted.")
        except Exception as e:
            await self.chat((f"خطا در آنمیوت کردن: {e}" if lang == "fa" else f"Error unmuting user: {e}"))
            logger.error(f"خطا در آنمیوت {target_username}: {e}")

    async def cmd_mr(self, user: User, parts: list):
        """!MR نام_رنک -> ساخت یک رنک دلخواه جدید"""
        if user.username.lower() not in self.config["admin_usernames"]:
            await self.chat(self.get_message("no_permission"))
            return
        lang = self.config.get("language", "fa")

        if len(parts) < 2:
            await self.chat("⚠️ فرمت اشتباه! استفاده کن از: !MR نام_رنک" if lang == "fa" else "⚠️ Wrong format! Use: !MR rank_name")
            return

        rank_name = parts[1]
        if rank_name in self.config["custom_ranks"]:
            await self.chat((f"⚠️ رنک «{rank_name}» از قبل وجود دارد." if lang == "fa" else f"⚠️ Rank \"{rank_name}\" already exists."))
            return

        self.config["custom_ranks"][rank_name] = []
        self.save_config()
        await self.chat(f"✅ رنک «{rank_name}» ساخته شد." if lang == "fa" else f"✅ Rank \"{rank_name}\" was created.")
        logger.info(f"{user.username} رنک {rank_name} رو ساخت.")

    async def cmd_gr(self, user: User, parts: list):
        """!GR نام_رنک @username -> دادن یا گرفتن رنک از کاربر (toggle)"""
        if user.username.lower() not in self.config["admin_usernames"]:
            await self.chat(self.get_message("no_permission"))
            return
        lang = self.config.get("language", "fa")

        if len(parts) < 3 or not parts[2].startswith("@"):
            await self.chat("⚠️ فرمت اشتباه! استفاده کن از: !GR نام_رنک @username" if lang == "fa"
                             else "⚠️ Wrong format! Use: !GR rank_name @username")
            return

        rank_name = parts[1]
        target_username = parts[2][1:].lower()

        if rank_name not in self.config["custom_ranks"]:
            await self.chat((f"⚠️ رنک «{rank_name}» وجود ندارد. اول با !MR بسازش." if lang == "fa"
                              else f"⚠️ Rank \"{rank_name}\" doesn't exist. Create it first with !MR."))
            return

        members = self.config["custom_ranks"][rank_name]
        if target_username in members:
            members.remove(target_username)
            self.save_config()
            await self.chat((f"➖ رنک «{rank_name}» از @{target_username} گرفته شد." if lang == "fa"
                              else f"➖ Rank \"{rank_name}\" was taken from @{target_username}."))
        else:
            members.append(target_username)
            self.save_config()
            await self.chat((f"➕ رنک «{rank_name}» به @{target_username} داده شد." if lang == "fa"
                              else f"➕ Rank \"{rank_name}\" was given to @{target_username}."))

    async def cmd_dr(self, user: User, parts: list):
        """!DR نام_رنک -> حذف کامل یک رنک دلخواه"""
        if user.username.lower() not in self.config["admin_usernames"]:
            await self.chat(self.get_message("no_permission"))
            return
        lang = self.config.get("language", "fa")

        if len(parts) < 2:
            await self.chat("⚠️ فرمت اشتباه! استفاده کن از: !DR نام_رنک" if lang == "fa" else "⚠️ Wrong format! Use: !DR rank_name")
            return

        rank_name = parts[1]
        if rank_name not in self.config["custom_ranks"]:
            await self.chat(f"⚠️ رنک «{rank_name}» وجود ندارد." if lang == "fa" else f"⚠️ Rank \"{rank_name}\" doesn't exist.")
            return

        del self.config["custom_ranks"][rank_name]
        self.save_config()
        await self.chat(f"🗑 رنک «{rank_name}» حذف شد." if lang == "fa" else f"🗑 Rank \"{rank_name}\" was deleted.")
        logger.info(f"{user.username} رنک {rank_name} رو حذف کرد.")

    async def perform_emote_scan(self, announce: bool = True) -> int:
        """با استفاده از کاتالوگ واقعی هایرایز (self.webapi)، دنس‌های واقعی جدیدی که هنوز تو لیست
        ربات نیستن رو پیدا می‌کنه و با کد عددی + کد فارسی + اسم اضافه می‌کنه. به‌جای حدس زدن شناسه‌ی
        دنس (که می‌تونه اشتباه و باعث خرابی بشه)، مستقیم از خود سرور هایرایز داده می‌گیره.
        این تابع هم از دستور دستی !emotescan و هم از اسکن خودکار دوره‌ای صدا زده میشه.
        ⚠️ هیچ سقفی نداره: هرچقدر دنس واقعی جدید تو کاتالوگ پیدا بشه، همه‌شون اضافه میشن.
        خروجی: تعداد دنس‌های جدیدی که اضافه شدند."""
        numeric_codes = [k for k in self.emotes.keys() if k.isdigit()]
        current_max = max((int(k) for k in numeric_codes), default=0)
        existing_ids = set(self.emotes.values())

        try:
            new_items = []
            # نکته: پارامترهای صفحه‌بندی (pagination) برای get_items() تو مستندات رسمی SDK
            # تایید نشده بودن، برای همین حذف شدن تا خطای ساختگی ایجاد نکنن. فقط یک صفحه بررسی میشه.
            response = await self.webapi.get_items()

            items_list = getattr(response, "items", None) or (response if isinstance(response, list) else [])

            for it in items_list:
                item_id = getattr(it, "id", None) or (it.get("id") if isinstance(it, dict) else None)
                item_type = getattr(it, "item_type", None) or getattr(it, "type", None) or (
                    it.get("item_type") if isinstance(it, dict) else None
                )
                if not item_id:
                    continue
                is_dance_like = (
                    item_id.startswith("dance-") or item_id.startswith("emote-") or item_id.startswith("idle-")
                    or (item_type and "emote" in str(item_type).lower())
                )
                if is_dance_like and item_id not in existing_ids:
                    new_items.append(item_id)
                    existing_ids.add(item_id)

            if not new_items:
                return 0

            added = 0
            code = current_max + 1
            for item_id in new_items:
                readable_name = item_id.split("-", 1)[1] if "-" in item_id else item_id
                self.emotes[str(code)] = item_id
                self.emotes[to_persian_digits(code)] = item_id
                self.emotes[readable_name] = item_id
                self.config["discovered_emotes"][str(code)] = item_id
                self.config["discovered_emotes"][to_persian_digits(code)] = item_id
                self.config["discovered_emotes"][readable_name] = item_id
                added += 1
                code += 1

            self.save_config()
            if announce and added:
                lang = self.config.get("language", "fa")
                await self.chat(
                    (f"🆕 اسکن خودکار {added} دنس واقعی جدید پیدا کرد و اضافه کرد (کدهای {current_max + 1} تا {code - 1})! برای لیست کامل: !dances"
                     if lang == "fa" else
                     f"🆕 Auto-scan found and added {added} new real dances (codes {current_max + 1} to {code - 1})! See !dances for the full list.")
                )
            logger.info(f"perform_emote_scan: {added} دنس جدید اضافه شد.")
            return added
        except AttributeError:
            logger.error("self.webapi.get_items() تو این نسخه از SDK در دسترس نیست.")
            return 0
        except Exception as e:
            if "structuring" in str(e).lower() or "cattrs" in str(type(e).__module__).lower():
                logger.error(
                    f"خطای ناسازگاری نسخه‌ی SDK هنگام پردازش پاسخ کاتالوگ (احتمالاً نسخه‌ی highrise-bot-sdk قدیمیه "
                    f"و فیلد جدیدی تو پاسخ سرور رو نمی‌شناسه): {e}"
                )
            else:
                logger.error(f"خطا در perform_emote_scan: {e}")
            return 0

    async def emote_autoscan_loop(self):
        """هر چند ساعت یک‌بار خودکار چک می‌کنه که آیا دنس جدیدی به بازی اضافه شده یا نه، بدون نیاز به دستور دستی."""
        try:
            while True:
                await sleep(6 * 60 * 60)  # هر ۶ ساعت
                try:
                    await self.perform_emote_scan(announce=True)
                except Exception as e:
                    logger.error(f"خطا در اسکن خودکار دوره‌ای دنس‌ها: {e}")
        except CancelledError:
            logger.info("اسکن خودکار دنس‌ها متوقف شد.")

    async def cmd_emotescan(self, user: User, parts: list):
        """!emotescan -> اجرای فوری و دستی اسکن دنس‌های جدید، بدون هیچ محدودیتی (علاوه بر اسکن خودکار هر ۶ ساعت)."""
        if user.username.lower() not in self.config["admin_usernames"]:
            await self.chat(self.get_message("no_permission"))
            return

        numeric_codes = [k for k in self.emotes.keys() if k.isdigit()]
        current_max = max((int(k) for k in numeric_codes), default=0)
        lang = self.config.get("language", "fa")

        await self.chat("🔎 در حال جستجوی دنس\u200cهای واقعی جدید تو کاتالوگ هایرایز... (ممکنه چند ثانیه طول بکشه)" if lang == "fa" else "🔎 Searching the Highrise catalog for new real dances... (may take a few seconds)")
        added = await self.perform_emote_scan(announce=False)

        if added:
            new_max = current_max + added
            await self.chat(
                (f"✅ {added} دنس واقعی جدید اضافه شد (کدهای {current_max + 1} تا {new_max}). "
                 f"الان مجموعاً {new_max} دنس داری! برای لیست کامل: !dances"
                 if lang == "fa" else
                 f"✅ {added} new real dances were added (codes {current_max + 1} to {new_max}). "
                 f"You now have {new_max} dances total! See !dances for the full list.")
            )
            logger.info(f"{user.username} با !emotescan تعداد {added} دنس جدید اضافه کرد.")
        else:
            await self.chat(
                "⚠️ دنس واقعی جدیدی تو کاتالوگ پیدا نشد، یا SDK نصب‌شده از self.webapi.get_items() پشتیبانی نمی‌کنه."
                if lang == "fa" else
                "⚠️ No new real dances were found in the catalog, or the installed SDK doesn't support self.webapi.get_items()."
            )

    async def set_bot_continuous_dance(self, actual_emote_name: str):
        """دنسِ همیشگی و بدون‌وقفه‌ی خود ربات رو روی emote داده‌شده تنظیم می‌کنه. هم از !emotebot
        و هم برای دنس پیش‌فرض (floss) موقع روشن شدن ربات استفاده میشه.
        🐛 قبلاً اگه همون اولین send_emote به هر دلیلِ گذرایی (مثلاً بات هنوز کاملاً «اسپاون»
        نشده بود تو روم، درست بعدِ اتصال) خطا می‌داد، کلِ حلقه برای همیشه ساکت می‌مرد و بات
        اصلاً دیگه دنس نمی‌زد. الان به‌جای مردن، دوباره تلاش می‌کنه (با یه مکثِ کوتاه)."""
        if self.user_id in self.dance_tasks:
            self.dance_tasks[self.user_id].cancel()
            self.dance_tasks.pop(self.user_id, None)

        duration = self.emote_durations.get(actual_emote_name, 15.0)
        sleep_time = duration

        async def new_emote_loop():
            consecutive_errors = 0
            try:
                while True:
                    try:
                        await self.highrise.send_emote(actual_emote_name, self.user_id)
                        consecutive_errors = 0
                        await sleep(sleep_time)
                    except CancelledError:
                        raise
                    except Exception as e:
                        consecutive_errors += 1
                        logger.error(f"خطا در دنس مداوم ربات (تلاشِ {consecutive_errors}): {e}")
                        if consecutive_errors >= 10:
                            logger.error("۱۰ بار پشتِ‌سرهم دنسِ مداوم شکست خورد — حلقه متوقف شد.")
                            return
                        await sleep(min(3.0 * consecutive_errors, 15.0))
            except CancelledError:
                logger.info("دنس مداوم ربات لغو شد.")

        self.dance_tasks[self.user_id] = create_task(new_emote_loop())

    async def cmd_emotebot(self, user: User, parts: list):
        admins_lower = [admin.lower() for admin in self.config.get("admin_usernames", [])]
        if user.username.lower() not in admins_lower:
            await self.chat("❌ این دستور مخصوص ادمین\u200cهای ربات است!" if self.config.get("language","fa") == "fa" else "❌ This command is only for bot admins!")
            return

        if len(parts) < 2:
            await self.chat("⚠️ فرمت اشتباه! نام یا شماره دنس را وارد کنید. مثال: !emotebot kpop" if self.config.get("language","fa") == "fa" else "⚠️ Wrong format! Enter a dance name or number. Example: !emotebot kpop")
            return

        input_emote = parts[1].strip().lower()

        # !emotebot random on/off -> بات هر ۵ ثانیه خودش یه دنسِ تصادفی (از بینِ دنس‌های شماره‌دار) می‌زنه
        if input_emote == "random":
            if len(parts) < 3 or parts[2].lower() not in ("on", "off"):
                await self.chat("⚠️ استفاده کن از: !emotebot random on یا !emotebot random off" if self.config.get("language","fa") == "fa"
                                 else "⚠️ Use: !emotebot random on or !emotebot random off")
                return
            enabled = parts[2].lower() == "on"
            if self.user_id in self.dance_tasks:
                self.dance_tasks[self.user_id].cancel()
                self.dance_tasks.pop(self.user_id, None)

            if not enabled:
                await self.set_bot_continuous_dance("dance-floss")
                await self.chat("🛑 دنسِ تصادفی خاموش شد — برگشت به دنسِ پیش‌فرض." if self.config.get("language","fa") == "fa"
                                 else "🛑 Random dance turned off — back to the default dance.")
                return

            dance_pool = [v for k, v in self.emotes.items() if k.isdigit()]
            if not dance_pool:
                await self.chat("⚠️ هیچ دنسِ شماره‌داری تو لیست پیدا نشد." if self.config.get("language","fa") == "fa"
                                 else "⚠️ No numbered dances were found in the list.")
                return

            async def random_dance_loop():
                try:
                    while True:
                        await self.highrise.send_emote(random.choice(dance_pool), self.user_id)
                        await sleep(5.0)
                except CancelledError:
                    logger.info("دنس تصادفی ربات لغو شد.")
                except Exception as e:
                    logger.error(f"خطا در دنسِ تصادفیِ ربات: {e}")

            self.dance_tasks[self.user_id] = create_task(random_dance_loop())
            await self.chat("🎲 دنسِ تصادفی روشن شد — هر ۵ ثانیه یه دنسِ جدید." if self.config.get("language","fa") == "fa"
                             else "🎲 Random dance turned on — a new dance every 5 seconds.")
            return

        # پیدا کردن نام رسمی دنس از روی شماره یا نام مستعار
        actual_emote_name = self.emotes.get(input_emote)
        
        if not actual_emote_name and input_emote in self.emotes.values():
            actual_emote_name = input_emote

        if not actual_emote_name:
            await self.chat("❌ دنس یا شماره وارد شده در لیست دنس\u200cهای ربات پیدا نشد!" if self.config.get("language","fa") == "fa" else "❌ The dance or number you entered wasn't found in the bot's dance list!")
            return

        await self.set_bot_continuous_dance(actual_emote_name)
        await self.chat((f"✅ دنس ربات روی حالت تکرار همیشگی (Loop) تنظیم شد: [{input_emote}]" if self.config.get("language","fa") == "fa" else f"✅ Bot dance set to continuous loop mode: [{input_emote}]"))
        logger.info(f"دنس مداوم ربات به {actual_emote_name} توسط {user.username} تغییر کرد.")

async def handle_ping(request):
    return aiohttp.web.Response(text="Bot is Alive!")

async def start_background_web_server():
    try:
        app = aiohttp.web.Application()
        app.router.add_get('/', handle_ping)
        runner = aiohttp.web.AppRunner(app)
        await runner.setup()
        port = int(os.getenv("PORT", 8080))
        site = aiohttp.web.TCPSite(runner, '0.0.0.0', port)
        await site.start()
        logger.info(f"وب‌سرور زنده نگهدارنده روی پورت {port} فعال شد.")
    except Exception as e:
        logger.error(f"خطا در اجرای وب‌سرور پس‌زمینه: {e}")
    
# ۲. تابع اصلی اجرای ربات (نسخه ضدضربه و مجهز به کنترل خطای تسک‌ها)
async def main():
    import os
    import asyncio
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer
    
    logger.info("تلاش برای بارگذاری متغیرهای محیطی...")
    room_id = os.getenv("ROOM_ID", "67e879221b70dc28e3343ac7")
    api_token = os.getenv("API_TOKEN", "76e900c3170cfd0e607722cf56180a6b342efe18c7c4efd8ecc78b36e7eaf8b8")
    
    if not room_id or not api_token:
        logger.error("ROOM_ID یا API_TOKEN تنظیم نشده‌اند.")
        return
    
    logger.info(f"ROOM_ID: {room_id}")
    logger.info(f"API_TOKEN: ****{api_token[-4:] if len(api_token) >= 4 else '****'} (برای امنیت کامل نمایش داده نمیشه)")

    # ساختار وب‌سرور داخلی و سبک پایتون
    class PingHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(b"Bot is Alive!")
        def log_message(self, format, *args):
            return

    def run_web_server():
        try:
            port = int(os.getenv("PORT", 8080))
            server = HTTPServer(('0.0.0.0', port), PingHandler)
            logger.info(f"وب‌سرور زنده نگهدارنده روی پورت {port} فعال شد.")
            server.serve_forever()
        except Exception as e:
            logger.error(f"خطا در اجرای وب‌سرور پس‌زمینه: {e}")

    # اجرای وب‌سرور در یک نخ کاملاً جداگانه برای جلوگیری از فریز شدن
    web_thread = threading.Thread(target=run_web_server, daemon=True)
    web_thread.start()

    # تنظیم مدیریت خطای جهانی برای asyncio تا هیچ تسکی ربات را کرش نکند
    def handle_exception(loop, context):
        msg = context.get("exception", context["message"])
        logger.error(f"یک تسک پس‌زمینه با خطا مواجه شد اما مهار شد: {msg}")

    try:
        loop = asyncio.get_running_loop()
        loop.set_exception_handler(handle_exception)
    except Exception as le:
        logger.error(f"خطا در تنظیم exception handler: {le}")

    max_reconnect_attempts = 10
    attempt = 0
    while attempt < max_reconnect_attempts:
        try:
            room_id = os.environ.get("ROOM_ID", room_id)
            bot_instance = AdvancedBot()
            bot_def = BotDefinition(room_id=room_id, api_token=api_token, bot=bot_instance)
            logger.info(f"تلاش برای اتصال به سرور Highrise... روم: {room_id}")
            from highrise.__main__ import main as highrise_main
            await highrise_main([bot_def])
            # ⚠️ اگه به اینجا برسیم یعنی اتصال بدون رخ دادن Exception قطع شده (نه یعنی موفق بوده).
            # این دقیقاً همون حالتیه که باعث میشد ربات بی‌وقفه و بدون هیچ فاصله‌ای تلاش کنه:
            # چون قبلاً هیچ افزایش attempt یا sleep‌ای رو این مسیر نداشتیم.
            logger.error(
                "اتصال به هایرایز بدون خطای مشخص و خیلی سریع قطع شد. این معمولاً یعنی "
                "API_TOKEN یا ROOM_ID اشتباهه/نامعتبره (سرور هایرایز درخواست رو رد کرده). "
                "لطفاً یه توکن جدید مستقیم از تنظیمات همون روم بساز و room_id رو هم دوباره چک کن."
            )
        except Exception as e:
            logger.error(f"اتصال WebSocket قطع شد یا خطا داد: {e}")
        try:
            await bot_instance.cleanup_tasks()
        except Exception:
            pass
        attempt += 1
        logger.info(f"انتظار برای اتصال مجدد... تلاش {attempt} از {max_reconnect_attempts}")
        await asyncio.sleep(6)

    logger.error(
        "❌ تعداد تلاش‌های اتصال مجدد به پایان رسید. ربات متوقف شد. "
        "لطفاً API_TOKEN و ROOM_ID رو از تنظیمات همون روم دوباره بساز و چک کن."
    )

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
