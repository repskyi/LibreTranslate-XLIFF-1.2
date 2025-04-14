import os
import re
import json
import shutil
import requests
from lxml import etree as ET



def normalize_lang_code(code):
    """
    Normalize language code from XLIFF to LibreTranslate format.
    Examples:
    'en-US' -> 'en' or 'en-us' if supported
    'uk-UA' -> 'uk' or 'uk-ua' if supported
    'zh-Hans' -> 'zh'
    'zh-Hant' -> 'zh'
    """
    if not code:
        return ""
    code = code.lower()
    if code in ("zh-hans", "zh-hant"):
        return "zh"

    # List of supported full language-region codes (customize as needed)
    supported_full_codes = {
        "en-us", "en-gb",
        "es-es",
        "de-de",
        "pl-pl",
        "uk-ua",
        "ru-ru"
    }
    if code in supported_full_codes:
        return code

    # Explicit mappings for common languages (fallback to base language)
    if code.startswith("de"):
        return "de"
    if code.startswith("pl"):
        return "pl"
    if code.startswith("uk"):
        return "uk"
    if code.startswith("ru"):
        return "ru"
    if code.startswith("es"):
        return "es"
    if code.startswith("en"):
        return "en"

    # Default: take only language part before hyphen
    return code.split('-')[0]

import uuid

def separate_tags_with_spaces(text):
    """
    Add spaces between tags and words if they are glued together.
    E.g., 'word<tag>' -> 'word <tag>', '<tag>word' -> '<tag> word'
    """
    # Тег після слова без пробілу
    text = re.sub(r'(\w)(<[^>]+>)', r'\1 \2', text)
    # Тег перед словом без пробілу
    text = re.sub(r'(<[^>]+>)(\w)', r'\1 \2', text)
    # Тег на початку рядка перед словом без пробілу
    text = re.sub(r'^(<[^>]+>)(\w)', r'\1 \2', text)

    # Тег після числа без пробілу
    text = re.sub(r'(\d)(<[^>]+>)', r'\1 \2', text)
    # Тег перед числом без пробілу
    text = re.sub(r'(<[^>]+>)(\d)', r'\1 \2', text)
    # Тег на початку рядка перед числом без пробілу
    text = re.sub(r'^(<[^>]+>)(\d)', r'\1 \2', text)

    # Розділення emoji і слова/числа без пробілу
    emoji_pattern = r"[" \
        "\U0001F300-\U0001F5FF" \
        "\U0001F600-\U0001F64F" \
        "\U0001F680-\U0001F6FF" \
        "\U0001F700-\U0001F77F" \
        "\U0001F780-\U0001F7FF" \
        "\U0001F800-\U0001F8FF" \
        "\U0001F900-\U0001F9FF" \
        "\U0001FA00-\U0001FA6F" \
        "\U0001FA70-\U0001FAFF" \
        "\U00002702-\U000027B0" \
        "\U000024C2-\U0001F251" \
        "\U0001F30D" \
        "]"

    text = re.sub(rf'([\w\d])({emoji_pattern})', r'\1 \2', text)
    text = re.sub(rf'({emoji_pattern})([\w\d])', r'\1 \2', text)
    text = re.sub(rf'^({emoji_pattern})([\w\d])', r'\1 \2', text)
    text = re.sub(rf'([\w\d])({emoji_pattern})$', r'\1 \2', text)

    return text

def replace_protected_elements_with_placeholders(text):
    """
    Replace all <tags> and emojis in text with placeholders {{TAG0}}, {{TAG1}}, etc.
    Returns (new_text, mapping_dict)
    """
    # Pattern for tags with attributes and quotes inside
    tag_pattern = re.compile(r"<[^<>]*(\"[^\"]*\"|'[^']*')?[^<>]*>")
    # Pattern for emojis (basic unicode emoji range)
    emoji_pattern = re.compile(
        "["
        "\U0001F300-\U0001F5FF"  # symbols & pictographs
        "\U0001F600-\U0001F64F"  # emoticons
        "\U0001F680-\U0001F6FF"  # transport & map symbols
        "\U0001F700-\U0001F77F"  # alchemical symbols
        "\U0001F780-\U0001F7FF"  # Geometric Shapes Extended
        "\U0001F800-\U0001F8FF"  # Supplemental Arrows-C
        "\U0001F900-\U0001F9FF"  # Supplemental Symbols and Pictographs
        "\U0001FA00-\U0001FA6F"  # Chess Symbols
        "\U0001FA70-\U0001FAFF"  # Symbols and Pictographs Extended-A
        "\U00002702-\U000027B0"  # Dingbats
        "\U000024C2-\U0001F251"  # Enclosed characters
        "\U0001F30D"              # 🌍 explicitly
        "]+", flags=re.UNICODE
    )

    mapping = {}
    new_text = text
    idx = 0

    # Replace tags
    for match in tag_pattern.finditer(text):
        tag = match.group()
        placeholder = f"{{{{TAG{idx}}}}}"
        mapping[f"TAG{idx}"] = tag
        new_text = new_text.replace(tag, placeholder)
        idx += 1

    # Replace emojis
    emojis = emoji_pattern.findall(new_text)
    for emoji in emojis:
        placeholder = f"{{{{TAG{idx}}}}}"
        mapping[f"TAG{idx}"] = emoji
        new_text = new_text.replace(emoji, placeholder)
        idx += 1

    return new_text, mapping

def restore_tags_from_placeholders(text, mapping):
    """
    Replace placeholders back with original tags, even if they were slightly modified by translator
    """
    for key, tag in mapping.items():
        # Create flexible pattern for TAG0, TAG1, etc.
        pattern = rf"[{{\s]*{key}[\s}}]*"
        regex = re.compile(pattern, re.IGNORECASE)
        # Replace all matches with original tag
        text = regex.sub(tag, text)
    return text

def should_translate(text):
    # Якщо у рядку є хоч один тег - не перекладати
    if re.search(r"<[^>]+>", text):
        return False
    # Якщо у рядку є емодзі - не перекладати
    emoji_pattern = re.compile(
        "["
        "\U0001F300-\U0001F5FF"
        "\U0001F600-\U0001F64F"
        "\U0001F680-\U0001F6FF"
        "\U0001F700-\U0001F77F"
        "\U0001F780-\U0001F7FF"
        "\U0001F800-\U0001F8FF"
        "\U0001F900-\U0001F9FF"
        "\U0001FA00-\U0001FA6F"
        "\U0001FA70-\U0001FAFF"
        "\U00002702-\U000027B0"
        "\U000024C2-\U0001F251"
        "\U0001F30D"
        "]", flags=re.UNICODE
    )
    if emoji_pattern.search(text):
        return False
    # Ігнорувати, якщо лише цифри, спецсимволи або порожній рядок
    if not text.strip():
        return False
    if re.fullmatch(r"[\d\s.,!?;:()\"'’\-–—]+", text):
        return False
    # Ігнорувати HTML-теги (рядок повністю тег)
    if re.fullmatch(r"<[^>]+>", text.strip()):
        return False
    # Ігнорувати шорткоди типу [shortcode]
    if re.fullmatch(r"\[.*?\]", text.strip()):
        return False
    # Ігнорувати, якщо менше або рівно 3 слів
    if len(text.strip().split()) <= 2:
        return False
    # Ігнорувати, якщо рядок складається лише з тегів або розмітки
    text_no_tags = re.sub(r"<[^>]+>", "", text)
    if not text_no_tags.strip():
        return False
    return True

def is_probably_person_name(text):
    """
    Heuristic: returns True if text looks like a full personal name (first + last + optional middle names).
    """
    stripped = text.strip()
    # Skip empty or very long strings
    if not stripped or len(stripped.split()) > 7:
        return False
    # Allow letters, spaces, hyphens, apostrophes
    if not re.fullmatch(r"[A-Za-zÀ-ÖØ-öø-ÿ'’\- ]+", stripped):
        return False
    # Check if all words start with uppercase letter
    words = stripped.split()
    if all(w and w[0].isupper() for w in words):
        return True
    return False

def is_url(text):
    """
    Returns True if the text looks like a URL.
    """
    stripped = text.strip()
    # Simple heuristic for URLs
    url_pattern = re.compile(r'^(https?://\S+|www\.\S+|\S+\.\S{2,})$', re.IGNORECASE)
    return bool(url_pattern.match(stripped))

def extract_translatable(text):
    # Витягує частини тексту, які потрібно перекласти, і зберігає решту
    parts = []
    last_end = 0
    for match in re.finditer(r"(<[^>]+>|\[.*?\]|\d+|\s+|[.,!?;:()\"'’\-–—])", text):
        if match.start() > last_end:
            parts.append(("trans", text[last_end:match.start()]))
        parts.append(("keep", match.group()))
        last_end = match.end()
    if last_end < len(text):
        parts.append(("trans", text[last_end:]))
    return parts

def call_api(text, source_lang, target_lang):
    url = "http://127.0.0.1:5000/translate"
    headers = {
        "Content-Type": "application/json"
    }
    payload = {
        "q": text,
        "source": source_lang if source_lang else "auto",
        "target": target_lang,
        "format": "text",
        "alternatives": 3,
        "api_key": ""
    }
    response = requests.post(url, headers=headers, json=payload)
    response.raise_for_status()
    data = response.json()

    # Defensive parsing based on possible LibreTranslate response formats
    if isinstance(data, dict):
        if "translatedText" in data:
            return data["translatedText"]
        elif "alternatives" in data and isinstance(data["alternatives"], list) and data["alternatives"]:
            return data["alternatives"][0]
    elif isinstance(data, list) and data:
        # Sometimes LibreTranslate returns a list of translations
        first = data[0]
        if isinstance(first, dict) and "translatedText" in first:
            return first["translatedText"]
        elif isinstance(first, str):
            return first

    # Fallback: return original text if parsing fails
    return text

import time

def process_file(filepath):
    parser = ET.XMLParser(remove_blank_text=False)
    tree = ET.parse(filepath, parser)
    root = tree.getroot()
    ns = {'ns': 'urn:oasis:names:tc:xliff:document:1.2'}

    file_tag = root.find('ns:file', ns)
    source_lang = file_tag.attrib.get('source-language', 'en')
    target_lang = file_tag.attrib.get('target-language', 'zh-hans')

    # Normalize language codes for LibreTranslate compatibility
    source_lang = normalize_lang_code(source_lang)
    target_lang = normalize_lang_code(target_lang)

    translated_count = 0
    start_time = time.time()

    for tu in root.findall('.//ns:trans-unit', ns):
        source_elem = tu.find('ns:source', ns)
        target_elem = tu.find('ns:target', ns)

        source_text = source_elem.text or ""
        # Якщо source-language auto, не перекладати
        if source_lang == "auto":
            continue
        if not should_translate(source_text):
            continue

        # If the entire segment is a full name, skip translation and do not add <target>
        if is_probably_person_name(source_text):
            print(f"Segment ID {tu.attrib.get('id', 'N/A')}: Full name detected, skipping translation and leaving original.", flush=True)
            continue

        # If the entire segment is a URL, skip translation and do not add <target>
        if is_url(source_text):
            print(f"Segment ID {tu.attrib.get('id', 'N/A')}: URL detected, skipping translation and leaving original.", flush=True)
            continue

        # Додаємо пробіли між тегами і словами
        separated_text = separate_tags_with_spaces(source_text)

        # Замінюємо теги та емодзі на плейсхолдери
        text_with_placeholders, tag_mapping = replace_protected_elements_with_placeholders(separated_text)

        # Переклад всього рядка з плейсхолдерами
        try:
            # Якщо є роздільники типу "✅", розбити рядок
            parts = re.split(r'(✅)', text_with_placeholders)
            translated_parts = []
            for part in parts:
                if part == "✅":
                    translated_parts.append(part)
                else:
                    try:
                        translated_part = call_api(part, source_lang, target_lang)
                    except Exception:
                        translated_part = part
                    translated_parts.append(translated_part)
            translated_text = ''.join(translated_parts)

            # Відновлюємо теги у перекладеному тексті незалежно від того, чи відбувся переклад
            translated_text = restore_tags_from_placeholders(translated_text, tag_mapping)
            # Якщо переклад збігається з оригіналом (з плейсхолдерами), вважати що переклад не відбувся
            if translated_text.strip() == restore_tags_from_placeholders(text_with_placeholders.strip(), tag_mapping):
                translated_text = source_text  # повертаємо оригінал
                print(f"[{source_lang}] {source_text} => [{target_lang}] {translated_text} (No translation performed)", flush=True)
            else:
                print(f"[{source_lang}] {source_text} => [{target_lang}] {translated_text}", flush=True)
        except Exception:
            translated_text = source_text  # fallback

        if target_elem is None:
            # Insert <target> after <source> to preserve order
            target_elem = ET.Element('target')
            target_elem.text = translated_text
            source_elem.addnext(target_elem)
        else:
            target_elem.text = translated_text

        translated_count += 1

        print(f"\n=== Segment ID: {tu.attrib.get('id', 'N/A')} ===", flush=True)
        print(f"Original full text [{source_lang}]: {source_text}", flush=True)
        print(f"Translated full text [{target_lang}]: {translated_text}\n", flush=True)

    # Якщо не перекладено жодного рядка — видаляємо файл і не зберігаємо
    if translated_count == 0:
        try:
            os.remove(filepath)
            print(f"File {filepath} deleted because no segments were translated.", flush=True)
        except Exception as e:
            print(f"Failed to delete {filepath}: {e}", flush=True)
        return

    # Зберігаємо переклад у той самий файл без зміни структури
    tree.write(filepath, encoding="utf-8", xml_declaration=True, pretty_print=False)

    elapsed = time.time() - start_time
    filename = os.path.basename(filepath)
    print(f"File: {filename}", flush=True)
    print(f"Source language: {source_lang}", flush=True)
    print(f"Target language: {target_lang}", flush=True)
    print(f"Translated segments: {translated_count}", flush=True)
    print(f"Time taken: {elapsed:.2f} seconds\n", flush=True)

def main():
    for fname in os.listdir("to-translate"):
        if fname.endswith(".xliff"):
            fpath = os.path.join("to-translate", fname)
            try:
                # Витягуємо мови з файлу
                tree = ET.parse(fpath)
                root = tree.getroot()
                ns = {'ns': 'urn:oasis:names:tc:xliff:document:1.2'}
                file_tag = root.find('ns:file', ns)
                source_lang = file_tag.attrib.get('source-language', 'en')
                target_lang = file_tag.attrib.get('target-language', 'zh-hans')

                # Normalize language codes for LibreTranslate compatibility
                source_lang = normalize_lang_code(source_lang)
                target_lang = normalize_lang_code(target_lang)

                process_file(fpath)
                print(f"Translated: {fname}", flush=True)
            except Exception as e:
                print(f"Error processing {fname}: {e}", flush=True)

if __name__ == "__main__":
    main()
