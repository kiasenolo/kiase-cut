// @filter 限制
// @category 轉換器
// @description 節點用：照 Blender 的「限制」節點：輸入是數值（圖進來就是黑白的明度，透明處是 0），限制在最小到最大之間（或範圍），結果是黑白的圖
// @source 數值
// @param mode menu 最小最大 "最小最大|範圍" "類型"
// @param lo float 0 -1000 1000 "最小"
// @param hi float 1 -1000 1000 "最大"

vec4 effect(vec2 uv) {
    float a = dot(src(uv).rgb, vec3(0.2126, 0.7152, 0.0722));        // (a float input: the picture's brightness over black)
    float r = mode == 0 ? min(max(a, lo), hi) : clamp(a, min(lo, hi), max(lo, hi));
    return vec4(vec3(r), 1.0);
}
