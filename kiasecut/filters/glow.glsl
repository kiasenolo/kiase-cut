// @filter 發光
// @category 模糊
// @description 亮的地方向外暈開
// @param threshold float 0.6 0 1 "亮度門檻"
// @param radius float 30 1 200 "半徑"
// @param intensity float 1 0 5 "強度"
// @param tint color #ffffff "光的顏色"
vec4 effect(vec2 uv) {
    vec4 c = src(uv);
    float r = radius * scale;
    vec3 acc = vec3(0.0);
    float total = 0.0;
    for (int i = 0; i < 80; i++) {             // a sunflower spiral over the disc
        float f = (float(i) + 0.5) / 80.0;
        float a = float(i) * 2.3999632;
        vec4 s = src(uv + vec2(cos(a), sin(a)) * sqrt(f) * r / resolution);
        float w = 1.0 - 0.8 * f;
        acc += max(s.rgb - threshold * s.a, 0.0) * w;
        total += w;
    }
    vec3 g = acc / total * intensity * 2.0 * tint.rgb;
    float a = max(c.a, clamp(max(g.r, max(g.g, g.b)), 0.0, 1.0));
    return vec4(min(c.rgb + g, vec3(a)), a);
}
