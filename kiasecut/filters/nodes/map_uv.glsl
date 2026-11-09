// @filter UV 貼圖
// @category 變換
// @description 節點用：照 Blender 的「UV 貼圖」（Map UV）：UV 圖的紅、綠是每個像素要去圖像的哪裡取色（0~1，左下角是 0,0），藍是透明度（結果乘上它，所以沒接 UV 就是全透明）。取樣可選最近點、雙線性、雙三次、各向異性（依 UV 的變化量沿長軸多取幾點）；超出圖的地方可選透明、延伸邊緣或重複，X 和 Y 分開選
// @source 圖像
// @input uv "UV"
// @param interp menu 雙線性 "最近點|雙線性|雙三次|各向異性" "取樣"
// @param ext_x menu 裁切 "裁切|延伸|重複" "延伸 X"
// @param ext_y menu 裁切 "裁切|延伸|重複" "延伸 Y"
// @socket in uv vector

// Reimplementation of Blender's Map UV compositor node: its behaviour checked against Blender 5.2 (a comment below says where code was ported from Blender's shaders).
// Blender: https://github.com/blender/blender
// SPDX-FileCopyrightText: Blender Authors (original, GPL-2.0-or-later); KiaseCut
// SPDX-License-Identifier: GPL-3.0-or-later

// The picture is read as Blender's GPU samplers do: the texel grid of the picture itself, outside of it transparent (裁切), the edge pixel (延伸) or
// the picture again (重複), per axis. Bicubic is Blender's cubic B-spline (gpu_shader_bicubic_sampler_lib.glsl).
int wrap_(int i, int n, int m, int mode, out bool gone) {          // (m: the margin round the frame that has a picture too)
    gone = false;
    if (i >= -m && i < n + m) return i;
    if (mode == 0) { gone = true; return 0; }
    if (mode == 1) return clamp(i, -m, n + m - 1);
    return i - n * int(floor(float(i) / float(n)));
}
vec4 texel_at(ivec2 p) {
    ivec2 n = ivec2(src_px);
    bool gx, gy;
    ivec2 m = ov_margin_px();
    int x = wrap_(p.x, n.x, m.x, ext_x, gx), y = wrap_(p.y, n.y, m.y, ext_y, gy);
    if (gx || gy) return vec4(0.0);
    return src((vec2(x, y) + 0.5) / src_px);
}
vec4 bilinear_(vec2 t) {                              // t: position in texels
    vec2 q = t - 0.5, i = floor(q), f = q - i;
    ivec2 p = ivec2(i);
    return mix(mix(texel_at(p), texel_at(p + ivec2(1, 0)), f.x), mix(texel_at(p + ivec2(0, 1)), texel_at(p + ivec2(1, 1)), f.x), f.y);
}
vec4 bicubic_(vec2 t) {
    vec2 q = t - 0.5, i = floor(q), f = q - i;
    vec2 f2 = f * f, f3 = f2 * f;
    vec2 w3 = f3 / 6.0, w0 = -w3 + f2 * 0.5 - f * 0.5 + 1.0 / 6.0, w1 = f3 * 0.5 - f2 + 2.0 / 3.0, w2 = 1.0 - w0 - w1 - w3;
    vec2 wx[4] = vec2[4](vec2(w0.x), vec2(w1.x), vec2(w2.x), vec2(w3.x));
    ivec2 p = ivec2(i);
    vec4 acc = vec4(0.0);
    for (int y = 0; y < 4; y++) {
        float wy = y == 0 ? w0.y : y == 1 ? w1.y : y == 2 ? w2.y : w3.y;
        for (int x = 0; x < 4; x++)
            acc += texel_at(p + ivec2(x - 1, y - 1)) * wx[x].x * wy;
    }
    return acc;
}
vec4 sample_(vec2 uv) {                               // uv: 0 - 1 over the picture, V down
    vec2 t = uv * src_px;
    if (interp == 0) return texel_at(ivec2(floor(t)));
    if (interp == 2) return bicubic_(t);
    return bilinear_(t);
}

// Blender 5.2 (compositor_map_uv.glsl): the colour is the picture at (u, v) times the third channel of the UV picture. Anisotropic
// (compositor_map_uv_anisotropic.glsl) hands the sampler the change of the UV to the neighbour pixels; there are no mip levels here, so
// the footprint is covered by bilinear taps along its longer side instead (the same as bilinear where the picture is not shrunk).
vec2 uv_of(vec2 at) {
    vec3 m = input_uv(at).rgb;
    return vec2(m.x, 1.0 - m.y);
}

vec4 effect(vec2 uv) {
    if (!has_input_uv()) return vec4(0.0);                 // (Blender's UV starts at (1, 0, 0): no alpha)
    vec3 m = input_uv(uv).rgb;
    vec2 at = vec2(m.x, 1.0 - m.y);
    vec4 c;
    if (interp == 3) {
        vec2 step = 1.0 / resolution;
        vec2 gx = (uv_of(uv + vec2(step.x, 0.0)) - uv_of(uv - vec2(step.x, 0.0))) * 0.5 * src_px;
        vec2 gy = (uv_of(uv + vec2(0.0, step.y)) - uv_of(uv - vec2(0.0, step.y))) * 0.5 * src_px;
        vec2 major = dot(gx, gx) >= dot(gy, gy) ? gx : gy;
        float taps = clamp(ceil(length(major)), 1.0, 16.0);
        c = vec4(0.0);
        for (int i = 0; i < 16; i++) {
            if (float(i) >= taps) break;
            float k = (float(i) + 0.5) / taps - 0.5;
            c += bilinear_((at * src_px) + major * k);
        }
        c /= taps;
    } else {
        c = sample_(at);
    }
    return c * m.z;
}
