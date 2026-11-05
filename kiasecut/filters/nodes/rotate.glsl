// @filter 旋轉
// @category 變換
// @description 節點用：照 Blender 的「旋轉」（Rotate）：圖像繞著畫面中心旋轉（角度為正是逆時針；欄位用度，從別的節點接進來的數字當弧度，像 Blender），取樣可選最近點、雙線性、雙三次、各向異性（旋轉時等於雙線性）；超出圖的地方可選透明、延伸邊緣或重複，X 和 Y 分開選
// @source 圖像
// @input angle "角度" angle
// @param angle float 0 -36000 36000 "角度（度）"
// @param interp menu 雙線性 "最近點|雙線性|雙三次|各向異性" "取樣"
// @param ext_x menu 裁切 "裁切|延伸|重複" "延伸 X"
// @param ext_y menu 裁切 "裁切|延伸|重複" "延伸 Y"

// Reimplementation of Blender's Rotate compositor node: its behaviour checked against Blender 5.2 (a comment below says where code was ported from Blender's shaders).
// Blender: https://github.com/blender/blender
// SPDX-FileCopyrightText: Blender Authors (original, GPL-2.0-or-later); KiaseCut
// SPDX-License-Identifier: GPL-3.0-or-later

// The picture is read as Blender's GPU samplers do: the texel grid of the picture itself, outside of it transparent (裁切), the edge pixel (延伸) or
// the picture again (重複), per axis. Bicubic is Blender's cubic B-spline (gpu_shader_bicubic_sampler_lib.glsl).
int wrap_(int i, int n, int mode, out bool gone) {
    gone = false;
    if (i >= 0 && i < n) return i;
    if (mode == 0) { gone = true; return 0; }
    if (mode == 1) return clamp(i, 0, n - 1);
    return i - n * int(floor(float(i) / float(n)));
}
vec4 texel_at(ivec2 p) {
    ivec2 n = ivec2(src_px);
    bool gx, gy;
    int x = wrap_(p.x, n.x, ext_x, gx), y = wrap_(p.y, n.y, ext_y, gy);
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

float bright(vec4 c) { return dot(c.rgb, vec3(0.2126, 0.7152, 0.0722)); }

// Blender 5.2 realizes the picture on its own domain turned about the centre of the picture (compositor_realize_on_domain.glsl):
// every pixel reads the picture where that turn takes it back to.
vec4 effect(vec2 uv) {
    vec2 res = resolution;
    float a = has_input_angle() ? bright(input_angle(uv)) : radians(angle);
    vec2 p = vec2(uv.x * res.x, (1.0 - uv.y) * res.y) - res * 0.5;     // (pixels from the centre, Y up)
    float c = cos(a), s = sin(a);
    vec2 q = vec2(c * p.x + s * p.y, -s * p.x + c * p.y) + res * 0.5;
    return sample_(vec2(q.x / res.x, 1.0 - q.y / res.y));
}
