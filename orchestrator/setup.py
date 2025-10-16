# orchestrator/setup.py

import getpass
import time  # Import modul time
from pathlib import Path

from .helpers import (
    print_success,
    print_error,
    print_info,
    print_warning,
    print_header,
    run_gh_api,
    read_file_lines,
    load_json_file,
    save_json_file,
    validate_api_key_format,
    API_KEYS_FILE,
    TOKENS_FILE,
    CONFIG_FILE,
    TOKEN_CACHE_FILE
)

def initialize_configuration():
    """Meminta input user untuk membuat file konfigurasi utama."""
    print_header("1. INITIALIZE CONFIGURATION")
    config = {}
    config['main_account_username'] = input("Username GitHub utama: ").strip()
    config['main_repo_name'] = input("Nama repository: ").strip()
    print_warning("\n⚠️ Token akan disembunyikan saat diketik")
    config['main_token'] = getpass.getpass("GitHub Personal Access Token: ").strip()

    if not all(config.values()):
        print_error("Semua field harus diisi!")
        return

    print_info("Memvalidasi token...")
    result = run_gh_api("api user", config['main_token'], max_retries=2)
    if not result["success"]:
        print_error(f"Token tidak valid: {result['error']}")
        return

    save_json_file(CONFIG_FILE, config)
    print_success(f"✅ Konfigurasi berhasil disimpan di {CONFIG_FILE}")

def import_api_keys():
    """Mengimpor API key dari input manual atau file."""
    print_header("2. IMPORT API KEYS")
    print("Pilih metode:\n 1. Input manual\n 2. Import dari file .txt")
    choice = input("\nPilihan (1/2): ").strip()

    keys = []
    if choice == '1':
        print_info("Masukkan API key (kosongkan untuk selesai)")
        while True:
            key = input(f"API Key #{len(keys) + 1}: ").strip()
            if not key:
                break
            if not validate_api_key_format(key):
                print_warning("⚠️ Format API key tidak valid, skip...")
                continue
            keys.append(key)
    elif choice == '2':
        source_file = input("Masukkan path ke file .txt: ").strip()
        if not Path(source_file).is_file():
            print_error(f"File tidak ditemukan: {source_file}")
            return
        keys = read_file_lines(Path(source_file))
    else:
        print_warning("Pilihan tidak valid.")
        return

    valid_keys = [k for k in keys if k and len(k) > 10]
    if valid_keys:
        API_KEYS_FILE.write_text("\n".join(valid_keys), encoding="utf-8")
        print_success(f"✅ Berhasil menyimpan {len(valid_keys)} API key(s)")
    else:
        print_warning("Tidak ada API key valid yang diinput.")

def show_api_keys_status():
    """Menampilkan status dan preview API key yang tersimpan."""
    print_header("3. SHOW API KEYS STATUS")
    if not API_KEYS_FILE.exists():
        print_warning("File API keys belum ada.")
        return

    keys = read_file_lines(API_KEYS_FILE)
    print_success(f"Total API Keys: {len(keys)}")
    if keys:
        print_info("\nPreview (3 key pertama):")
        for i, key in enumerate(keys[:3], 1):
            print(f" {i}. {key[:8]}...{key[-6:]}")

def import_github_tokens():
    """Mengimpor token GitHub dari file .txt."""
    print_header("4. IMPORT GITHUB TOKENS")
    source_file = input("Masukkan path ke file .txt berisi token: ").strip()
    if not Path(source_file).is_file():
        print_error(f"File tidak ditemukan: {source_file}")
        return

    tokens = [line for line in read_file_lines(Path(source_file)) if line.startswith(("ghp_", "github_pat_"))]
    if tokens:
        TOKENS_FILE.write_text("\n".join(tokens), encoding="utf-8")
        print_success(f"✅ Berhasil mengimpor {len(tokens)} token")
    else:
        print_error("Tidak ada token valid ditemukan.")

def validate_github_tokens():
    """Memvalidasi semua token GitHub dan menyimpan yang valid."""
    print_header("5. VALIDATE GITHUB TOKENS")
    if not TOKENS_FILE.exists():
        print_error("File tokens.txt belum ada.")
        return

    tokens = read_file_lines(TOKENS_FILE)
    print_info(f"Memvalidasi {len(tokens)} token...")

    token_cache = load_json_file(TOKEN_CACHE_FILE)
    valid_tokens, invalid_tokens = [], []

    for i, token in enumerate(tokens, 1):
        print(f"[{i}/{len(tokens)}] Validating...", end="", flush=True)
        
        # Cek cache dulu untuk mengurangi panggilan API
        if token in token_cache:
            print_success(f" ✅ @{token_cache[token]} (from cache)")
            valid_tokens.append(token)
            time.sleep(0.1) # Jeda singkat bahkan untuk cache
            continue

        result = run_gh_api("api user --jq .login", token, max_retries=2)
        if result["success"]:
            username = result["output"]
            print_success(f" ✅ @{username}")
            token_cache[token] = username
            valid_tokens.append(token)
        else:
            # Berikan pesan error yang lebih informatif
            error_msg = result.get('error', 'Unknown error').split('\n')[0]
            print_error(f" ❌ Invalid ({error_msg})")
            invalid_tokens.append(token)
            
        # ==================================================================
        # PERBAIKAN UTAMA: Tambahkan jeda 1 detik di sini
        # Ini mencegah GitHub API rate limiting saat memvalidasi banyak token.
        time.sleep(1)
        # ==================================================================

    save_json_file(TOKEN_CACHE_FILE, token_cache)

    # Hanya tulis kembali token yang valid ke file tokens.txt
    if valid_tokens:
        TOKENS_FILE.write_text("\n".join(valid_tokens), encoding="utf-8")
        print_success(f"\nValidasi selesai! Valid: {len(valid_tokens)}/{len(tokens)}. Token invalid otomatis dihapus.")
    else:
        print_warning("Tidak ada token valid yang ditemukan.")
