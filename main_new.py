import streamlit as st
import pandas as pd
import ast
import os
import re
import openpyxl
import datetime
from dotenv import load_dotenv
from openai import AzureOpenAI

# ====== KONFIGURASI AZURE OPENAI ======
load_dotenv()
client = AzureOpenAI(
    api_key=os.getenv("AZURE_OPENAI_KEY"),
    api_version=os.getenv("AZURE_OPENAI_VERSION"),
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT")
)
AZURE_MODEL = os.getenv("AZURE_OPENAI_DEPLOYMENT")

# ====== FILE LOG ======
LOG_FILE = "search_log.csv"

def log_search(user_input, brand, tipe, tahun, transmisi, hasil_ditemukan):
    """Simpan log pencarian ke CSV"""
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_entry = pd.DataFrame([{
        "timestamp": timestamp,
        "user_input": user_input,
        "brand": brand,
        "tipe": tipe,
        "tahun": tahun,
        "transmisi": transmisi,
        "hasil_ditemukan": hasil_ditemukan
    }])
    if not os.path.exists(LOG_FILE):
        log_entry.to_csv(LOG_FILE, index=False)
    else:
        log_entry.to_csv(LOG_FILE, mode="a", header=False, index=False)

# ====== GPT EXTRACT PARAMS ======
def extract_params(input_text):
    try:
        resp = client.chat.completions.create(
            model=AZURE_MODEL,
            messages=[
                {"role": "system", "content": (
                    "Ekstrak brand, tipe lengkap, tahun, dan transmisi dari input teks berikut. "
                    "Jawab dalam Python dict format (kutip tunggal):\n"
                    "{'brand':'...', 'tipe':'...', 'tahun':..., 'transmisi':'...'}\n"
                    "Jika tidak ada tahun atau tipe, kosongkan nilainya. "
                    "Untuk transmisi, map ke 'AT'/'MT' bila terdeteksi. "
                    "Sinonim: at/a/t/auto/automatic/matic -> AT; mt/m/t/manual -> MT. "
                    "Brand dan model yang tersedia: DAIHATSU, HONDA, MITSUBISHI, SUZUKI, TOYOTA, HYUNDAI, MAZDA, NISSAN."
                )},
                {"role": "user", "content": input_text}
            ],
            temperature=0,
            max_tokens=150
        )
        d = ast.literal_eval(resp.choices[0].message.content)
        return d.get('brand'), d.get('tipe'), d.get('tahun'), d.get('transmisi')
    except Exception:
        return None, None, None, None

# ====== FALLBACK EXTRACTION ======
def fallback_extract(input_text, df):
    text = input_text.lower()
    brand = None
    tahun = None
    tipe = None

    # cari tahun
    year_match = re.search(r"(20\d{2})", text)
    if year_match:
        tahun = year_match.group(1)

    # deteksi transmisi
    transmisi = None
    if any(k in text for k in ["at", "auto", "matic"]):
        transmisi = "AT"
    elif any(k in text for k in ["mt", "manual"]):
        transmisi = "MT"

    # cari brand berdasarkan kata di teks
    for b in df["merk"].str.lower().unique():
        if b in text:
            brand = b
            break

    # cari tipe
    for t in df["tipe_match"].str.lower().unique():
        if any(word in t for word in text.split()):
            tipe = t
            break

    return brand, tipe, tahun, transmisi

# ====== FORMAT RUPIAH ======
def format_rupiah(value):
    if pd.isnull(value) or value == 0:
        return "-"
    juta = value / 1_000_000
    return f"Rp {juta:,.0f} juta".replace(",", ".")

# ====== LOAD DATA ======
@st.cache_data
def load_data():
    df = pd.read_excel("summary_OTR_with_OTR_VM.xlsx")
    df.columns = df.columns.str.lower().str.strip()
    return df

df = load_data()

# ====== UI ======
st.set_page_config(page_title="New Car Prices 2025", page_icon="🚗", layout="centered")
st.title("🚗 New Car Prices 2025")
st.write("Silakan Input Brand, Tipe, Tahun, dan (opsional) Transmisi Mobil:")
st.caption("Contoh: *toyota avanza 1.3 e 2020* atau *sigra 2025 manual* atau *calya 2025 automatic*")

user_input = st.text_input("", placeholder="contoh: Rush 2024 manual")

if st.button("Cari Harga"):
    if not user_input.strip():
        st.warning("Masukkan teks pencarian terlebih dahulu.")
    else:
        # Parsing via GPT
        brand, tipe, tahun, transmisi = extract_params(user_input)

        # Fallback
        if not brand or not tipe or not tahun:
            brand, tipe, tahun, transmisi = fallback_extract(user_input, df)

        # 🔧 AUTO CORRECT BRAND BERDASARKAN TIPE
        if tipe:
            df_tipe = df[df["tipe_match"].str.lower().str.contains(tipe.lower(), na=False)]
            if not df_tipe.empty:
                brand_correct = df_tipe["merk"].iloc[0]
                if not brand or brand.lower() != brand_correct.lower():
                    brand = brand_correct.lower()

        st.info(
            f"📋 **Hasil Ekstraksi:** "
            f"Brand: **{(brand or '').upper()}**, "
            f"Tipe: **{tipe or '-'}**, "
            f"Tahun: **{tahun or '-'}**, "
            f"Transmisi: **{transmisi or 'Semua'}**"
        )

        # validasi minimum
        if not brand or not tipe or not tahun:
            st.error("❌ Data tidak lengkap. Pastikan input berisi brand, tipe, dan tahun.")
        else:
            brand = brand.strip().lower()
            tipe = tipe.strip().lower()
            tahun = str(tahun).strip()

            # filter utama
            df_filtered = df[
                (df["merk"].str.lower() == brand)
                & (df["tipe_match"].str.lower().str.contains(tipe))
                & (df["tahun"].astype(str) == tahun)
            ].copy()

            # === Jika tahun tidak ditemukan ===
            if df_filtered.empty:
                df_alt = df[
                    (df["merk"].str.lower() == brand)
                    & (df["tipe_match"].str.lower().str.contains(tipe))
                ].copy()

                if not df_alt.empty:
                    tahun_tersedia = sorted(df_alt["tahun"].astype(str).unique())
                    tahun_str = ", ".join(tahun_tersedia)
                    st.warning(
                        f"⚠️ Tipe **{tipe.title()}** tidak tersedia pada tahun **{tahun}**, "
                        f"namun tersedia pada tahun: **{tahun_str}**."
                    )
                else:
                    st.error("🚫 Data tidak ditemukan untuk kombinasi tersebut.")

                # log tetap ditulis meski data kosong
                log_search(user_input, brand, tipe, tahun, transmisi, 0)
                st.stop()

            # ===== FORMAT TABEL =====
            df_filtered.loc[df_filtered["transmisi"].str.lower() == "automatic", "tipe_label"] = \
                df_filtered["tipe_match"].str.title() + " A/T"
            df_filtered.loc[df_filtered["transmisi"].str.lower() == "manual", "tipe_label"] = \
                df_filtered["tipe_match"].str.title() + " M/T"

            # filter transmisi
            if transmisi == "AT":
                df_filtered = df_filtered[df_filtered["transmisi"].str.lower() == "automatic"]
            elif transmisi == "MT":
                df_filtered = df_filtered[df_filtered["transmisi"].str.lower() == "manual"]

            # hitung Max = avg + 10%
            df_filtered["max_calc"] = df_filtered["otr_avg"] * 1.10

            # format angka
            df_filtered["Min"] = df_filtered["otr_min"].apply(format_rupiah)
            df_filtered["Average"] = df_filtered["otr_avg"].apply(format_rupiah)
            df_filtered["Max"] = df_filtered["max_calc"].apply(format_rupiah)
            df_filtered["Harga Baru"] = df_filtered["otr_vm"].apply(format_rupiah)

            result_df = df_filtered[["tipe_label", "Min", "Average", "Max", "Harga Baru"]].drop_duplicates()
            result_df.rename(columns={"tipe_label": "Tipe"}, inplace=True)

            # Tambahkan nomor urut mulai dari 1
            result_df.reset_index(drop=True, inplace=True)
            result_df.index = result_df.index + 1
            result_df.index.name = "No"

            # ===== TAMPILKAN HASIL =====
            st.markdown("### 💰 On The Road Realisasi New Car 2025")
            st.dataframe(result_df, use_container_width=True)

            # ===== LOG PENCARIAN =====
            log_search(user_input, brand, tipe, tahun, transmisi, len(result_df))

# ===== OPSI MELIHAT LOG =====
# st.divider()
# if st.checkbox("📜 Tampilkan Log Pencarian"):
#     if os.path.exists(LOG_FILE):
#         st.dataframe(pd.read_csv(LOG_FILE))
#     else:
#         st.info("Belum ada log pencarian.")
