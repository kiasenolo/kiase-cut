// @filter 限制
// @category 轉換器
// @description 節點用：照 Blender 的「限制」節點：把圖像每個通道限制在最小到最大之間（或範圍）
// @source 數值
// @param mode menu 最小最大 "最小最大|範圍" "類型"
// @param lo float 0 -1000 1000 "最小"
// @param hi float 1 -1000 1000 "最大"

vec4 effect(vec2 uv) {
    vec4 a = unpremultiply(src(uv));
    vec3 r = mode == 0 ? clamp(a.rgb, min(lo, hi), max(lo, hi)) : clamp(a.rgb, lo, hi);
    return premultiply(vec4(r, a.a));
}
