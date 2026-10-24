// @filter 我的濾鏡
// @category 自訂
// @description 這是範本：把畫面變暗並加上一點顏色。規格見同資料夾的 FORMAT.md
// @param amount float 0.5 0 1 "強度"
// @param tint color #ff8800 "顏色"

// 每個像素會呼叫一次 effect()。uv 是 0~1 的座標，(0,0) 在畫面左上角。
// 用 src(uv) 讀取原本的畫面；回傳值是處理後的顏色（預乘透明度）。
vec4 effect(vec2 uv) {
    vec4 c = src(uv);                          // 預乘透明度的 RGBA
    vec3 shade = mix(c.rgb, c.rgb * tint.rgb, amount);   // 乘上顏色
    return vec4(shade * (1.0 - 0.3 * amount), c.a);
}
