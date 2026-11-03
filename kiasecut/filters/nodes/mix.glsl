// @filter 混合
// @category 色彩
// @description 節點用：照 Blender 的「混合」節點（Mix）：資料型態選顏色、浮點或向量。顏色：把 B 以選的混合模式（19 種）混到圖像上；浮點：圖進來是黑白的明度，結果是黑白的圖；向量：紅綠藍當 XYZ，係數可以是統一的一個數，也可以是向量（每個軸各自的係數，接到「係數（向量）」）。係數可以接一張圖當遮罩，不限制係數時可以超過 0~1（往外推）。「使用 B 的透明度」開著時 B 的透明度會乘上係數（常見的疊圖）；關掉就和 Blender 一樣直接算預乘後的四個通道：混合模式時透明度也跟著混，其他模式透明度用圖像的
// @source 圖像
// @input b "B"
// @input facv "係數（向量）"
// @param data_type menu 顏色 "顏色|浮點|向量" "資料型態"
// @param factor_mode menu 統一 "統一|非統一" "係數模式"
// @param blend menu 混合 "混合|變暗|相乘|加深顏色|變亮|濾色|加亮顏色|相加|疊加|柔光|線性光|差異|排除|相減|相除|色相|飽和度|顏色|明度" "混合模式"
// @param fac float 1 -5 5 "係數"
// @param clamp_fac bool true "限制係數"
// @param use_alpha bool false "使用 B 的透明度"
// @param clamp_on bool false "限制結果"
// @enable factor_mode data_type == 向量
// @enable blend data_type == 顏色
// @enable use_alpha data_type == 顏色
// @enable clamp_on data_type == 顏色
// @show facv data_type == 向量
// @show facv factor_mode == 非統一

// Reimplementation of Blender's Mix compositor node: its behaviour checked against Blender 5.2 (a comment below says where code was ported from Blender's shaders).
// Blender: https://github.com/blender/blender
// SPDX-FileCopyrightText: Blender Authors (original, GPL-2.0-or-later); KiaseCut
// SPDX-License-Identifier: GPL-3.0-or-later

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
    float f = fac;
    if (clamp_fac) f = clamp(f, 0.0, 1.0);
    if (data_type == 1) {                                      // float: the brightness of each picture over black
        float a = dot(src(uv).rgb, vec3(0.2126, 0.7152, 0.0722)), b = dot(input_b(uv).rgb, vec3(0.2126, 0.7152, 0.0722));
        return vec4(vec3(mix(a, b, f)), 1.0);
    }
    if (data_type == 2) {                                      // vector: red, green, blue are x, y, z
        vec3 a = src(uv).rgb, b = input_b(uv).rgb;
        vec3 k = vec3(f);
        if (factor_mode == 1) {
            k = has_input_facv() ? input_facv(uv).rgb : vec3(0.5);
            if (clamp_fac) k = clamp(k, 0.0, 1.0);
        }
        return vec4(mix(a, b, k), 1.0);
    }
    if (!use_alpha) {                                          // as Blender: the four channels as they are stored (premultiplied)
        vec4 a = src(uv), b = input_b(uv);
        vec3 r = blend_color(a.rgb, b.rgb, f);
        float alpha = blend == 0 ? mix(a.a, b.a, f) : a.a;
        if (clamp_on) { r = clamp(r, 0.0, 1.0); alpha = clamp(alpha, 0.0, 1.0); }
        return vec4(r, alpha);
    }
    vec4 a = unpremultiply(src(uv)), b = unpremultiply(input_b(uv));
    f *= b.a;
    vec3 r = blend_color(a.rgb, b.rgb, f);
    if (clamp_on) r = clamp(r, 0.0, 1.0);
    return premultiply(vec4(r, a.a));
}
