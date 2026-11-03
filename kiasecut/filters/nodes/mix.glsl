// @filter 混合
// @category 色彩
// @description 節點用：照 Blender 的「混合」節點（Mix）：把 B 以選的混合模式（19 種）混到圖像上，係數可以接一張圖當遮罩
// @source 圖像
// @input b "B"
// @param blend menu 混合 "混合|變暗|相乘|加深顏色|變亮|濾色|加亮顏色|相加|疊加|柔光|線性光|差異|排除|相減|相除|色相|飽和度|顏色|明度" "混合模式"
// @param fac float 1 0 1 "係數"
// @param use_alpha bool true "使用 B 的透明度"
// @param clamp_on bool false "限制在 0~1"

vec3 rgb_to_hsv(vec3 c) {
    float mx = max(c.r, max(c.g, c.b)), mn = min(c.r, min(c.g, c.b)), d = mx - mn;
    float h = 0.0;
    if (d > 1e-6) {
        if (mx == c.r) h = mod((c.g - c.b) / d, 6.0);
        else if (mx == c.g) h = (c.b - c.r) / d + 2.0;
        else h = (c.r - c.g) / d + 4.0;
        h /= 6.0;
    }
    return vec3(h, mx > 1e-6 ? d / mx : 0.0, mx);
}

vec3 hsv_to_rgb(vec3 c) {
    vec3 k = clamp(abs(mod(c.x * 6.0 + vec3(0.0, 4.0, 2.0), 6.0) - 3.0) - 1.0, 0.0, 1.0);
    return c.z * mix(vec3(1.0), k, c.y);
}

// Blender's blend functions (blender::math, node_composite_mix): f is the factor, fm = 1 - f
vec3 blend_color(vec3 a, vec3 b, float f) {
    float fm = 1.0 - f;
    vec3 r = a;
    if (blend == 0) return fm * a + f * b;
    if (blend == 1) return fm * a + f * min(a, b);
    if (blend == 2) return a * (fm + f * b);
    if (blend == 3) {
        vec3 t = fm + f * b;
        return mix(max(1.0 - (1.0 - a) / max(t, vec3(1e-6)), 0.0), vec3(0.0), lessThanEqual(t, vec3(0.0)));
    }
    if (blend == 4) return fm * a + f * max(a, b);
    if (blend == 5) return 1.0 - (fm + f * (1.0 - b)) * (1.0 - a);
    if (blend == 6) {
        vec3 t = 1.0 - f * b;
        return mix(min(a / max(t, vec3(1e-6)), 1.0), vec3(1.0), lessThanEqual(t, vec3(0.0)));
    }
    if (blend == 7) return a + f * b;
    if (blend == 8) return mix(a * (fm + 2.0 * f * b), 1.0 - (fm + 2.0 * f * (1.0 - b)) * (1.0 - a), step(vec3(0.5), a));
    if (blend == 9) {
        vec3 scr = 1.0 - (1.0 - b) * (1.0 - a);
        return fm * a + f * ((1.0 - a) * b * a + a * scr);
    }
    if (blend == 10) return a + f * (2.0 * b - 1.0);
    if (blend == 11) return fm * a + f * abs(a - b);
    if (blend == 12) return max(fm * a + f * (a + b - 2.0 * a * b), 0.0);
    if (blend == 13) return a - f * b;
    if (blend == 14) return mix(a, fm * a + f * a / max(b, vec3(1e-6)), notEqual(b, vec3(0.0)));
    vec3 ha = rgb_to_hsv(a), hb = rgb_to_hsv(b);
    if (blend == 15) {                                           // hue
        if (hb.y != 0.0) { ha.x = hb.x; r = fm * a + f * hsv_to_rgb(ha); }
    } else if (blend == 16) {                                    // saturation
        if (ha.y != 0.0) { ha.y = fm * ha.y + f * hb.y; r = hsv_to_rgb(ha); }
    } else if (blend == 17) {                                    // colour
        if (hb.y != 0.0) { ha.x = hb.x; ha.y = hb.y; r = fm * a + f * hsv_to_rgb(ha); }
    } else {                                                     // value
        ha.z = fm * ha.z + f * hb.z; r = hsv_to_rgb(ha);
    }
    return r;
}

vec4 effect(vec2 uv) {
    vec4 a = unpremultiply(src(uv)), b = unpremultiply(input_b(uv));
    float f = clamp(fac, 0.0, 1.0) * (use_alpha ? b.a : 1.0);
    vec3 r = blend_color(a.rgb, b.rgb, f);
    if (clamp_on) r = clamp(r, 0.0, 1.0);
    return premultiply(vec4(r, a.a));
}
