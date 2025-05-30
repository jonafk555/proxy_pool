#!/usr/bin/env python3

import requests
import sys
import time
import logging
import argparse
import tempfile
import shutil
import os
from random import choice
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- 1. 設定日誌 ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

# --- 2. 代理驗證函數 ---
def check_proxy(proxy, timeout, test_url):
    """
    檢查單個代理是否可用。
    """
    proxies_dict = {'http': f'http://{proxy}', 'https': f'http://{proxy}'}
    try:
        r = requests.get(test_url, proxies=proxies_dict, timeout=timeout)
        if r.status_code == 200:
            logging.debug(f"代理 {proxy} 驗證成功。")
            return proxy, True
        else:
            logging.warning(f"代理 {proxy} 驗證失敗 (狀態碼: {r.status_code})。")
            return proxy, False
    except requests.exceptions.Timeout:
        logging.warning(f"代理 {proxy} 驗證超時 ({timeout} 秒)。")
        return proxy, False
    except requests.exceptions.RequestException as e:
        logging.warning(f"代理 {proxy} 驗證失敗: {e}")
        return proxy, False

def check_proxies_concurrently(proxies_list, timeout, test_url, max_workers):
    """
    使用線程池並行檢查代理清單。
    """
    valid_proxies = []
    if not proxies_list:
        return valid_proxies

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_proxy = {executor.submit(check_proxy, proxy, timeout, test_url): proxy for proxy in proxies_list}
        total_proxies = len(proxies_list)
        logging.info(f"開始並行檢查 {total_proxies} 個代理...")
        for i, future in enumerate(as_completed(future_to_proxy)):
            proxy, is_valid = future.result()
            if is_valid:
                valid_proxies.append(proxy)
            if (i + 1) % (max_workers // 2 if max_workers > 1 else 1) == 0 or (i + 1) == total_proxies: # 適時更新進度
                 logging.info(f"已檢查 {i+1}/{total_proxies} 個代理... 目前找到 {len(valid_proxies)} 個可用代理。")
    return valid_proxies

# --- 3. Proxychains 設定檔更新函數 ---
def update_proxychains_conf(proxy_address, conf_path, proxy_type="http"):
    """
    更新 proxychains 設定檔。
    """
    if os.geteuid() != 0:
        logging.error(f"更新 {conf_path} 需要 root 權限。請使用 sudo 執行。")
        return False

    if not os.path.exists(conf_path):
        logging.error(f"設定檔 {conf_path} 不存在。")
        return False

    backup_path = f"{conf_path}.bak.{int(time.time())}"
    logging.info(f"正在備份 {conf_path} 到 {backup_path}...")
    try:
        shutil.copy2(conf_path, backup_path)
    except Exception as e:
        logging.error(f"備份失敗: {e}")
        return False

    new_lines = []
    try:
        with open(conf_path, 'r', encoding='utf-8') as f_read:
            for line in f_read:
                stripped_line = line.strip()
                if not (stripped_line.startswith('http ') or \
                        stripped_line.startswith('socks4 ') or \
                        stripped_line.startswith('socks5 ') or \
                        stripped_line.startswith('https ')):
                    new_lines.append(line)
                else:
                    logging.debug(f"移除舊代理行: {stripped_line}")

        ip, port = proxy_address.split(':')
        new_proxy_line = f"{proxy_type} {ip} {port}\n"

        proxy_list_tag_index = -1
        for i, line_content in enumerate(new_lines):
            if line_content.strip() == "[ProxyList]":
                proxy_list_tag_index = i
                break
        
        if proxy_list_tag_index != -1:
            new_lines.insert(proxy_list_tag_index + 1, f"# Added by script at {time.ctime()}\n")
            new_lines.insert(proxy_list_tag_index + 2, new_proxy_line)
        else:
            new_lines.append(f"\n# Added by script at {time.ctime()} (no [ProxyList] tag found)\n")
            new_lines.append(new_proxy_line)

        with tempfile.NamedTemporaryFile(mode='w', delete=False, encoding='utf-8', dir=os.path.dirname(conf_path)) as temp_f:
            temp_path = temp_f.name
            for line_to_write in new_lines:
                temp_f.write(line_to_write)

        shutil.move(temp_path, conf_path)
        try:
            shutil.copymode(backup_path, conf_path)
            original_stat = os.stat(backup_path)
            shutil.chown(conf_path, user=original_stat.st_uid, group=original_stat.st_gid)
        except Exception as e:
            logging.warning(f"設定檔案權限或擁有者時出錯: {e}")

        logging.info(f"已更新 {conf_path} 使用代理: {proxy_type} {proxy_address}")
        return True

    except Exception as e:
        logging.error(f"更新設定檔 {conf_path} 失敗: {e}")
        logging.info(f"正在從備份 {backup_path} 還原...")
        try:
            shutil.move(backup_path, conf_path)
        except Exception as restore_e:
            logging.error(f"還原設定檔失敗: {restore_e}.")
        return False
    finally:
        if 'temp_path' in locals() and os.path.exists(temp_path):
            os.remove(temp_path)

# --- 4. 匯出可用代理到檔案 ---
def export_valid_proxies(valid_proxies, output_file_path):
    """
    將可用的代理清單匯出到指定的檔案。
    """
    if not valid_proxies:
        logging.info("沒有可用的代理可以匯出。")
        return

    try:
        with open(output_file_path, 'w', encoding='utf-8') as f:
            for proxy in valid_proxies:
                f.write(f"{proxy}\n")
        logging.info(f"已成功將 {len(valid_proxies)} 個可用代理匯出到: {output_file_path}")
    except IOError as e:
        logging.error(f"匯出可用代理到檔案 {output_file_path} 失敗: {e}")


# --- 5. 主程式 ---
def main():
    parser = argparse.ArgumentParser(
        description="優化的代理池程式，用於驗證代理、輪換 proxychains 設定，並可匯出可用代理。",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument('-f', '--file', default='proxy-list.txt',
                        help="指定包含代理清單的 TXT 檔案 (每行格式 'ip:port')。\n預設: proxy-list.txt")
    parser.add_argument('-o', '--output-file', type=str, default=None,
                        help="指定一個 TXT 檔案路徑，用於儲存測試後可用的代理清單。\n若未指定，則不匯出到檔案。")
    parser.add_argument('-t', '--timeout', type=int, default=5,
                        help="代理驗證的超時時間 (秒)。\n預設: 5")
    parser.add_argument('-u', '--url', default='http://icanhazip.com',
                        help="用於驗證代理的 URL。\n預設: http://icanhazip.com")
    parser.add_argument('-w', '--workers', type=int, default=20,
                        help="並行驗證代理的執行緒數量。\n預設: 20")
    parser.add_argument('-c', '--conf', default='/etc/proxychains4.conf',
                        help="proxychains 設定檔路徑。\n預設: /etc/proxychains4.conf")
    parser.add_argument('-s', '--sleep', type=int, default=60,
                        help="代理切換間隔時間 (秒)。\n預設: 60")
    parser.add_argument('--proxy-type', default='http', choices=['http', 'socks4', 'socks5', 'https'],
                        help="要設定到 proxychains 的代理類型。\n預設: http")
    parser.add_argument('--no-update', action='store_true',
                        help="僅驗證代理並匯出 (如果指定了 -o)，不更新 proxychains4.conf。")
    parser.add_argument('--verbose', '-v', action='store_true',
                        help="啟用 DEBUG 等級日誌輸出。")

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # 讀取代理清單
    logging.info(f"準備從檔案 '{args.file}' 讀取代理清單...")
    try:
        with open(args.file, 'r', encoding='utf-8') as f:
            proxies = [
                line.strip() for line in f
                if line.strip() and not line.strip().startswith('#') and ':' in line.strip()
            ]
        logging.info(f"從 {args.file} 成功讀取了 {len(proxies)} 個代理。")
        if not proxies:
            logging.warning(f"代理清單 {args.file} 為空或格式不符。請確保每行格式為 'ip:port'。")
            # 即使清單為空，也允許繼續執行，check_proxies_concurrently 會處理空列表
    except FileNotFoundError:
        logging.error(f"代理清單檔案 {args.file} 不存在。程式終止。")
        sys.exit(1)
    except Exception as e:
        logging.error(f"讀取代理清單 {args.file} 失敗: {e}。程式終止。")
        sys.exit(1)

    # 驗證代理
    if not proxies: # 如果讀取後 proxies 列表為空
        logging.warning("沒有從檔案中讀取到任何代理，無法進行驗證。")
        valid_proxies = []
    else:
        valid_proxies = check_proxies_concurrently(proxies, args.timeout, args.url, args.workers)
    
    logging.info(f"代理驗證完成，共找到 {len(valid_proxies)} 個可用代理。")

    # 匯出可用的代理 (如果在命令列中指定了 --output-file)
    if args.output_file:
        export_valid_proxies(valid_proxies, args.output_file)
    elif not valid_proxies:
        logging.info("沒有可用的代理可以操作。")
        if not args.no_update: # 如果需要更新 proxychains 但無可用代理
            logging.error("無法更新 proxychains4.conf，因為沒有可用的代理。")
        sys.exit(1) # 如果沒有可用代理，且沒有指定匯出檔案，則退出

    if not valid_proxies: # 再次檢查，確保有代理可用於後續操作
        logging.info("最終沒有可用的代理。程式結束。")
        sys.exit(0 if args.no_update else 1)


    # 如果設定了 --no-update，則僅驗證和匯出 (如果指定)，然後結束
    if args.no_update:
        if not args.output_file: # 如果沒有指定輸出檔案，則打印到控制台
            logging.info("找到的可用代理 (未匯出到檔案)：")
            for p in valid_proxies:
                print(p)
        logging.info("已執行驗證和匯出 (如果適用)。由於指定了 --no-update，程式結束。")
        sys.exit(0)

    # 進入代理輪換模式
    logging.info(f"進入代理輪換模式 (每 {args.sleep} 秒切換一次，按 Ctrl+C 結束)...")
    try:
        while True:
            if not valid_proxies: # 理論上前面已經處理，但作為防禦性程式碼
                logging.error("輪換模式中止：沒有可用的代理。")
                break
            selected_proxy = choice(valid_proxies)
            logging.info(f">> 嘗試使用代理：{selected_proxy} (類型: {args.proxy_type}) 到 {args.conf}")
            
            if update_proxychains_conf(selected_proxy, args.conf, args.proxy_type):
                logging.info(f"成功將代理 {selected_proxy} 設定到 {args.conf}")
            else:
                 logging.warning(f"更新 {args.conf} 失敗。將在下個週期重試。")
            
            logging.info(f"等待 {args.sleep} 秒進行下一次切換...")
            time.sleep(args.sleep)
    except KeyboardInterrupt:
        logging.info("收到使用者中斷訊號 (Ctrl+C)，程式結束。")
    except Exception as e:
        logging.error(f"主迴圈發生未知錯誤: {e}", exc_info=True)
    finally:
        logging.info("程式執行完畢。")

# --- 6. 程式入口點 ---
if __name__ == "__main__":
    main()
