// @filter 透明度覆蓋
// @category 色彩
// @description 節點用：照 Blender 的 Alpha Over：前景 B 蓋在背景（圖像）上，兩邊的透明度都算進去
// @source 背景
// @input b "前景"
// @param fac float 1 0 1 "係數"

vec4 effect(vec2 uv) {
    vec4 bg = src(uv), fg = input_b(uv) * clamp(fac, 0.0, 1.0);
    return fg + bg * (1.0 - fg.a);
}
