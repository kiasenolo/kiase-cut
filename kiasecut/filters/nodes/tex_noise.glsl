// @filter 雜訊紋理
// @category 紋理
// @description 節點用：照 Blender 的「雜訊紋理」節點：Perlin 雜訊疊出來的連貫雜訊。維度 1D 用 W、2D 用向量的 X Y、3D 用向量、4D 用向量加 W；類型：多重分形、脊狀多重分形、混合多重分形、fBM、異質地形。向量沒接線就用影像座標（統一：長邊 -1 到 1，Y 向上）。向量和各個數字都可以接別的節點（沒接就用欄位）。輸出「係數」（灰階）和「顏色」
// @source "向量"
// @input in_w "W" w
// @input in_scale "比例" tex_scale
// @input in_detail "細節" detail
// @input in_roughness "粗糙度" roughness
// @input in_lacunarity "間隙度" lacunarity
// @input in_offset "偏移" offset
// @input in_gain "增益" gain
// @input in_distortion "扭曲" distortion
// @output fac "係數"
// @output color "顏色"
// @param dims menu 2D "1D|2D|3D|4D" "維度"
// @param ntype menu fBM "多重分形|脊狀多重分形|混合多重分形|fBM|異質地形" "類型"
// @param normalized bool true "正規化"
// @param w float 0 -1000000 1000000 "W"
// @param tex_scale float 5 -1000000 1000000 "比例"
// @param detail float 2 0 15 "細節"
// @param roughness float 0.5 0 1 "粗糙度"
// @param lacunarity float 2 -1000000 1000000 "間隙度"
// @param offset float 0 -1000000 1000000 "偏移"
// @param gain float 1 -1000000 1000000 "增益"
// @param distortion float 0 -1000000 1000000 "扭曲"
// @show src dims != 1D
// @show w dims == 1D|4D
// @show in_w dims == 1D|4D
// @show offset ntype == 脊狀多重分形|混合多重分形|異質地形
// @show in_offset ntype == 脊狀多重分形|混合多重分形|異質地形
// @show gain ntype == 脊狀多重分形|混合多重分形
// @show in_gain ntype == 脊狀多重分形|混合多重分形
// @socket in - vector
// @socket out fac float
// @socket out color color

// Reimplementation of Blender's Noise Texture shader node as a compositor node: the sockets, settings and shader code are Blender's (gpu_shader_material_tex_noise.glsl, gpu_shader_material_fractal_noise.glsl, gpu_shader_material_noise.glsl, gpu_shader_common_hash.glsl), checked against Blender 5.2.
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
#define FLOORFRAC(x, x_int, x_fract) { float x_floor = floor(x); x_int = int(x_floor); x_fract = x - x_floor; }
float bi_mix(float v0, float v1, float v2, float v3, float x, float y)
{
  float x1 = 1.0 - x;
  return (1.0 - y) * (v0 * x1 + v1 * x) + y * (v2 * x1 + v3 * x);
}
float tri_mix(float v0,
              float v1,
              float v2,
              float v3,
              float v4,
              float v5,
              float v6,
              float v7,
              float x,
              float y,
              float z)
{
  float x1 = 1.0 - x;
  float y1 = 1.0 - y;
  float z1 = 1.0 - z;
  return z1 * (y1 * (v0 * x1 + v1 * x) + y * (v2 * x1 + v3 * x)) +
         z * (y1 * (v4 * x1 + v5 * x) + y * (v6 * x1 + v7 * x));
}
float quad_mix(float v0,
               float v1,
               float v2,
               float v3,
               float v4,
               float v5,
               float v6,
               float v7,
               float v8,
               float v9,
               float v10,
               float v11,
               float v12,
               float v13,
               float v14,
               float v15,
               float x,
               float y,
               float z,
               float w)
{
  return mix(tri_mix(v0, v1, v2, v3, v4, v5, v6, v7, x, y, z),
             tri_mix(v8, v9, v10, v11, v12, v13, v14, v15, x, y, z),
             w);
}
float fade(float t)
{
  return t * t * t * (t * (t * 6.0 - 15.0) + 10.0);
}
float negate_if(float value, uint condition)
{
  return (condition != 0u) ? -value : value;
}
float noise_grad(uint hash, float x)
{
  uint h = hash & 15u;
  float g = float(1u + (h & 7u));
  return negate_if(g, h & 8u) * x;
}
float noise_grad(uint hash, float x, float y)
{
  uint h = hash & 7u;
  float u = h < 4u ? x : y;
  float v = 2.0 * (h < 4u ? y : x);
  return negate_if(u, h & 1u) + negate_if(v, h & 2u);
}
float noise_grad(uint hash, float x, float y, float z)
{
  uint h = hash & 15u;
  float u = h < 8u ? x : y;
  float vt = ((h == 12u) || (h == 14u)) ? x : z;
  float v = h < 4u ? y : vt;
  return negate_if(u, h & 1u) + negate_if(v, h & 2u);
}
float noise_grad(uint hash, float x, float y, float z, float w)
{
  uint h = hash & 31u;
  float u = h < 24u ? x : y;
  float v = h < 16u ? y : z;
  float s = h < 8u ? z : w;
  return negate_if(u, h & 1u) + negate_if(v, h & 2u) + negate_if(s, h & 4u);
}
float noise_perlin(float x)
{
  int X;
  float fx;
  FLOORFRAC(x, X, fx);
  float u = fade(fx);
  float r = mix(noise_grad(hash_int(X), fx), noise_grad(hash_int(X + 1), fx - 1.0), u);
  return r;
}
float noise_perlin(vec2 vec)
{
  int X, Y;
  float fx, fy;
  FLOORFRAC(vec.x, X, fx);
  FLOORFRAC(vec.y, Y, fy);
  float u = fade(fx);
  float v = fade(fy);
  float r = bi_mix(noise_grad(hash_int2(X, Y), fx, fy),
                   noise_grad(hash_int2(X + 1, Y), fx - 1.0, fy),
                   noise_grad(hash_int2(X, Y + 1), fx, fy - 1.0),
                   noise_grad(hash_int2(X + 1, Y + 1), fx - 1.0, fy - 1.0),
                   u,
                   v);
  return r;
}
float noise_perlin(vec3 vec)
{
  int X, Y, Z;
  float fx, fy, fz;
  FLOORFRAC(vec.x, X, fx);
  FLOORFRAC(vec.y, Y, fy);
  FLOORFRAC(vec.z, Z, fz);
  float u = fade(fx);
  float v = fade(fy);
  float w = fade(fz);
  float r = tri_mix(noise_grad(hash_int3(X, Y, Z), fx, fy, fz),
                    noise_grad(hash_int3(X + 1, Y, Z), fx - 1.0, fy, fz),
                    noise_grad(hash_int3(X, Y + 1, Z), fx, fy - 1.0, fz),
                    noise_grad(hash_int3(X + 1, Y + 1, Z), fx - 1.0, fy - 1.0, fz),
                    noise_grad(hash_int3(X, Y, Z + 1), fx, fy, fz - 1.0),
                    noise_grad(hash_int3(X + 1, Y, Z + 1), fx - 1.0, fy, fz - 1.0),
                    noise_grad(hash_int3(X, Y + 1, Z + 1), fx, fy - 1.0, fz - 1.0),
                    noise_grad(hash_int3(X + 1, Y + 1, Z + 1), fx - 1.0, fy - 1.0, fz - 1.0),
                    u,
                    v,
                    w);
  return r;
}
float noise_perlin(vec4 vec)
{
  int X, Y, Z, W;
  float fx, fy, fz, fw;
  FLOORFRAC(vec.x, X, fx);
  FLOORFRAC(vec.y, Y, fy);
  FLOORFRAC(vec.z, Z, fz);
  FLOORFRAC(vec.w, W, fw);
  float u = fade(fx);
  float v = fade(fy);
  float t = fade(fz);
  float s = fade(fw);
  float r = quad_mix(
      noise_grad(hash_int4(X, Y, Z, W), fx, fy, fz, fw),
      noise_grad(hash_int4(X + 1, Y, Z, W), fx - 1.0, fy, fz, fw),
      noise_grad(hash_int4(X, Y + 1, Z, W), fx, fy - 1.0, fz, fw),
      noise_grad(hash_int4(X + 1, Y + 1, Z, W), fx - 1.0, fy - 1.0, fz, fw),
      noise_grad(hash_int4(X, Y, Z + 1, W), fx, fy, fz - 1.0, fw),
      noise_grad(hash_int4(X + 1, Y, Z + 1, W), fx - 1.0, fy, fz - 1.0, fw),
      noise_grad(hash_int4(X, Y + 1, Z + 1, W), fx, fy - 1.0, fz - 1.0, fw),
      noise_grad(hash_int4(X + 1, Y + 1, Z + 1, W), fx - 1.0, fy - 1.0, fz - 1.0, fw),
      noise_grad(hash_int4(X, Y, Z, W + 1), fx, fy, fz, fw - 1.0),
      noise_grad(hash_int4(X + 1, Y, Z, W + 1), fx - 1.0, fy, fz, fw - 1.0),
      noise_grad(hash_int4(X, Y + 1, Z, W + 1), fx, fy - 1.0, fz, fw - 1.0),
      noise_grad(hash_int4(X + 1, Y + 1, Z, W + 1), fx - 1.0, fy - 1.0, fz, fw - 1.0),
      noise_grad(hash_int4(X, Y, Z + 1, W + 1), fx, fy, fz - 1.0, fw - 1.0),
      noise_grad(hash_int4(X + 1, Y, Z + 1, W + 1), fx - 1.0, fy, fz - 1.0, fw - 1.0),
      noise_grad(hash_int4(X, Y + 1, Z + 1, W + 1), fx, fy - 1.0, fz - 1.0, fw - 1.0),
      noise_grad(
          hash_int4(X + 1, Y + 1, Z + 1, W + 1), fx - 1.0, fy - 1.0, fz - 1.0, fw - 1.0),
      u,
      v,
      t,
      s);
  return r;
}
float noise_scale1(float result)
{
  return 0.2500 * result;
}
float noise_scale2(float result)
{
  return 0.6616 * result;
}
float noise_scale3(float result)
{
  return 0.9820 * result;
}
float noise_scale4(float result)
{
  return 0.8344 * result;
}
float snoise(float p)
{
  float precision_correction = 0.5 * float(abs(p) >= 1000000.0);
  p = compatible_mod(p, 100000.0) + precision_correction;
  return noise_scale1(noise_perlin(p));
}
float noise(float p)
{
  return 0.5 * snoise(p) + 0.5;
}
float snoise(vec2 p)
{
  vec2 precision_correction = 0.5 * vec2(float(abs(p.x) >= 1000000.0),
                                              float(abs(p.y) >= 1000000.0));
  p = compatible_mod(p, 100000.0) + precision_correction;
  return noise_scale2(noise_perlin(p));
}
float noise(vec2 p)
{
  return 0.5 * snoise(p) + 0.5;
}
float snoise(vec3 p)
{
  vec3 precision_correction = 0.5 * vec3(float(abs(p.x) >= 1000000.0),
                                              float(abs(p.y) >= 1000000.0),
                                              float(abs(p.z) >= 1000000.0));
  p = compatible_mod(p, 100000.0) + precision_correction;
  return noise_scale3(noise_perlin(p));
}
float noise(vec3 p)
{
  return 0.5 * snoise(p) + 0.5;
}
float snoise(vec4 p)
{
  vec4 precision_correction = 0.5 * vec4(float(abs(p.x) >= 1000000.0),
                                              float(abs(p.y) >= 1000000.0),
                                              float(abs(p.z) >= 1000000.0),
                                              float(abs(p.w) >= 1000000.0));
  p = compatible_mod(p, 100000.0) + precision_correction;
  return noise_scale4(noise_perlin(p));
}
float noise(vec4 p)
{
  return 0.5 * snoise(p) + 0.5;
}
#define NOISE_FBM(T) \
  float noise_fbm(T co, \
                  float detail, \
                  float roughness, \
                  float lacunarity, \
                  float offset, \
                  float gain, \
                  bool normalize) \
  { \
    T p = co; \
    float fscale = 1.0; \
    float amp = 1.0; \
    float maxamp = 0.0; \
    float sum = 0.0; \
\
    for (int i = 0; i <= int(detail); i++) { \
      float t = snoise(fscale * p); \
      sum += t * amp; \
      maxamp += amp; \
      amp *= roughness; \
      fscale *= lacunarity; \
    } \
    float rmd = detail - floor(detail); \
    if (rmd != 0.0) { \
      float t = snoise(fscale * p); \
      float sum2 = sum + t * amp; \
      return normalize ? \
                 mix(0.5 * sum / maxamp + 0.5, 0.5 * sum2 / (maxamp + amp) + 0.5, rmd) : \
                 mix(sum, sum2, rmd); \
    } \
    else { \
      return normalize ? 0.5 * sum / maxamp + 0.5 : sum; \
    } \
  }
#define NOISE_MULTI_FRACTAL(T) \
  float noise_multi_fractal(T co, \
                            float detail, \
                            float roughness, \
                            float lacunarity, \
                            float offset, \
                            float gain, \
                            bool normalize) \
  { \
    T p = co; \
    float value = 1.0; \
    float pwr = 1.0; \
\
    for (int i = 0; i <= int(detail); i++) { \
      value *= (pwr * snoise(p) + 1.0); \
      pwr *= roughness; \
      p *= lacunarity; \
    } \
\
    float rmd = detail - floor(detail); \
    if (rmd != 0.0) { \
      value *= (rmd * pwr * snoise(p) + 1.0);                \
    } \
\
    return value; \
  }
#define NOISE_HETERO_TERRAIN(T) \
  float noise_hetero_terrain(T co, \
                             float detail, \
                             float roughness, \
                             float lacunarity, \
                             float offset, \
                             float gain, \
                             bool normalize) \
  { \
    T p = co; \
    float pwr = roughness; \
\
                                                                      \
    float value = offset + snoise(p); \
    p *= lacunarity; \
\
    for (int i = 1; i <= int(detail); i++) { \
      float increment = (snoise(p) + offset) * pwr * value; \
      value += increment; \
      pwr *= roughness; \
      p *= lacunarity; \
    } \
\
    float rmd = detail - floor(detail); \
    if (rmd != 0.0) { \
      float increment = (snoise(p) + offset) * pwr * value; \
      value += rmd * increment; \
    } \
\
    return value; \
  }
#define NOISE_HYBRID_MULTI_FRACTAL(T) \
  float noise_hybrid_multi_fractal(T co, \
                                   float detail, \
                                   float roughness, \
                                   float lacunarity, \
                                   float offset, \
                                   float gain, \
                                   bool normalize) \
  { \
    T p = co; \
    float pwr = 1.0; \
    float value = 0.0; \
    float weight = 1.0; \
\
    for (int i = 0; (weight > 0.001) && (i <= int(detail)); i++) { \
      if (weight > 1.0) { \
        weight = 1.0; \
      } \
\
      float signal = (snoise(p) + offset) * pwr; \
      pwr *= roughness; \
      value += weight * signal; \
      weight *= gain * signal; \
      p *= lacunarity; \
    } \
\
    float rmd = detail - floor(detail); \
    if ((rmd != 0.0) && (weight > 0.001)) { \
      if (weight > 1.0) { \
        weight = 1.0; \
      } \
      float signal = (snoise(p) + offset) * pwr; \
      value += rmd * weight * signal; \
    } \
\
    return value; \
  }
#define NOISE_RIDGED_MULTI_FRACTAL(T) \
  float noise_ridged_multi_fractal(T co, \
                                   float detail, \
                                   float roughness, \
                                   float lacunarity, \
                                   float offset, \
                                   float gain, \
                                   bool normalize) \
  { \
    T p = co; \
    float pwr = roughness; \
\
    float signal = offset - abs(snoise(p)); \
    signal *= signal; \
    float value = signal; \
    float weight = 1.0; \
\
    for (int i = 1; i <= int(detail); i++) { \
      p *= lacunarity; \
      weight = clamp(signal * gain, 0.0, 1.0); \
      signal = offset - abs(snoise(p)); \
      signal *= signal; \
      signal *= weight; \
      value += signal * pwr; \
      pwr *= roughness; \
    } \
\
    return value; \
  }
NOISE_FBM(float)
NOISE_FBM(vec2)
NOISE_FBM(vec3)
NOISE_FBM(vec4)
NOISE_MULTI_FRACTAL(float)
NOISE_MULTI_FRACTAL(vec2)
NOISE_MULTI_FRACTAL(vec3)
NOISE_MULTI_FRACTAL(vec4)
NOISE_HETERO_TERRAIN(float)
NOISE_HETERO_TERRAIN(vec2)
NOISE_HETERO_TERRAIN(vec3)
NOISE_HETERO_TERRAIN(vec4)
NOISE_HYBRID_MULTI_FRACTAL(float)
NOISE_HYBRID_MULTI_FRACTAL(vec2)
NOISE_HYBRID_MULTI_FRACTAL(vec3)
NOISE_HYBRID_MULTI_FRACTAL(vec4)
NOISE_RIDGED_MULTI_FRACTAL(float)
NOISE_RIDGED_MULTI_FRACTAL(vec2)
NOISE_RIDGED_MULTI_FRACTAL(vec3)
NOISE_RIDGED_MULTI_FRACTAL(vec4)
#define NOISE_FRACTAL_DISTORTED_1D(NOISE_TYPE) \
  if (distortion != 0.0) { \
    p += snoise(p + random_float_offset(0.0)) * distortion; \
  } \
\
  value = NOISE_TYPE(p, detail, roughness, lacunarity, offset, gain, normalize != 0.0); \
  if (compute_color != 0.0) { \
    color = vec4(value, \
                   NOISE_TYPE(p + random_float_offset(1.0), \
                              detail, \
                              roughness, \
                              lacunarity, \
                              offset, \
                              gain, \
                              normalize != 0.0), \
                   NOISE_TYPE(p + random_float_offset(2.0), \
                              detail, \
                              roughness, \
                              lacunarity, \
                              offset, \
                              gain, \
                              normalize != 0.0), \
                   1.0); \
  }
#define NOISE_FRACTAL_DISTORTED_2D(NOISE_TYPE) \
  if (distortion != 0.0) { \
    p += vec2(snoise(p + random_vec2_offset(0.0)) * distortion, \
                snoise(p + random_vec2_offset(1.0)) * distortion); \
  } \
\
  value = NOISE_TYPE(p, detail, roughness, lacunarity, offset, gain, normalize != 0.0); \
  if (compute_color != 0.0) { \
    color = vec4(value, \
                   NOISE_TYPE(p + random_vec2_offset(2.0), \
                              detail, \
                              roughness, \
                              lacunarity, \
                              offset, \
                              gain, \
                              normalize != 0.0), \
                   NOISE_TYPE(p + random_vec2_offset(3.0), \
                              detail, \
                              roughness, \
                              lacunarity, \
                              offset, \
                              gain, \
                              normalize != 0.0), \
                   1.0); \
  }
#define NOISE_FRACTAL_DISTORTED_3D(NOISE_TYPE) \
  if (distortion != 0.0) { \
    p += vec3(snoise(p + random_vec3_offset(0.0)) * distortion, \
                snoise(p + random_vec3_offset(1.0)) * distortion, \
                snoise(p + random_vec3_offset(2.0)) * distortion); \
  } \
\
  value = NOISE_TYPE(p, detail, roughness, lacunarity, offset, gain, normalize != 0.0); \
  if (compute_color != 0.0) { \
    color = vec4(value, \
                   NOISE_TYPE(p + random_vec3_offset(3.0), \
                              detail, \
                              roughness, \
                              lacunarity, \
                              offset, \
                              gain, \
                              normalize != 0.0), \
                   NOISE_TYPE(p + random_vec3_offset(4.0), \
                              detail, \
                              roughness, \
                              lacunarity, \
                              offset, \
                              gain, \
                              normalize != 0.0), \
                   1.0); \
  }
#define NOISE_FRACTAL_DISTORTED_4D(NOISE_TYPE) \
  if (distortion != 0.0) { \
    p += vec4(snoise(p + random_vec4_offset(0.0)) * distortion, \
                snoise(p + random_vec4_offset(1.0)) * distortion, \
                snoise(p + random_vec4_offset(2.0)) * distortion, \
                snoise(p + random_vec4_offset(3.0)) * distortion); \
  } \
\
  value = NOISE_TYPE(p, detail, roughness, lacunarity, offset, gain, normalize != 0.0); \
  if (compute_color != 0.0) { \
    color = vec4(value, \
                   NOISE_TYPE(p + random_vec4_offset(4.0), \
                              detail, \
                              roughness, \
                              lacunarity, \
                              offset, \
                              gain, \
                              normalize != 0.0), \
                   NOISE_TYPE(p + random_vec4_offset(5.0), \
                              detail, \
                              roughness, \
                              lacunarity, \
                              offset, \
                              gain, \
                              normalize != 0.0), \
                   1.0); \
  }
float random_float_offset(float seed)
{
  return 100.0 + hash_float_to_float(seed) * 100.0;
}
vec2 random_vec2_offset(float seed)
{
  return vec2(100.0 + hash_vec2_to_float(vec2(seed, 0.0)) * 100.0,
                100.0 + hash_vec2_to_float(vec2(seed, 1.0)) * 100.0);
}
vec3 random_vec3_offset(float seed)
{
  return vec3(100.0 + hash_vec2_to_float(vec2(seed, 0.0)) * 100.0,
                100.0 + hash_vec2_to_float(vec2(seed, 1.0)) * 100.0,
                100.0 + hash_vec2_to_float(vec2(seed, 2.0)) * 100.0);
}
vec4 random_vec4_offset(float seed)
{
  return vec4(100.0 + hash_vec2_to_float(vec2(seed, 0.0)) * 100.0,
                100.0 + hash_vec2_to_float(vec2(seed, 1.0)) * 100.0,
                100.0 + hash_vec2_to_float(vec2(seed, 2.0)) * 100.0,
                100.0 + hash_vec2_to_float(vec2(seed, 3.0)) * 100.0);
}
void node_noise_tex_fbm_1d(vec3 co,
                           float w,
                           float scale,
                           float detail,
                           float roughness,
                           float lacunarity,
                           float offset,
                           float gain,
                           float distortion,
                           float normalize,
                           float compute_color,
                           out float value,
                           out vec4 color)
{
  detail = clamp(detail, 0.0, 15.0);
  roughness = max(roughness, 0.0);
  float p = w * scale;
  NOISE_FRACTAL_DISTORTED_1D(noise_fbm)
}
void node_noise_tex_fbm_2d(vec3 co,
                           float w,
                           float scale,
                           float detail,
                           float roughness,
                           float lacunarity,
                           float offset,
                           float gain,
                           float distortion,
                           float normalize,
                           float compute_color,
                           out float value,
                           out vec4 color)
{
  detail = clamp(detail, 0.0, 15.0);
  roughness = max(roughness, 0.0);
  vec2 p = co.xy * scale;
  NOISE_FRACTAL_DISTORTED_2D(noise_fbm)
}
void node_noise_tex_fbm_3d(vec3 co,
                           float w,
                           float scale,
                           float detail,
                           float roughness,
                           float lacunarity,
                           float offset,
                           float gain,
                           float distortion,
                           float normalize,
                           float compute_color,
                           out float value,
                           out vec4 color)
{
  detail = clamp(detail, 0.0, 15.0);
  roughness = max(roughness, 0.0);
  vec3 p = co * scale;
  NOISE_FRACTAL_DISTORTED_3D(noise_fbm)
}
void node_noise_tex_fbm_4d(vec3 co,
                           float w,
                           float scale,
                           float detail,
                           float roughness,
                           float lacunarity,
                           float offset,
                           float gain,
                           float distortion,
                           float normalize,
                           float compute_color,
                           out float value,
                           out vec4 color)
{
  detail = clamp(detail, 0.0, 15.0);
  roughness = max(roughness, 0.0);
  vec4 p = vec4(co, w) * scale;
  NOISE_FRACTAL_DISTORTED_4D(noise_fbm)
}
void node_noise_tex_multi_fractal_1d(vec3 co,
                                     float w,
                                     float scale,
                                     float detail,
                                     float roughness,
                                     float lacunarity,
                                     float offset,
                                     float gain,
                                     float distortion,
                                     float normalize,
                                     float compute_color,
                                     out float value,
                                     out vec4 color)
{
  detail = clamp(detail, 0.0, 15.0);
  roughness = max(roughness, 0.0);
  float p = w * scale;
  NOISE_FRACTAL_DISTORTED_1D(noise_multi_fractal)
}
void node_noise_tex_multi_fractal_2d(vec3 co,
                                     float w,
                                     float scale,
                                     float detail,
                                     float roughness,
                                     float lacunarity,
                                     float offset,
                                     float gain,
                                     float distortion,
                                     float normalize,
                                     float compute_color,
                                     out float value,
                                     out vec4 color)
{
  detail = clamp(detail, 0.0, 15.0);
  roughness = max(roughness, 0.0);
  vec2 p = co.xy * scale;
  NOISE_FRACTAL_DISTORTED_2D(noise_multi_fractal)
}
void node_noise_tex_multi_fractal_3d(vec3 co,
                                     float w,
                                     float scale,
                                     float detail,
                                     float roughness,
                                     float lacunarity,
                                     float offset,
                                     float gain,
                                     float distortion,
                                     float normalize,
                                     float compute_color,
                                     out float value,
                                     out vec4 color)
{
  detail = clamp(detail, 0.0, 15.0);
  roughness = max(roughness, 0.0);
  vec3 p = co * scale;
  NOISE_FRACTAL_DISTORTED_3D(noise_multi_fractal)
}
void node_noise_tex_multi_fractal_4d(vec3 co,
                                     float w,
                                     float scale,
                                     float detail,
                                     float roughness,
                                     float lacunarity,
                                     float offset,
                                     float gain,
                                     float distortion,
                                     float normalize,
                                     float compute_color,
                                     out float value,
                                     out vec4 color)
{
  detail = clamp(detail, 0.0, 15.0);
  roughness = max(roughness, 0.0);
  vec4 p = vec4(co, w) * scale;
  NOISE_FRACTAL_DISTORTED_4D(noise_multi_fractal)
}
void node_noise_tex_hetero_terrain_1d(vec3 co,
                                      float w,
                                      float scale,
                                      float detail,
                                      float roughness,
                                      float lacunarity,
                                      float offset,
                                      float gain,
                                      float distortion,
                                      float normalize,
                                      float compute_color,
                                      out float value,
                                      out vec4 color)
{
  detail = clamp(detail, 0.0, 15.0);
  roughness = max(roughness, 0.0);
  float p = w * scale;
  NOISE_FRACTAL_DISTORTED_1D(noise_hetero_terrain)
}
void node_noise_tex_hetero_terrain_2d(vec3 co,
                                      float w,
                                      float scale,
                                      float detail,
                                      float roughness,
                                      float lacunarity,
                                      float offset,
                                      float gain,
                                      float distortion,
                                      float normalize,
                                      float compute_color,
                                      out float value,
                                      out vec4 color)
{
  detail = clamp(detail, 0.0, 15.0);
  roughness = max(roughness, 0.0);
  vec2 p = co.xy * scale;
  NOISE_FRACTAL_DISTORTED_2D(noise_hetero_terrain)
}
void node_noise_tex_hetero_terrain_3d(vec3 co,
                                      float w,
                                      float scale,
                                      float detail,
                                      float roughness,
                                      float lacunarity,
                                      float offset,
                                      float gain,
                                      float distortion,
                                      float normalize,
                                      float compute_color,
                                      out float value,
                                      out vec4 color)
{
  detail = clamp(detail, 0.0, 15.0);
  roughness = max(roughness, 0.0);
  vec3 p = co * scale;
  NOISE_FRACTAL_DISTORTED_3D(noise_hetero_terrain)
}
void node_noise_tex_hetero_terrain_4d(vec3 co,
                                      float w,
                                      float scale,
                                      float detail,
                                      float roughness,
                                      float lacunarity,
                                      float offset,
                                      float gain,
                                      float distortion,
                                      float normalize,
                                      float compute_color,
                                      out float value,
                                      out vec4 color)
{
  detail = clamp(detail, 0.0, 15.0);
  roughness = max(roughness, 0.0);
  vec4 p = vec4(co, w) * scale;
  NOISE_FRACTAL_DISTORTED_4D(noise_hetero_terrain)
}
void node_noise_tex_hybrid_multi_fractal_1d(vec3 co,
                                            float w,
                                            float scale,
                                            float detail,
                                            float roughness,
                                            float lacunarity,
                                            float offset,
                                            float gain,
                                            float distortion,
                                            float normalize,
                                            float compute_color,
                                            out float value,
                                            out vec4 color)
{
  detail = clamp(detail, 0.0, 15.0);
  roughness = max(roughness, 0.0);
  float p = w * scale;
  NOISE_FRACTAL_DISTORTED_1D(noise_hybrid_multi_fractal)
}
void node_noise_tex_hybrid_multi_fractal_2d(vec3 co,
                                            float w,
                                            float scale,
                                            float detail,
                                            float roughness,
                                            float lacunarity,
                                            float offset,
                                            float gain,
                                            float distortion,
                                            float normalize,
                                            float compute_color,
                                            out float value,
                                            out vec4 color)
{
  detail = clamp(detail, 0.0, 15.0);
  roughness = max(roughness, 0.0);
  vec2 p = co.xy * scale;
  NOISE_FRACTAL_DISTORTED_2D(noise_hybrid_multi_fractal)
}
void node_noise_tex_hybrid_multi_fractal_3d(vec3 co,
                                            float w,
                                            float scale,
                                            float detail,
                                            float roughness,
                                            float lacunarity,
                                            float offset,
                                            float gain,
                                            float distortion,
                                            float normalize,
                                            float compute_color,
                                            out float value,
                                            out vec4 color)
{
  detail = clamp(detail, 0.0, 15.0);
  roughness = max(roughness, 0.0);
  vec3 p = co * scale;
  NOISE_FRACTAL_DISTORTED_3D(noise_hybrid_multi_fractal)
}
void node_noise_tex_hybrid_multi_fractal_4d(vec3 co,
                                            float w,
                                            float scale,
                                            float detail,
                                            float roughness,
                                            float lacunarity,
                                            float offset,
                                            float gain,
                                            float distortion,
                                            float normalize,
                                            float compute_color,
                                            out float value,
                                            out vec4 color)
{
  detail = clamp(detail, 0.0, 15.0);
  roughness = max(roughness, 0.0);
  vec4 p = vec4(co, w) * scale;
  NOISE_FRACTAL_DISTORTED_4D(noise_hybrid_multi_fractal)
}
void node_noise_tex_ridged_multi_fractal_1d(vec3 co,
                                            float w,
                                            float scale,
                                            float detail,
                                            float roughness,
                                            float lacunarity,
                                            float offset,
                                            float gain,
                                            float distortion,
                                            float normalize,
                                            float compute_color,
                                            out float value,
                                            out vec4 color)
{
  detail = clamp(detail, 0.0, 15.0);
  roughness = max(roughness, 0.0);
  float p = w * scale;
  NOISE_FRACTAL_DISTORTED_1D(noise_ridged_multi_fractal)
}
void node_noise_tex_ridged_multi_fractal_2d(vec3 co,
                                            float w,
                                            float scale,
                                            float detail,
                                            float roughness,
                                            float lacunarity,
                                            float offset,
                                            float gain,
                                            float distortion,
                                            float normalize,
                                            float compute_color,
                                            out float value,
                                            out vec4 color)
{
  detail = clamp(detail, 0.0, 15.0);
  roughness = max(roughness, 0.0);
  vec2 p = co.xy * scale;
  NOISE_FRACTAL_DISTORTED_2D(noise_ridged_multi_fractal)
}
void node_noise_tex_ridged_multi_fractal_3d(vec3 co,
                                            float w,
                                            float scale,
                                            float detail,
                                            float roughness,
                                            float lacunarity,
                                            float offset,
                                            float gain,
                                            float distortion,
                                            float normalize,
                                            float compute_color,
                                            out float value,
                                            out vec4 color)
{
  detail = clamp(detail, 0.0, 15.0);
  roughness = max(roughness, 0.0);
  vec3 p = co * scale;
  NOISE_FRACTAL_DISTORTED_3D(noise_ridged_multi_fractal)
}
void node_noise_tex_ridged_multi_fractal_4d(vec3 co,
                                            float w,
                                            float scale,
                                            float detail,
                                            float roughness,
                                            float lacunarity,
                                            float offset,
                                            float gain,
                                            float distortion,
                                            float normalize,
                                            float compute_color,
                                            out float value,
                                            out vec4 color)
{
  detail = clamp(detail, 0.0, 15.0);
  roughness = max(roughness, 0.0);
  vec4 p = vec4(co, w) * scale;
  NOISE_FRACTAL_DISTORTED_4D(noise_ridged_multi_fractal)
}

// (the settings pick one of the twenty functions: a type and a dimension)
#define NOISE_ARGS co, ww, sc, dt, rg, lc, of, gn, ds, nm, cc, value, color
#define NOISE_DIM(F) { if (dims == 0) F##_1d(NOISE_ARGS); else if (dims == 1) F##_2d(NOISE_ARGS); else if (dims == 2) F##_3d(NOISE_ARGS); else F##_4d(NOISE_ARGS); }

vec4 effect(vec2 uv) {
    vec3 co = vector_in(uv);
    float ww = num(has_input_in_w(), input_in_w(uv), w), sc = num(has_input_in_scale(), input_in_scale(uv), tex_scale);
    float dt = num(has_input_in_detail(), input_in_detail(uv), detail), rg = num(has_input_in_roughness(), input_in_roughness(uv), roughness);
    float lc = num(has_input_in_lacunarity(), input_in_lacunarity(uv), lacunarity), of = num(has_input_in_offset(), input_in_offset(uv), offset);
    float gn = num(has_input_in_gain(), input_in_gain(uv), gain), ds = num(has_input_in_distortion(), input_in_distortion(uv), distortion);
    float nm = normalized ? 1.0 : 0.0, cc = output_index == 1 ? 1.0 : 0.0, value = 0.0;
    vec4 color = vec4(0.0, 0.0, 0.0, 1.0);
    if (ntype == 0) NOISE_DIM(node_noise_tex_multi_fractal)
    else if (ntype == 1) NOISE_DIM(node_noise_tex_ridged_multi_fractal)
    else if (ntype == 2) NOISE_DIM(node_noise_tex_hybrid_multi_fractal)
    else if (ntype == 3) NOISE_DIM(node_noise_tex_fbm)
    else NOISE_DIM(node_noise_tex_hetero_terrain)
    return output_index == 0 ? grey(value) : color;
}
