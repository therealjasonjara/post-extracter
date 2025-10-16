import pandas as pd
from bs4 import BeautifulSoup
import re
import unicodedata
import os
from ftfy import fix_text
from tqdm import tqdm
from urllib.parse import urlparse # Ensure urlparse is imported

ROW_LIMIT = None

def fix_mojibake(text):
    """
    Fixes mojibake (garbled text due to incorrect encoding) in a given string.
    Uses the ftfy library for robust fixing.
    """
    if pd.isna(text):
        return text
    try:
        return fix_text(text)
    except Exception:
        # Return original text if fixing fails to prevent data loss
        return text

def final_unicode_cleanup(text):
    """
    Performs a final unicode cleanup, including fixing mojibake and normalizing
    unicode characters to their canonical composed form (NFC).
    """
    if pd.isna(text):
        return text
    try:
        text = fix_text(text)
        text = unicodedata.normalize("NFC", text)
        return text
    except Exception:
        # Return original text if cleanup fails
        return text

def slugify(text):
    """
    Converts a string into a URL-friendly slug.
    Removes non-ASCII characters, converts to lowercase, replaces spaces with hyphens,
    and removes leading numbers.
    """
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    slug = re.sub(r"[\s_-]+", "-", text)
    return re.sub(r"^\d+-*", "", slug)

def clean_html(raw_html):
    """
    Cleans raw HTML by extracting text content from paragraphs and other tags.
    Returns a string with paragraphs joined by double newlines.
    """
    if isinstance(raw_html, bytes):
        raw_html = raw_html.decode('utf-8', errors='ignore')
    soup = BeautifulSoup(str(raw_html), "html.parser")
    # Extract text from all <p> tags, preserving internal spacing and replacing non-breaking spaces
    paragraphs = [p.get_text(" ", strip=True).replace("\u00A0", " ") for p in soup.find_all("p")]
    if paragraphs:
        return "\n\n".join(paragraphs)
    # If no paragraphs, get all text from the soup
    return soup.get_text(" ", strip=True).replace("\u00A0", " ")

def remove_leading_numbering(text):
    """
    Removes common leading numbering patterns (e.g., "1. ", "2- ", "3) ") from a string.
    """
    return re.sub(r"^\s*\d+\s*[\.\-\)\:]*\s*", "", text)

def transform_html_body(raw_html):
    """
    Transforms the main HTML body content:
    - Removes WordPress comment tags.
    - Replaces non-breaking spaces.
    - Unwraps <strong> tags within <h2>, <h3>, <p>.
    - Wraps <p> content in <span> with font-size:14px.
    - Processes <h2> tags for table of contents (TOC) generation (adds IDs, styling).
    - Wraps <h3> content in <span> with font-size:18px.
    - Converts image source URLs to relative filenames.
    - Converts all <a> tag hrefs to relative paths.
    - Inserts a generated Table of Contents at the beginning if <h2> tags are found.
    """
    if pd.isna(raw_html):
        return raw_html
    html = raw_html.decode('utf-8', errors='ignore') if isinstance(raw_html, bytes) else str(raw_html)
    html = re.sub(r'<!--\s*\/?wp:[^>]*-->', '', html) # Remove WordPress comment tags
    soup = BeautifulSoup(html, "html.parser")

    # Replace non-breaking spaces
    for element in soup.find_all(string=True):
        if "\xa0" in element:
            element.replace_with(element.replace("\xa0", " "))

    # Unwrap <strong> tags within specific elements
    for tag in soup.find_all(["h2", "h3", "p"]):
        for strong in tag.find_all("strong"):
            strong.unwrap()

    # Apply font-size to <p> tags
    for p in soup.find_all("p"):
        text = p.get_text(" ", strip=True)
        p.clear() # Clear existing content
        span = soup.new_tag("span", style="font-size:14px;")
        span.string = text
        p.append(span)

    toc_items = []
    # Process <h2> tags for TOC
    for h2 in soup.find_all("h2"):
        text = h2.get_text(strip=True)
        clean_text = remove_leading_numbering(text)
        slug = slugify(clean_text)
        h2.clear()
        h2["id"] = slug # Add ID for anchor links
        h2["style"] = "font-size: 24px; color:#000000;"
        b = soup.new_tag("b")
        b.string = text
        h2.append(b)
        toc_items.append((slug, clean_text))

    # Apply font-size to <h3> tags
    for h3 in soup.find_all("h3"):
        text = h3.get_text(strip=True)
        h3.clear()
        span = soup.new_tag("span", style="font-size:18px;")
        span.string = text
        h3.append(span)

    # Logic for relative image links:
    # Iterates through <img> tags and converts absolute URLs in 'src' to just the filename.
    for img_tag in soup.find_all("img"):
        if "src" in img_tag.attrs:
            img_url = img_tag["src"]
            try:
                # Parse the URL to get the path, then extract the base filename
                parsed_url = urlparse(img_url)
                filename = os.path.basename(parsed_url.path)
                if filename:
                    img_tag["src"] = filename # Update src to be just the filename
            except Exception:
                # In case of any error during URL parsing, leave the src as is
                pass

    # --- START OF MODIFICATION FOR ALL LINKS ---
    # Iterate through <a> tags and convert absolute URLs in 'href' to relative paths.
    for a_tag in soup.find_all("a"):
        if "href" in a_tag.attrs:
            link_url = a_tag["href"]
            try:
                parsed_url = urlparse(link_url)
                # We want the path part of the URL for relative links
                relative_path = parsed_url.path
                if relative_path:
                    a_tag["href"] = relative_path
            except Exception:
                # In case of any error during URL parsing, leave the href as is
                pass
    # --- END OF MODIFICATION FOR ALL LINKS ---

    # Insert Table of Contents if items were found
    if toc_items:
        toc_html = '<div style="background-color: #f9f9f9; padding: 16px; border-radius: 8px; margin-bottom: 20px;"><strong>Table of Contents</strong>'
        toc_html += '<ol style="padding-left: 20px; margin-top: 8px; line-height: 1.8;">'
        for slug, text in toc_items:
            toc_html += f'<li><a href="#{slug}">{text}</a></li>'
        toc_html += '</ol></div>'
        toc_soup = BeautifulSoup(toc_html, "html.parser")
        soup.insert(0, toc_soup) # Insert TOC at the beginning of the body

    # The previous unwrap for <a> tags has been removed to allow href modification.
    # If the intent was to keep the text but remove the link functionality,
    # that would require a different approach (e.g., replacing <a> with <span>).
    # For now, <a> tags are kept with relative hrefs.

    return str(soup) # Return the modified HTML as a string

def clean_content_column_in_batches(input_csv_path, output_csv_path, batch_size=100):
    """
    Processes a CSV file in batches to clean and transform specified columns.
    - Filters out 'draft' status rows.
    - Applies mojibake fixing and HTML cleaning to 'content output' column.
    - Applies mojibake fixing and HTML body transformation to 'body (html code without cms links)' column.
    - Applies final unicode cleanup to all object type columns.
    - Saves the processed data to a new CSV file.
    """
    # Remove output file if it already exists to ensure a clean start
    if os.path.exists(output_csv_path):
        os.remove(output_csv_path)

    first_batch = True
    # Calculate total rows for tqdm progress bar
    total_rows = sum(1 for _ in open(input_csv_path, encoding='utf-8')) - 1 # Subtract 1 for header
    with tqdm(total=total_rows, desc="Processing rows", unit="rows", colour="green") as pbar:
        # Read CSV in chunks (batches)
        for chunk in pd.read_csv(input_csv_path, encoding='utf-8', chunksize=batch_size):
            df = chunk.copy() # Work on a copy of the chunk

            # Normalize column names to lowercase and strip whitespace
            df.columns = [col.strip().lower() for col in df.columns]

            # Filter out rows where 'status' is 'draft' (case-insensitive, whitespace-stripped)
            if "status" in df.columns:
                df = df[df["status"].astype(str).str.strip().str.lower() != "draft"]
                df = df.drop(columns=["status"]) # Drop the status column after filtering

            # Process 'content output (non-html format: content body)' column
            content_col = "content output  (non-html format: content body)"
            if content_col in df.columns:
                df[content_col] = df[content_col].apply(fix_mojibake).apply(clean_html)

            # Process 'body (html code without cms links)' column
            html_col = "body (html code without cms links)"
            if html_col in df.columns:
                df[html_col] = df[html_col].apply(fix_mojibake).apply(transform_html_body)

            # Remove any image-related columns that were previously handled by download functions
            columns_to_drop_if_exist = [
                "all images"
            ]

            for col_name in columns_to_drop_if_exist:
                col_lower = col_name.lower() # Ensure we check the normalized column name
                if col_lower in df.columns:
                    df = df.drop(columns=[col_lower])

            # Apply final unicode cleanup to all object (string) columns
            for col in df.select_dtypes(include=["object"]).columns:
                df[col] = df[col].apply(final_unicode_cleanup)

            # Save processed batch to output CSV
            # 'mode='a'' for append, 'header=first_batch' to write header only once
            df.to_csv(output_csv_path, index=False, mode='a', header=first_batch, encoding='utf-8')
            first_batch = False # After the first batch, subsequent writes won't include header
            pbar.update(len(df)) # Update progress bar

    print(f"\n✅ All batches processed. Cleaned content saved to: {output_csv_path}")

# Define input and output file paths
input_path = "ATH-US-Export.csv"
output_path = "ATH-US-Export-Cleaned-CSV-Only.csv" # Changed output filename

# Run the batch processing function
clean_content_column_in_batches(input_path, output_path, batch_size=50)
