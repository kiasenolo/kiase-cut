# ！！！注意！！！
### 這是一個 全AI生的專案
### 全AI生的 全AI生的 全AI生的 很重要 所以講三次
### 千萬 不要過度依賴 把他當做正式的軟體來使用
### 這個東西是我自己用的 所以我出事了 我自己承擔
### 但是你如果過度依賴 然後在某一次的更新 也炸了 那不關我的事
### 哦對了 我不會python 所以這個專案裡面的東西我都不懂
### 出事了 你丟issues 我只會 自己復現 -> 給AI修
### 這東西不會有多少人工介入
# Beta 0.2.0b1 （2026 11 12）
## 第一個公開 Beta：只有桌面版（Linux / Windows） Android 還沒有 下週之後再說
## 詳細請看這個[Release](https://github.com/kiasenolo/kiase-cut/releases/tag/v0.2.0b1)
# 目前各版本狀態 （上次更新：2026 11 15）
## Arch Linux （主要 穩定） [ 裝置：HP Laptop 15 fd0218tu ]
配置基本跟你查到的型號一樣 但我這臺記憶體多8GB 所以是16GB  
測試環境是KDE Plasma Wayland  

linux版本是目前我確定 能用且相對穩定的版本  
大部分的功能都是在這裡測試的  
所以我說能用 一般都是保證Linux能用  
## Windows （穩定 但效能問題）
配置是13代i5的桌機 有RTX3050 RAM 16GB

現在的Windows版本相對來說 有比較好了  
但可能還是會出現我們親愛的Windows**專屬**的BUG  
我的主要環境不是windows 再加上我通常只有回到家才會用到windows  
所以基本上 很難去保證windows不出事  
那你可能會說 那你回到家讓AI修啊  
但 我很常在一個禮拜還沒過完的情況下 就把一個禮拜的配額...他媽用完了....我是弱智  
而且我禮拜一到五都在宿舍 在宿舍用的電腦是什麼？linux  
對 我有windows 但我不想 因為我覺得每次切到windows我都與世隔絕 不好  
那五晚上然後六和日才會是在家的  
## Android （極度不穩定） [ 裝置：2410CRP4CG ]
包不穩定的兄弟 他媽新版本甚至編譯失敗  
有點傻逼 但我不知道 我覺得可能是我刪錯東西還是怎樣  
但是就....這個東西 你用它 等於 你今天在跟你的人生戰鬥  
如果你覺得你人生活到頭了 你可以考慮自己抓舊版本編譯  
在你的手機上面用過哪怕那麼一次 你就會豁然開朗  
然後噴一句 這他媽什麼玩意兒 傻逼東西  
這個東西用起來 根本就是手機/平板上他媽長了個傻逼電腦  
手機更慘 我其實有在我自己的 Galaxy A56 裝過  
哇 就....如果你的眼睛不會痛的話 你用吧  
然後第一步就是先處理最大寬度 後續的使用 基本就是你就已經不是跟人生搏鬥那麼簡單了  
## macOS （根本沒有）
你給我錢買 M6 MacBook Pro 14-inch 我就幫你測試  
或者幫我買一個 M5 Ultra Mac Studio + Studio Display 也可以  
兩個都買就更好了  
我是可以虛擬機測試啦.....測試你媽啦 那種環境最好是有這種耐心可以測試  
## iPadOS （...）
同上 然後你還需要再要給我買iPad Pro  
然後幫我交這個 安裝測試軟體的授權費 還有上架的  
然後每個月給我100/200美元用ClaudeCode開發kiase-cut  
我現在在用Pro 所以....沒關係 你給我300美元就好  
這樣 就好了 因為要處理多個平臺的話 會更加麻煩 更加吃token  
然後我也是會累的 所以你還要多給我一百萬美元  
而且聽說這個會有點複雜 啊不然這樣 我們請我們的Claude來解釋一下這個  

> 由 Claude 解釋 憑印象整理 沒有逐項查證
>
> 1. **要有 Mac**：iOS / iPadOS 只能用 Xcode 編譯 沒 Mac 連編譯都不行  
> 2. **要錢**：發佈要 Apple Developer Program（每年 99 美元） 免費帳號裝的 app 7 天就過期  
> 3. **技術**：PySide6 沒有官方 iOS 版 numpy / Pillow / ffmpeg / MLT 都要重新交叉編譯 OpenGL 也要改走 Metal  
> 4. **審核**：App Store 對內嵌 Python 直譯器的規定 不確定會不會過  
>
> 簡單來說 等於把 Android 那條路再走一次 還多一個 Mac

對 所以就是 你要我搞這個 你會整死我  
不要覺得程式碼全部AI生 我就可以真的輕輕鬆鬆去做其他事情了  
很多時候 很多的問題 你還是需要自己去抓 才會比較準  
你必須要先成為使用者 你才能理解使用者的處境  
差不多是這個意思  
當然 避免爭議 我不是說你開發一個東西你就一定要完全站在使用者的角度  
這很難 但這也就是為什麼我們有時候需要測試人員的原因  
公開這個專案的其中一個原因其實也是這個

哦對了 如果你真的很想的話 你可以自己寫 或者 自己去用AI生  
但是如果你給我丟PR 我不會收 因為我必須確定我自己有過審核 我才敢收  
# 如何使用
## 第零步 // 前置條件
### Windows
先去裝 Git 你要把東西clone下來你需要他  
連接：https://git-scm.com/install/windows  

再來裝 kdenlive  
連接：https://kdenlive.org/  
我知道沒有人會去動 但 就是 裝預設的路徑就好  
我的渲染核心是mlt 所以mlt是我爸爸  
ffmpeg也會跟著kdenlive一起來 ffmpeg也是我爸爸  
其實如果你有裝Shotcut也是可以的 但是你要額外配置ffmpeg  
我這邊懶惰教 索性kdenlive 解決一切  

然後去裝python 然後加到環境變數  
連接：https://www.python.org/ftp/python/3.14.10/python-3.14.10-amd64.exe  
**然後 切記 切記 切記**  
**勾選下面的 `Add python.exe to PATH`**  
**你不勾 用不了**  
### Arch Linux
裝這四個基礎套件  
`sudo pacman -S git python mlt ffmpeg`  
然後就...沒了 就這樣  
## 第一步 // clone
```
cd 你喜歡的/資料夾//或者//你平時放/應用程式/的地方
git clone https://github.com/kiasenolo/kiase-cut
```
## 第二步 // 打開
### Windows
點 `start_kiasecut.bat`
### Arch Linux
先 `chmod +x start_kiasecut.sh` ( 只需要做第一次 )  
然後再 `./start_kiasecut.sh`
### 初次啟動
第一次開會等半年（開玩笑）  
給他一點耐心 同時確保自己的網絡環境不會太差  
就好了 他把所有東西裝好就基本沒事了  
會吃掉你保守1.5GB的儲存空間  
## 啊你的Android版本勒？
上面也講過了 不穩定 而且我不熟悉他的build  
所以我可能要跟AI大戰三百萬回合我才可以寫出android的build教學  
因為這個東西會牽扯到一大堆 sdk java 什麼鬼的 而且我只用linux build過  
windows沒測試 所以就 有興趣自己研究 我這邊暫時不提供  
等到我覺得時機成熟 我再寫教學  
但是這個禮拜我的AI使用限制爆了  
所以要等下禮拜我繼續浪費token讓AI研究&優化android版本  
# 檢查更新
Windows : `update.bat`  
Linux : `update.sh` ( 記得先 `chmod +x update.sh` 然後只需要做第一次 )  
# 前言
簡單來説 我的慣用系統是linux
啊FL和我的那一堆VST 經過AI幫我部署後 幾乎全部都能在Linux用了（雖然有時不穩定）  
唯獨剪映 他真的 我哭死 這東西似乎用了什麽特殊手段 導致用wine開 根本用不了  
AI來了也沒輒 claude直接說 沒辦法 但可以嘗試換軟體或者直接重開到windows  
但每次重開到windows 我就跟世界脫節一樣 雖然還是能作曲  
但是我寫的程式 我的blender專案 全部都在linux啊！！！！！！   
我受不了了！！！！ 啊！！！！ AI！！！啟動！！！！  
額...對....所以我決定用AI vibe出來一個剪片軟體  
你可以想像 他就是一個縫合怪 縫了很多 我會用到的東西 縫了很多很神奇的邏輯  
但不一定適合所有的人 但反正 對我來說 就是好用 就這樣  

我要用AI取代掉你們這群繪師...的剪片軟體....啊不然勒？  
你指望我取代你們繪師哦？我有病吧？我還想看你們畫圖誒  
我不是弱智好嗎？  

## 分享一些故事
我以前其實算是 一個很喜歡玩剪片的人  
但是 我一直找不到適合自己的軟體  
主要是 我以前是玩平面設計軟體起家的 所以我對這方面特別敏感  
但我遇到的很多免費的剪片軟體都沒有類似的功能  
以至於我到現在 都還沒有一個剪片的固定流程  

我作曲有了 FL編曲 blender/lunacy做圖  
我修圖/製圖也有 畫師畫圖/我拿我自己的圖片 lunacy做遮罩 blender修圖  
寫網頁更不用講 這個東西以前做到現在 算很成熟了  
界面設計也是直接用lunacy搞  

就唯獨剪片  
- blender?
  - 剪片界面的邏輯不適合我 有些東西不夠直覺 
  - 要做些簡單的效果可能會需要複雜的步驟
- 剪映？
  - 近乎完美 效能也不錯 但是大 有一些不必要的東西
  - hmmmm 這是之前發現的 他會...加密你的草稿 雖然後來發現有人[做了個工具](https://github.com/zzz1999/jy-draft-port)解決這個問題 算是鬆了一口氣 我之前做的東西還有救
  - 要做些神奇的特效 需要用blender提前算好
  - 有些素材需要用lunacy搞
- 達文西？
  - 我的筆電用達文西？搞笑嗎？
  - 對我不太友善 但還是要講 這東西對於專業的人來說 一定好用
- 還有其他一些我查到的 免費的軟體 但不外乎都是
  - 沒有關鍵幀
  - 有關鍵幀 但能調的東西不多
  - 蛤？預覽窗不能直接編輯東西哦
  - emmm 能直接拖 但沒有對齊....啊....
  - 啊！！！達文西的時間線概念很香啊！！！！但是他沒有啊！！！啊！！！

等等 之類的 就 這也是為什麼我會決定用AI生一個  
-> 誒你用AE啊  
<- ...  
<- 我....我用不習慣....而且....我....沒錢....試用版用完了.....  
-> PR勒？  
<- 小時候開過一次 不會用 放棄了 試用版 早就過了  
-> 誒之前不是有個很紅的 [ArtCraft](https://getartcraft.com/)?  
<- 可是 他東西是Adobe的邏輯 我前面有講 我用不習慣 所以我一開始就沒考慮  
大概是這樣  

## 我具體讓AI縫了什麼？
首先 平常因為用作曲軟體的次數 大於 剪片軟體  
所以 索性把FL播放列表的拖拽 滾輪 之類的邏輯 抄過來了 體驗一樣真好  
其次 設計軟體 我自己是參照lunacy（我用習慣了） 所以一些排版啊 什麼的 就 對 lunacy的邏輯比較爽 但是現在還沒auto layout （AI生這個 沒有精確提示詞應該效果不太好）  
再來 是達文西的 可以給片段上色 但達文西是固定幾個顏色 但我的可以亂上色 比較爽  
最後 上字幕軟體的批量編輯邏輯 就 多選文字片段 然後你就可以在同一個輸入區裡面 編輯不同的字幕了 不需要一個一個去找

## 有沒有一些特色
有 包有的 除了縫合以外 還有下面這些神奇的東西：
- 你可以用blender的合成器 做你自己的視覺效果 然後導到這個剪片軟體裡面
- 有一些自定形狀 你做一些幾何的東西 你的人生會比較好過
- 有一種叫做靜態複合片段的東西 讓你可以用剪片軟體 做一張圖 然後在裡面使用 （你要export成圖片也不是不行）

差不多是這樣 很爽啊

## 一些補充
- blender的合成器轉glsl是我用AI生的
  - 他放在/tools/converters/compositor_to_hyprshade.py
  - 他的名字之所以叫 合成 to Hyprshade 是因為當初這個東西是為Hyprshade服務的
  - 那本身自己就有用blender修圖的習慣 所以做自制效果器其實不會太難

## 最後
青菜蘿蔔各有所愛 沒有一個剪片軟體是完美的（AE PR 達文西除外 他們對於某些專業的人來說 也許是完美的）  
我生的這個也不例外 生這個剪片軟體的目的 只是為了創造一個 屬於自己的工作流程 自己的使用邏輯  
公開 也只是為了給有需要的人用而已 反正這東西免費  
我也不會推薦你們把這個剪片軟體當作你們的日用剪片軟體（畢竟是AI生的 AI很難幫你覆蓋全範圍的測試 穩定性不保證）  
除非 大多數人覺得他穩定 / 或者我哪天用他很屌很帥的東西 然後我一頓誇穩定性 那就另當別論  

反正 雖然 我不是專業剪片的 我自己剪出來的東西也沒多好  
但我還是希望 生出一個這樣的東西 讓市場多一種選擇  

## 哦對了
雖然東西是全AI生的 但是在效果器那邊 可以看到有個分類叫做KILO的  
裡面的效果都是我之前用blender自己做的  
然後把它轉出來 給kiaseCut用的  
你可以在VFX聞到我的臭味 不是一個很好的體驗 但是無所謂  

# KiaseCut是什麼？

就是 一個我自己覺得 跟剪映差不多簡單 但是會比剪映還要能夠做更多事情的軟體
生他 就只是為了解決我長期以來面對的作業系統問題 和 沒有一個正式的剪片工作流

---
# 然後以下 全AI生 對於有興趣瞭解的人 可以看看 也推薦看看
## 執行

需要 Python 3.11+、`pip install PySide6 numpy Pillow moderngl`（moderngl 負責跑效果器 預覽和匯出都用它）、
PATH 裡有 ffmpeg 還有 MLT 7：  
Windows 用 Kdenlive 或 Shotcut 裡面那份（會自動找 找不到就把 `KIASECUT_MLT` 設成它的安裝資料夾）  
Linux 用系統套件（`mlt` / `libmlt7`）  

或者直接用 `start_kiasecut.bat`（Windows：缺套件會幫你裝）  
`./start_kiasecut.sh`（Linux：第一次會把套件裝進 `.venv` ffmpeg 或 MLT 沒裝會警告 後面的參數會原封不動傳進去）  
`update.bat` / `./update.sh` 會把最新版拉進 git 資料夾（只做 fast-forward 你在資料夾裡改的東西不會被蓋掉）下次啟動會補裝缺的套件  

```
python -m kiasecut                         # 專案管理器：選一個專案
python -m kiasecut draft_content.dec.json  # 匯入解密後的剪映草稿
python -m kiasecut project.kiasecut.json   # 開啟存好的專案
```

不想裝 Python 的話：`./build_exec.sh`（Linux）或 `build_exec.bat`（Windows）
會用 PyInstaller（`packaging/kiasecut.spec`）在 `app-build-exec/kiasecut/` 做出執行檔 整個資料夾複製走 裡面的 `kiasecut` / `kiasecut.exe` 就是程式  
MLT 和 ffmpeg 不包在裡面 找法同上：MLT 的外掛要用它自己編譯時的 Qt 和 FFmpeg 所以渲染引擎（`engine/`）是獨立的程式 不會碰到編輯器的 Qt 和 FFmpeg  
`build_exec.bat --bundle-mlt` 會把 Kdenlive 的 MLT、Qt 和 ffmpeg 複製進資料夾（`mlt/`） 給沒裝 Kdenlive 的電腦用  

## 專案資料夾

一個專案就是一個資料夾（檔案 > 新專案 會問名字和位置）：

```
My Video/
    My Video.kiasecut.json   專案檔（媒體路徑存成相對於這個資料夾的路徑）
    Media/                   媒體庫：裡面的子資料夾就是媒體庫的資料夾
    Cache/                   波形、代理檔（只有 設定 > 緩存位置 > 專案內 才會放這裡）
    Exports/                 匯出的影片（匯出視窗預設從這裡開始）
    Backup/                  專案檔的舊副本 每存一次一份
```

自動存檔和復原：專案有沒存的修改時 每隔幾分鐘（設定 > 自動存檔間隔）會寫一份副本到 `~/Documents/KiaseCut/auto-save` 
檔名是專案名加時間 只留最新的幾份（設定 > 自動存檔上限 預設 30 開啟資料夾 可以看到它們） 專案檔本身不會被動到  
如果 KiaseCut 不是正常關閉的（當機、斷電） 下次啟動會問你要不要把最新的自動存檔拿回來：它會以「未儲存的修改」開啟 照平常存檔就好（它的專案資料夾已經不在的話 就當作沒有資料夾的專案）  
每個正在跑的 KiaseCut 會在那裡放一個 `session-<pid>.json` 正常關閉就會刪掉  
`crash.log` 在它們旁邊 記著 Python 對當機的紀錄（每個執行緒的堆疊） 開 issue 時可以附上  

## License

KiaseCut is free software under the GNU General Public License, version 3 or (at your
option) any later version: see `LICENSE`. This covers every version published so far, from
the first commit on. It comes with no warranty.

The exception is what KIASENOLO drew by hand: the logo and the pictures for the wiki's demos
(`images/`), the interface's icons (`kiasecut/look/glyphs/`, the arrows `kiasecut/look/arrow-*.svg`
and `partial.svg`; their sources in `icon/`) and the Lunacy documents they are drawn in
(`images.free`, `icons.free`). The demo pictures the program makes from them
(`kiasecut/wikibuild.py`, in the user's cache folder, not in the repository) are theirs too.
They are © 2026 KIASENOLO under CC BY 4.0 (`LICENSES/CC-BY-4.0.txt`): use, change and share them,
also commercially, with credit to "KIASENOLO". `REUSE.toml` says it for each file.

Taken from elsewhere:

| In KiaseCut | From | License |
|---|---|---|
| `kiasecut/filters/blender_glare.glsl` | Blender's Glare compositor node (`node_composite_glare.cc`, `compositor_glare_*.glsl`) | GPL-2.0-or-later |
| `kiasecut/filters/blender_lens_distortion.glsl` | Blender's Lens Distortion compositor node (`node_composite_lens_distortion.cc`, `compositor_*_lens_distortion.glsl`) | GPL-2.0-or-later |
| `kiasecut/filters/oil_paint.glsl` | Blender's Kuwahara compositor node (`compositor_kuwahara_*.glsl`) | GPL-2.0-or-later |
| `kiasecut/filters/nodes/dilate_erode.glsl`, `nodes/filter.glsl`, `blur.glsl` | Blender's Dilate/Erode, Filter and Blur compositor nodes (`compositor_morphological_*.glsl`, `compositor_filter.glsl`, `RE_filter_value`) | GPL-2.0-or-later |
| `kiasecut/filters/blender_tex_*.glsl`, `blender_color_ramp.glsl` | Blender's texture nodes (Brick, Checker, Gradient, Magic, Noise, Voronoi, Wave, White Noise) and Color Ramp (`colorband.cc`) | GPL-2.0-or-later |
| `kiasecut/filters/nodes/tex_*.glsl` | Blender's texture nodes as compositor nodes, with Blender's sockets, settings and shader code (`gpu_shader_material_tex_*.glsl`, `gpu_shader_material_noise.glsl`, `..._fractal_noise.glsl`, `..._voronoi.glsl`, `gpu_shader_common_hash.glsl`) | GPL-2.0-or-later |
| `kiasecut/filters/nodes/*.glsl` (all but `picture.glsl` and `tex_*.glsl`), `posterize.glsl`, `invert.glsl` | reimplementations of the Blender compositor nodes of the same names (Math, Mix, Map Range, Vector Math, Value, Switch ...): their behaviour and constants, checked against Blender 5.2 | GPL-2.0-or-later |
| `kiasecut/nodemenu.py` | the layout of Blender's compositor Add menu (`node_add_menu_compositor.py`) | GPL-2.0-or-later |
| `kiasecut/filters/blender_sensor_noise.glsl` | the Sensor Noise node group of Blender's Essentials assets (`compositing_nodes_essentials.blend`), by Blender Studio | CC0 (public domain) |
| `kiasecut/filters/blender_vignette.glsl`, `nodes/rounded_square_mask.glsl` | the Vignette and Rounded Square Mask node groups of Blender's Essentials assets (`compositing_nodes_essentials.blend`), by Blender Studio | CC0 (public domain) |

Each was exported with `compositor_to_hyprshade.py` or read from Blender's shaders, then rewritten by
hand; its header names the Blender files. GPL-2.0-or-later code can be used under GPL-3.0, which is
how KiaseCut carries it. The license texts are in `LICENSES/` (`GPL-2.0-or-later.txt`,
`CC0-1.0.txt`, `CC-BY-4.0.txt`; KiaseCut's own is `LICENSE`). Blender: <https://www.blender.org>, source at
<https://projects.blender.org/blender/blender>, © Blender Authors.

The full list of what a build carries, with the license texts, is `THIRD-PARTY-NOTICES.md`.

Used, not included: PySide6 / Qt (LGPL-3.0), MLT (LGPL-2.1), FFmpeg (LGPL or GPL, by
build), numpy (BSD), Pillow (MIT-CMU), moderngl (MIT). An executable from
`build_exec.bat --bundle-mlt` also carries Kdenlive's MLT, Qt and FFmpeg: hand on their
licenses with it (Kdenlive's `share/` holds them).
