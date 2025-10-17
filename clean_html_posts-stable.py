import pandas as pd
from bs4 import BeautifulSoup
import re
import unicodedata
import os
import requests
from urllib.parse import urlparse
from ftfy import fix_text
from tqdm import tqdm

BATCH_SIZE = 30

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
    for idx, row in df.iterrows():
        html_content = row.get(html_column)
        title = row.get("name")
        
        if pd.isna(html_content) or not str(html_content).strip():
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
            if os.path.exists(save_path):
                continue
            
            try:
                response = requests.get(img_url.strip(), timeout=10)
                response.raise_for_status()
                with open(save_path, "wb") as f:
                    f.write(response.content)
            except Exception:
                continue

def download_and_replace_with_filename(df, image_column, base_folder="DownloadedImages", hero_mode=False):
    updated_filenames = []
    
    for idx, row in df.iterrows():
        image_url = row.get(image_column)
        title = row.get("name")
        
        if pd.isna(image_url) or not str(image_url).strip():
            updated_filenames.append("")
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
    
    df[image_column] = updated_filenames

def download_all_images(df, image_column, base_folder="DownloadedImages"):
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

def process_batch(df_batch):
    """Process a single batch of rows"""
    df = df_batch.copy()
    
    # Normalize column names
    df.columns = [col.strip().lower() for col in df.columns]
    
    # Filter out draft status
    if "status" in df.columns:
        df = df[df["status"].astype(str).str.strip().str.lower() != "draft"]
        df = df.drop(columns=["status"])
    
    # Process content column
    content_col = "content output  (non-html format: content body)"
    if content_col in df.columns:
        df[content_col] = df[content_col].apply(fix_mojibake).apply(clean_html)
    
    # Process HTML body column
    html_col = "body (html code without cms links)"
    if html_col in df.columns:
        df[html_col] = df[html_col].apply(fix_mojibake)
        download_images_from_html_column(df, html_col, base_folder="DownloadedImages")
        df[html_col] = df[html_col].apply(transform_html_body)
    
    # Process image columns
    image_columns = [
        ("articledetailsheroimage (extracted main image from cms)", True),
        ("articlepreviewimage (extracted main image from cms)", False),
        ("articlepreviewimagemedium (extracted main image from cms)", False),
    ]
    
    for col, hero_mode in image_columns:
        col_lower = col.lower()
        if col_lower in df.columns:
            download_and_replace_with_filename(df, col_lower, base_folder="DownloadedImages", hero_mode=hero_mode)
    
    # Process all images column
    all_images_col = "all images"
    if all_images_col in df.columns:
        download_all_images(df, all_images_col, base_folder="DownloadedImages")
        df = df.drop(columns=[all_images_col])
    
    # Final unicode cleanup
    for col in df.select_dtypes(include=["object"]).columns:
        df[col] = df[col].apply(final_unicode_cleanup)
    
    return df

def process_csv_in_batches(input_csv_path, output_csv_path, batch_size=BATCH_SIZE):
    """Main processing function that handles batches and tracks progress"""
    
    # Remove existing output file
    if os.path.exists(output_csv_path):
        os.remove(output_csv_path)
    
    # Read the full CSV to get total count and track indices
    print(f"📖 Reading input file: {input_csv_path}")
    full_df = pd.read_csv(input_csv_path, encoding='utf-8')
    full_df['__batch_index'] = full_df.index
    total_rows = len(full_df)
    
    print(f"📊 Total rows to process: {total_rows}")
    print(f"📦 Batch size: {batch_size}")
    print(f"🔄 Total batches: {(total_rows + batch_size - 1) // batch_size}\n")
    
    processed_indices = set()
    first_batch = True
    
    # Process in batches
    with tqdm(total=total_rows, desc="Processing rows", unit="rows") as pbar:
        for start_idx in range(0, total_rows, batch_size):
            end_idx = min(start_idx + batch_size, total_rows)
            batch_df = full_df.iloc[start_idx:end_idx].copy()
            
            try:
                # Process the batch
                processed_df = process_batch(batch_df)
                
                # Track processed indices
                batch_indices = batch_df['__batch_index'].tolist()
                processed_indices.update(batch_indices)
                
                # Remove tracking column before saving
                if '__batch_index' in processed_df.columns:
                    processed_df = processed_df.drop(columns=['__batch_index'])
                
                # Save to output
                processed_df.to_csv(
                    output_csv_path, 
                    index=False, 
                    mode='a', 
                    header=first_batch, 
                    encoding='utf-8'
                )
                first_batch = False
                
                pbar.update(len(batch_df))
                
            except Exception as e:
                print(f"\n❌ Error processing batch {start_idx}-{end_idx}: {e}")
                pbar.update(len(batch_df))
                continue
    
    print(f"\n✅ Initial processing complete!")
    print(f"📁 Output saved to: {output_csv_path}")
    
    # Check for skipped rows
    all_indices = set(range(total_rows))
    skipped_indices = all_indices - processed_indices
    
    return list(skipped_indices)

def process_skipped_rows(input_csv_path, output_csv_path, skipped_indices):
    """Process rows that were skipped in the initial run"""
    
    if not skipped_indices:
        print("\n✨ No skipped rows detected. All rows processed successfully!")
        return []
    
    print(f"\n⚠️  Detected {len(skipped_indices)} skipped rows")
    print(f"📋 Skipped indices: {sorted(skipped_indices)[:20]}{'...' if len(skipped_indices) > 20 else ''}")
    print(f"\n🔄 Reprocessing skipped rows...\n")
    
    # Read full CSV
    full_df = pd.read_csv(input_csv_path, encoding='utf-8')
    full_df['__batch_index'] = full_df.index
    
    # Read existing output to append to it
    existing_df = pd.read_csv(output_csv_path, encoding='utf-8')
    
    successfully_processed = []
    
    with tqdm(total=len(skipped_indices), desc="Reprocessing skipped rows", unit="rows") as pbar:
        for idx in sorted(skipped_indices):
            try:
                row_df = full_df.iloc[[idx]].copy()
                processed_df = process_batch(row_df)
                
                # Remove tracking column
                if '__batch_index' in processed_df.columns:
                    processed_df = processed_df.drop(columns=['__batch_index'])
                
                # Append to output
                processed_df.to_csv(
                    output_csv_path, 
                    index=False, 
                    mode='a', 
                    header=False, 
                    encoding='utf-8'
                )
                
                successfully_processed.append(idx)
                pbar.update(1)
                
            except Exception as e:
                print(f"\n❌ Error reprocessing row {idx}: {e}")
                pbar.update(1)
                continue
    
    still_skipped = set(skipped_indices) - set(successfully_processed)
    
    if still_skipped:
        print(f"\n⚠️  {len(still_skipped)} rows still could not be processed")
        print(f"📋 Problematic indices: {sorted(still_skipped)}")
    else:
        print(f"\n✅ All skipped rows successfully processed!")
    
    return list(still_skipped)

def main():
    input_path = "ATH-US-Export.csv"
    output_path = "ATH-US-Export-Cleaned.csv"
    
    print("="*60)
    print("🚀 Starting Batch Processing Script")
    print("="*60 + "\n")
    
    # Initial batch processing
    skipped = process_csv_in_batches(input_path, output_path, batch_size=BATCH_SIZE)
    
    # Process skipped rows if any
    if skipped:
        final_skipped = process_skipped_rows(input_path, output_path, skipped)
        
        if final_skipped:
            print(f"\n⚠️  Warning: {len(final_skipped)} rows could not be processed after retry")
            print(f"💾 Saving problematic indices to 'skipped_rows.txt'")
            with open("skipped_rows.txt", "w") as f:
                f.write("\n".join(map(str, sorted(final_skipped))))
    
    print("\n" + "="*60)
    print("🎉 Processing Complete!")
    print("="*60)

if __name__ == "__main__":
    main()