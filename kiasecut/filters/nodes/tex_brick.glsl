// @filter 磚塊紋理
// @category 紋理
// @description 節點用：照 Blender 的「磚塊紋理」節點：一排排錯開的磚，磚縫可以調粗細和柔邊。向量沒接線就用影像座標。向量、三個顏色和各個數字都可以接別的節點（沒接就用欄位）。輸出「顏色」和「係數」（磚縫的地方是 1）
// @source "向量"
// @input c1 "顏色 1"
// @input c2 "顏色 2"
// @input cm "磚縫"
// @input in_scale "比例" tex_scale
// @input in_msize "磚縫大小" mortar_size
// @input in_msmooth "磚縫柔邊" mortar_smooth
// @input in_bias "偏向" bias
// @input in_width "磚寬" brick_width
// @input in_height "列高" row_height
// @output color "顏色"
// @output fac "係數"
// @param color1 color #cccccc "顏色 1"
// @param color2 color #333333 "顏色 2"
// @param mortar color #000000 "磚縫"
// @param tex_scale float 5 -1000000 1000000 "比例"
// @param mortar_size float 0.02 0 0.125 "磚縫大小"
// @param mortar_smooth float 0.1 0 1 "磚縫柔邊"
// @param bias float 0 -1 1 "偏向"
// @param brick_width float 0.5 0.01 100 "磚寬"
// @param row_height float 0.25 0.01 100 "列高"
// @param offset_amount float 0.5 0 1 "錯位"
// @param offset_freq int 2 1 99 "錯位間隔"
// @param squash float 1 0 99 "壓縮"
// @param squash_freq int 2 1 99 "壓縮間隔"
// @socket in - vector
// @socket in c1 color
// @socket in c2 color
// @socket in cm color
// @socket out color color
// @socket out fac float

// Reimplementation of Blender's Brick Texture shader node as a compositor node: the sockets, settings and shader code are Blender's (gpu_shader_material_tex_brick.glsl), checked against Blender 5.2.
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

#define rot(x, k) (((x) << (k)) | ((x) >> (32 - (k))))
#define mix(a, b, c) \
  { \
    a -= c; \
    a ^= rot(c, 4); \
    c += b; \
    b -= a; \
    b ^= rot(a, 6); \
    a += c; \
    c -= b; \
    c ^= rot(b, 8); \
    b += a; \
    a -= c; \
    a ^= rot(c, 16); \
    c += b; \
    b -= a; \
    b ^= rot(a, 19); \
    a += c; \
    c -= b; \
    c ^= rot(b, 4); \
    b += a; \
  }
#define final(a, b, c) \
  { \
    c ^= b; \
    c -= rot(b, 14); \
    a ^= c; \
    a -= rot(c, 11); \
    b ^= a; \
    b -= rot(a, 25); \
    c ^= b; \
    c -= rot(b, 16); \
    a ^= c; \
    a -= rot(c, 4); \
    b ^= a; \
    b -= rot(a, 14); \
    c ^= b; \
    c -= rot(b, 24); \
  }
uint hash_uint(uint kx)
{
  uint a, b, c;
  a = b = c = 0xdeadbeefu + (1u << 2u) + 13u;
  a += kx;
  final(a, b, c);
  return c;
}
uint hash_uint2(uint kx, uint ky)
{
  uint a, b, c;
  a = b = c = 0xdeadbeefu + (2u << 2u) + 13u;
  b += ky;
  a += kx;
  final(a, b, c);
  return c;
}
uint hash_uint3(uint kx, uint ky, uint kz)
{
  uint a, b, c;
  a = b = c = 0xdeadbeefu + (3u << 2u) + 13u;
  c += kz;
  b += ky;
  a += kx;
  final(a, b, c);
  return c;
}
uint hash_uint4(uint kx, uint ky, uint kz, uint kw)
{
  uint a, b, c;
  a = b = c = 0xdeadbeefu + (4u << 2u) + 13u;
  a += kx;
  b += ky;
  c += kz;
  mix(a, b, c);
  a += kw;
  final(a, b, c);
  return c;
}
#undef rot
#undef final
#undef mix
uint hash_int(int kx)
{
  return hash_uint(uint(kx));
}
uint hash_int2(int kx, int ky)
{
  return hash_uint2(uint(kx), uint(ky));
}
uint hash_int3(int kx, int ky, int kz)
{
  return hash_uint3(uint(kx), uint(ky), uint(kz));
}
uint hash_int4(int kx, int ky, int kz, int kw)
{
  return hash_uint4(uint(kx), uint(ky), uint(kz), uint(kw));
}
ivec2 hash_pcg2d_i(ivec2 v)
{
  v = v * 1664525 + 1013904223;
  v.x += v.y * 1664525;
  v.y += v.x * 1664525;
  v = v ^ (v >> 16);
  v.x += v.y * 1664525;
  v.y += v.x * 1664525;
  return v;
}
ivec3 hash_pcg3d_i(ivec3 v)
{
  v = v * 1664525 + 1013904223;
  v.x += v.y * v.z;
  v.y += v.z * v.x;
  v.z += v.x * v.y;
  v = v ^ (v >> 16);
  v.x += v.y * v.z;
  v.y += v.z * v.x;
  v.z += v.x * v.y;
  return v;
}
ivec4 hash_pcg4d_i(ivec4 v)
{
  v = v * 1664525 + 1013904223;
  v.x += v.y * v.w;
  v.y += v.z * v.x;
  v.z += v.x * v.y;
  v.w += v.y * v.z;
  v = v ^ (v >> 16);
  v.x += v.y * v.w;
  v.y += v.z * v.x;
  v.z += v.x * v.y;
  v.w += v.y * v.z;
  return v;
}
float hash_uint_to_float(uint kx)
{
  return float(hash_uint(kx)) / float(0xFFFFFFFFu);
}
float hash_uint2_to_float(uint kx, uint ky)
{
  return float(hash_uint2(kx, ky)) / float(0xFFFFFFFFu);
}
float hash_uint3_to_float(uint kx, uint ky, uint kz)
{
  return float(hash_uint3(kx, ky, kz)) / float(0xFFFFFFFFu);
}
float hash_uint4_to_float(uint kx, uint ky, uint kz, uint kw)
{
  return float(hash_uint4(kx, ky, kz, kw)) / float(0xFFFFFFFFu);
}
float hash_float_to_float(float k)
{
  return hash_uint_to_float(floatBitsToUint(k));
}
float hash_vec2_to_float(vec2 k)
{
  return hash_uint2_to_float(floatBitsToUint(k.x), floatBitsToUint(k.y));
}
float hash_vec3_to_float(vec3 k)
{
  return hash_uint3_to_float(floatBitsToUint(k.x), floatBitsToUint(k.y), floatBitsToUint(k.z));
}
float hash_vec4_to_float(vec4 k)
{
  return hash_uint4_to_float(
      floatBitsToUint(k.x), floatBitsToUint(k.y), floatBitsToUint(k.z), floatBitsToUint(k.w));
}
vec2 hash_vec2_to_vec2(vec2 k)
{
  return vec2(hash_vec2_to_float(k), hash_vec3_to_float(vec3(k, 1.0)));
}
vec3 hash_vec3_to_vec3(vec3 k)
{
  return vec3(hash_vec3_to_float(k),
                hash_vec4_to_float(vec4(k, 1.0)),
                hash_vec4_to_float(vec4(k, 2.0)));
}
vec4 hash_vec4_to_vec4(vec4 k)
{
  return vec4(hash_vec4_to_float(k.xyzw),
                hash_vec4_to_float(k.wxyz),
                hash_vec4_to_float(k.zwxy),
                hash_vec4_to_float(k.yzwx));
}
vec2 hash_int2_to_vec2(ivec2 k)
{
  ivec2 h = hash_pcg2d_i(k);
  return vec2(h & 0x7fffffff) * (1.0 / float(0x7fffffff));
}
vec3 hash_int3_to_vec3(ivec3 k)
{
  ivec3 h = hash_pcg3d_i(k);
  return vec3(h & 0x7fffffff) * (1.0 / float(0x7fffffff));
}
vec4 hash_int4_to_vec4(ivec4 k)
{
  ivec4 h = hash_pcg4d_i(k);
  return vec4(h & 0x7fffffff) * (1.0 / float(0x7fffffff));
}
vec3 hash_int2_to_vec3(ivec2 k)
{
  return hash_int3_to_vec3(ivec3(k.x, k.y, 0));
}
vec3 hash_int4_to_vec3(ivec4 k)
{
  return hash_int4_to_vec4(k).xyz;
}
vec3 hash_float_to_vec3(float k)
{
  return vec3(hash_float_to_float(k),
                hash_vec2_to_float(vec2(k, 1.0)),
                hash_vec2_to_float(vec2(k, 2.0)));
}
vec3 hash_vec2_to_vec3(vec2 k)
{
  return vec3(hash_vec2_to_float(k),
                hash_vec3_to_float(vec3(k, 1.0)),
                hash_vec3_to_float(vec3(k, 2.0)));
}
vec3 hash_vec4_to_vec3(vec4 k)
{
  return vec3(
      hash_vec4_to_float(k.xyzw), hash_vec4_to_float(k.zxwy), hash_vec4_to_float(k.wzyx));
}
vec2 hash_float_to_vec2(float k)
{
  return vec2(hash_float_to_float(k), hash_vec2_to_float(vec2(k, 1.0)));
}
vec2 hash_vec3_to_vec2(vec3 k)
{
  return vec2(hash_vec3_to_float(k.xyz), hash_vec3_to_float(k.zxy));
}
vec2 hash_vec4_to_vec2(vec4 k)
{
  return vec2(hash_vec4_to_float(k.xyzw), hash_vec4_to_float(k.zxwy));
}
float integer_noise(int n)
{
  uint nn;
  nn = (uint(n) + 1013u) & 0x7fffffffu;
  nn = (nn >> 13u) ^ nn;
  nn = (uint(nn * (nn * nn * 60493u + 19990303u)) + 1376312589u) & 0x7fffffffu;
  return 0.5 * (float(nn) / 1073741824.0);
}
float wang_hash_noise(uint s)
{
  s = (s ^ 61u) ^ (s >> 16u);
  s *= 9u;
  s = s ^ (s >> 4u);
  s *= 0x27d4eb2du;
  s = s ^ (s >> 15u);
  return fract(float(s) / 4294967296.0);
}
vec2 calc_brick_texture(vec3 p,
                          float mortar_size,
                          float mortar_smooth,
                          float bias,
                          float brick_width,
                          float row_height,
                          float offset_amount,
                          int offset_frequency,
                          float squash_amount,
                          int squash_frequency)
{
  int bricknum, rownum;
  float offset = 0.0;
  float x, y;
  rownum = int(floor(p.y / row_height));
  if (offset_frequency != 0 && squash_frequency != 0) {
    brick_width *= ((rownum - (rownum / squash_frequency) * squash_frequency) != 0) ? 1.0 : squash_amount;
    offset = ((rownum - (rownum / offset_frequency) * offset_frequency) != 0) ? 0.0 : (brick_width * offset_amount);
  }
  bricknum = int(floor((p.x + offset) / brick_width));
  x = (p.x + offset) - brick_width * bricknum;
  y = p.y - row_height * rownum;
  float tint = clamp((integer_noise((rownum << 16) + (bricknum & 0xFFFF)) + bias), 0.0, 1.0);
  float min_dist = min(min(x, y), min(brick_width - x, row_height - y));
  if (min_dist >= mortar_size) {
    return vec2(tint, 0.0);
  }
  else if (mortar_smooth == 0.0) {
    return vec2(tint, 1.0);
  }
  else {
    min_dist = 1.0 - min_dist / mortar_size;
    return vec2(tint, smoothstep(0.0, mortar_smooth, min_dist));
  }
}
void node_tex_brick(vec3 co,
                    vec4 color1,
                    vec4 color2,
                    vec4 mortar,
                    float scale,
                    float mortar_size,
                    float mortar_smooth,
                    float bias,
                    float brick_width,
                    float row_height,
                    float offset_amount,
                    float offset_frequency,
                    float squash_amount,
                    float squash_frequency,
                    out vec4 color,
                    out float fac)
{
  vec2 f2 = calc_brick_texture(co * scale,
                                 mortar_size,
                                 mortar_smooth,
                                 bias,
                                 brick_width,
                                 row_height,
                                 offset_amount,
                                 int(offset_frequency),
                                 squash_amount,
                                 int(squash_frequency));
  float tint = f2.x;
  float f = f2.y;
  if (f != 1.0) {
    float facm = 1.0 - tint;
    color1 = facm * color1 + tint * color2;
  }
  color = mix(color1, mortar, f);
  fac = f;
}

vec4 effect(vec2 uv) {
    vec4 c, c1 = col(has_input_c1(), input_c1(uv), color1), c2 = col(has_input_c2(), input_c2(uv), color2), cm = col(has_input_cm(), input_cm(uv), mortar);
    float f;
    node_tex_brick(vector_in(uv), c1, c2, cm,
                   num(has_input_in_scale(), input_in_scale(uv), tex_scale), num(has_input_in_msize(), input_in_msize(uv), mortar_size),
                   num(has_input_in_msmooth(), input_in_msmooth(uv), mortar_smooth), num(has_input_in_bias(), input_in_bias(uv), bias),
                   num(has_input_in_width(), input_in_width(uv), brick_width), num(has_input_in_height(), input_in_height(uv), row_height),
                   offset_amount, float(offset_freq), squash, float(squash_freq), c, f);
    return output_index == 1 ? grey(f) : premultiply(c);
}
