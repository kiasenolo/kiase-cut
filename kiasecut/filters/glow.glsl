// @filter 發光
// @category 模糊
// @description 亮的地方向外暈開（高斯光暈，像 AE 的 Glow）
// @passes 5
// @param threshold float 0.6 0 1 "亮度門檻"
// @param softness float 0.2 0 1 "門檻柔邊"
// @param radius float 30 1 300 "半徑"
// @param intensity float 1 0 5 "強度"
// @param tint color #ffffff "光的顏色"
// @param mode menu 保留色相 "保留色相|濾色|相加|變亮" "混合方式"
// @param glow_only bool false "只顯示光"

// The part of a pixel that glows: its own colour, faded in by its brightness (the brightest
// channel, so saturated lights glow too). Scaling the whole colour keeps its hue.
vec4 bright(vec4 s) {
    if (s.a <= 0.0) return vec4(0.0);
    float v = max(s.r, max(s.g, s.b)) / s.a;
    float k = max(softness * 0.5, 0.001);
    return s * smoothstep(threshold - k, threshold + k, v);
}

// One direction of a Gaussian blur; with stride > 1 every stride-th pixel is read, which is
// only smooth on a picture already blurred by about that much.
vec4 gauss(vec2 uv, vec2 dir, float sigma, float stride, bool extract) {
    if (sigma < 0.3) return extract ? bright(src(uv)) : src(uv);
    float reach = 3.0 * sigma;
    vec4 sum = vec4(0.0);
    float total = 0.0;
    for (int i = -64; i <= 64; i++) {
        float d = float(i) * stride;
        if (abs(d) > reach) continue;
        float w = exp(-0.5 * d * d / (sigma * sigma));
        vec4 s = src(uv + dir * d / resolution);
        sum += (extract ? bright(s) : s) * w;
        total += w;
    }
    return sum / total;
}

vec4 effect(vec2 uv) {
    // each direction is blurred twice: finely (every pixel), then coarsely for the rest of
    // the radius; the two add up to one Gaussian of the whole radius
    float sigma = radius / 2.0;
    float s1 = min(sigma, 8.0);
    float s2 = sqrt(max(sigma * sigma - s1 * s1, 0.0));
    float stride2 = max(1.0, 3.0 * s2 / 64.0);
    if (pass_index == 0) return gauss(uv, vec2(1.0, 0.0), s1, 1.0, true);
    if (pass_index == 1) return gauss(uv, vec2(1.0, 0.0), s2, stride2, false);
    if (pass_index == 2) return gauss(uv, vec2(0.0, 1.0), s1, 1.0, false);
    if (pass_index == 3) return gauss(uv, vec2(0.0, 1.0), s2, stride2, false);

    vec4 c = original(uv);
    vec4 g = src(uv);
    vec4 l = vec4(g.rgb * tint.rgb, g.a) * intensity;          // the light, premultiplied
    l.a = min(l.a, 1.0);
    l.rgb /= max(1.0, max(l.r, max(l.g, l.b)) / max(l.a, 1e-4)); // too strong: dimmed whole, not per channel
    if (glow_only) return l;
    float a = c.a + l.a - c.a * l.a;
    if (mode == 0) {                                                  // 保留色相: added, and past white the whole
        vec3 s = c.rgb + l.rgb;                                       // colour is dimmed, so orange stays orange
        return vec4(s / max(1.0, max(s.r, max(s.g, s.b)) / max(a, 1e-4)), a);
    }
    if (mode == 1) return vec4(c.rgb + l.rgb - c.rgb * l.rgb, a);    // 濾色: brightens, never past white
    if (mode == 3) return vec4(max(c.rgb, l.rgb), max(c.a, l.a));     // 變亮: only where the light is brighter
    return vec4(min(c.rgb + l.rgb, vec3(a)), a);                      // 相加
}
