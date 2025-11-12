import streamlit as st
import pandas as pd
import ast
import os
import re
import openpyxl
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
                    "Brand dan model yang tersedia: DAIHATSU, HONDA, MITSUBISHI, SUZUKI, TOYOTA."
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

# ====== FALLBACK EXTRACTION (auto brand detect) ======
def fallback_extract(input_text, df):
    text = input_text.lower()
    brand = None
    tahun = None
    tipe = None

    # cari tahun
    year_match = re.search(r"(20\d{2})", text)
    if year_match:
        tahun = year_match.group(1)

    # cari brand
    for b in df["merk"].str.lower().unique():
        if b in text:
            brand = b
            break

    # cari tipe
    for t in df["tipe_match"].str.lower().unique():
        words = [w for w in text.split() if w.isalpha()]
        if all(word in t for word in words):
            tipe = t
            brand_guess = df.loc[df["tipe_match"].str.lower() == t, "merk"].iloc[0]
            if not brand:
                brand = brand_guess.lower()
            break

    if not tipe:
        for t in df["tipe_match"].str.lower().unique():
            if any(word in t for word in text.split() if word.isalpha()):
                tipe = t
                brand_guess = df.loc[df["tipe_match"].str.lower() == t, "merk"].iloc[0]
                if not brand:
                    brand = brand_guess.lower()
                break

    # deteksi transmisi dari input
    transmisi = None
    if any(k in text for k in ["at", "auto", "matic"]):
        transmisi = "AT"
    elif any(k in text for k in ["mt", "manual"]):
        transmisi = "MT"

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

# ====== UI SETUP ======
st.set_page_config(page_title="New Car Prices 2025", page_icon="🚗", layout="centered")

st.title("🚗 New Car Prices 2025")
st.write("Silakan Input Brand, Tipe, Tahun, dan (opsional) Transmisi Mobil:")
st.caption("Contoh: *toyota avanza 1.3 e 2020* atau *sigra 2025 manual* atau *gran max 2024 automatic*")

user_input = st.text_input("", placeholder="contoh: Kijang Innova 2029")

if st.button("Cari Harga"):
    if not user_input.strip():
        st.warning("Masukkan teks pencarian terlebih dahulu.")
    else:
        # GPT parsing
        brand, tipe, tahun, transmisi = extract_params(user_input)

        # fallback jika GPT gagal
        if not brand or not tipe or not tahun:
            brand, tipe, tahun, transmisi = fallback_extract(user_input, df)

        st.info(
            f"📋 **Hasil Ekstraksi:** "
            f"Brand: **{brand}**, Tipe: **{tipe}**, Tahun: **{tahun}**, Transmisi: **{transmisi or 'Semua'}**"
        )

        # validasi hasil minimal
        if not brand or not tipe or not tahun:
            st.error("❌ Data tidak lengkap. Pastikan input berisi brand, tipe, dan tahun.")
        else:
            brand = brand.strip().lower()
            tipe = tipe.strip().lower()
            tahun = str(tahun).strip()

            # filter dasar
            df_filtered = df[
                (df["merk"].str.lower() == brand)
                & (df["tipe_match"].str.lower().str.contains(tipe))
                & (df["tahun"].astype(str) == tahun)
            ].copy()

            # === Jika tahun tidak ditemukan, tampilkan alternatif yang tersedia ===
            if df_filtered.empty:
                # Cek apakah tipe dan brand-nya ada tapi tahun tidak tersedia
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


            else:
                # tambahkan suffix transmisi
                df_filtered.loc[df_filtered["transmisi"].str.lower() == "automatic", "tipe_label"] = \
                    df_filtered["tipe_match"].str.title() + " A/T"
                df_filtered.loc[df_filtered["transmisi"].str.lower() == "manual", "tipe_label"] = \
                    df_filtered["tipe_match"].str.title() + " M/T"

                # filter berdasarkan transmisi jika user menyebutnya
                if transmisi == "AT":
                    df_filtered = df_filtered[df_filtered["transmisi"].str.lower() == "automatic"]
                elif transmisi == "MT":
                    df_filtered = df_filtered[df_filtered["transmisi"].str.lower() == "manual"]

                # hitung Max = Average + 10%
                df_filtered["max_calc"] = df_filtered["otr_avg"] * 1.10

                # format nilai
                df_filtered["Min"] = df_filtered["otr_min"].apply(format_rupiah)
                df_filtered["Average"] = df_filtered["otr_avg"].apply(format_rupiah)
                df_filtered["Max"] = df_filtered["max_calc"].apply(format_rupiah)
                df_filtered["Harga Baru"] = df_filtered["otr_vm"].apply(format_rupiah)

                result_df = df_filtered[["tipe_label", "Min", "Average", "Max", "Harga Baru"]].drop_duplicates()
                result_df.rename(columns={"tipe_label": "Tipe"}, inplace=True)

                st.markdown("### 💰 On The Road Realisasi New Car 2025")
                st.caption("Sumber data: summary_OTR_with_OTR_VM.xlsx")
                st.dataframe(result_df, use_container_width=True)
