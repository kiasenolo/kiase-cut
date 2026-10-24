// @filter 色溫與色調
// @category 色彩
// @description 色溫：偏暖（黃）或偏冷（藍）；色調：偏洋紅或偏綠
// @param temperature float 0 -1 1 "色溫"
// @param tint float 0 -1 1 "色調"
vec4 effect(vec2 uv) {
    vec4 c = unpremultiply(src(uv));
    vec3 gain = vec3(1.0 + 0.3 * temperature, 1.0 + 0.05 * temperature, 1.0 - 0.3 * temperature);
    gain *= vec3(1.0 + 0.12 * tint, 1.0 - 0.2 * tint, 1.0 + 0.12 * tint);
    return premultiply(vec4(clamp(c.rgb * gain, 0.0, 1.0), c.a));
}
