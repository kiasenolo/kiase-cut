// @filter 漸層紋理
// @category 紋理
// @description 節點用：照 Blender 的「漸層紋理」節點：依向量算出 0 到 1 的漸層。類型：線性、二次、平滑、對角、球形、二次球形、放射。向量沒接線就用影像座標（統一：長邊 -1 到 1，中心是原點，Y 向上），所以線性漸層從畫面中間才開始。輸出「顏色」（灰階）和「係數」
// @source "向量"
// @output color "顏色"
// @output fac "係數"
// @param gtype menu 線性 "線性|二次|平滑|對角|球形|二次球形|放射" "類型"

// Reimplementation of Blender's Gradient Texture shader node as a compositor node: the sockets, settings and shader code are Blender's (gpu_shader_material_tex_gradient.glsl), checked against Blender 5.2.
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

float calc_gradient(vec3 p, int gradient_type)
{
  float x, y, z;
  x = p.x;
  y = p.y;
  z = p.z;
  if (gradient_type == 0) {
    return x;
  }
  else if (gradient_type == 1) {
    float r = max(x, 0.0);
    return r * r;
  }
  else if (gradient_type == 2) {
    float r = min(max(x, 0.0), 1.0);
    float t = r * r;
    return (3.0 * t - 2.0 * t * r);
  }
  else if (gradient_type == 3) {
    return (x + y) * 0.5;
  }
  else if (gradient_type == 4) {
    return atan(y, x) / (M_PI * 2) + 0.5;
  }
  else {
    float r = max(0.999999 - sqrt(x * x + y * y + z * z), 0.0);
    if (gradient_type == 5) {
      return r * r;
    }
    else if (gradient_type == 6) {
      return r;
    }
  }
  return 0.0;
}
void node_tex_gradient(vec3 co, float gradient_type, out vec4 color, out float fac)
{
  float f = calc_gradient(co, int(gradient_type));
  f = clamp(f, 0.0, 1.0);
  color = vec4(f, f, f, 1.0);
  fac = f;
}

// (the menu is in Blender's order; the shader numbers them linear, quadratic, easing, diagonal, radial, quadratic sphere, spherical)
const int GRADIENT_TYPE[7] = int[7](0, 1, 2, 3, 6, 5, 4);

vec4 effect(vec2 uv) {
    vec4 c;
    float f;
    node_tex_gradient(vector_in(uv), float(GRADIENT_TYPE[gtype]), c, f);
    return output_index == 1 ? grey(f) : c;
}
