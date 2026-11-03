// @filter 設定透明度
// @category 色彩
// @description 節點用：照 Blender 的「設定透明度」：透明度是數值（圖進來就是黑白的明度，沒接線就用欄位裡的數字）。套用遮罩：乘上圖像原本的透明度；取代透明度：直接換成這個數值
// @source 圖像
// @input alpha_img "透明度" alpha
// @param type menu 套用遮罩 "套用遮罩|取代透明度" "類型"
// @param alpha float 1 0 1 "透明度"

vec4 effect(vec2 uv) {
    vec4 c = unpremultiply(src(uv)), m = input_alpha_img(uv);
    float k = has_input_alpha_img() ? clamp(dot(m.rgb, vec3(0.2126, 0.7152, 0.0722)), 0.0, 1.0) : clamp(alpha, 0.0, 1.0);
    return premultiply(vec4(c.rgb, type == 0 ? c.a * k : k));
}
