# orchestrator/collaboration.py

import json
import time
import re
from typing import List, Set, Tuple, Dict

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
        print_success("✅ Semua akun sudah diundang.")
        print_success(f"\n{'='*47}")
        print_success(f"✅ Proses selesai!")
        print_info(f"   Berhasil: 0, Gagal: 0, Total: {total_accounts}")
        print_success(f"{'='*47}")
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
            print_error(f" ❌ {result['error']}")
            failed_count += 1
        time.sleep(1)

    print_success(f"\n{'='*47}")
    print_success(f"✅ Proses selesai!")
    print_info(f"   Berhasil: {success_count}, Gagal: {failed_count}, Total: {total_accounts}")
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

    for i, (token, username) in enumerate(token_cache.items(), 1):
        if username in accepted_users:
            print(f"[{i}/{len(token_cache)}] @{username} - ✅ Already accepted")
            skipped_count += 1
            continue

        print(f"[{i}/{len(token_cache)}] @{username}...", end="", flush=True)
        result = run_gh_api("api user/repository_invitations", token)

        if not result["success"]:
            print_error(f" ❌ Gagal fetch invitations")
            skipped_count += 1
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
                    skipped_count += 1
            else:
                print_info(" ℹ️ No invitation found")
                skipped_count += 1
        except (json.JSONDecodeError, KeyError):
            print_error(f" ❌ Gagal parse JSON")
            skipped_count += 1

        time.sleep(1)

    print_success(f"\n{'='*47}")
    print_success(f"✅ Proses selesai!")
    print_info(f"   Berhasil: {accepted_count}, Dilewati: {skipped_count}, Total: {total_accounts}")
    print_success(f"{'='*47}")


def get_user_repos_matching_pattern(token: str, repo_name: str) -> List[str]:
    """Mendapatkan semua repo yang match pattern."""
    result = run_gh_api("api user/repos --paginate --jq '.[].name'", token, max_retries=2, timeout=60)
    
    if not result["success"] or not result["output"].strip():
        return []
    
    matching_repos_set: Set[str] = set()
    pattern = re.compile(r'^' + re.escape(repo_name) + r'(-\d+)?$', re.IGNORECASE)
    
    for line in result["output"].strip().split('\n'):
        if line.strip():
            repo = line.strip().strip('"').strip("'")
            if pattern.match(repo):
                matching_repos_set.add(repo)
    
    return sorted(matching_repos_set)


def is_exact_repo_name(repo: str, base_name: str) -> bool:
    """Check apakah repo name exact match tanpa suffix angka."""
    return repo.lower() == base_name.lower()


def check_if_correct_fork(repo_path: str, token: str, expected_parent: str) -> bool:
    """Cek apakah repo adalah fork valid dari expected parent."""
    result = run_gh_api(f"api repos/{repo_path} --jq '.parent.full_name'", token, max_retries=1)
    if not result["success"]:
        return False
    
    parent = result["output"].strip().strip('"')
    return parent == expected_parent


def get_default_branch(repo_path: str, token: str) -> str:
    """Mendapatkan nama branch default."""
    result = run_gh_api(f"api repos/{repo_path} --jq '.default_branch'", token, max_retries=1)
    if result["success"] and result["output"].strip():
        return result["output"].strip().strip('"')
    return "main"


def delete_repository(repo_path: str, token: str) -> bool:
    """Menghapus repository."""
    result = run_gh_api(f"api -X DELETE repos/{repo_path}", token, max_retries=2, timeout=30)
    if not result["success"]:
        write_log(f"Failed to delete {repo_path}: {result.get('error')}")
    return result["success"]


def sync_fork_with_upstream(fork_repo: str, token: str) -> bool:
    """Sinkronisasi fork dengan upstream."""
    default_branch = get_default_branch(fork_repo, token)
    
    sync_result = run_gh_api(f"api -X POST repos/{fork_repo}/merge-upstream -f branch={default_branch}", token, max_retries=2)
    
    if sync_result["success"]:
        return True
    
    error_msg = sync_result.get('error', '').lower()
    if any(keyword in error_msg for keyword in ['up-to-date', 'up to date', 'already']):
        return True
    
    return False


def set_repo_public(repo_path: str, token: str) -> bool:
    """Set repository visibility menjadi public."""
    result = run_gh_api(f"api -X PATCH repos/{repo_path} -f private=false", token, max_retries=1)
    return result["success"] or "unprocessable" in result.get("error", "").lower()


def cleanup_repos(username: str, token: str, matching_repos: List[str], source_repo: str, repo_name: str, force_delete_all: bool) -> Tuple[int, List[str]]:
    """Delete repos sesuai mode."""
    if not matching_repos:
        return 0, []
    
    deleted_count = 0
    kept_repos: List[str] = []
    
    for repo in matching_repos:
        repo_path = f"{username}/{repo}"
        
        if force_delete_all:
            print_warning(f"    🗑️  Force deleting: {repo}")
            if delete_repository(repo_path, token):
                print_success(f"    ✅ Deleted: {repo}")
                deleted_count += 1
                time.sleep(2)
            else:
                print_error(f"    ❌ Failed to delete: {repo}")
        else:
            is_exact = is_exact_repo_name(repo, repo_name)
            is_valid_fork = check_if_correct_fork(repo_path, token, source_repo) if is_exact else False
            
            if is_exact and is_valid_fork:
                print_success(f"    ✅ Keeping valid fork: {repo}")
                kept_repos.append(repo)
                continue
            
            print_warning(f"    🗑️  Deleting: {repo}")
            if delete_repository(repo_path, token):
                print_success(f"    ✅ Deleted: {repo}")
                deleted_count += 1
                time.sleep(2)
            else:
                print_error(f"    ❌ Failed to delete: {repo}")
    
    return deleted_count, kept_repos


def create_new_fork(username: str, token: str, source_repo: str, fork_repo: str) -> bool:
    """Create fork baru."""
    result = run_gh_api(f"api -X POST repos/{source_repo}/forks", token, max_retries=2)
    
    if result["success"]:
        print_success("    ✅ Fork created")
        time.sleep(5)
        
        if set_repo_public(fork_repo, token):
            print_info("    🔓 Set public")
        
        append_to_file(FORKED_REPOS_FILE, username)
        return True
    else:
        print_error(f"    ❌ Failed: {result.get('error')}")
        write_log(f"Fork failed for @{username}: {result.get('error')}")
        return False


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

    total_accounts = len(token_cache)
    print_info(f"📊 Memulai proses untuk {total_accounts} akun...")

    forked_users = read_file_lines(FORKED_REPOS_FILE)
    main_username = config['main_account_username']
    source_repo = f"{main_username}/{config['main_repo_name']}"
    repo_name = config['main_repo_name']

    users_to_process = {u: t for t, u in token_cache.items() if u != main_username}

    if not users_to_process:
        print_success("✅ Tidak ada akun untuk diproses.")
        print_success(f"\n{'='*47}")
        print_success(f"✅ Proses selesai!")
        print_info(f"   Berhasil: 0, Dilewati: 0, Total: {total_accounts}")
        print_success(f"{'='*47}")
        return

    print_info(f"Source: {source_repo}")
    print_info(f"Total users: {len(users_to_process)}")
    
    print_info("\n🤔 Pilih aksi untuk SEMUA user:")
    print(f"{Style.CYAN}  y{Style.ENDC} - Delete SEMUA repos (paksa) & create fork baru")
    print(f"{Style.CYAN}  n{Style.ENDC} - Keep exact valid fork, sync & set public")
    
    while True:
        action = input(f"\n{Style.BOLD}[y/n]:{Style.ENDC} ").strip().lower()
        if action in ['y', 'n']:
            break
        print_warning("Invalid input. Masukkan 'y' atau 'n'")
    
    if action == 'n':
        print_info("\n⏭️  Mode: Sync only")
    else:
        print_warning("\n🗑️  Mode: Force cleanup + Create")
    
    print(f"\n{'='*50}")
    print_info("PROCESSING...")
    print('='*50)
    
    success_count = 0
    sync_count = 0
    create_count = 0
    skip_count = 0
    
    for i, (username, token) in enumerate(users_to_process.items(), 1):
        print(f"\n[{i}/{len(users_to_process)}] @{username}")
        print('-'*50)
        
        fork_repo = f"{username}/{repo_name}"
        is_valid_fork = check_if_correct_fork(fork_repo, token, source_repo)
        
        if is_valid_fork:
            print_success("✅ Valid fork detected")
            
            if action == 'y':
                print_warning("⚠️  Force deleting valid fork...")
                matching = get_user_repos_matching_pattern(token, repo_name)
                if matching:
                    deleted, _ = cleanup_repos(username, token, matching, source_repo, repo_name, force_delete_all=True)
                    if deleted > 0:
                        print_success(f"✅ Deleted {deleted} repo(s)")
                        time.sleep(3)
                else:
                    print_info("ℹ️  No matching repositories found to delete.")
                
                print_info("🍴 Creating new fork...")
                if create_new_fork(username, token, source_repo, fork_repo):
                    create_count += 1
                    success_count += 1
                else:
                    skip_count += 1
            else:
                print_info("🔄 Syncing...")
                if sync_fork_with_upstream(fork_repo, token):
                    print_success("✅ Synced")
                    sync_count += 1
                else:
                    print_warning("⚠️  Sync failed")
                
                set_repo_public(fork_repo, token)
                
                if username not in forked_users:
                    append_to_file(FORKED_REPOS_FILE, username)
                
                success_count += 1
        else:
            matching_repos = get_user_repos_matching_pattern(token, repo_name)
            
            if action == 'y':
                if matching_repos:
                    print_warning(f"⚠️  Force deleting ALL {len(matching_repos)} repo(s)...")
                    deleted, _ = cleanup_repos(username, token, matching_repos, source_repo, repo_name, force_delete_all=True)
                    if deleted > 0:
                        print_success(f"✅ Deleted {deleted} repo(s)")
                        time.sleep(3)
                else:
                    print_info("ℹ️  No matching repositories found to delete.")
                
                print_info("🍴 Creating new fork...")
                if create_new_fork(username, token, source_repo, fork_repo):
                    create_count += 1
                    success_count += 1
                else:
                    skip_count += 1
            else:
                if matching_repos:
                    print_info("🔍 Checking repos...")
                    deleted, kept = cleanup_repos(username, token, matching_repos, source_repo, repo_name, force_delete_all=False)
                    
                    if deleted > 0:
                        print_success(f"✅ Cleaned {deleted} invalid repo(s)")
                        time.sleep(3)
                    
                    if kept:
                        first_valid = f"{username}/{kept[0]}"
                        print_info(f"🔄 Syncing: {kept[0]}...")
                        
                        if sync_fork_with_upstream(first_valid, token):
                            print_success("✅ Synced")
                            set_repo_public(first_valid, token)
                            sync_count += 1
                            success_count += 1
                        else:
                            print_warning("⚠️  Sync failed")
                            skip_count += 1
                    else:
                        print_info("🍴 Creating new fork...")
                        if create_new_fork(username, token, source_repo, fork_repo):
                            create_count += 1
                            success_count += 1
                        else:
                            skip_count += 1
                else:
                    print_info("🍴 Creating new fork...")
                    if create_new_fork(username, token, source_repo, fork_repo):
                        create_count += 1
                        success_count += 1
                    else:
                        skip_count += 1
        
        time.sleep(2)
    
    print(f"\n{'='*50}")
    print_success("✅ Proses selesai!")
    print_info(f"   Berhasil: {success_count}, Dilewati: {skip_count}, Total: {total_accounts}")
    print_info(f"   Synced: {sync_count} | Created: {create_count}")
    print('='*50)
