#!/usr/bin/env python3

import argparse
import logging
import os
import shutil
import sys
import tempfile
import time

# --- 1. 設定日誌 ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)

# --- 2. 更新 Proxychains 設定檔函數 ---
def update_proxychains_with_pool(
    validated_proxies_list,
    conf_path,
    chain_strategy="random_chain",
    default_proxy_type="http"
):
    """
    更新 proxychains 設定檔，使用提供的代理池並設定鏈策略。

    Args:
        validated_proxies_list (list): 包含 'ip:port' 字串的已驗證代理清單。
        conf_path (str): proxychains 設定檔路徑。
        chain_strategy (str): 要啟用的鏈策略 (例如 "random_chain", "round_robin_chain", "strict_chain")。
        default_proxy_type (str): 清單中所有代理的預設類型 (例如 "http", "socks4", "socks5")。

    Returns:
        bool: 更新成功返回 True，否則 False。
    """
    if os.geteuid() != 0:
        logging.error(f"更新 {conf_path} 需要 root 權限。請使用 sudo 執行。")
        return False

    if not os.path.exists(conf_path):
        logging.error(f"設定檔 {conf_path} 不存在。")
        return False

    backup_path = f"{conf_path}.bak.pool.{int(time.time())}"
    logging.info(f"正在備份 {conf_path} 到 {backup_path}...")
    try:
        shutil.copy2(conf_path, backup_path)
    except Exception as e:
        logging.error(f"備份失敗: {e}")
        return False

    new_config_lines = []
    original_lines = []
    try:
        with open(conf_path, 'r', encoding='utf-8') as f_read:
            original_lines = f_read.readlines()
    except Exception as e:
        logging.error(f"讀取設定檔 {conf_path} 失敗: {e}")
        return False

    # 已知鏈策略指令
    known_strategies = ["random_chain", "round_robin_chain", "strict_chain", "dynamic_chain"]
    strategy_set = False
    in_proxy_list_section = False
    proxy_list_header_written = False

    for line in original_lines:
        stripped_line = line.strip()

        # 處理鏈策略行
        is_strategy_line = False
        for known_strat in known_strategies:
            if stripped_line.startswith(known_strat) or stripped_line.startswith(f"#{known_strat}"):
                is_strategy_line = True
                if known_strat == chain_strategy or (known_strat == "dynamic_chain" and chain_strategy == "strict_chain"): # dynamic_chain is alias for strict_chain
                    new_config_lines.append(f"{chain_strategy}\n") # 取消註解並設定為選擇的策略
                    strategy_set = True
                    logging.debug(f"設定鏈策略為: {chain_strategy}")
                elif known_strat == "dynamic_chain" and chain_strategy != "strict_chain" and chain_strategy != "dynamic_chain":
                     new_config_lines.append(f"#{known_strat}\n") # 註解掉 dynamic_chain 如果不是選它
                elif chain_strategy != known_strat : # 註解掉其他策略
                    new_config_lines.append(f"#{known_strat}\n" if not stripped_line.startswith("#") else line)
                else: # 其他情況，例如 dynamic_chain 和 strict_chain 互相對應
                    new_config_lines.append(line) # 保留原樣，可能已正確
                break
        
        if is_strategy_line:
            continue

        # 處理 [ProxyList] 區段
        if stripped_line == "[ProxyList]":
            new_config_lines.append("[ProxyList]\n")
            logging.debug("找到 [ProxyList] 區段。正在寫入提供的代理...")
            for proxy_ip_port in validated_proxies_list:
                try:
                    ip, port = proxy_ip_port.split(':')
                    new_config_lines.append(f"{default_proxy_type} {ip} {port}\n")
                except ValueError:
                    logging.warning(f"代理格式錯誤，已跳過: {proxy_ip_port}")
            in_proxy_list_section = True
            proxy_list_header_written = True
            continue
        
        if in_proxy_list_section:
            # 在 [ProxyList] 區段之後，我們只保留註解、空行或新的區段標頭
            if stripped_line.startswith("#") or not stripped_line or stripped_line.startswith("["):
                new_config_lines.append(line)
                if stripped_line.startswith("[") and stripped_line != "[ProxyList]":
                    in_proxy_list_section = False # 離開 ProxyList 區段
            # 其他 (看起來像舊代理的行) 會被忽略
            continue
            
        new_config_lines.append(line)

    # 如果遍歷完畢，策略行仍未被顯式設定（例如原設定檔中沒有對應行）
    if not strategy_set and chain_strategy in known_strategies:
        # 嘗試在檔案開頭附近插入策略（這是一個簡化處理，理想位置可能更複雜）
        # 或者，更好的做法是要求 `proxychains4.conf` 至少包含被註解的策略行
        logging.warning(f"選擇的策略 '{chain_strategy}' 在原設定檔中沒有對應的行可以取消註解。將嘗試添加。")
        # 簡單地加到設定檔頂部，通常策略設定在頂部
        new_config_lines.insert(0, f"{chain_strategy}\n")


    # 如果原檔案沒有 [ProxyList] 標頭，則在末尾添加
    if not proxy_list_header_written:
        logging.warning(f"設定檔 {conf_path} 中未找到 [ProxyList] 標頭。將在檔案末尾添加代理。")
        new_config_lines.append("\n[ProxyList]\n")
        for proxy_ip_port in validated_proxies_list:
            try:
                ip, port = proxy_ip_port.split(':')
                new_config_lines.append(f"{default_proxy_type} {ip} {port}\n")
            except ValueError:
                logging.warning(f"代理格式錯誤，已跳過: {proxy_ip_port}")


    # 使用臨時檔案進行寫入
    try:
        with tempfile.NamedTemporaryFile(mode='w', delete=False, encoding='utf-8', dir=os.path.dirname(conf_path)) as temp_f:
            temp_path = temp_f.name
            for line_to_write in new_config_lines:
                temp_f.write(line_to_write)
        
        shutil.move(temp_path, conf_path)
        try:
            shutil.copymode(backup_path, conf_path)
            original_stat = os.stat(backup_path)
            shutil.chown(conf_path, user=original_stat.st_uid, group=original_stat.st_gid)
        except Exception as e:
            logging.warning(f"設定檔案權限或擁有者時出錯: {e}")

        logging.info(f"已成功更新 {conf_path}。啟用策略: {chain_strategy}。共加入 {len(validated_proxies_list)} 個代理。")
        return True
    except Exception as e:
        logging.error(f"寫入更新後的設定檔 {conf_path} 失敗: {e}")
        logging.info(f"正在從備份 {backup_path} 還原...")
        try:
            shutil.move(backup_path, conf_path)
        except Exception as restore_e:
            logging.error(f"還原設定檔失敗: {restore_e}.")
        return False
    finally:
        if 'temp_path' in locals() and os.path.exists(temp_path):
            os.remove(temp_path)

# --- 3. 主程式 ---
def main():
    parser = argparse.ArgumentParser(
        description="使用已驗證的代理池來設定 proxychains4.conf。",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument('-i', '--input-file', required=True,
                        help="包含已驗證代理清單的 TXT 檔案 (每行格式 'ip:port')。")
    parser.add_argument('-c', '--conf', default='/etc/proxychains4.conf',
                        help="proxychains 設定檔路徑。\n預設: /etc/proxychains4.conf")
    parser.add_argument('-s', '--strategy', default='random_chain',
                        choices=['random_chain', 'round_robin_chain', 'strict_chain'],
                        help="要啟用的 proxychains 鏈策略。\n預設: random_chain")
    parser.add_argument('-pt', '--proxy-type', default='http',
                        choices=['http', 'socks4', 'socks5', 'https'],
                        help="代理清單中所有代理的預設類型。\n預設: http")
    parser.add_argument('--verbose', '-v', action='store_true',
                        help="啟用 DEBUG 等級日誌輸出。")

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # 讀取已驗證的代理清單
    validated_proxies = []
    try:
        with open(args.input_file, 'r', encoding='utf-8') as f:
            validated_proxies = [
                line.strip() for line in f
                if line.strip() and not line.strip().startswith('#') and ':' in line.strip()
            ]
        if not validated_proxies:
            logging.error(f"提供的代理清單檔案 {args.input_file} 為空或格式不符。程式終止。")
            sys.exit(1)
        logging.info(f"從 {args.input_file} 成功讀取了 {len(validated_proxies)} 個已驗證代理。")
    except FileNotFoundError:
        logging.error(f"代理清單檔案 {args.input_file} 不存在。程式終止。")
        sys.exit(1)
    except Exception as e:
        logging.error(f"讀取代理清單檔案 {args.input_file} 失敗: {e}。程式終止。")
        sys.exit(1)

    # 更新 proxychains4.conf
    if update_proxychains_with_pool(
        validated_proxies,
        args.conf,
        args.strategy,
        args.proxy_type
    ):
        logging.info("Proxychains 設定成功完成。")
    else:
        logging.error("Proxychains 設定失敗。請檢查日誌以獲取詳細資訊。")
        sys.exit(1)

# --- 4. 程式入口點 ---
if __name__ == "__main__":
    main()
