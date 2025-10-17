import pandas as pd
from bs4 import BeautifulSoup
import re
import unicodedata
import os
import requests
from urllib.parse import urlparse
from ftfy import fix_text
from tqdm import tqdm

ROW_LIMIT = None

def fix_mojibake(text):
    if pd.isna(text):
        return text
    try:
        return fix_text(text)
    except Exception:
        return text

def final_unicode_cleanup(text):
    if pd.isna(text):
        return text
    try:
        text = fix_text(text)
        text = unicodedata.normalize("NFC", text)
        return text
    except Exception:
        return text

def slugify(text):
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    return re.sub(r"[\s_-]+", "-", text)

def clean_html(raw_html):
    if isinstance(raw_html, bytes):
        raw_html = raw_html.decode('utf-8', errors='ignore')
    soup = BeautifulSoup(str(raw_html), "html.parser")
    paragraphs = [p.get_text(" ", strip=True).replace("\u00A0", " ") for p in soup.find_all("p")]
    if paragraphs:
        return "\n\n".join(paragraphs)
    return soup.get_text(" ", strip=True).replace("\u00A0", " ")

def remove_leading_numbering(text):
    return re.sub(r"^\s*\d+\s*[\.\-\)\:]*\s*", "", text)

def transform_html_body(raw_html):
    if pd.isna(raw_html):
        return raw_html
    html = raw_html.decode('utf-8', errors='ignore') if isinstance(raw_html, bytes) else str(raw_html)
    html = re.sub(r'<!--\s*\/?wp:[^>]*-->', '', html)
    soup = BeautifulSoup(html, "html.parser")
    for element in soup.find_all(string=True):
        if "\xa0" in element:
            element.replace_with(element.replace("\xa0", " "))
    for tag in soup.find_all(["h2", "h3", "p"]):
        for strong in tag.find_all("strong"):
            strong.unwrap()
    for p in soup.find_all("p"):
        text = p.get_text(" ", strip=True)
        p.clear()
        span = soup.new_tag("span", style="font-size:14px;")
        span.string = text
        p.append(span)
    toc_items = []
    for h2 in soup.find_all("h2"):
        text = h2.get_text(strip=True)
        clean_text = remove_leading_numbering(text)
        slug = slugify(clean_text)
        h2.clear()
        h2["id"] = slug
        h2["style"] = "font-size: 24px; color:#000000;"
        b = soup.new_tag("b")
        b.string = text
        h2.append(b)
        toc_items.append((slug, clean_text))
    for h3 in soup.find_all("h3"):
        text = h3.get_text(strip=True)
        h3.clear()
        span = soup.new_tag("span", style="font-size:18px;")
        span.string = text
        h3.append(span)

    # Logic for relative image links
    for img_tag in soup.find_all("img"):
        if "src" in img_tag.attrs:
            img_url = img_tag["src"]
            try:
                parsed_url = urlparse(img_url)
                filename = os.path.basename(parsed_url.path)
                if filename:
                    img_tag["src"] = filename
            except Exception:
                pass

    if toc_items:
        toc_html = '<div style="background-color: #f9f9f9; padding: 16px; border-radius: 8px; margin-bottom: 20px;"><strong>Table of Contents</strong>'
        toc_html += '<ol style="padding-left: 20px; margin-top: 8px; line-height: 1.8;">'
        for slug, text in toc_items:
            toc_html += f'<li><a href="#{slug}">{text}</a></li>'
        toc_html += '</ol></div>'
        toc_soup = BeautifulSoup(toc_html, "html.parser")
        soup.insert(0, toc_soup)
    for a_tag in soup.find_all("a"):
        a_tag.insert_before(" ")
        a_tag.insert_after(" ")
        a_tag.unwrap()

    return str(soup)

def download_images_from_html_column(df, html_column, base_folder="DownloadedImages"):
    with tqdm(total=len(df), desc=f"Downloading images from {html_column}", unit="row", colour="yellow") as pbar:
        for idx, row in df.iterrows():
            html_content = row.get(html_column)
            title = row.get("name")
            if pd.isna(html_content) or not str(html_content).strip():
                pbar.update(1)
                continue
            if pd.isna(title) or not str(title).strip():
                title = f"untitled-row-{idx}"
            slug = slugify(title)
            article_folder = os.path.join(base_folder, slug)
            os.makedirs(article_folder, exist_ok=True)
            soup = BeautifulSoup(str(html_content), "html.parser")
            for img_idx, img_tag in enumerate(soup.find_all("img")):
                img_url = img_tag.get("src")
                if not img_url:
                    continue
                img_url = str(img_url).strip()
                if not img_url or img_url.lower().startswith("data:"):
                    continue
                try:
                    parsed_url = urlparse(img_url)
                    if parsed_url.scheme.lower() not in {"http", "https"}:
                        continue
                    filename = os.path.basename(parsed_url.path) or f"embedded_{idx}_{img_idx}.jpg"
                except Exception:
                    filename = f"embedded_{idx}_{img_idx}.jpg"
                save_path = os.path.join(article_folder, filename)
                try:
                    response = requests.get(img_url.strip(), timeout=30)
                    response.raise_for_status()
                    with open(save_path, "wb") as f:
                        f.write(response.content)
                except Exception:
                    continue
            pbar.update(1)

def download_and_replace_with_filename(df, image_column, base_folder="DownloadedImages", hero_mode=False):
    updated_filenames = []
    with tqdm(total=len(df), desc=f"Downloading {image_column}", unit="file", colour="cyan") as pbar:
        for idx, row in df.iterrows():
            image_url = row.get(image_column)
            title = row.get("name")
            if pd.isna(image_url) or not str(image_url).strip():
                updated_filenames.append("")
                pbar.update(1)
                continue
            if pd.isna(title) or not str(title).strip():
                title = f"untitled-row-{idx}"
            slug = slugify(title)
            article_folder = os.path.join(base_folder, slug)
            target_folder = os.path.join(article_folder, "HEROIMAGE") if hero_mode else article_folder
            os.makedirs(target_folder, exist_ok=True)
            try:
                parsed_url = urlparse(str(image_url).strip())
                filename = os.path.basename(parsed_url.path) or f"{slug}_{idx}.jpg"
            except Exception:
                filename = f"{slug}_{idx}.jpg"
            save_path = os.path.join(target_folder, filename)
            try:
                response = requests.get(image_url.strip(), timeout=30)
                response.raise_for_status()
                with open(save_path, "wb") as f:
                    f.write(response.content)
                updated_filenames.append(filename)
            except Exception:
                updated_filenames.append("")
            pbar.update(1)
    df[image_column] = updated_filenames

def download_all_images(df, image_column, base_folder="DownloadedImages"):
    total_images = sum(len(str(row.get(image_column)).split("|")) for _, row in df.iterrows() if pd.notna(row.get(image_column)) and str(row.get(image_column)).strip())
    with tqdm(total=total_images, desc=f"Downloading {image_column}", unit="img", colour="magenta") as pbar:
        for idx, row in df.iterrows():
            image_urls = row.get(image_column)
            title = row.get("name")
            if pd.isna(image_urls) or not str(image_urls).strip():
                continue
            if pd.isna(title) or not str(title).strip():
                title = f"untitled-row-{idx}"
            slug = slugify(title)
            article_folder = os.path.join(base_folder, slug)
            os.makedirs(article_folder, exist_ok=True)
            urls = [url.strip() for url in str(image_urls).split("|") if url.strip()]
            for i, url in enumerate(urls):
                try:
                    parsed_url = urlparse(url)
                    filename = os.path.basename(parsed_url.path) or f"all_image_{idx}_{i}.jpg"
                except Exception:
                    filename = f"all_image_{idx}_{i}.jpg"
                save_path = os.path.join(article_folder, filename)
                try:
                    response = requests.get(url, timeout=30)
                    response.raise_for_status()
                    with open(save_path, "wb") as f:
                        f.write(response.content)
                except Exception:
                    pass
                pbar.update(1)

def process_single_batch(df_batch, base_folder="DownloadedImages"):
    df = df_batch.copy()
    df.columns = [col.strip().lower() for col in df.columns]
    if "status" in df.columns:
        df = df.drop(columns=["status"])
    content_col = "content output  (non-html format: content body)"
    if content_col in df.columns:
        df[content_col] = df[content_col].apply(fix_mojibake).apply(clean_html)
    html_col = "body (html code without cms links)"
    if html_col in df.columns:
        df[html_col] = df[html_col].apply(fix_mojibake)
        download_images_from_html_column(df, html_col, base_folder=base_folder)
        df[html_col] = df[html_col].apply(transform_html_body)
    image_columns = [
        ("articledetailsheroimage (extracted main image from cms)", True),
        ("articlepreviewimage (extracted main image from cms)", False),
        ("articlepreviewimagemedium (extracted main image from cms)", False),
    ]
    for col, hero_mode in image_columns:
        col_lower = col.lower()
        if col_lower in df.columns:
            download_and_replace_with_filename(df, col_lower, base_folder=base_folder, hero_mode=hero_mode)
    all_images_col = "all images"
    if all_images_col in df.columns:
        download_all_images(df, all_images_col, base_folder=base_folder)
        df = df.drop(columns=[all_images_col])
    for col in df.select_dtypes(include=["object"]).columns:
        df[col] = df[col].apply(final_unicode_cleanup)
    return df

def clean_content_column_in_batches(input_csv_path, output_csv_path, batch_size=30):
    if os.path.exists(output_csv_path):
        os.remove(output_csv_path)
    full_df = pd.read_csv(input_csv_path, encoding='utf-8').reset_index(drop=True)
    full_df["__original_index"] = full_df.index
    total_rows = len(full_df)
    processed_indices = set()
    processed_batches = []
    with tqdm(total=total_rows, desc="Processing rows", unit="rows", colour="green") as pbar:
        for start in range(0, total_rows, batch_size):
            end = min(start + batch_size, total_rows)
            batch_df = full_df.iloc[start:end].copy()
            actual_new_rows = end - start
            if len(batch_df) < batch_size and processed_indices:
                needed = batch_size - len(batch_df)
                top_up_indices = [idx for idx in sorted(processed_indices) if idx < start][:needed]
                if len(top_up_indices) < needed:
                    remaining_needed = needed - len(top_up_indices)
                    additional = [idx for idx in sorted(processed_indices) if idx not in top_up_indices][:remaining_needed]
                    top_up_indices.extend(additional)
                if top_up_indices:
                    top_up_df = full_df.iloc[top_up_indices].copy()
                    batch_df = pd.concat([batch_df, top_up_df], ignore_index=True)
            try:
                processed_batch = process_single_batch(batch_df, base_folder="DownloadedImages")
            except Exception as exc:
                print(f"❌ Failed to process rows {list(range(start, end))}: {exc}")
                continue
            processed_batches.append(processed_batch)
            processed_indices.update(range(start, end))
            pbar.update(actual_new_rows)
    missing_indices = sorted(set(range(total_rows)) - processed_indices)
    attempt = 1
    while missing_indices:
        print(f"\n🔁 Reprocessing {len(missing_indices)} rows (attempt {attempt})...")
        reprocess_df = full_df.iloc[missing_indices].copy()
        for start in range(0, len(reprocess_df), batch_size):
            end = min(start + batch_size, len(reprocess_df))
            sub_batch = reprocess_df.iloc[start:end].copy()
            primary_indices = missing_indices[start:end]
            try:
                if len(sub_batch) < batch_size and processed_indices:
                    needed = batch_size - len(sub_batch)
                    sorted_processed = [idx for idx in sorted(processed_indices) if idx not in primary_indices]
                    if len(sorted_processed) < needed:
                        sorted_processed.extend(idx for idx in sorted(processed_indices) if idx not in sorted_processed)
                    top_up_indices = sorted_processed[:needed]
                    if top_up_indices:
                        top_up_df = full_df.iloc[top_up_indices].copy()
                        sub_batch = pd.concat([sub_batch, top_up_df], ignore_index=True)
                processed_batch = process_single_batch(sub_batch, base_folder="DownloadedImages")
            except Exception as exc:
                print(f"❌ Failed to reprocess rows {missing_indices[start:end]}: {exc}")
                continue
            processed_batches.append(processed_batch)
            processed_indices.update(primary_indices)
        new_missing = sorted(set(range(total_rows)) - processed_indices)
        if new_missing == missing_indices:
            break
        missing_indices = new_missing
        attempt += 1
    combined = pd.concat(processed_batches, ignore_index=True) if processed_batches else pd.DataFrame()
    processed_index_values = []
    if "__original_index" in combined.columns:
        combined = combined.sort_values("__original_index").drop_duplicates(subset="__original_index", keep="last")
        processed_index_values = combined["__original_index"].tolist()
        combined = combined.drop(columns=["__original_index"])
    if not processed_index_values:
        processed_index_values = sorted(processed_indices)
    if not combined.empty:
        combined.to_csv(output_csv_path, index=False, encoding='utf-8')
    missing_after_processing = sorted(set(range(total_rows)) - set(processed_index_values))
    if missing_after_processing:
        print(f"\n⚠️ Unable to process rows at indices: {missing_after_processing}")
    else:
        print(f"\n✅ All batches processed. Cleaned content saved to: {output_csv_path}")

input_path = "ATH-US-Export.csv"
output_path = "ATH-US-Export-Cleaned.csv"
clean_content_column_in_batches(input_path, output_path, batch_size=30)
