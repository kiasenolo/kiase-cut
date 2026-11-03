// @filter 影像座標
// @category 輸入
// @description 節點用：照 Blender 的「影像座標」：輸出每個像素的座標（紅＝X、綠＝Y，Y 向上）。統一：畫面中心是原點、長邊從 -1 到 1，不會被拉伸；正規化：左下 (0, 0) 到右上 (1, 1)；像素：以畫布像素計
// @output uniform "統一"
// @output normalized "正規化"
// @output pixel "像素"

vec4 effect(vec2 uv) {
    vec2 R = resolution;
    vec2 n = vec2(uv.x, 1.0 - uv.y);
    if (output_index == 0) return vec4((n * 2.0 - 1.0) * R / max(R.x, R.y), 0.0, 1.0);
    if (output_index == 1) return vec4(n, 0.0, 1.0);
    return vec4(n * R, 0.0, 1.0);
}
