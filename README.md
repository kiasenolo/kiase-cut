# ！！！注意！！！
### 這是一個 全AI生的專案
### 全AI生的 全AI生的 全AI生的 很重要 所以講三次
### 千萬 不要過度依賴 把他當做正式的軟體來使用
### 這個東西是我自己用的 所以我出事了 我自己承擔
### 但是你如果過度依賴 然後在某一次的更新 也炸了 那不關我的事
# 前言 （這段是KILO自己加的）
簡單來説 我的慣用系統是linux
啊FL和我FL的那一堆插件 經過AI幫我部署後 都能在Linux用了（雖然有時不穩定）
唯獨剪映 他真的 我哭死 似乎是有特殊的手段 導致wine用不了  
AI來了也沒輒 claude直接說 沒辦法 但我可以嘗試換軟體或者直接重開到windows  
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
但是 我一直找不到適合自己的  
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

# KiaseCut

A small Jianying (剪映)-style video editor on top of the MLT engine. Goal: edit — and
reproduce frame-accurately — the kind of video made in Jianying, without its extras.

## Run

Needs Python 3.11+, `pip install PySide6 numpy Pillow moderngl` (moderngl runs the filters, in the
preview and the export), ffmpeg on PATH, and MLT 7:
on Windows the copy inside Kdenlive or Shotcut (found automatically, or set
`KIASECUT_MLT` to the install folder); on Linux the system package (`mlt` / `libmlt7`).

Or start it with `start_kiasecut.bat` (Windows: installs the packages if missing) or
`./start_kiasecut.sh` (Linux: installs them into `.venv` on the first run, warns when
ffmpeg or MLT is missing, passes its arguments on). `update.bat` / `./update.sh` pull the
latest version into a git checkout (fast-forward only: changes made in the folder are never
merged over); the next start installs any missing packages.

```
python -m kiasecut                         # the project manager: pick a project
python -m kiasecut draft_content.dec.json  # import a decrypted Jianying draft
python -m kiasecut project.kiasecut.json   # open a saved project
```

An executable without Python: `./build_exec.sh` (Linux) or `build_exec.bat` (Windows)
builds `app-build-exec/kiasecut/` with PyInstaller (`packaging/kiasecut.spec`) — copy the
whole folder, the program is `kiasecut` / `kiasecut.exe` in it. MLT and ffmpeg stay
outside, found as above: MLT's plugins need the very Qt and FFmpeg they were built with, so
the render engine is a program of its own (`engine/`) that has neither of the editor's.
`build_exec.bat --bundle-mlt` copies Kdenlive's MLT, Qt and ffmpeg into the folder (`mlt/`),
for machines without Kdenlive.

Project manager (專案管理器, shown when it starts without a project, and from 檔案 >
專案管理器… / Ctrl+Shift+O): every project - those in the projects folder (where 新專案
puts them) and those on the recent list - as cards, newest first, with a search box. Each
card shows the project's title (檔案 > 專案資訊), its folder's name and when it was last
saved; one without a title shows just the folder and the time.
It works like a small file manager over the projects folder: folders that group projects
show as folder cards (double-click to go in, 上一層 - or the ↑ card - to go back; the search
box looks through every folder), 新增資料夾 makes one, 新增專案… makes a project in the folder
shown. Right-click a card to rename it, copy it (建立副本), move it to another folder (or drag
it onto a folder card or ↑), delete it (to the recycle bin - a project that owns its folder
goes with the whole folder, a project sharing its folder with others only with its file),
open its folder or take its thumbnail away. The project open in the editor is not moved,
renamed or deleted there; the recent list follows what was moved or deleted.
Double-click one to open it; 開啟其他專案… is also there. A project has no thumbnail at first:
檔案 > 把目前畫面設為專案縮圖 saves the frame the preview shows, or make a static compound
named `_thumbnail` (it has to be static; another kind cannot take that name) - its picture
becomes the thumbnail every time the project is saved, and wins over a saved frame. The
picture is `<project name>.thumbnail.png` in the project folder.

Space play/pause · ←/→ step a frame · Home/End · Ctrl+I import · Ctrl+S save · Ctrl+E export.

Playback mode (播放, in the timeline toolbar): 停在暫停處 stops where playback is, 回到開始處
goes back to where it began (as in DAWs). The choice is remembered.

Sound plays on the system's default output and follows it: unplug headphones or plug them
back in (or pick another output in the system) and playing goes on there, no restart needed.
On Linux the preview's sound goes through Qt's PulseAudio output (PipeWire serves it too):
Qt 6.12's own PipeWire output crashed the program as playing started. Setting
`QT_AUDIO_BACKEND=pipewire` picks that one anyway.

Timeline precision (精度, in the timeline toolbar): how many steps a second has while
editing - the playhead, ←/→, splits and keyframes move in them, and the ruler marks each one
when zoomed in (the zoom reaches 40 px per step). 跟專案 uses the project's frame rate. It
only changes editing: playback still shows the project's frame rate, and the export uses
the project's (or the export dialog's) frame rate, sampling the timeline at its own frames.
It is saved with the project.

Editing: drag a clip to move it (also onto another track of the same kind), drag its
edges to trim; moves and trims snap to the playhead and to other clips' starts, ends and
keyframes while 吸附 (N, in the timeline toolbar) is on, as Jianying's auto-snap; a yellow
line marks where the drag has snapped. Dragging the playhead snaps to the same clip edges,
keyframes and beats; it can be dragged on the ruler or by its line anywhere on the tracks
(the line lights up and the cursor changes when the mouse is on it). Clicking a clip only selects it: the
playhead and the view stay where they are (the view follows the playhead during playback
and for jumps such as Home / End / keyframes). Ctrl+B splits the
selected clip (or every clip under the playhead), Delete removes, Ctrl+T adds a text,
Ctrl+Up / Ctrl+Down move the selected clips to the track above / below (at the same time;
nothing moves when one would land on another clip), Ctrl+Z / Ctrl+Y undo and redo. Right-click a track header or clip to rename it or give it
a colour (double-click a track name to rename).

Colour pickers show what they do while they are open: the colour under the mouse goes on the
preview (texts, built-in assets, effects), the timeline (track and clip colours) or the
內建素材 thumbnails at once; OK keeps it, Cancel puts back what was there. Every effect colour
has an alpha (the picker's A channel).

Time selection, as in FL Studio: drag with the right button anywhere on the timeline to
select a span (it snaps like clips do); playback starts at it and loops
inside it, and a marked export uses it. Ctrl+Shift+D (or Alt+X) clears it; a right click
without dragging opens the menu. I / O still set its ends at the playhead.

Volume line: every sound clip shows a line at its volume (in dB: 0 dB two thirds up, +20 dB
at the top), following its volume keyframes, which are points on it. Drag the line up or
down to change the clip's volume. With keyframes only a level stretch moves - between two
points of the same volume (both points go up or down together, the rest stays), or before
the first / after the last point; a sloping stretch cannot be grabbed. Alt+drag moves the
whole line (every keyframe, in dB). Drag a point to change that keyframe (up / down) or its
time (sideways). The value is shown
while dragging.

Output: right of the timeline a level meter shows the left / right peak of what is playing
(peak hold; red above 0 dB) and its fader sets the project's master volume (-60 … +12 dB,
double-click for 0 dB), used by the preview and the export.

Keyframes on the timeline: the selected clip shows its keyframes as orange diamonds; drag
one sideways to move every keyframe at that time (snapping to frames, the playhead and other
clips' starts, ends and keyframes),
click it to go there.

Navigation (timeline and curve editor alike): the wheel moves up and down, Shift+wheel
left and right, Ctrl+wheel zooms time around the mouse, the middle button drags the view and
Ctrl+middle-drag zooms it around where the drag started, as in Blender: sideways the time,
up and down the track height (the curve editor: the values); right / up zooms in.

Selection: Ctrl / Shift + click adds or removes clips; keep the button down and drag on to
sweep over more: they all follow the first clip (selected when it was not, deselected when
it was), as does a Ctrl / Shift selection box by the first clip it reaches. Dragging on empty
track space draws a selection box, Ctrl+A selects every clip of the open timeline, Ctrl+D clears the
selection. Dragging any selected clip moves the whole selection (one undo step); Delete and
Ctrl+B act on all of it. The inspector shows what the selected clips have in common: a
value they share is shown, one that differs shows "--", and typing a value (or a colour,
mask, keyframe ◆, curve) sets it on every selected clip as one undo step.

Track height: Alt+wheel or the 軌道高度 slider scales every track; drag the line under a
track name to size that track alone (double-click it to reset).

Timelines: a project holds several timelines (as in DaVinci Resolve) sharing its media
and compounds; they are tabs above the timeline: click to open one (it opens when the button
is let go, so a tab can be dragged down without switching first). A compound can have a tab
too: right-click a compound clip (or a compound in the 複合片段 tab) > 在新的分頁開啟, or drag
it from the 複合片段 tab onto the tabs - it opens by itself there (⧉, ◧ for a static one),
and each tab keeps its own playhead and view; the open tabs are saved with the project. + for a new one (with
V1 / A1), double-click to rename, right-click to duplicate or delete. Each keeps its own
tracks; edits, playback and export work on the open one. A timeline can be used inside
another (nested, as in Resolve): drag its tab, or its ⧉ row in the 複合片段 tab, onto the
timeline. The clip shows that timeline live (editing it changes every place it is used);
a timeline can never end up inside itself, and one in use cannot be deleted. Older projects open as one
timeline.

Look: a DaVinci Resolve-like dark layout: the viewer has the timeline name and timecode
above it and icon transport controls below (start, previous frame, play, next frame, end,
fullscreen); the timeline toolbar uses icons (undo, redo, blade, delete, text, snapping,
track height); tracks are labelled V1… (from the bottom) and A1…. Clips are coloured by
type (pictures blue, compound violet, text mauve, sound green, or a colour you set): the
colour outlines the clip and fills it see-through (alpha 0x50), so the name stays readable
on any colour; a selected clip is outlined white. A track's colour turns its row a deep
shade of it, marks its header edge and colours its clips that keep the default colour (a
clip given its own colour keeps it; 預設顏色 on a clip makes it follow its track again). The
track's right-click menu can also give its clips colours of their own: 將軌道顏色套用到所有
片段 (they keep it when the track's colour changes), 設定所有片段的顏色…, 所有片段改回預設
顏色 (one undo step each).
Renaming and colours happen where the thing is, not in a window in the middle of the screen:
重新命名 / F2 puts a name field over the item's own name (a clip's label, a track header, a
tab, a row of a panel's list), the old name selected; a colour opens a small picker right under
the clip, the track header or the swatch button (above it when there is no room): colours, the
last ones picked, a saturation / brightness square with a hue strip, alpha where it has one, and
the hex (ff0000 or #ff0000). What is tried shows at once; Enter or a click elsewhere keeps it
(that click does nothing else), Esc goes back.
Dragging on the ruler always moves the playhead, also over clips scrolled up under it.

Groups (群組, as in Lunacy): select picture clips and press Ctrl+G (or right-click > 建立群組):
they go into one group clip on the topmost track they were on, with the tracks they were on,
and keep their places on the canvas and in time. Unlike a compound a group is not shared and
has no canvas of its own - its clips move with it, keeping where they are to each other. A
group's ▸ / ▾ (or a double-click) opens it on the timeline: its tracks show as lanes under its
track, where its clips are picked, dragged (along a lane, onto another lane of the group,
never out of it) and trimmed like any clip; groups go inside groups too. While open the track
is as tall as the most lanes any open group on it needs, so heights stay put while playing;
folded it is its usual height (the open groups are saved with the view). A group never cuts
its clips: it can be made longer, not shorter than them, and cutting it (Ctrl+B) cuts its
clips too. On the preview a group is one box around its clips: click one of its clips to
select it, then drag anywhere inside the box (its clips or the space between them) to move it; scale and
turn it in the inspector (its own transform, keyframes too); double-click it to pick the clip
under the mouse, which can then be edited on the canvas like any clip (while the group is not
moved, scaled or turned). Effects, masks, blend modes and opacity on a group work on the group
as a whole. 最下面的物件當遮罩 (in its inspector, or the group's right-click menu on the timeline
and in the layer list) makes the clips of its bottom track cut the ones above them by their
alpha, a clipping mask; once it is on, 顯示遮罩物件 also draws those bottom clips, 顯示主體 (on
at first) draws the clips being cut - off, only the mask object shows, handy while placing
it - and 反轉遮罩 turns it around - the clips above are kept where the bottom ones are not, so their shape is
cut out (in the inspector and the same right-click menus; the layer list marks it 反轉遮罩).
Ctrl+Shift+G (解散群組) puts the clips back on the tracks around it with the group's position,
scale and opacity folded in (a turned group, or one with transform keyframes, is refused).
Projects with groups export through the preview renderer.

Compound clips: double-click one (or right-click > 編輯複合片段) to edit its content;
the breadcrumb above the timeline shows where you are, Esc / 返回上一層 goes back.
Compounds are reusable: each one is stored once in the project and any number of compound
clips (on any timeline, nested too) show it, so editing it inside one clip changes every
clip that shows it. The 複合片段 tab beside the media library lists them with how often
they are used and where; drag one onto the timeline to use it again, click a use to select
it, double-click to open it, right-click to rename (or delete an unused one). A compound
that no clip shows (a `_thumbnail`, one a mask uses) opens by itself: double-click it, or
right-click any compound > 進入編輯 (返回上一層 goes back to where you were). Right-click
anywhere in that list for 新增時間線, 新增複合片段 or 新增靜態複合片段: a new compound
asks for its name and resolution (the project's, a preset or any size - only its proportions
matter: what is in it stays vector and is drawn at the size it is shown or exported at),
starts empty and opens by itself to be filled (made on the timeline, it takes the size of
the level it is in without asking); drag it onto a timeline to use it. A clip's
「設為獨立（不再共用）」 gives it its own copy. Older projects and Jianying drafts are
converted on opening: identical copies become one shared compound. Right-click selected
clips > 建立複合片段 puts them into a new compound (one clip takes their place).

Compounds in the Library (Library tab > 複合片段): right-click a compound in the 複合片段 list,
or a compound clip on the timeline, > 存到 Library… (or select the clip and press
存選取的複合片段) to keep it for every project - a transition, a title, a lower third. It is
saved as one `.kccomp` file with the compounds it shows; files it uses that are not in the
Library are copied into the Library's hidden `compounds/.media` folder, so it still works
when the first project is gone or on another computer that has the Library. Drag it onto a
timeline (or the layer list, or a static compound's picture), or right-click > 放到播放頭: the
project gets its own copy, once - using it again places the same compound until the file is
saved over. A compound that shows a timeline cannot be saved this way.

Static clips (靜態片段, ◧): a picture built in the editor. Right-click selected picture
clips > 建立靜態片段 turns them into one, frozen as they look at the playhead (that moment
becomes its first frame: like a picture, a static clip only ever shows its first frame, so
what ended before it is left out); right-click
a free spot on a picture track > 新增空白靜態片段 starts an empty one. On the timeline it
behaves like a picture: any length, no sound, drawn once and reused. Double-click it to
edit its content (the playhead opens at its first frame, the only one it shows); every clip that uses it
changes with it, as with compounds.
A static compound is edited as a picture, not on a timeline: while one is open a layer list
takes the timeline's place, as in Photoshop - every picture clip is a layer, the top one
first, with a small picture of it on a checkerboard. A group's ▸ opens it in the list: its
layers show indented under it and are selected, hidden, locked and restacked (dragged, 上移 /
下移) inside it like any other; when its bottom object is its mask, that layer is marked 遮罩.
Click (Ctrl / Shift for several) to select, drag layers to restack them (one per
track), the dot hides a layer and the padlock locks it, double-click a name to rename it;
文字 and 形狀 ▾ add a layer at the top (shapes in the 內建素材 tab's colours), 上移 / 下移
restack the selection, 群組 groups it, 複製 copies it right above itself, 刪除 removes it;
right-clicking the selection offers the same, plus 重新命名 and hiding / locking them all. Drag
media onto the list - from the media library, the Library tab, 內建素材, the 複合片段 list or the
file manager - and they become layers where they are dropped (between the two nearest layers;
one undo step). An effect from the VFX tab dropped on a layer goes onto it; dropped between
layers it becomes a filter layer there. Media dropped on the preview instead become the top
layer, centred where they were let go. A
layer that does not cover the picture's moment shows dimmed (only that moment is drawn). The
preview, the inspector and every edit work on the selected layers as on clips.

Components (元件, ❖): compounds with parameters - live ones (元件, edited on their timeline)
and static ones (靜態元件, edited as layers). Make one with right-click selected clips >
建立元件 / 建立靜態元件, a free spot on a picture track > 新增空白靜態元件, the 複合片段 list >
新增元件 / 新增靜態元件, or turn any compound or static clip into one (轉為元件: its clip's
right-click menu, the compound list, or the button above a static clip's layers; 轉回複合片段 /
轉回靜態片段 goes back). Its parameters are listed beside its timeline, or under a static one's
layers (參數): right-click clips (layers) > 設為參數 makes a parameter of a text's words
(文字內容) or colour, a shape's fill, outline or gradient colour, a picture (圖片) or whether
the clip shows (顯示) - or hands it to a parameter already there, so one parameter (a 主色,
say) can set several clips; 解除參數 lets it go, and clips a parameter sets are marked ❖.
Click a parameter to select its clips, double-click it to set its default (what its clips
have), right-click to rename, restack or delete it. Every clip that shows the component
then has 元件參數 in the inspector: its own value of each parameter, with ◆ keyframes in the
clip's time like any value (colours blend, words, pictures and switches hold until the next
key) and ↺ to go back to the component's own; one left alone follows the component as it
changes. A value holds for the whole content, in place of the clip's own (keyframes
included); hiding a clip only hides its picture. A project whose component clips set values
of their own is exported by KiaseCut's own renderer.

Media library (left): import files (Ctrl+Shift+I), organise them in folders by dragging,
and drag media onto the timeline (or double-click to add at the playhead). Importing a
Jianying draft fills the library with the media it uses. SVG files work like any picture
and are drawn at the size they are shown, so they stay sharp at any zoom (the MLT export
gets a PNG drawn at the clip's largest size).

Built-in assets (內建素材 tab): solid colours, gradients (presets, plus horizontal /
vertical / diagonal / radial ones, a subtitle backing and a vignette) and basic shapes
(rectangle, circle, triangle, star, heart, arrow, parallelogram, arc, ring, frames, line…).
The two colours at the top of the tab paint the 自訂 ones and the shapes (the first fills
them, the second outlines them; alpha works too). Drag one onto the
timeline or double-click it (Alt + drop on a picture clip replaces its source). The clip
keeps its parameters: select it and the inspector's 素材參數 sets its size in canvas pixels
(寬 / 高), its colours and what its kind has: gradient type and angle, corner radius,
polygon sides, star points and inner radius, a parallelogram's 斜度. A shape has a fill
(填充) and an outline (外框) that can each be switched on, together or alone; the outline has
its own colour, a width down to 0, a 外框位置 (inside the edge, centred on it or outside it -
outside reaches past the frame) and a 轉角 (直角 miter, 圓角 round, 倒角 bevel). An ellipse is
also an arc, as in Lunacy: 開始 ° (clockwise from 3 o'clock), 弧掃 % of a full turn and 比例 %
(a hole of that share of the radius: a ring, or a slice of one; 100 % leaves only the
outline). Shapes of older projects keep
their look (their filled / outline choice becomes these switches). Every
one of them has a ◆ and keyframes like position or scale: sizes, angles and colours blend
between keyframes (sides and points step), choices hold until the next one; the numbers
also show in the curve editor. Unlike other pictures it is not fitted to the canvas but
drawn at that size, so resizing it keeps corners and outlines as they are (scaling
stretches them). On the preview its corner and edge squares change 寬 / 高 rather than
the scale: an edge one side, a corner both (Shift keeps their ratio), the opposite edge or
corner staying put (Alt: the centre). Solids and gradients start at the canvas's size,
shapes at 400 px (on a 1080-high canvas). The preview and the export draw it from its
parameters at every frame (an export with asset keyframes goes through KiaseCut's own
renderer); the SVG written into Media/.內建素材 when it is made (hidden from the media
library, drawn again if missing) only gives it a file like any picture.

Fonts across Windows and Linux (字體對應): texts name font files, and a project made on one
system names fonts the other does not have. When a project opens with such fonts, a window
lists them with a stand-in to pick for each (one is suggested: what was picked for it
before on this computer, a font with the same file name, or the usual equivalent, such as
Noto Sans CJK for 微軟正黑體 or Liberation Sans for Arial). It does not block the editor;
closing it (or 之後再說) leaves those texts in a default font, and it comes back the next
time the project opens. 編輯 > 字體對應… opens it any time and lists every font the
project's texts use (with how many texts use each). The choice is kept in the project per
operating system: the clips keep
their own font, Linux uses its stand-in and Windows its own font (or its own stand-in for a
font picked on Linux). It is not an edit, so undo leaves it alone. A font this computer has
can be swapped there too (換成, 「（不變）」 by default): every text using it - keyframes and
styled ranges included, in every timeline and compound - takes the new font. That one is an
edit of the texts (for every system), and Ctrl+Z undoes it.

Replacing a clip's source (替換素材): hold Alt while dropping media (from the library, the
Library tab or the 複合片段 tab) on a clip: the clip lights up with 替換素材, and on release
it shows the new media in its place, keeping its position, length, transform, mask,
effects and keyframes. Pictures, videos and compounds replace pictures, videos and
compound clips; sounds replace sounds. A clip longer than a new video or sound is
shortened to it. Dropped on one of several selected clips, every selected clip that can take
it is replaced (批量替換: they all light up while dragging), in one undo step. A compound kept
in the Library can replace them too. In a static compound the same works on the layer list
and on its picture (Alt + drop on a layer).

Align and space (the buttons at the top of 屬性, as Lunacy's six): left, centre, right, top,
middle, bottom - several selected clips line up with the box around them, one clip with the
canvas. With two or more selected, 平均間距 makes the gaps between neighbours (in the order
they stand along the way they spread most) the same, their average; the 間距 field shows
the gap when they are all equal ("--" when not) and typing a number sets every gap to it,
negative ones included (the clips then overlap by that much). Each is one undo step.

Preview: click a clip on the canvas to select it and drag it to move it; it snaps to the
canvas centre lines and edges, to other clips' centres and edges and to equal spacing
between clips: centred between its neighbours, or as far from a neighbour as two other
clips are apart, shown with pink gap marks (hold Ctrl to move freely). Hold Alt while
dragging to copy instead, as in Lunacy: the clips stay and copies of them go where they are
dropped, each on the row above its original (one undo step); Alt+drag on the timeline does the
same in time (copies later or on other rows). Shift / Ctrl+click
adds clips to the selection (or takes them out), and dragging from an empty spot draws a
box that selects every clip it touches; several selected clips move together. When they
stand in a row, a column or a grid, hovering them shows pink bars in the gaps (upright
between columns, flat between rows): drag one to make all the column gaps (or row gaps) the
same width. Drag a corner or edge square to scale it: the opposite corner or edge stays where
it is (hold Alt to scale about the centre), and the moving edges snap to the same lines
as a move does (hold Ctrl to scale freely). With X / Y scale linked, corners and edges keep
the clip's proportions; unlinked, a corner sets X and Y freely (Shift keeps the proportions)
and an edge changes only its own axis. Drag the round handle above it to rotate it (it
settles on right angles; Shift turns in 15° steps).

Beat alignment (節拍 tab, for a selected sound clip or a video with sound): switch on BPM 對齊 and enter the
BPM and the start offset (the first beat's time in the sound); 細分 splits each beat into
1, 1/2, 1/3, 1/4 or 1/6, or thins it to a line every 2 or 4 beats (BPM ÷2 / ÷4: 180 → 90,
the BPM typed in stays as it is). 拍號 sets how many beats make a bar (2/4 … 12/8, or 不分小節):
the first beat of every bar, counted from the first beat, gets the long line and the other
beats shorter ones, so bars can be told apart at a glance.
The grid shows as lines down from the clip's top, coloured by where in the beat they fall
(yellow beat, orange half, pink third, cyan quarter, violet sixth) and shorter and thinner
the smaller the division (a bar's first beat reaches about half way down the clip; lines too close
at the zoom are left out), and everything that snaps (clips, trims, keyframes, the playhead)
lands on them. Switching it off keeps the numbers; 重置 deletes them (after asking) and
switches it off.

Saving also stores the view: the playhead, the open compound clip, the timeline's scroll
and zoom and the track heights of each timeline come back when the project is opened.

Side tabs show only when the selection has use for them: 屬性 always, 效果 for pictures,
texts and filters, 遮罩 for what takes a mask, 節拍 for one clip with sound (a silent video
has none), 字幕 for texts and 關鍵幀曲線 for any clip.

Masks have their own tab (遮罩, beside 屬性): switch the mask on or off (off keeps its
settings; on for a clip without one adds a rectangle), pick its shape, invert it, remove
it, and set its centre, size, rotation and feather with keyframes. While that tab is open
the preview is the mask editor and only masks can be changed there: drag inside the mask
to move it, the squares to size it, the round handle to turn it and the arrow below it for
the feather (a switched-off mask is drawn dimmed). Back on 屬性 the preview edits the clip
again. An effect's 範圍 (in the 效果 tab) is edited the same way: press 編輯遮罩 beside it
(picking a shape for 範圍 switches it on too). Every drag
shows live and is one undo step; keyframed values get their keyframe at the playhead.

The 複合片段 shape cuts a clip with a compound's picture (a track matte): pick the
compound and whether its Alpha (where it is opaque) or its 明度 (where it is bright) lets
the clip through. A compound plays along with the clip's time (held at its last frame after
its end); a static compound (◧) is one picture. While the 遮罩 tab is open the mask's frame
is on the preview: drag it to move it, the squares to size it (the corner keeps its
proportions, Shift frees them) and the round handle to turn it. The compound itself is only
drawn over the clip with 預覽複合片段 on, at the 不透明度 typed beside it (how strongly the
preview shows it), which makes placing it easier. A compound that shows the clip's own level is not
offered (it would cut with itself); projects with a compound mask export through the
preview renderer.
編輯區域 (live compounds only - a static one has no time): with it ticked, the mask's
compound shows as a ghost over the clip on the timeline, lying where its time runs along the
clip; drag it sideways to pick which part of the compound cuts the clip (it snaps to frames,
one undo step; before its start / after its end the compound holds its first / last frame).

The 圖片 shape cuts with a picture file the same way: pick one of the media library's pictures
(or 瀏覽圖片檔…), its Alpha or its 明度, then move, size (the corner keeps its proportions,
Shift frees them) and turn its frame on the preview; 預覽圖片 shows it over the clip at the
不透明度 typed beside it. Its path is stored relative to the project folder like any media.
Ctrl+wheel zooms the preview (to reach handles of clips bigger than the canvas), the
middle button drags it. F toggles fullscreen; double-click a text on the preview to type its
words right there (Ctrl+Enter or a click elsewhere closes it, Esc puts the words back).

Scale has an X and a Y value with a link button between them: linked (the default), changing
one changes the other in the same proportion and their keyframes are added and removed
together; unlinked, each changes alone (the curve editor then shows 縮放 Y on its own).

Keyframes and masks: every animatable value in the inspector (position, scale, rotation,
opacity, volume, text size / colour / letter and line spacing / italic, mask centre / size /
rotation / feather) has a ◆ button that adds or removes a keyframe at the playhead;
changing a value that already has keyframes edits or adds the keyframe at the playhead, as
in Jianying. ◀/▶ jump between keyframes, and the curve menu sets linear / ease-in /
ease-out / ease-in-out from the keyframe at the playhead to the next. Pictures, videos and
compound clips take line, mirror, circle, rectangle or compound masks (see the 遮罩 tab). The
mouse wheel never changes a number field. Number fields work like Resolve's: press and
drag up / down to change the value (Shift for fine steps, Ctrl for big ones), click to type
one. Limits work like Blender's soft and hard limits: dragging stops at a field's usual
range (or where the value already is, when it is outside it), while typing a number or
dragging with Alt held goes past it, up to a hard limit where one makes sense (opacity
0 - 100 %, sizes not below 0) and without any for the rest - effect parameters included.
Position X / Y (and a mask's centre and size) sit side by side on one row. The
previous / next keyframe buttons (◀ ▶) are in the curve editor.

Text alignment (對齊, beside the font): 靠左, 置中 (the default), 靠右 and 齊頭尾 (justified:
every line but the last is spread to the widest one, between every two characters, so CJK
lines without spaces fill out too). It is saved with text styles and keyframes like the font.

Choices keyframe too: the font, the text alignment, the blend mode, a mask's shape and invert, and a filter's
on / off parameters and range shape have ◆ buttons like the numbers. Their keyframes hold
(a step, no blending or curve) until the next keyframe; picking another value at the
playhead edits or adds the keyframe there.

Background effects (套用至背景, at the top of the 效果 tab once a clip has an effect): the clip's
effects work on what is under it instead of on the clip, only inside its shape (its alpha,
mask and opacity) - a frosted-glass panel is a shape with 模糊 and 套用至背景, but any effect
works (invert, pixelate, colour…). A built-in shape can still be drawn on top (to tint the
glass) or hidden with 隱藏本體; a picture, video, text or compound clip with 套用至背景 always
hides itself, leaving only its effect on the background.

Blend modes (混合模式, under 畫面 for pictures, videos, texts and compound clips): normal,
multiply, screen, overlay, darken, lighten, colour dodge / burn, hard / soft light,
difference, exclusion and add, mixing the clip with what the tracks below show. The
preview draws them; a project that uses a blend mode (or a keyframed mask shape /
invert) exports through the preview renderer, as projects with filters do.

Curve editor (the 關鍵幀曲線 tab beside 屬性): tick any parameters of the selected clip and
their keyframes show together as value-over-time curves, each in its own colour (colours
as R/G/B lines). 正規化 gives every curve the same height; untick it to read them on one
axis. Click a keyframe to select it, Ctrl / Shift + click or a selection box for several,
Ctrl+A for all, Ctrl+D for none; dragging moves the whole selection (time snaps to frames, Shift keeps to
one direction). Drag the bezier handles to shape a curve, double-click to add a keyframe
to the nearest curve, Delete to remove the selection. Alt+wheel zooms values; Ctrl+middle-drag
zooms around where the drag started, as in Blender's graph editor (sideways: time, up and
down: values; right / up: in), while a plain middle drag still moves the view. 全部顯示
fits again; a click on the time ruler moves the playhead. The preview follows every drag. The segment
after each selected keyframe takes a CSS `cubic-bezier(x1, y1, x2, y2)` typed in (y may
overshoot, for bounces) or a preset (linear, ease in / out / in-out, back). Time and value
can be typed too: with several keyframes selected they show "--" where they differ, and a
typed number goes to all of them.

Speed and freeze frames (速度, in 屬性 for videos, sounds and compound clips, static ones
excepted): 速度 plays the source faster or slower (2 × twice as fast, 0.5 × half as fast;
dragging keeps to 0.1 - 10 ×, typing reaches 0.01 - 100 ×). The clip keeps the same stretch of
its source, so it gets shorter or longer - as far as the room after it allows - and its
keyframes and fades stretch with it; the sound is resampled (its pitch follows, like a tape),
the beat grid and the waveform follow, and a compound clip's whole content runs at that
speed. 凍結幀 holds the clip on one frame for its whole length, like a picture (silent, and it
can then be any length); 第 … 格 picks which frame, counted from the clip's start (drag or
type to fine-tune), and 播放頭 takes the frame under the playhead. Projects with either export
through the preview renderer.

降低幀數 (in the effect list, under 時間): the clip moves in steps of its 每秒幾格 - videos,
compound content, keyframe animation and the other effects all update only that often, for a
choppy, stop-motion look; it changes no pixels itself.

Sound and tracks: audio and video clips show their waveform on the timeline (white, the
highest and lowest sample of every millisecond, so zooming in shows detail; following
the clip volume and fades). Audio track headers have mute and solo buttons, picture
tracks an eye to hide them (and mute, when they hold videos or compound clips); muted /
hidden tracks are dimmed. Every track header also has a padlock (鎖定): a locked track's
clips cannot be selected at all - not by a click, a selection box or 全選, on the timeline
or the preview - and nothing is moved or dropped onto it (a drop there makes a new track);
it still plays, shows and is snapped to. It is drawn hatched. Drag the right edge of the
track headers to make them wider (to read long track names) or narrower; the width is saved
with the timeline's view. The track menu (right-click a header) sets a track volume in dB,
moves tracks up or down, adds video / text / audio tracks and deletes them. Drag a picture
clip above the top row, or a sound clip below the bottom row, to put it on a new track.
分離音訊 in a video clip's menu moves its sound onto an audio track. Preview and export
follow the same rules (a solo track silences the others on its level).

GPU acceleration (設定 > GPU 加速, on by default): frames are composited on the graphics
card (glrender.py, any OpenGL 3.3 card): every clip is a textured quad whose transform,
opacity, mask, feather and blend mode are worked out per pixel, compounds and static clips
are drawn into layers there and filters run on them without leaving the card; only the
finished frame is read back. A busy scene (feathered masks, blend modes, a filter) went
from 3 to 250 fps at preview size and from 0.7 to 92 fps at 1080p; the two renderers are
compared frame by frame in tests/test_glrender.py (within 1/255 on average). Without
OpenGL, or with the switch off, the QPainter renderer (render.py) does it. With an NVIDIA
card, exports are also encoded with NVENC (several times faster than x264 on real footage;
pictures larger than 4096 px, or a card that refuses, fall back to x264), and HEVC / AV1 /
VP9 videos are decoded and scaled on the card. Videos play from ffmpeg streams
(videoreader.py) that read the file front to back instead of seeking for every frame: a 4K
clip went from ~15 to 30 fps in the preview.

Export (Ctrl+E): the whole film or the range marked with I / O (Alt+X clears), at high,
standard or small-file quality, at any frame rate (10 / 25 / 30 / 40 / 60 / 100 fps or a
custom one) and any size as a multiple of the project's resolution (0.25× / 0.5× / 1× / 2× /
4× or custom; sizes are rounded to even numbers). A project is not tied to a frame rate or
a pixel size: times are microseconds and positions, text sizes and masks are fractions of
the canvas, so every rate and size renders the same picture. The project's own fps only
sets the timeline's frame grid, and its width and height the canvas shape.

Export the current frame (檔案 > 匯出目前畫面…, Ctrl+Shift+E): the frame at the playhead (of
the timeline or compound that is open) as a picture - PNG, JPEG, WebP, TIFF or BMP - at a
multiple of the project's resolution, as the video export. PNG, WebP and TIFF can keep a
transparent background; without it (or in JPEG / BMP) the empty parts get the background
colour picked there. JPEG and WebP take a quality. The choices are remembered; the file goes
to the project's Exports folder, named after the project and the time.

## Project folder

A project is a folder, as in FL Studio (File > New project asks for a name and a place):

```
My Video/
    My Video.kiasecut.json   the project file (media paths are stored relative to the folder)
    Media/                  the media library: its sub-folders are the library folders
    Cache/                  waveforms, proxies (only with 設定 > 緩存位置 > 專案內)
    Exports/                rendered videos (the export dialog starts here)
    Backup/                 earlier copies of the project file, one per save
```

The cache (waveforms, decoded sound, drawn texts and masks, proxy pictures) goes where
設定 > 緩存位置 says: 預設 puts it in `~/.cache/KiaseCut/projects` (one folder per project, kept
when the project is moved or renamed), 專案內 in the project's Cache folder, 專案外 in a folder
you pick. Outside the project, moving or copying a project leaves the cache behind. File >
清除專案緩存… deletes the open project's cache wherever it is; it is made again when needed.

Autosave and recovery: while a project has unsaved changes, a copy is written every few
minutes (設定 > 自動存檔間隔) to `~/Documents/KiaseCut/auto-save`, named after the project and
the time; only the newest ones are kept (設定 > 自動存檔上限, 30 at first - 開啟資料夾 shows
them). The project file itself is not touched. If KiaseCut ends without closing (a crash, a
power cut), the next start asks whether to bring the newest autosave back: it opens as
unsaved changes of its project, to be saved as usual (or, when its project folder is gone, as
a project without a folder). Each running KiaseCut keeps a `session-<pid>.json` there, removed
when it closes normally; `crash.log` beside them collects Python's record of a crash (every
thread's stack), for reporting it.

The media library is the Media folder: imports (dialog, or files dragged in from the file
manager) are copied into it, new folders / renaming / moving / deleting in the library do the
same to the files (deleting uses the recycle bin), and files added or removed in Media by hand
show up in the library. Clips follow renamed or moved files. Because of that, these are not
part of Ctrl+Z. File > Project info (F11) holds title, author, genre, URL, comments and the
project's history: when it was started, last opened and saved, and the time spent on it.
What is typed there is kept however the window closes (關閉, Esc or its ×).
Older projects (and Jianying drafts) are offered to be tidied into a project folder; File >
Collect media into the project folder does it any time. Several project files can share one
folder (File > Save as).

## How it works

| module | role |
|---|---|
| `project.py` | project model (JSON); Jianying units and bezier keyframes |
| `importers/jianying.py` | draft_content.json → project |
| `curves.py` | keyframe evaluation (Jianying's bezier handles) |
| `edit.py` | move / trim / split / delete / keyframe / mask / name edits with undo |
| `library.py` | media library: folders, probing, placing media on a timeline |
| `recovery.py` | autosave folder, crash recovery, crash.log |
| `textlayout.py` | text rendering calibrated to Jianying's layout |
| `masks.py` | line / mirror / circle / rectangle masks as MLT splines (or baked mattes) |
| `render.py`, `audiomix.py` | live preview: frames drawn with QPainter, audio mixed with numpy |
| `glrender.py` | the same frames composited with OpenGL (GPU) |
| `waveform.py` | cached audio peaks for timeline waveforms |
| `videoreader.py`, `gpu.py` | streamed video pictures for the preview; GPU decoding / NVENC |
| `svgimage.py` | SVG pictures drawn at the size they are shown |
| `build.py` | project → MLT XML for export (cached text images) |
| `mltlib.py`, `engine.py`, `client.py` | MLT through ctypes, in its own process |
| `ui/` | PySide6 window, timeline, preview player |

Preview and export read the same project but render it differently. The preview draws
each frame straight from the project model (render.py, audiomix.py), so edits and drags
show on the next frame and playback runs at 60 fps; it was checked frame by frame against
the MLT output. Exports build an MLT document (build.py) and render it in a separate
engine process: an MLT crash cannot take the editor down, and MLT's Qt never shares a
process with PySide6's Qt. The engine also supplies single video pictures to the preview
(after a jump); while playing, they come from ffmpeg streams (videoreader.py).

## Accuracy check

```
python tools/golden.py DRAFT.json JIANYING_EXPORT.mp4 out/golden --remap OLD_PREFIX=NEW_PREFIX
```

imports the draft, exports it, and compares ~430 frames with Jianying's own export.
For the AlianShit draft: median per-frame difference 0.25, max 2.42 (of 255);
audio within 1 ms and 0.5 dB.

## Tests

```
python -m unittest discover tests            # edit operations
python tools/smoke_edit.py PROJECT.kiasecut.json out/   # drives the real window headless
python tools/smoke_keys.py PROJECT.kiasecut.json out/   # keyframes and masks, headless
python tools/smoke_curves.py PROJECT.kiasecut.json out/ # curve editor: drag, cubic-bezier, presets
python tools/smoke_audio.py PROJECT.kiasecut.json out/  # waveforms, mute / solo / hide, new tracks
python tools/smoke_select.py PROJECT.kiasecut.json out/ # multi-select, track heights, compound list
python tools/smoke_handles.py PROJECT.kiasecut.json out/ # scale / rotate / mask handles on the preview
python tools/smoke_reuse.py PROJECT.kiasecut.json out/  # shared compounds, timeline ◆ drag, time selection
python tools/smoke_volume.py PROJECT.kiasecut.json out/ # volume line, 吸附, clip clicks, meter, master volume
python tools/smoke_inspector.py PROJECT.kiasecut.json out/ # number dragging, X / Y row, nested timelines
python tools/smoke_features.py PROJECT.kiasecut.json out/ IMAGE AUDIO # library, compounds, preview drag, range export
python tools/stress_drag.py PROJECT.kiasecut.json       # rapid preview drags + playback fps
```

## Status

Milestones 1 (import → preview → export), 2 (move, trim, split, text editing) and
3 (keyframes, easing, masks) work, plus the media library, compound editing, preview
dragging with snapping, range export, a curve editor with cubic-bezier input, waveforms and per-track
mute / solo / hide / volume. Edits and drags show on the next preview frame.
Masks are drawn by MLT's rotoscoping filter before the clip transform, so they follow the
clip like Jianying's and need no pre-rendering (`build.build(..., mask_mode="baked")`
still renders the screen-space mattes they were verified against).

Known: on the first frame of a clip that starts exactly on a frame boundary, Jianying can
show a slightly different picture (max frame difference 4.9 at two such frames).

## Other converters

`tools/converters/` holds the standalone converters this project grew from:
`jianying_to_blender.py` (+ `jy_build.py`) builds a Blender VSE project, and `jy_mlt.py`
turns its `timeline.json` into plain MLT XML or a `.kdenlive` project with editable titles.

`extra/compositor_to_hyprshade.py` is a Blender add-on (Compositor > Node menu > Export as
Shader / Filter): it turns a compositor node tree or node group into a one-pass GLSL screen
shader (Hyprshade, OBS, ShaderGlass) or a KiaseCut filter whose group inputs become
keyframeable parameters.

## License

KiaseCut is free software under the GNU General Public License, version 3 or (at your
option) any later version: see `LICENSE`. This covers every version published so far, from
the first commit on. It comes with no warranty.

Taken from elsewhere:

| In KiaseCut | From | License |
|---|---|---|
| `kiasecut/filters/blender_glare.glsl` | Blender's Glare compositor node (`node_composite_glare.cc`, `compositor_glare_*.glsl`) | GPL-2.0-or-later |
| `kiasecut/filters/blender_lens_distortion.glsl` | Blender's Lens Distortion compositor node (`node_composite_lens_distortion.cc`, `compositor_*_lens_distortion.glsl`) | GPL-2.0-or-later |
| `kiasecut/filters/blender_sensor_noise.glsl` | the Sensor Noise node group of Blender's Essentials assets (`compositing_nodes_essentials.blend`), by Blender Studio | CC0 (public domain) |
| `kiasecut/filters/blender_vignette.glsl` | the Vignette node group of Blender's Essentials assets (`compositing_nodes_essentials.blend`), by Blender Studio | CC0 (public domain) |

Each was exported with `compositor_to_hyprshade.py`, then rewritten by hand; its header names
the Blender files. Blender: <https://www.blender.org>, source at
<https://projects.blender.org/blender/blender>, © Blender Authors.

Used, not included: PySide6 / Qt (LGPL-3.0), MLT (LGPL-2.1), FFmpeg (LGPL or GPL, by
build), numpy (BSD), Pillow (MIT-CMU), moderngl (MIT). An executable from
`build_exec.bat --bundle-mlt` also carries Kdenlive's MLT, Qt and FFmpeg: hand on their
licenses with it (Kdenlive's `share/` holds them).
