// @filter 棋盤格紋理
// @category 紋理
// @description 節點用：照 Blender 的「棋盤格紋理」節點：兩種顏色交錯的方格，3D（Z 每過一格就黑白反轉）。向量沒接線就用影像座標（統一：長邊 -1 到 1，Y 向上）。向量、顏色 1、顏色 2、比例都可以接別的節點（顏色沒接就用欄位裡的顏色）。輸出「顏色」和「係數」（顏色 1 的地方是 1，顏色 2 的地方是 0）
// @source "向量"
// @input c1 "顏色 1"
// @input c2 "顏色 2"
// @input in_scale "比例" tex_scale
// @output color "顏色"
// @output fac "係數"
// @param color1 color #cccccc "顏色 1"
// @param color2 color #333333 "顏色 2"
// @param tex_scale float 5 -1000000 1000000 "比例"
// @socket in - vector
// @socket in c1 color
// @socket in c2 color
// @socket out color color
// @socket out fac float

// Reimplementation of Blender's Checker Texture shader node as a compositor node: the sockets, settings and shader code are Blender's (gpu_shader_material_tex_checker.glsl), checked against Blender 5.2.
// Blender: https://github.com/blender/blender
// SPDX-FileCopyrightText: Blender Authors (original, GPL-2.0-or-later); KiaseCut
// SPDX-License-Identifier: GPL-3.0-or-later

#define M_PI 3.14159265358979323846
#define M_PI_2 1.57079632679489661923
#define M_SQRT2 1.41421356237309504880
#define M_1_PI 0.318309886183790671538
#define M_TAU 6.28318530717958647692
float length_squared(vec2 v) { return dot(v, v); }
float length_squared(vec3 v) { return dot(v, v); }
float length_squared(vec4 v) { return dot(v, v); }
float safe_divide(float a, float b) { return b != 0.0 ? a / b : 0.0; }
vec2 safe_divide(vec2 a, vec2 b) { return mix(vec2(0.0), a / b, notEqual(b, vec2(0.0))); }
vec3 safe_divide(vec3 a, vec3 b) { return mix(vec3(0.0), a / b, notEqual(b, vec3(0.0))); }
vec4 safe_divide(vec4 a, vec4 b) { return mix(vec4(0.0), a / b, notEqual(b, vec4(0.0))); }
vec2 safe_divide(vec2 a, float b) { return b != 0.0 ? a / b : vec2(0.0); }
vec3 safe_divide(vec3 a, float b) { return b != 0.0 ? a / b : vec3(0.0); }
vec4 safe_divide(vec4 a, float b) { return b != 0.0 ? a / b : vec4(0.0); }
#define FLT_MAX 3.402823466e+38
float compatible_mod(float a, float b) {
    if (b != 0.0) {
        int N = int(a / b);
        return a - N * b;
    }
    return 0.0;
}
vec2 compatible_mod(vec2 a, float b) { return vec2(compatible_mod(a.x, b), compatible_mod(a.y, b)); }
vec3 compatible_mod(vec3 a, float b) { return vec3(compatible_mod(a.x, b), compatible_mod(a.y, b), compatible_mod(a.z, b)); }
vec4 compatible_mod(vec4 a, float b) { return vec4(compatible_mod(a.x, b), compatible_mod(a.y, b), compatible_mod(a.z, b), compatible_mod(a.w, b)); }
vec3 uniform_coords(vec2 uv) {          // (Blender's Image Coordinates, uniform: the long side -1 to 1, y up, z 0 - what a texture node's unlinked Vector is)
    vec2 R = resolution, p = vec2(uv.x, 1.0 - uv.y) * R, q = floor(p) + 0.5;
    if (all(lessThan(abs(p - q), vec2(0.002)))) p = q;          // (drawn at the canvas size: the pixel's centre as Blender works it out, so a hash sees the very same numbers)
    return vec3((p - R / 2.0) / max(R.x, R.y) * 2.0, 0.0);
}
vec3 vector_in(vec2 uv) { return has_src() ? unpremultiply(src(uv)).rgb : uniform_coords(uv); }
float num(bool linked, vec4 c, float field) { return linked ? dot(c.rgb, vec3(0.2126, 0.7152, 0.0722)) * (c.a > 0.0 ? 1.0 : 0.0) : field; }
vec4 col(bool linked, vec4 c, vec4 field) { return linked ? unpremultiply(c) : field; }
vec4 grey(float f) { return vec4(vec3(f), 1.0); }

void node_tex_checker(
    vec3 co, vec4 color1, vec4 color2, float scale, out vec4 color, out float fac)
{
  vec3 p = co * scale;
  p = (p + 0.000001) * 0.999999;
  int xi = int(abs(floor(p.x)));
  int yi = int(abs(floor(p.y)));
  int zi = int(abs(floor(p.z)));
  bool check = (((xi % 2) == (yi % 2)) == bool((zi % 2)));
  color = check ? color1 : color2;
  fac = check ? 1.0 : 0.0;
}

vec4 effect(vec2 uv) {
    vec4 c, c1 = col(has_input_c1(), input_c1(uv), color1), c2 = col(has_input_c2(), input_c2(uv), color2);
    float f;
    node_tex_checker(vector_in(uv), c1, c2, num(has_input_in_scale(), input_in_scale(uv), tex_scale), c, f);
    return output_index == 1 ? grey(f) : premultiply(c);
}
