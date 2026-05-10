import discord
import re
import gspread
import pytesseract
import requests
from PIL import Image
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import os
import json


print("🔥 BOT START 🔥")

TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise ValueError("❌ DISCORD_TOKEN tidak ditemukan!")

SHEET_URL = "https://docs.google.com/spreadsheets/d/1cHKMzUicBHky3Hf-08y2ZnyLOVGTwIgmo4SlE3eXfRo/edit"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

_google_creds_json = os.getenv("GOOGLE_CREDENTIALS")
if not _google_creds_json:
    raise ValueError("❌ GOOGLE_CREDENTIALS tidak ditemukan! Set environment variable di Railway.")

_creds_data = json.loads(_google_creds_json)
CRED_PATH = os.path.join(BASE_DIR, "credentials.json")
with open(CRED_PATH, "w") as _f:
    json.dump(_creds_data, _f)


TEMP_DIR = os.path.join(BASE_DIR, "temp")
os.makedirs(TEMP_DIR, exist_ok=True)

if os.name == "nt":
    pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
else:
    pytesseract.pytesseract.tesseract_cmd = "tesseract"

scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]

creds = ServiceAccountCredentials.from_json_keyfile_name(CRED_PATH, scope)
client_gsheet = gspread.authorize(creds)
sheet = client_gsheet.open_by_url(SHEET_URL).sheet1

print("✅ SHEETS CONNECTED")

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

# =========================
# 💰 PARSER — FIX #1: Handle 200.000 / 200,000 / 200k / 200rb
# =========================
def parse_text(text):
    text = text.lower().strip()

    # ── Normalise angka format Indonesia ──────────────────────────────
    # Contoh: "200.000" → "200000", "1.500.000" → "1500000"
    # Titik dianggap ribuan jika diikuti tepat 3 digit (bukan desimal)
    def normalize_number(s):
        # Ganti titik-ribuan: 1.500.000 → 1500000
        s = re.sub(r'(\d)\.(\d{3})(?=[\D]|$)', r'\1\2', s)
        # Ganti koma-ribuan: 1,500,000 → 1500000
        s = re.sub(r'(\d),(\d{3})(?=[\D]|$)', r'\1\2', s)
        return s

    text_norm = normalize_number(text)

    # Pola: angka (opsional desimal) diikuti satuan opsional
    match = re.search(
        r'(\d+(?:[.,]\d+)?)\s*(rb|ribu|k|jt|juta|m|b|t)?',
        text_norm
    )
    if not match:
        return None

    # Bersihkan sisa koma/titik desimal jika ada
    raw_num = match.group(1).replace(",", ".").replace(".", "")
    nominal = float(raw_num) if raw_num else 0
    satuan  = match.group(2)

    multiplier = {
        "rb":   1_000,
        "ribu": 1_000,
        "k":    1_000,
        "jt":   1_000_000,
        "juta": 1_000_000,
        "m":    1_000_000_000,
        "b":    1_000_000_000,
        "t":    1_000_000_000_000,
    }

    if satuan in multiplier:
        nominal *= multiplier[satuan]

    nominal = int(nominal)

    # Kategori
    if any(x in text for x in ["makan", "kopi", "nasi", "minum", "snack"]):
        kategori = "Makanan"
    elif any(x in text for x in ["gojek", "grab", "bensin", "ojek", "parkir"]):
        kategori = "Transport"
    elif any(x in text for x in ["gaji", "bonus", "jual", "pendapatan", "transfer masuk"]):
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
    data  = sheet.get_all_records()
    today = datetime.now().strftime("%Y-%m-%d")
    masuk = keluar = 0
    for row in data:
        if today in str(row.get("Tanggal", "")):
            masuk  += clean_amount(row.get("Pendapatan"))
            keluar += clean_amount(row.get("Pengeluaran"))
    return masuk, keluar


def get_month_year(month, year):
    data   = sheet.get_all_records()
    target = f"{year}-{int(month):02d}"
    masuk  = keluar = 0
    for row in data:
        if target in str(row.get("Tanggal", "")):
            masuk  += clean_amount(row.get("Pendapatan"))
            keluar += clean_amount(row.get("Pengeluaran"))
    return masuk, keluar


def get_specific_date(full_date):
    data  = sheet.get_all_records()
    masuk = keluar = 0
    for row in data:
        if full_date == str(row.get("Tanggal", "")).strip():
            masuk  += clean_amount(row.get("Pendapatan"))
            keluar += clean_amount(row.get("Pengeluaran"))
    return masuk, keluar


# =========================
# FIX #3: Insert baris SEBELUM baris TOTAL
# =========================
def get_insert_row() -> int:
    """
    Cari baris TOTAL dengan deteksi yang tepat:
    Scan kolom A s/d E, cari baris yang salah satu kolomnya persis "TOTAL".
    Ini menghindari false-positive dari kata 'total' di tengah kalimat catatan.
    """
    all_rows = sheet.get_all_values()
    for i, row in enumerate(all_rows):
        # Cek setiap sel di baris, apakah ada yang persis "TOTAL" (bukan mengandung)
        for cell in row[:5]:  # kolom A-E saja
            if cell.strip().upper() == "TOTAL":
                return i + 1  # gspread 1-indexed: insert di sini → TOTAL geser ke bawah
    # Tidak ada baris TOTAL → sisipkan setelah baris terakhir yang ada datanya
    for i in range(len(all_rows) - 1, -1, -1):
        if any(c.strip() for c in all_rows[i]):
            return i + 2
    return len(all_rows) + 1


def insert_data_row(row_data: list):
    """
    Sisipkan satu baris data di posisi yang benar (sebelum TOTAL).
    """
    target_row = get_insert_row()
    sheet.insert_row(row_data, target_row)


# =========================
# FIX #2: Proses satu baris transaksi (helper)
# =========================
def process_single_line(line: str) -> dict | None:
    """
    Proses satu baris teks transaksi.
    Return dict jika berhasil, None jika bukan transaksi.
    """
    line = line.strip().lower()
    if not (line.startswith("masuk") or line.startswith("keluar")):
        return None

    tipe   = "Pendapatan" if line.startswith("masuk") else "Pengeluaran"
    result = parse_text(line)
    if not result:
        return None

    nominal, kategori = result
    tanggal           = datetime.now().strftime("%Y-%m-%d")
    pendapatan        = nominal if tipe == "Pendapatan" else ""
    pengeluaran       = nominal if tipe == "Pengeluaran" else ""

    insert_data_row([tanggal, kategori, pendapatan, pengeluaran, line])

    return {"tipe": tipe, "nominal": nominal, "kategori": kategori}


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

    text = message.content.strip()
    text_lower = text.lower()

    # =========================
    # HELP
    # =========================
    if text_lower.startswith("!help"):
        await message.channel.send(
            "📘 **PANDUAN BOT KEUANGAN**\n\n"
            "💸 **INPUT TRANSAKSI (satu atau banyak baris)**\n"
            "```\n"
            "keluar kopi 20rb\n"
            "masuk gaji 5jt\n"
            "keluar 200.000\n"
            "masuk 1.500.000\n"
            "keluar bensin 50000\n"
            "masuk bonus 300k\n"
            "```\n"
            "💰 **SATUAN YANG DIDUKUNG**\n"
            "• `k` / `rb` / `ribu` = ×1.000\n"
            "• `jt` / `juta` = ×1.000.000\n"
            "• `m` / `b` = ×1.000.000.000\n"
            "• `t` = ×1.000.000.000.000\n"
            "• Format titik ribuan: `200.000`, `1.500.000` ✅\n\n"
            "📊 **COMMAND LAPORAN**\n"
            "• `!today` — transaksi hari ini\n"
            "• `!bulan` — bulan ini\n"
            "• `!bulan 4` — April tahun ini\n"
            "• `!bulan 4 2025` — April 2025\n"
            "• `!tanggal 2026-04-26` — tanggal spesifik\n\n"
            "📸 **STRUK / FOTO**\n"
            "Kirim gambar + tulis `masuk` atau `keluar`"
        )
        return

    # =========================
    # TODAY
    # =========================
    if text_lower.startswith("!today"):
        masuk, keluar = get_today()
        saldo = masuk - keluar
        await message.channel.send(
            f"📊 **HARI INI**\n"
            f"💰 Masuk : Rp {masuk:,}\n"
            f"💸 Keluar: Rp {keluar:,}\n"
            f"📉 Saldo : Rp {saldo:,}"
        )
        return

    # =========================
    # BULAN
    # =========================
    if text_lower.startswith("!bulan"):
        try:
            parts = text_lower.split()
            if len(parts) == 1:
                now   = datetime.now()
                masuk, keluar = get_month_year(now.month, now.year)
                label = "BULAN INI"
            elif len(parts) == 2:
                month = parts[1]
                year  = datetime.now().year
                masuk, keluar = get_month_year(month, year)
                label = f"{month}/{year}"
            elif len(parts) == 3:
                month = parts[1]
                year  = parts[2]
                masuk, keluar = get_month_year(month, year)
                label = f"{month}/{year}"
            else:
                raise ValueError

            saldo = masuk - keluar
            await message.channel.send(
                f"📊 **{label}**\n"
                f"💰 Masuk : Rp {masuk:,}\n"
                f"💸 Keluar: Rp {keluar:,}\n"
                f"📉 Saldo : Rp {saldo:,}"
            )
        except Exception:
            await message.channel.send("❌ Format: `!bulan 4 2025`")
        return

    # =========================
    # TANGGAL
    # =========================
    if text_lower.startswith("!tanggal"):
        try:
            tanggal = text_lower.split()[1]
            masuk, keluar = get_specific_date(tanggal)
            saldo = masuk - keluar
            await message.channel.send(
                f"📅 **{tanggal}**\n"
                f"💰 Masuk : Rp {masuk:,}\n"
                f"💸 Keluar: Rp {keluar:,}\n"
                f"📉 Saldo : Rp {saldo:,}"
            )
        except Exception:
            await message.channel.send("❌ Format: `!tanggal 2026-04-26`")
        return

    # =========================
    # OCR (STRUK)
    # =========================
    if message.attachments:
        for attachment in message.attachments:
            if any(ext in attachment.filename.lower() for ext in ['png', 'jpg', 'jpeg']):
                await message.channel.send("📸 Membaca struk...")

                response = requests.get(attachment.url)
                filepath = os.path.join(TEMP_DIR, "temp.jpg")

                with open(filepath, "wb") as f:
                    f.write(response.content)

                img      = Image.open(filepath)
                text_ocr = pytesseract.image_to_string(img)
                nominal  = extract_total(text_ocr)

                os.remove(filepath)

                if not nominal:
                    await message.channel.send("❌ Gagal baca struk, total tidak ditemukan")
                    return

                tipe = "Pendapatan" if "masuk" in text_lower else "Pengeluaran"

                pendapatan  = nominal if tipe == "Pendapatan"  else ""
                pengeluaran = nominal if tipe == "Pengeluaran" else ""

                tanggal = datetime.now().strftime("%Y-%m-%d")
                insert_data_row([
                    tanggal,
                    "Struk",
                    pendapatan,
                    pengeluaran,
                    f"OCR {tipe}"
                ])

                emoji = "💰" if tipe == "Pendapatan" else "💸"
                await message.channel.send(
                    f"{emoji} **STRUK TERDETEKSI**\n"
                    f"💵 Rp {nominal:,}\n"
                    f"📊 {tipe}"
                )
                return

    # =========================
    # FIX #2: INPUT MULTI-BARIS
    # Pisahkan pesan per baris, proses tiap baris
    # =========================
    lines = [l.strip() for l in text.split("\n") if l.strip()]

    # Cek apakah ada minimal satu baris transaksi
    transaksi_lines = [
        l for l in lines
        if l.lower().startswith("masuk") or l.lower().startswith("keluar")
    ]

    if not transaksi_lines:
        await message.channel.send(
            "⚠️ Tidak ada transaksi yang dikenali.\n"
            "Gunakan format: `masuk` / `keluar` diikuti nominal.\n"
            "Ketik `!help` untuk panduan lengkap."
        )
        return

    # Proses semua baris transaksi
    hasil    = []
    gagal    = []

    for line in transaksi_lines:
        result = process_single_line(line)
        if result:
            emoji = "💰" if result["tipe"] == "Pendapatan" else "💸"
            hasil.append(
                f"{emoji} **{result['tipe']}** | {result['kategori']} | Rp {result['nominal']:,}"
            )
        else:
            gagal.append(f"❌ Gagal baca: `{line}`")

    # Susun balasan
    reply_parts = []

    if hasil:
        jumlah = len(hasil)
        reply_parts.append(f"✅ **{jumlah} transaksi dicatat:**\n" + "\n".join(hasil))

    if gagal:
        reply_parts.append("\n".join(gagal))

    await message.channel.send("\n\n".join(reply_parts))


client.run(TOKEN)
