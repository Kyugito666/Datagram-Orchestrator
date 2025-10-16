# orchestrator/collaboration.py

import json
import time
import re
from typing import List, Set, Tuple

from .helpers import (
    Style,
    print_success,
    print_error,
    print_info,
    print_warning,
    print_header,
    run_gh_api,
    read_file_lines,
    append_to_file,
    load_json_file,
    disable_workflow,
    CONFIG_FILE,
    TOKEN_CACHE_FILE,
    INVITED_USERS_FILE,
    ACCEPTED_USERS_FILE,
    FORKED_REPOS_FILE,
    write_log
)


def invoke_auto_invite():
    """Mengundang semua akun di cache token sebagai kolaborator."""
    print_header("6. AUTO INVITE COLLABORATORS")
    config = load_json_file(CONFIG_FILE)
    if not config:
        print_error("Konfigurasi belum diset.")
        return

    token_cache = load_json_file(TOKEN_CACHE_FILE)
    if not token_cache:
        print_error("Token cache kosong.")
        return

    total_accounts = len(token_cache)
    print_info(f"📊 Memulai proses untuk {total_accounts} akun...")

    invited_users = read_file_lines(INVITED_USERS_FILE)
    main_username = config['main_account_username']
    users_to_invite = [u for u in token_cache.values() if u not in invited_users and u != main_username]

    if not users_to_invite:
        print_success("✅ Semua akun yang valid sudah diundang.")
        return

    print_info(f"Akan mengundang {len(users_to_invite)} user baru...")
    repo_path = f"{main_username}/{config['main_repo_name']}"
    success_count = 0
    failed_count = 0

    for i, username in enumerate(users_to_invite, 1):
        print(f"[{i}/{len(users_to_invite)}] Mengundang @{username}...", end="", flush=True)
        result = run_gh_api(
            f"api --silent -X PUT repos/{repo_path}/collaborators/{username} -f permission=push",
            config['main_token']
        )
        if result["success"]:
            print_success(" ✅")
            append_to_file(INVITED_USERS_FILE, username)
            success_count += 1
        else:
            error_msg = result.get('error', '').lower()
            if "already a collaborator" in error_msg:
                print_warning(" ⚠️  Already a collaborator")
                append_to_file(INVITED_USERS_FILE, username) # Tandai sudah diundang
                success_count += 1
            else:
                print_error(f" ❌ {result['error']}")
                failed_count += 1
        time.sleep(1)

    print_success(f"\n{'='*47}")
    print_success(f"✅ Proses selesai!")
    print_info(f"   Berhasil: {success_count}, Gagal: {failed_count}, Total Undangan Baru: {len(users_to_invite)}")
    print_success(f"{'='*47}")


def invoke_auto_accept():
    """Menerima undangan kolaborasi secara otomatis untuk semua akun."""
    print_header("7. AUTO ACCEPT INVITATIONS")
    config = load_json_file(CONFIG_FILE)
    token_cache = load_json_file(TOKEN_CACHE_FILE)

    if not config or not token_cache:
        print_error("Konfigurasi atau token cache tidak ditemukan.")
        return

    total_accounts = len(token_cache)
    print_info(f"📊 Memulai proses untuk {total_accounts} akun...")

    target_repo = f"{config['main_account_username']}/{config['main_repo_name']}".lower()
    accepted_users = read_file_lines(ACCEPTED_USERS_FILE)
    print_info(f"Target: {target_repo}\nMengecek {len(token_cache)} akun...")

    accepted_count = 0
    skipped_count = 0
    no_invite_count = 0

    for i, (token, username) in enumerate(token_cache.items(), 1):
        if username in accepted_users:
            print(f"[{i}/{total_accounts}] @{username} - ✅ Already accepted")
            skipped_count += 1
            continue

        print(f"[{i}/{total_accounts}] @{username}...", end="", flush=True)
        result = run_gh_api("api user/repository_invitations", token)

        if not result["success"]:
            print_error(f" ❌ Gagal fetch invitations")
            continue

        try:
            invitations = json.loads(result["output"])
            inv_id = next(
                (inv['id'] for inv in invitations if inv.get('repository', {}).get('full_name', '').lower() == target_repo),
                None
            )

            if inv_id:
                accept_result = run_gh_api(f"api --method PATCH /user/repository_invitations/{inv_id} --silent", token)
                if accept_result["success"]:
                    print_success(" ✅ Accepted")
                    append_to_file(ACCEPTED_USERS_FILE, username)
                    accepted_count += 1
                else:
                    print_error(f" ❌ Gagal accept: {accept_result['error']}")
            else:
                print_info(" ℹ️ No invitation found")
                no_invite_count += 1
        except (json.JSONDecodeError, KeyError):
            print_error(f" ❌ Gagal parse JSON")

        time.sleep(1)

    print_success(f"\n{'='*47}")
    print_success(f"✅ Proses selesai!")
    print_info(f"   Diterima: {accepted_count}, Sudah Diterima: {skipped_count}, Tanpa Undangan: {no_invite_count}, Total: {total_accounts}")
    print_success(f"{'='*47}")


def check_if_correct_fork(repo_path: str, token: str, expected_parent: str) -> bool:
    """Cek apakah repo adalah fork valid dari expected parent."""
    result = run_gh_api(f"api repos/{repo_path} --jq .parent.full_name", token, max_retries=2)
    if not result["success"]:
        return False
    parent = result["output"].strip().strip('"')
    return parent.lower() == expected_parent.lower()


def get_default_branch(repo_path: str, token: str) -> str:
    """Mendapatkan nama branch default."""
    result = run_gh_api(f"api repos/{repo_path} --jq .default_branch", token, max_retries=1)
    if result["success"] and result["output"].strip():
        return result["output"].strip().strip('"')
    return "main"


def delete_repository(repo_path: str, token: str) -> bool:
    """Menghapus repository."""
    print_warning(f"    🗑️  Deleting repository: {repo_path}")
    # PERINGATAN: Perintah ini destruktif. Pastikan user sudah setuju.
    result = run_gh_api(f"api -X DELETE repos/{repo_path}", token, max_retries=2, timeout=60)
    if result["success"]:
        print_success(f"    ✅ Successfully initiated deletion for {repo_path}")
        # Beri jeda agar GitHub memproses penghapusan
        time.sleep(5)
        return True
    else:
        write_log(f"Failed to delete {repo_path}: {result.get('error')}")
        print_error(f"    ❌ Failed to delete {repo_path}")
        return False


def sync_fork_with_upstream(fork_repo: str, token: str) -> bool:
    """Sinkronisasi fork dengan upstream."""
    print_info(f"    🔄 Syncing fork {fork_repo} with upstream...")
    default_branch = get_default_branch(fork_repo, token)
    
    # Nonaktifkan workflow sebelum sync untuk menghindari trigger yang tidak diinginkan
    disable_workflow(fork_repo, token, "datagram-runner.yml")
    
    sync_result = run_gh_api(f"api -X POST repos/{fork_repo}/merge-upstream -f branch={default_branch}", token, max_retries=2)
    
    if sync_result["success"]:
        print_success("    ✅ Sync successful.")
        return True
    
    error_msg = sync_result.get('error', '').lower()
    if any(keyword in error_msg for keyword in ['up-to-date', 'up to date', 'already']):
        print_info("    ℹ️  Fork is already up-to-date.")
        return True
    
    print_warning(f"    ⚠️  Sync failed: {sync_result.get('error')}")
    return False

def create_new_fork(username: str, token: str, source_repo: str) -> bool:
    """Membuat fork baru dan menunggu hingga selesai."""
    print_info(f"    🍴 Creating a new fork of {source_repo} for @{username}...")
    fork_repo_path = f"{username}/{source_repo.split('/')[1]}"
    
    # Hapus file cache lama jika ada
    # (Penting jika user menjalankan ulang setelah kegagalan)
    if username in read_file_lines(FORKED_REPOS_FILE):
        print_info(f"    ℹ️  Removing stale cache entry for @{username}")
        # Logika untuk menghapus line spesifik dari file
        lines = read_file_lines(FORKED_REPOS_FILE)
        new_lines = [line for line in lines if line != username]
        FORKED_REPOS_FILE.write_text('\n'.join(new_lines) + '\n')

    result = run_gh_api(f"api -X POST repos/{source_repo}/forks", token, max_retries=1)
    
    if not result["success"]:
        error_msg = result.get('error', '').lower()
        if 'forks must have unique names' in error_msg:
            print_warning("    ⚠️  Fork already exists. Skipping creation.")
            # Anggap berhasil jika fork sudah ada
        else:
            print_error(f"    ❌ Fork creation failed: {result.get('error')}")
            write_log(f"Fork failed for @{username}: {result.get('error')}")
            return False

    # Polling untuk memastikan fork sudah ada
    print_info("    ⏳ Waiting for fork to be created...")
    timeout = 120  # Tunggu maksimal 2 menit
    start_time = time.time()
    fork_created = False
    while time.time() - start_time < timeout:
        check_result = run_gh_api(f"api repos/{fork_repo_path}", token, max_retries=1)
        if check_result["success"]:
            print_success("    ✅ Fork is ready!")
            fork_created = True
            break
        time.sleep(5)
    
    if not fork_created:
        print_error("    ❌ Timeout: Fork was not ready in time.")
        return False

    # Nonaktifkan workflow di fork baru
    print_info("    🔒 Disabling workflow on new fork...")
    disable_workflow(fork_repo_path, token, "datagram-runner.yml")
    
    # Tambahkan ke cache
    append_to_file(FORKED_REPOS_FILE, username)
    return True

def invoke_auto_create_or_sync_fork():
    """Membuat atau sync fork untuk semua akun kolaborator."""
    print_header("8. AUTO CREATE OR SYNC FORK REPOSITORY")
    
    config = load_json_file(CONFIG_FILE)
    if not config:
        print_error("Konfigurasi belum diset.")
        return

    token_cache = load_json_file(TOKEN_CACHE_FILE)
    if not token_cache:
        print_error("Token cache kosong.")
        return

    main_username = config['main_account_username']
    source_repo = f"{main_username}/{config['main_repo_name']}"
    repo_name = config['main_repo_name']

    # Proses semua akun kecuali akun utama
    users_to_process = {u: t for t, u in token_cache.items() if u != main_username}
    num_to_process = len(users_to_process)

    if not users_to_process:
        print_success("✅ Tidak ada akun kolaborator untuk diproses.")
        return

    print_info(f"Source Repository: {source_repo}")
    print_info(f"Total kolaborator untuk diproses: {num_to_process}")
    
    print_warning("\nMode Operasi:")
    print(f"{Style.CYAN}  1. Sync & Keep{Style.ENDC}   : Sinkronisasi fork yang sudah ada. Buat baru jika tidak ada.")
    print(f"{Style.CYAN}  2. Force Clean & Create{Style.ENDC} : HAPUS SEMUA fork lama, lalu buat yang baru (DESTRUKTIF).")
    
    while True:
        action = input(f"\nPilih mode (1/2): ").strip()
        if action in ['1', '2']:
            break
        print_warning("Pilihan tidak valid.")

    if action == '1':
        print_info("\nMode: Sync & Keep")
    else:
        print_warning("\nMode: Force Clean & Create. Ini akan menghapus repo yang ada.")
        if input("   Anda yakin ingin melanjutkan? (y/n): ").lower() != 'y':
            print_warning("Operasi dibatalkan.")
            return

    print(f"\n{'='*50}")
    
    success_count = 0
    failed_count = 0
    
    for i, (username, token) in enumerate(users_to_process.items(), 1):
        print(f"\n[{i}/{num_to_process}] Processing @{username}")
        print('-'*50)
        
        fork_repo_path = f"{username}/{repo_name}"
        
        # Cek apakah fork yang benar sudah ada
        is_fork_valid = check_if_correct_fork(fork_repo_path, token, source_repo)
        
        if action == '2': # Force Clean & Create
            print_info("   Mode 'Force Clean': Menghapus fork lama jika ada.")
            # Cek repo dengan nama yang sama, meskipun bukan fork yang valid
            repo_exists_result = run_gh_api(f"api repos/{fork_repo_path}", token, max_retries=1)
            if repo_exists_result["success"]:
                if not delete_repository(fork_repo_path, token):
                    failed_count += 1
                    continue # Gagal hapus, jangan lanjutkan
            else:
                print_info("   ℹ️  Tidak ada repo lama yang perlu dihapus.")
            
            # Buat fork baru
            if create_new_fork(username, token, source_repo):
                success_count += 1
            else:
                failed_count += 1

        elif action == '1': # Sync & Keep
            if is_fork_valid:
                print_success("   ✅ Valid fork ditemukan.")
                if sync_fork_with_upstream(fork_repo_path, token):
                    success_count += 1
                else:
                    failed_count += 1 # Gagal sync
            else:
                print_warning("   ⚠️  Fork tidak valid atau tidak ditemukan.")
                if create_new_fork(username, token, source_repo):
                    success_count += 1
                else:
                    failed_count += 1
        
        time.sleep(2) # Jeda antar akun
    
    print(f"\n{'='*50}")
    print_success("✅ Proses Selesai!")
    print_info(f"   Berhasil: {success_count}, Gagal: {failed_count}, Total: {num_to_process}")
    print('='*50)
