# proxy_pool

## proxy_pool_check

1.  **自動從 TXT 檔案匯入代理清單** (這部分功能已經透過 `-f` 或 `--file` 參數實現，我會確保說明清晰)。
2.  **在結束測試後，將可用的代理 (格式 IP:Port) 匯出到一個指定的 TXT 檔案中**。
### 主要更新內容：

1.  **新增 `--output-file` 命令列參數**：
    * 在 `argparse` 設定中，新增了 `-o` 或 `--output-file` 選項。
    * 使用者可以透過這個參數指定一個檔案名稱，用於儲存驗證後可用的代理。

2.  **新增 `export_valid_proxies` 函數**：
    * 這個函數負責將 `valid_proxies` 清單中的代理逐行寫入到由 `--output-file` 指定的檔案中。
    * 包含基本的錯誤處理（如 `IOError`）。

3.  **在 `main` 函數中呼叫匯出邏輯**：
    * 在代理驗證 (`check_proxies_concurrently`) 完成後，如果使用者提供了 `--output-file` 參數，則呼叫 `export_valid_proxies` 函數。
    * 無論是否設定了 `--no-update`，只要指定了 `--output-file`，並且有可用代理，就會執行匯出。

4.  **日誌和流程調整**：
    * 更新了日誌訊息，使其更清晰地反映操作流程。
    * 如果 `proxy-list.txt` 讀取後為空，或者驗證後沒有可用代理，會有更明確的提示和處理。
    * 如果沒有可用代理，且使用者未指定 `--no-update`（即打算更新 `proxychains4.conf`），程式會以錯誤狀態退出。

### 如何使用更新後的腳本：

1.  **儲存腳本**：將程式碼儲存為 `.py` 檔案 (例如 `proxy_pool_check.py`)。
2.  **賦予執行權限**：`chmod +x proxy_pool_check.py`。
3.  **準備代理清單**：建立一個 TXT 檔案 (例如 `proxy-list.txt`)，每行包含一個 `ip:port` 格式的代理。

4.  **執行範例**：
    * **驗證代理並將可用代理匯出到 `valid_proxies.txt`，但不更新 `proxychains.conf`**：
        ```bash
        ./proxy_pool_check.py -f proxy-list.txt -o valid_proxies.txt --no-update
        ```
    * **從 `my_proxies.txt` 讀取，驗證後將可用代理匯出到 `good_ones.txt`，並開始輪換更新 `/etc/proxychains4.conf` (需要 sudo)**：
        ```bash
        sudo ./proxy_pool_check.py -f my_proxies.txt -o good_ones.txt -s 120 --proxy-type socks5
        ```
    * **僅驗證代理，並將結果打印到控制台 (不匯出到檔案，不更新 `proxychains`)**：
        ```bash
        ./proxy_pool_check.py --no-update
        ```
        (如果 `valid_proxies` 非空且未指定 `-o`，可用代理會列印到控制台)
    * **從預設檔案 `proxy-list.txt` 讀取並更新 `proxychains4.conf`，不另外匯出可用代理到檔案**：
        ```bash
        sudo ./proxy_pool_check.py
        ```
## config_proxy_pool

1.  **儲存腳本**：將上面的程式碼儲存為 `config_proxy_pool.py`。
2.  **賦予執行權限**：`chmod +x config_proxy_pool.py`。
3.  **準備已驗證的代理清單檔案**：
    * 這個檔案應該是純文字檔案，每行包含一個 `ip:port` 格式的代理。
    * 例如，你可以使用前一個 `proxy_pool_check.py` 腳本的 `-o valid_proxies.txt` 選項來產生這個檔案。

4.  **執行範例 (通常需要 sudo 來修改 `/etc/proxychains.conf`)**：
    * **使用 `valid_proxies.txt` 中的代理，設定為 `random_chain` 策略，代理類型為 `http`**：
        ```bash
        sudo ./config_proxy_pool.py -i valid_proxies.txt
        ```
    * **使用 `my_socks_proxies.txt`，設定為 `round_robin_chain`，代理類型為 `socks5`，並指定設定檔路徑**：
        ```bash
        sudo ./config_proxy_pool.py -i my_socks_proxies.txt -s round_robin_chain -pt socks5 -c /usr/local/etc/proxychains4.conf
        ```
    * **啟用詳細日誌輸出**：
        ```bash
        sudo ./config_proxy_pool.py -i valid_proxies.txt -v
        ```
* **讀取代理清單**：從指定的檔案讀取所有 `ip:port`。
* **設定鏈策略**：
    * 它會嘗試取消註解您選擇的策略行 (例如 `random_chain`)。
    * 同時，它會嘗試註解掉 `proxychains.conf` 中其他的已知策略行，以確保只有您選擇的策略生效。
* **清空並填充 `[ProxyList]`**：
    * 腳本會找到 `[ProxyList]` 區段。
    * 它會移除該區段下任何已存在的舊代理條目。
    * 然後，將您提供的已驗證代理清單中的所有代理（以指定的 `proxy-type` 格式化）添加到該區段。
* **安全寫入**：同樣使用備份、臨時檔案和原子移動操作來安全地更新設定檔。

現在您有兩個腳本：
1.  第一個腳本 (`proxy_pool_check.py` 或類似名稱) 用於 **驗證代理** 並可將單個代理輪換寫入 `proxychains.conf`，或 **匯出所有可用代理** 到一個檔案。
2.  第二個腳本 (`config_proxy_pool.py`) 用於讀取那個匯出的可用代理清單檔案，並將 **整個代理池配置到 `proxychains.conf`** 中，讓 `proxychains` 工具自己根據您選擇的策略（如 `random_chain`）來使用這些代理。
