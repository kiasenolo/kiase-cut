// @filter 混合
// @category 節點
// @description 節點用：把 B 以選的模式混到圖像上（「混合」就是 Alpha Over：B 蓋在圖像上）
// @source 圖像
// @input b "B"
// @param mode menu 混合 "混合|相加|相乘|濾色|疊加|相減|差異|變暗|變亮" "模式"
// @param fac float 1 0 1 "係數"

vec3 blend_rgb(vec3 a, vec3 b) {
    if (mode == 1) return a + b;
    if (mode == 2) return a * b;
    if (mode == 3) return 1.0 - (1.0 - a) * (1.0 - b);
    if (mode == 4) return mix(2.0 * a * b, 1.0 - 2.0 * (1.0 - a) * (1.0 - b), step(vec3(0.5), a));
    if (mode == 5) return a - b;
    if (mode == 6) return abs(a - b);
    if (mode == 7) return min(a, b);
    if (mode == 8) return max(a, b);
    return b;
}

vec4 effect(vec2 uv) {
    vec4 a = unpremultiply(src(uv)), b = unpremultiply(input_b(uv));
    float fb = clamp(fac, 0.0, 1.0) * b.a;
    float ao = a.a + fb * (1.0 - a.a);
    if (ao <= 0.0) return vec4(0.0);
    vec3 m = blend_rgb(a.rgb, b.rgb);
    vec3 rgb = ((1.0 - fb) * a.a * a.rgb + fb * (1.0 - a.a) * b.rgb + fb * a.a * m) / ao;
    return vec4(rgb * ao, ao);
}
