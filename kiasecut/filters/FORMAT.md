# 濾鏡檔格式（.glsl）

濾鏡是一個文字檔，副檔名 `.glsl`，放在 Library 的 `filters` 資料夾（或它的子資料夾）裡就會出現在
濾鏡清單。內建的濾鏡也是用同一個格式寫的，可以直接當範例看（程式資料夾裡的 `kiasecut/filters/`）。
存檔之後程式會自動重新讀取，不用重開。

一個濾鏡 = 標頭註解 + 一個 `effect()` 函式。你**不用**寫 `#version`、`uniform` 宣告和 `main()`，
程式會自動補上。

## 最小的例子

```glsl
// @filter 變暗
// @param amount float 0.5 0 1 "強度"

vec4 effect(vec2 uv) {
    vec4 c = src(uv);
    return vec4(c.rgb * (1.0 - amount), c.a);
}
```

## 標頭（寫在檔案最前面，每行 `// @名稱 內容`）

| 標頭 | 說明 |
|---|---|
| `// @filter 名稱` | 濾鏡在清單裡顯示的名字（沒寫就用檔名） |
| `// @category 分類` | 清單裡的分類（選填） |
| `// @description 說明` | 一行說明（選填） |
| `// @passes N` | 要繪製幾次（預設 1，最多 32）。第 2 次起 `src()` 讀到的是上一次的結果，可以用來做分離式模糊；要讀原本的畫面用 `original()` |
| `// @precision float` | 搭配 `@passes`：最後一次之前的每一次繪製都用 16 位元浮點數存（不寫或寫 `8bit` 就是 8 位元），暗部不會被量化、亮度也能超過 1 |
| `// @levels 數字… [選單參數]` | 搭配 `@passes`：第 i 次繪製的圖是畫布縮小 2^數字 倍（取整數、不會比預覽的圖大；`2f` 的 `f` 表示這一次不再因選單縮小），最後可以接一個選單參數的名字，選單選第幾個就再多縮小 2^幾 倍（像 Glare 的品質）。沒寫到的繪製維持原本大小。這些縮小的圖用 32 位元浮點數存，用來做縮小再放大的金字塔（Bloom） |
| `// @extras 編號或 -…` | 搭配 `@passes`：每一次繪製除了 `src()`（上一次）以外，還可以用 `extra(uv)` 讀前面某一次繪製的結果（`-` 表示不讀）。`pass_px`、`src_px`、`extra_px`（`vec2`）是這一次、上一次、extra 那一次的圖的像素大小 |
| `// @param 名稱 型別 預設值 [最小 最大] ["顯示名稱"]` | 宣告一個參數，見下面（`menu` 是 `// @param 名稱 menu 預設選項 "選項1\|選項2\|…" ["顯示名稱"]`） |
| `// @input 名稱 ["顯示名稱"]` | 多一張可以讀的圖（節點編輯器裡多一個輸入插槽）：shader 裡用 `input_名稱(uv)` 讀（預乘透明度，和 `src()` 一樣）；沒接圖就是全透明。可以寫好幾行 |
| `// @output 名稱 ["顯示名稱"]` | 節點編輯器裡多一個輸出（可以寫好幾行；有寫就取代原本唯一的「圖像」輸出）：每個被接出去的輸出各畫一次，shader 裡 `output_index` 是它的順序（0 起算），用它決定這次輸出哪一張圖。範例：`nodes/separate_color.glsl`（分離色彩）。Blender 轉 KiaseCut 的外掛（`tools/converters/compositor_to_hyprshade.py`）會把 Group Output 的每個輸出都寫成 `@output`（原本選的那個排第一，所以當一般濾鏡用時結果不變） |
| `// @shared` | 搭配 `@output` 和 `@passes`：只有最後一次繪製會看 `output_index`，所以同時要好幾個輸出時，最後一次之前的繪製只畫一次、大家共用（像 Blender 的節點，執行一次就給出所有用到的輸出），每個輸出只多畫最後一次。沒寫的濾鏡每個輸出都整個重畫 |
| `// @alone 輸出名稱…` | 搭配 `@shared`：這些輸出只用最後一次繪製，不看前面的結果（Glare 的「亮部」只要原圖），所以只要這幾個輸出時前面的繪製都不畫 |
| `// @skip 次序 參數 條件` | 搭配 `@passes`：條件成立時，這幾次繪製（`1-23`，或單獨 `3`）不畫。條件寫法同 `@enable`（`type != Bloom`、`mode == A\|B`）。用在某些設定下根本沒用到的繪製（Glare 只有 Bloom 才用縮小再放大那一串）。被跳過的繪製留在 `extra()` 讀到的是空圖 |
| `// @source 名稱` | 節點編輯器裡，主要那張圖（`src()`）的插槽叫什麼（預設「圖像」） |
| `// @panel 名稱 [closed]` | 之後的參數放進一個可以摺疊的面板（像 Blender 節點的面板）；`closed` 是一開始收起來；`// @panel -` 回到最上層 |
| `// @show 參數或輸入 條件` | 節點上只在條件成立時才顯示這一列（參數或 `@input` 的插槽），條件寫法和 `@enable` 一樣；用不上的運算就不佔位置（像 Blender 的「數學」）。參數在面板上同時也會變灰 |
| `// @enable 參數 條件` | 條件不成立時，這個參數在面板上變灰（用不上），見下面「用不上的參數」 |

### 參數

`@param` 宣告的參數會在程式的「濾鏡」面板長出對應的欄位（數字、勾選框、顏色選擇器、下拉選單），
在 shader 裡就是同名的 `uniform`，直接用名字讀就好。

| 型別 | 預設值寫法 | 在 shader 裡的型別 | 面板上的欄位 |
|---|---|---|---|
| `float` | `0.5` | `float` | 數字欄，可以打關鍵幀 |
| `int` | `4` | `int` | 整數欄 |
| `bool` | `true` / `false` | `bool` | 勾選框 |
| `color` | `#rrggbb` 或 `#rrggbbaa` | `vec4`（RGBA，0~1，**沒有**預乘） | 顏色選擇器 |
| `vec2` | `0.5,0.5` | `vec2` | 兩個數字欄（X、Y） |
| `vec3` | `0.1,0.2,0.3` | `vec3` | 三個數字欄（X、Y、Z） |
| `curve` | `0,0,1,1`（直線；或 cubic-bezier 的 x1,y1,x2,y2，x 在 0~1） | `float[128]` | 曲線編輯器（和關鍵幀曲線編輯器一樣：拖關鍵點和控制柄、雙擊新增、Delete 刪除）；在 shader 裡用 `curve_ease(名稱, x)` 取得曲線在 x（0~1）的值，曲線本身不能打關鍵幀 |
| `gradient` | `0:#000000,1:#ffffff`（`位置:顏色`，位置 0~1，2~32 個色標，顏色可以帶透明度） | `float 名稱_p[32]`、`vec4 名稱_c[32]`、`int 名稱_n`（位置、顏色、個數） | 漸變編輯器（和漸變素材的一樣：點色標下方新增、拖曳移動、雙擊改顏色和透明度）；在 shader 裡用 `gradient_eval(名稱_p, 名稱_c, 名稱_n, x, 插值, 色彩模式, 色相)` 取得漸變在 x（0~1）的顏色（一般的、沒預乘的 RGBA）：插值 0 緩和、1 基數、2 線性、3 B 樣條、4 固定；色彩模式 0 RGB、1 HSV、2 HSL（HSV／HSL 一律線性）；色相 0 最近、1 最遠、2 順時針、3 逆時針。算法照 Blender 的 Color Ramp，漸變本身不能打關鍵幀 |
| `menu` | 選項名稱，或它的編號（0 起算） | `int`（選到第幾個，0 起算） | 下拉選單 |

- `float`、`int`、`vec2`、`vec3` 可以接 `最小 最大`，限制面板欄位的範圍（不寫就是 -1000 ~ 1000）。
- 最後可以放用雙引號包起來的顯示名稱，例如 `"半徑"`。
- `menu` 的選項寫在預設值後面，用 `|` 隔開、整串用雙引號包起來，例如
  `// @param mode menu 平滑 "線性|平滑|銳利" "模式"`；shader 裡 `mode` 是 0、1、2。
  和勾選框一樣，選項的關鍵幀不會漸變，會維持到下一個關鍵幀。
- 內建濾鏡有 `seed` 參數時，新增效果會用當下秒數（包含小數秒）產生一個初始種子，
  避免每個新效果都從相同圖樣開始；種子仍可在面板修改，存進專案後也會固定不變。
- 名稱只能用英文字母、數字、底線，不能以數字開頭，也不能跟下面的內建名稱重複。
- `color` 參數在「效果」面板可以改用圖片、影片或複合片段當來源（像遮罩一樣擺在片段上）：
  濾鏡讀到的就是每個像素在來源那個位置的顏色，來源沒蓋到或透明的地方是設定的顏色。
  寫濾鏡時不用改什麼，照常把它當顏色用就好（它在 shader 裡是一個 `#define`，所以不要拿參數的
  名字去取別的變數名）。
- `float` 參數在「效果」面板有「使用遮罩」按鈕：選一張圖片、影片或複合片段（一樣擺在片段上），
  濾鏡讀到的就是 **數字 × 那個位置的明度**（白色是數字本身、黑色是 0），來源沒蓋到或透明的地方是數字本身。
  一樣是 `#define`，照常用名字讀就好；因為每個像素可能不同，不要把它用在 `#if` 或陣列大小這種要固定的地方。

### 面板和用不上的參數

```glsl
// @param type menu Bloom "Bloom|Streaks|Fog Glow" "類型"
// @panel 亮部
// @param threshold float 0.7 0 1 "亮度門檻"
// @param clamp_on bool false "限制亮度"
// @param maximum float 1 0 1 "最大亮度"
// @panel 光芒
// @param size float 0.5 0 1 "大小"
// @param streaks int 4 1 16 "光芒數"
// @enable maximum clamp_on
// @enable size type == Bloom|Fog Glow
// @enable streaks type != Bloom
```

- 沒有在任何 `@panel` 裡的參數排在最上面，面板照寫的順序排在後面；面板在「效果」面板上可以摺疊。
- `@enable` 的條件：`布林參數`（打勾時才用得上）、`!布林參數`、`參數 == 值1|值2`、`參數 != 值`。
  menu 的值寫選項的名字（也可以寫編號），數字參數寫數字。同一個參數可以有好幾行 `@enable`，全部成立才用得上。
  `@enable` 可以寫在檔案標頭的任何位置。
- 用不上的參數只是變灰，值照樣傳給 shader，也照樣可以打關鍵幀。

## 程式提供的東西

| 名稱 | 型別 | 說明 |
|---|---|---|
| `src(vec2 uv)` | 函式 → `vec4` | 讀取輸入的畫面。`uv` 的 (0,0) 是左上角、(1,1) 是右下角。超出範圍會取邊緣的顏色。**預乘透明度**（RGB 已經乘過 A） |
| `original(vec2 uv)` | 函式 → `vec4` | 讀取濾鏡**還沒處理過**的畫面（每一次繪製都一樣），搭配 `@passes`，例如最後一次把模糊過的光疊回原圖。和 `src()` 一樣是預乘透明度 |
| `unpremultiply(vec4)` / `premultiply(vec4)` | 函式 | 在預乘和一般 RGBA 之間轉換。調色類的濾鏡要先 `unpremultiply`，算完再 `premultiply` |
| `rand(vec2 p)` | 函式 → `float` | 0~1 的偽隨機數，同樣的 `p` 永遠得到同樣的結果 |
| `resolution` | `vec2` | **畫布**的大小（像素），不管預覽是小視窗、全螢幕還是匯出都一樣。預覽畫得比畫布小時，程式會照預覽和畫布的比例換算，所以用「像素」當單位的參數（半徑、距離…）直接寫畫布的像素數就好（`偏移 / resolution` 換成 uv），小預覽、全螢幕和匯出看起來都一樣 |
| `scale` | `float` | 固定是 1（舊的濾鏡用它把像素換算成畫面大小，現在不用了，留著讓舊檔案照常運作） |
| `time` | `float` | 從這個濾鏡開始作用起經過的秒數 |
| `progress` | `float` | 0~1：濾鏡持續時間內走到哪裡了 |
| `frame` | `int` | 從濾鏡開始作用起的第幾格 |
| `pass_index` | `int` | 現在是第幾次繪製（0 起算），搭配 `@passes` |

`effect(vec2 uv)` 必須回傳**預乘透明度**的 `vec4`。語言是 GLSL 3.30（`#version 330`），
`#line` 已經設好，所以編譯錯誤訊息的行號就是你檔案裡的行號（標頭那幾行也算）。

## 作用範圍

- 濾鏡**套在片段上**：只處理那個片段（連同它的變形）畫出來的內容。
- 濾鏡**當成獨立片段放在時間軸上**：處理它**下面所有軌道**合起來的畫面，作用的時間就是片段的長度。
- 兩種都可以加遮罩，遮罩以外的地方保持原樣；片段的「不透明度」就是濾鏡的強度。
- 每個效果都有「混合程度」（0~100%，可以打關鍵幀）：濾鏡的結果和它拿到的畫面照這個比例混合，0% 就是沒套用。

## 檔案放哪裡

`Library/filters/` 底下任意位置。檔案修改後，專案裡用到它的地方下一格就會更新。
專案裡記的是檔案路徑（在 Library 裡的會存成 `@library/…`，換電腦、換 Library 位置都找得到）。

## 匯出

含有濾鏡的專案用內建的畫面渲染器匯出（和預覽同一套），需要 OpenGL 3.3（一般的顯示卡驅動都有）。

## 用 Blender 合成器做濾鏡

`tools/converters/compositor_to_hyprshade.py` 是 Blender 插件。在合成器（Compositor）裡把效果做成**節點群組**，
選單 Node →「Export as Shader / Filter」→ 格式選「KiaseCut filter (.glsl)」，把輸出的 `.glsl` 放進 Library 的 `filters` 資料夾即可。

- 畫面（片段的圖）從哪裡來：群組輸入裡叫 `Image` 或 `Input` 的 Color 插槽（沒有就用第一個 Color 輸入）、
  沒接線的群組節點的 `Image`／`Input` 插槽，或叫「Input」的 Image 節點。所以 Blender 裡不需要一直載著一張圖片。
- 群組的輸入（Image／Input 以外）會變成參數，面板上可以調、可以打關鍵幀：Float → `float`、Integer → `int`、Boolean → `bool`、
  Color → `color`、Vector → `vec3`（2D 向量 → `vec2`）、Menu → `menu`。群組輸入的最小／最大值就是欄位範圍。
- 群組介面裡的**面板**（Panel）會變成 `// @panel`，一樣可以摺疊；面板預設收起來的，匯出後也是收起來。
- Menu 輸入會變成下拉選單，匯出後還能切換、打關鍵幀（可以隔著轉接點、穿進內層群組的 Menu 輸入）：
  接到 Menu Switch 時選項就是 Menu Switch 的項目；接到節點自己的選單（例如 Glare 的 Type、Quality，Blur 的類型）時，
  選項就是那個選單的選項，匯出檔裡每個選項各有一份程式，由參數挑一份來跑。
- `Scene Time` 節點用片段時間（`time`）；`Blur`、`Glare`、`Dilate/Erode`、`Pixelate` 的取樣數等寫在檔案裡的 `#define` 區，可以自己改。
- `Glare` 的七種類型都能匯出（含 Quality、Clamp、Saturation、Tint 與 Highlights 輸出）：Fog Glow、Streaks、Simple Star 照 Blender 的算法做，
  Ghosts 是取樣近似（有一點顆粒，`GHOST_SAMPLES` 調高會更平滑但比較慢），Kernel 若接了核心圖片則只輸出 highlights。
  Simple Star 和 Ghosts 的 Iterations（Simple Star 還有 Fade）在匯出時就固定了。
- `#define LINEARIZE 1`：照 Blender 的方式在線性光裡運算（預設）；`FLIP_Y`、`COMPOSITE_OVER_SCREEN` 同樣在 `#define` 區。
- 限制：決定結構的選項（Interpolation、節點自己的類型選單等）若沒有接到群組的 Menu 輸入，在匯出時就固定了；Switch / Index Switch 若接到群組輸入（參數）或計算出來的值，匯出後仍可切換；`String to Image` 不支援（文字請用編輯器的文字片段）。

## 當成節點用

每個濾鏡（內建的、Library 裡的）在「節點」面板都是一個節點：`src()` 是第一個輸入插槽，`@input` 宣告的圖是
其他輸入插槽，`float` 和 `color` 參數也有插槽（接上圖，就是「使用遮罩」：每個像素讀那張圖）。
`kiasecut/filters/nodes/` 裡是專門為節點寫的（混合、數學、分離／合併通道、設定透明度、變換、圖片來源），
寫法和一般濾鏡一模一樣，可以當範例：

```glsl
// @filter 混合
// @input b "B"
// @param fac float 1 0 1 "係數"
vec4 effect(vec2 uv) {
    vec4 a = unpremultiply(src(uv)), b = unpremultiply(input_b(uv));
    ...
}
```

節點圖本身是一個效果（新增效果 > 節點效果），存在片段上；用「存成自定效果」存進 Library 的「效果預設」，
圖、設定、圖片來源都一起存。每個節點畫一次（一個 shader pass），所以 `@passes`、`@levels` 的濾鏡也能當節點。
