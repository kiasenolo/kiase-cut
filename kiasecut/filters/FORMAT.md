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
| `// @passes N` | 要繪製幾次（預設 1，最多 8）。第 2 次起 `src()` 讀到的是上一次的結果，可以用來做分離式模糊 |
| `// @param 名稱 型別 預設值 [最小 最大] ["顯示名稱"]` | 宣告一個參數，見下面 |

### 參數

`@param` 宣告的參數會在程式的「濾鏡」面板長出對應的欄位（數字、勾選框、顏色選擇器），
在 shader 裡就是同名的 `uniform`，直接用名字讀就好。

| 型別 | 預設值寫法 | 在 shader 裡的型別 | 面板上的欄位 |
|---|---|---|---|
| `float` | `0.5` | `float` | 數字欄，可以打關鍵幀 |
| `int` | `4` | `int` | 整數欄 |
| `bool` | `true` / `false` | `bool` | 勾選框 |
| `color` | `#rrggbb` 或 `#rrggbbaa` | `vec4`（RGBA，0~1，**沒有**預乘） | 顏色選擇器 |
| `vec2` | `0.5,0.5` | `vec2` | 兩個數字欄（X、Y） |
| `vec3` | `0.1,0.2,0.3` | `vec3` | 三個數字欄（X、Y、Z） |

- `float`、`int`、`vec2`、`vec3` 可以接 `最小 最大`，限制面板欄位的範圍（不寫就是 -1000 ~ 1000）。
- 最後可以放用雙引號包起來的顯示名稱，例如 `"半徑"`。
- 名稱只能用英文字母、數字、底線，不能以數字開頭，也不能跟下面的內建名稱重複。

## 程式提供的東西

| 名稱 | 型別 | 說明 |
|---|---|---|
| `src(vec2 uv)` | 函式 → `vec4` | 讀取輸入的畫面。`uv` 的 (0,0) 是左上角、(1,1) 是右下角。超出範圍會取邊緣的顏色。**預乘透明度**（RGB 已經乘過 A） |
| `unpremultiply(vec4)` / `premultiply(vec4)` | 函式 | 在預乘和一般 RGBA 之間轉換。調色類的濾鏡要先 `unpremultiply`，算完再 `premultiply` |
| `rand(vec2 p)` | 函式 → `float` | 0~1 的偽隨機數，同樣的 `p` 永遠得到同樣的結果 |
| `resolution` | `vec2` | 正在處理的畫面大小（像素）。預覽和匯出的大小不同，所以長度請不要寫死像素數 |
| `scale` | `float` | `resolution.y / 1080`。要用「像素」當單位的參數（半徑、距離…）乘上它，這樣預覽和匯出看起來一樣 |
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
  Color → `color`、Vector → `vec3`（2D 向量 → `vec2`）。群組輸入的最小／最大值就是欄位範圍。
- `Scene Time` 節點用片段時間（`time`）；`Blur`、`Glare`、`Dilate/Erode`、`Pixelate` 的取樣數等寫在檔案裡的 `#define` 區，可以自己改。
- `#define LINEARIZE 1`：照 Blender 的方式在線性光裡運算（預設）；`FLIP_Y`、`COMPOSITE_OVER_SCREEN` 同樣在 `#define` 區。
- 限制：決定結構的選項（Menu Switch、Interpolation 等）在匯出時就固定了；Switch / Index Switch 若接到群組輸入（參數）或計算出來的值，匯出後仍可切換；`String to Image` 不支援（文字請用編輯器的文字片段）。

