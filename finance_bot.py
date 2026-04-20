import discord
import re
import gspread
import pytesseract
import requests
from PIL import Image
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import os

print("🔥 BOT START 🔥")

TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise ValueError("❌ DISCORD_TOKEN tidak ditemukan!")

SHEET_URL = "https://docs.google.com/spreadsheets/d/1cHKMzUicBHky3Hf-08y2ZnyLOVGTwIgmo4SlE3eXfRo/edit"

import json

scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]

creds_dict = json.loads(os.getenv("credentials"))
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)

client_gsheet = gspread.authorize(creds)
sheet = client_gsheet.open_by_url(SHEET_URL).sheet1

TEMP_DIR = "temp"
os.makedirs(TEMP_DIR, exist_ok=True)
if os.name == "nt":
    pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
else:
    pytesseract.pytesseract.tesseract_cmd = "tesseract"

print("✅ SHEETS CONNECTED")

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

# =========================
# 💰 PARSER
# =========================
def parse_text(text):
    text = text.lower().replace(",", ".")

    match = re.search(r'(\d+(?:\.\d+)?)\s*(rb|ribu|k|jt|juta|m|b|t)?', text)
    if not match:
        return None

    nominal = float(match.group(1))
    satuan = match.group(2)

    multiplier = {
        "rb": 1_000,
        "ribu": 1_000,
        "k": 1_000,
        "jt": 1_000_000,
        "juta": 1_000_000,
        "m": 1_000_000_000,
        "b": 1_000_000_000,
        "t": 1_000_000_000_000
    }

    if satuan in multiplier:
        nominal *= multiplier[satuan]

    nominal = int(nominal)

    if any(x in text for x in ["makan","kopi","nasi"]):
        kategori = "Makanan"
    elif any(x in text for x in ["gojek","grab","bensin"]):
        kategori = "Transport"
    elif any(x in text for x in ["gaji","bonus","jual","pendapatan"]):
        kategori = "Pendapatan"
    else:
        kategori = "Lainnya"

    return nominal, kategori

# =========================
# CLEAN ANGKA
# =========================
def clean_amount(value):
    if not value:
        return 0
    angka = re.findall(r'\d+', str(value))
    if not angka:
        return 0
    return int("".join(angka))

# =========================
# OCR
# =========================
def extract_total(text):
    for line in text.split("\n"):
        if "total" in line.lower():
            angka = re.findall(r'\d+', line)
            if angka:
                return int("".join(angka))
    return None

# =========================
# REPORT
# =========================
def get_today():
    data = sheet.get_all_records()
    today = datetime.now().strftime("%Y-%m-%d")

    masuk = keluar = 0
    for row in data:
        if today in str(row.get("Tanggal", "")):
            masuk += clean_amount(row.get("Pendapatan"))
            keluar += clean_amount(row.get("Pengeluaran"))

    return masuk, keluar

def get_month_year(month, year):
    data = sheet.get_all_records()
    target = f"{year}-{int(month):02d}"

    masuk = keluar = 0
    for row in data:
        if target in str(row.get("Tanggal", "")):
            masuk += clean_amount(row.get("Pendapatan"))
            keluar += clean_amount(row.get("Pengeluaran"))

    return masuk, keluar

def get_specific_date(full_date):
    data = sheet.get_all_records()

    masuk = keluar = 0
    for row in data:
        if full_date == str(row.get("Tanggal", "")).strip():
            masuk += clean_amount(row.get("Pendapatan"))
            keluar += clean_amount(row.get("Pengeluaran"))

    return masuk, keluar

# =========================
# READY
# =========================
@client.event
async def on_ready():
    print(f"🤖 {client.user} READY")

# =========================
# MAIN
# =========================
@client.event
async def on_message(message):

    if message.author.bot:
        return

    text = message.content.lower().strip()

    # =========================
    # HELP
    # =========================
    if text.startswith("!help"):
        await message.channel.send(
            "📘 **PANDUAN BOT KEUANGAN**\n\n"
            "💸 **INPUT TRANSAKSI**\n"
            "• keluar kopi 20rb\n"
            "• masuk gaji 5jt\n\n"
            "💰 **SATUAN**\n"
            "• k/rb = ribu\n"
            "• jt = juta\n"
            "• m = miliar\n"
            "• t = triliun\n\n"
            "📊 **COMMAND**\n"
            "• !today\n"
            "• !bulan\n"
            "• !bulan 4\n"
            "• !bulan 4 2025\n"
            "• !tanggal 2026-04-26\n\n"
            "📸 **STRUK**\n"
            "Kirim gambar + tulis:\n"
            "• masuk\n"
            "• keluar\n"
        )
        return

    # =========================
    # TODAY
    # =========================
    if text.startswith("!today"):
        masuk, keluar = get_today()
        saldo = masuk - keluar

        await message.channel.send(
            f"📊 HARI INI\n💰 Rp {masuk:,}\n💸 Rp {keluar:,}\n📉 Rp {saldo:,}"
        )
        return

    # =========================
    # BULAN
    # =========================
    if text.startswith("!bulan"):
        try:
            parts = text.split()

            if len(parts) == 1:
                now = datetime.now()
                masuk, keluar = get_month_year(now.month, now.year)
                label = "BULAN INI"

            elif len(parts) == 2:
                month = parts[1]
                year = datetime.now().year
                masuk, keluar = get_month_year(month, year)
                label = f"{month}/{year}"

            elif len(parts) == 3:
                month = parts[1]
                year = parts[2]
                masuk, keluar = get_month_year(month, year)
                label = f"{month}/{year}"

            else:
                raise ValueError

            saldo = masuk - keluar

            await message.channel.send(
                f"📊 {label}\n💰 Rp {masuk:,}\n💸 Rp {keluar:,}\n📉 Rp {saldo:,}"
            )

        except:
            await message.channel.send("❌ Format: !bulan 4 2025")
        return

    # =========================
    # TANGGAL
    # =========================
    if text.startswith("!tanggal"):
        try:
            tanggal = text.split()[1]
            masuk, keluar = get_specific_date(tanggal)
            saldo = masuk - keluar

            await message.channel.send(
                f"📅 {tanggal}\n💰 Rp {masuk:,}\n💸 Rp {keluar:,}\n📉 Rp {saldo:,}"
            )
        except:
            await message.channel.send("❌ Format: !tanggal 2026-04-26")
        return

    # =========================
    # OCR (STRUK)
    # =========================
    if message.attachments:
        for attachment in message.attachments:
            if any(ext in attachment.filename.lower() for ext in ['png','jpg','jpeg']):
                await message.channel.send("📸 Membaca struk...")

                response = requests.get(attachment.url)
                filepath = os.path.join(TEMP_DIR, "temp.jpg")

                with open(filepath, "wb") as f:
                    f.write(response.content)

                img = Image.open(filepath)
                text_ocr = pytesseract.image_to_string(img)
                nominal = extract_total(text_ocr)

                os.remove(filepath)

                if not nominal:
                    await message.channel.send("❌ Gagal baca struk")
                    return

                # =========================
                # DETECT MASUK / KELUAR
                # =========================
                tipe = "Pengeluaran"
                if "masuk" in text:
                    tipe = "Pendapatan"

                if tipe == "Pendapatan":
                    pendapatan = nominal
                    pengeluaran = ""
                else:
                    pendapatan = ""
                    pengeluaran = nominal

                tanggal = datetime.now().strftime("%Y-%m-%d")

                # 🔥 INSERT LANGSUNG (AMAN TANPA FUNCTION)
                all_rows = sheet.get_all_values()
                next_row = max(len(all_rows) + 1, 3)

                sheet.insert_row([
                    tanggal,
                    "Struk",
                    pendapatan,
                    pengeluaran,
                    f"OCR {tipe}"
                ], next_row)

                emoji = "💰" if tipe == "Pendapatan" else "💸"

                await message.channel.send(
                    f"{emoji} STRUK TERDETEKSI\n💵 Rp {nominal:,}\n📊 {tipe}"
                )

                return
    # =========================
    # INPUT TEXT
    # =========================
    if not (text.startswith("masuk") or text.startswith("keluar")):
        await message.channel.send("⚠️ Gunakan: masuk / keluar")
        return

    tipe = "Pendapatan" if text.startswith("masuk") else "Pengeluaran"

    result = parse_text(text)
    if not result:
        await message.channel.send("❌ Nominal tidak ditemukan")
        return

    nominal, kategori = result
    tanggal = datetime.now().strftime("%Y-%m-%d")

    pendapatan = nominal if tipe == "Pendapatan" else ""
    pengeluaran = nominal if tipe == "Pengeluaran" else ""

    sheet.append_row([tanggal, kategori, pendapatan, pengeluaran, text])

    emoji = "💰" if tipe == "Pendapatan" else "💸"

    await message.channel.send(
        f"{emoji} Dicatat!\n📁 {kategori}\n💵 Rp {nominal:,}"
    )

client.run(TOKEN)
