// @filter Voronoi 紋理
// @category 紋理
// @description 節點用：照 Blender 的「Voronoi 紋理」節點：隨機點把畫面切成一塊一塊的細胞。維度 1D 用 W、2D 用向量的 X Y、3D 用向量、4D 用向量加 W；特徵：F1（最近的點）、F2（第二近）、平滑 F1、到邊緣距離、N 球半徑；距離算法：歐幾里得、曼哈頓、切比雪夫、閔可夫斯基。向量沒接線就用影像座標。輸出「距離」、「顏色」、「位置」、「W」和「半徑」（依特徵和維度，只顯示用得到的）
// @source "向量"
// @input in_w "W" w
// @input in_scale "比例" tex_scale
// @input in_detail "細節" detail
// @input in_roughness "粗糙度" roughness
// @input in_lacunarity "間隙度" lacunarity
// @input in_smooth "平滑度" smoothness
// @input in_exponent "指數" exponent
// @input in_random "隨機性" randomness
// @output distance "距離"
// @output color "顏色"
// @output position "位置"
// @output wout "W"
// @output radius "半徑"
// @param dims menu 2D "1D|2D|3D|4D" "維度"
// @param metric menu 歐幾里得 "歐幾里得|曼哈頓|切比雪夫|閔可夫斯基" "距離"
// @param feature menu F1 "F1|F2|平滑 F1|到邊緣距離|N 球半徑" "特徵"
// @param normalized bool false "正規化"
// @param w float 0 -1000000 1000000 "W"
// @param tex_scale float 5 -1000000 1000000 "比例"
// @param detail float 0 0 15 "細節"
// @param roughness float 0.5 0 1 "粗糙度"
// @param lacunarity float 2 -1000000 1000000 "間隙度"
// @param smoothness float 1 0 1 "平滑度"
// @param exponent float 0.5 0 1000000 "指數"
// @param randomness float 1 0 1 "隨機性"
// @show src dims != 1D
// @show w dims == 1D|4D
// @show in_w dims == 1D|4D
// @show metric dims != 1D
// @show metric feature == F1|F2|平滑 F1
// @show exponent dims != 1D
// @show exponent metric == 閔可夫斯基
// @show exponent feature == F1|F2|平滑 F1
// @show in_exponent dims != 1D
// @show in_exponent metric == 閔可夫斯基
// @show in_exponent feature == F1|F2|平滑 F1
// @show detail feature != N 球半徑
// @show in_detail feature != N 球半徑
// @show roughness feature != N 球半徑
// @show in_roughness feature != N 球半徑
// @show lacunarity feature != N 球半徑
// @show in_lacunarity feature != N 球半徑
// @show smoothness feature == 平滑 F1
// @show in_smooth feature == 平滑 F1
// @show normalized feature == F1|F2|平滑 F1
// @show distance feature != N 球半徑
// @show color feature == F1|F2|平滑 F1
// @show position feature == F1|F2|平滑 F1
// @show wout dims == 1D|4D
// @show wout feature == F1|F2|平滑 F1
// @show radius feature == N 球半徑

// Reimplementation of Blender's Voronoi Texture shader node as a compositor node: the sockets, settings and shader code are Blender's (gpu_shader_material_tex_voronoi.glsl, gpu_shader_material_fractal_voronoi.glsl, gpu_shader_material_voronoi.glsl, gpu_shader_common_hash.glsl), checked against Blender 5.2.
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
#define SHD_VORONOI_EUCLIDEAN 0
#define SHD_VORONOI_MANHATTAN 1
#define SHD_VORONOI_CHEBYCHEV 2
#define SHD_VORONOI_MINKOWSKI 3
#define SHD_VORONOI_F1 0
#define SHD_VORONOI_F2 1
#define SHD_VORONOI_SMOOTH_F1 2
#define SHD_VORONOI_DISTANCE_TO_EDGE 3
#define SHD_VORONOI_N_SPHERE_RADIUS 4
struct VoronoiParams {
  float scale;
  float detail;
  float roughness;
  float lacunarity;
  float smoothness;
  float exponent;
  float randomness;
  float max_distance;
  bool normalize;
  int feature;
  int metric;
};
                             VoronoiParams VoronoiParams_ctor_() {VoronoiParams r;r.scale=0.0;r.detail=0.0;r.roughness=0.0;r.lacunarity=0.0;r.smoothness=0.0;r.exponent=0.0;r.randomness=0.0;r.max_distance=0.0;r.normalize=false;r.feature=0;r.metric=0;return r;}
struct VoronoiOutput {
  float Distance;
  vec3 Color;
  vec4 Position;
};
                             VoronoiOutput VoronoiOutput_ctor_() {VoronoiOutput r;r.Distance=0.0;r.Color=vec3(0);r.Position=vec4(0);return r;}
float voronoi_distance(float a, float b)
{
  return abs(a - b);
}
float voronoi_distance(vec2 a, vec2 b, VoronoiParams params)
{
  if (params.metric == SHD_VORONOI_EUCLIDEAN) {
    return distance(a, b);
  }
  else if (params.metric == SHD_VORONOI_MANHATTAN) {
    return abs(a.x - b.x) + abs(a.y - b.y);
  }
  else if (params.metric == SHD_VORONOI_CHEBYCHEV) {
    return max(abs(a.x - b.x), abs(a.y - b.y));
  }
  else if (params.metric == SHD_VORONOI_MINKOWSKI) {
    return pow(pow(abs(a.x - b.x), params.exponent) + pow(abs(a.y - b.y), params.exponent),
               1.0 / params.exponent);
  }
  else {
    return 0.0;
  }
}
float voronoi_distance(vec3 a, vec3 b, VoronoiParams params)
{
  if (params.metric == SHD_VORONOI_EUCLIDEAN) {
    return distance(a, b);
  }
  else if (params.metric == SHD_VORONOI_MANHATTAN) {
    return abs(a.x - b.x) + abs(a.y - b.y) + abs(a.z - b.z);
  }
  else if (params.metric == SHD_VORONOI_CHEBYCHEV) {
    return max(abs(a.x - b.x), max(abs(a.y - b.y), abs(a.z - b.z)));
  }
  else if (params.metric == SHD_VORONOI_MINKOWSKI) {
    return pow(pow(abs(a.x - b.x), params.exponent) + pow(abs(a.y - b.y), params.exponent) +
                   pow(abs(a.z - b.z), params.exponent),
               1.0 / params.exponent);
  }
  else {
    return 0.0;
  }
}
float voronoi_distance(vec4 a, vec4 b, VoronoiParams params)
{
  if (params.metric == SHD_VORONOI_EUCLIDEAN) {
    return distance(a, b);
  }
  else if (params.metric == SHD_VORONOI_MANHATTAN) {
    return abs(a.x - b.x) + abs(a.y - b.y) + abs(a.z - b.z) + abs(a.w - b.w);
  }
  else if (params.metric == SHD_VORONOI_CHEBYCHEV) {
    return max(abs(a.x - b.x), max(abs(a.y - b.y), max(abs(a.z - b.z), abs(a.w - b.w))));
  }
  else if (params.metric == SHD_VORONOI_MINKOWSKI) {
    return pow(pow(abs(a.x - b.x), params.exponent) + pow(abs(a.y - b.y), params.exponent) +
                   pow(abs(a.z - b.z), params.exponent) + pow(abs(a.w - b.w), params.exponent),
               1.0 / params.exponent);
  }
  else {
    return 0.0;
  }
}
vec4 voronoi_position(float coord)
{
  return vec4(0.0, 0.0, 0.0, coord);
}
VoronoiOutput voronoi_f1(VoronoiParams params, float coord)
{
  float cellPosition = floor(coord);
  float localPosition = coord - cellPosition;
  float minDistance = FLT_MAX;
  float targetOffset = 0.0;
  float targetPosition = 0.0;
  for (int i = -1; i <= 1; i++) {
    float cellOffset = i;
    float pointPosition = cellOffset +
                          hash_float_to_float(cellPosition + cellOffset) * params.randomness;
    float distanceToPoint = voronoi_distance(pointPosition, localPosition);
    if (distanceToPoint < minDistance) {
      targetOffset = cellOffset;
      minDistance = distanceToPoint;
      targetPosition = pointPosition;
    }
  }
  VoronoiOutput octave;
  octave.Distance = minDistance;
  octave.Color = hash_float_to_vec3(cellPosition + targetOffset);
  octave.Position = voronoi_position(targetPosition + cellPosition);
  return octave;
}
VoronoiOutput voronoi_smooth_f1(VoronoiParams params, float coord)
{
  float cellPosition = floor(coord);
  float localPosition = coord - cellPosition;
  float smoothDistance = 0.0;
  float smoothPosition = 0.0;
  vec3 smoothColor = vec3(0.0);
  float h = -1.0;
  for (int i = -2; i <= 2; i++) {
    float cellOffset = i;
    float pointPosition = cellOffset +
                          hash_float_to_float(cellPosition + cellOffset) * params.randomness;
    float distanceToPoint = voronoi_distance(pointPosition, localPosition);
    h = h == -1.0 ?
            1.0 :
            smoothstep(
                0.0, 1.0, 0.5 + 0.5 * (smoothDistance - distanceToPoint) / params.smoothness);
    float correctionFactor = params.smoothness * h * (1.0 - h);
    smoothDistance = mix(smoothDistance, distanceToPoint, h) - correctionFactor;
    correctionFactor /= 1.0 + 3.0 * params.smoothness;
    vec3 cellColor = hash_float_to_vec3(cellPosition + cellOffset);
    smoothColor = mix(smoothColor, cellColor, h) - correctionFactor;
    smoothPosition = mix(smoothPosition, pointPosition, h) - correctionFactor;
  }
  VoronoiOutput octave;
  octave.Distance = smoothDistance;
  octave.Color = smoothColor;
  octave.Position = voronoi_position(cellPosition + smoothPosition);
  return octave;
}
VoronoiOutput voronoi_f2(VoronoiParams params, float coord)
{
  float cellPosition = floor(coord);
  float localPosition = coord - cellPosition;
  float distanceF1 = FLT_MAX;
  float distanceF2 = FLT_MAX;
  float offsetF1 = 0.0;
  float positionF1 = 0.0;
  float offsetF2 = 0.0;
  float positionF2 = 0.0;
  for (int i = -1; i <= 1; i++) {
    float cellOffset = i;
    float pointPosition = cellOffset +
                          hash_float_to_float(cellPosition + cellOffset) * params.randomness;
    float distanceToPoint = voronoi_distance(pointPosition, localPosition);
    if (distanceToPoint < distanceF1) {
      distanceF2 = distanceF1;
      distanceF1 = distanceToPoint;
      offsetF2 = offsetF1;
      offsetF1 = cellOffset;
      positionF2 = positionF1;
      positionF1 = pointPosition;
    }
    else if (distanceToPoint < distanceF2) {
      distanceF2 = distanceToPoint;
      offsetF2 = cellOffset;
      positionF2 = pointPosition;
    }
  }
  VoronoiOutput octave;
  octave.Distance = distanceF2;
  octave.Color = hash_float_to_vec3(cellPosition + offsetF2);
  octave.Position = voronoi_position(positionF2 + cellPosition);
  return octave;
}
float voronoi_distance_to_edge(VoronoiParams params, float coord)
{
  float cellPosition = floor(coord);
  float localPosition = coord - cellPosition;
  float midPointPosition = hash_float_to_float(cellPosition) * params.randomness;
  float leftPointPosition = -1.0 + hash_float_to_float(cellPosition - 1.0) * params.randomness;
  float rightPointPosition = 1.0 + hash_float_to_float(cellPosition + 1.0) * params.randomness;
  float distanceToMidLeft = abs((midPointPosition + leftPointPosition) / 2.0 - localPosition);
  float distanceToMidRight = abs((midPointPosition + rightPointPosition) / 2.0 - localPosition);
  return min(distanceToMidLeft, distanceToMidRight);
}
float voronoi_n_sphere_radius(VoronoiParams params, float coord)
{
  float cellPosition = floor(coord);
  float localPosition = coord - cellPosition;
  float closestPoint = 0.0;
  float closestPointOffset = 0.0;
  float minDistance = FLT_MAX;
  for (int i = -1; i <= 1; i++) {
    float cellOffset = i;
    float pointPosition = cellOffset +
                          hash_float_to_float(cellPosition + cellOffset) * params.randomness;
    float distanceToPoint = abs(pointPosition - localPosition);
    if (distanceToPoint < minDistance) {
      minDistance = distanceToPoint;
      closestPoint = pointPosition;
      closestPointOffset = cellOffset;
    }
  }
  minDistance = FLT_MAX;
  float closestPointToClosestPoint = 0.0;
  for (int i = -1; i <= 1; i++) {
    if (i == 0) {
      continue;
    }
    float cellOffset = i + closestPointOffset;
    float pointPosition = cellOffset +
                          hash_float_to_float(cellPosition + cellOffset) * params.randomness;
    float distanceToPoint = abs(closestPoint - pointPosition);
    if (distanceToPoint < minDistance) {
      minDistance = distanceToPoint;
      closestPointToClosestPoint = pointPosition;
    }
  }
  return abs(closestPointToClosestPoint - closestPoint) / 2.0;
}
vec4 voronoi_position(vec2 coord)
{
  return vec4(coord.x, coord.y, 0.0, 0.0);
}
VoronoiOutput voronoi_f1(VoronoiParams params, vec2 coord)
{
  vec2 cellPosition_f = floor(coord);
  vec2 localPosition = coord - cellPosition_f;
  ivec2 cellPosition = ivec2(cellPosition_f);
  float minDistance = FLT_MAX;
  ivec2 targetOffset = ivec2(0);
  vec2 targetPosition = vec2(0.0);
  for (int j = -1; j <= 1; j++) {
    for (int i = -1; i <= 1; i++) {
      ivec2 cellOffset = ivec2(i, j);
      vec2 pointPosition = vec2(cellOffset) +
                             hash_int2_to_vec2(cellPosition + cellOffset) * params.randomness;
      float distanceToPoint = voronoi_distance(pointPosition, localPosition, params);
      if (distanceToPoint < minDistance) {
        targetOffset = cellOffset;
        minDistance = distanceToPoint;
        targetPosition = pointPosition;
      }
    }
  }
  VoronoiOutput octave;
  octave.Distance = minDistance;
  octave.Color = hash_int2_to_vec3(cellPosition + targetOffset);
  octave.Position = voronoi_position(targetPosition + cellPosition_f);
  return octave;
}
VoronoiOutput voronoi_smooth_f1(VoronoiParams params, vec2 coord)
{
  vec2 cellPosition_f = floor(coord);
  vec2 localPosition = coord - cellPosition_f;
  ivec2 cellPosition = ivec2(cellPosition_f);
  float smoothDistance = 0.0;
  vec3 smoothColor = vec3(0.0);
  vec2 smoothPosition = vec2(0.0);
  float h = -1.0;
  for (int j = -2; j <= 2; j++) {
    for (int i = -2; i <= 2; i++) {
      ivec2 cellOffset = ivec2(i, j);
      vec2 pointPosition = vec2(cellOffset) +
                             hash_int2_to_vec2(cellPosition + cellOffset) * params.randomness;
      float distanceToPoint = voronoi_distance(pointPosition, localPosition, params);
      h = h == -1.0 ?
              1.0 :
              smoothstep(0.0,
                         1.0,
                         0.5 + 0.5 * (smoothDistance - distanceToPoint) / params.smoothness);
      float correctionFactor = params.smoothness * h * (1.0 - h);
      smoothDistance = mix(smoothDistance, distanceToPoint, h) - correctionFactor;
      correctionFactor /= 1.0 + 3.0 * params.smoothness;
      vec3 cellColor = hash_int2_to_vec3(cellPosition + cellOffset);
      smoothColor = mix(smoothColor, cellColor, h) - correctionFactor;
      smoothPosition = mix(smoothPosition, pointPosition, h) - correctionFactor;
    }
  }
  VoronoiOutput octave;
  octave.Distance = smoothDistance;
  octave.Color = smoothColor;
  octave.Position = voronoi_position(cellPosition_f + smoothPosition);
  return octave;
}
VoronoiOutput voronoi_f2(VoronoiParams params, vec2 coord)
{
  vec2 cellPosition_f = floor(coord);
  vec2 localPosition = coord - cellPosition_f;
  ivec2 cellPosition = ivec2(cellPosition_f);
  float distanceF1 = FLT_MAX;
  float distanceF2 = FLT_MAX;
  ivec2 offsetF1 = ivec2(0);
  vec2 positionF1 = vec2(0.0);
  ivec2 offsetF2 = ivec2(0);
  vec2 positionF2 = vec2(0.0);
  for (int j = -1; j <= 1; j++) {
    for (int i = -1; i <= 1; i++) {
      ivec2 cellOffset = ivec2(i, j);
      vec2 pointPosition = vec2(cellOffset) +
                             hash_int2_to_vec2(cellPosition + cellOffset) * params.randomness;
      float distanceToPoint = voronoi_distance(pointPosition, localPosition, params);
      if (distanceToPoint < distanceF1) {
        distanceF2 = distanceF1;
        distanceF1 = distanceToPoint;
        offsetF2 = offsetF1;
        offsetF1 = cellOffset;
        positionF2 = positionF1;
        positionF1 = pointPosition;
      }
      else if (distanceToPoint < distanceF2) {
        distanceF2 = distanceToPoint;
        offsetF2 = cellOffset;
        positionF2 = pointPosition;
      }
    }
  }
  VoronoiOutput octave;
  octave.Distance = distanceF2;
  octave.Color = hash_int2_to_vec3(cellPosition + offsetF2);
  octave.Position = voronoi_position(positionF2 + cellPosition_f);
  return octave;
}
float voronoi_distance_to_edge(VoronoiParams params, vec2 coord)
{
  vec2 cellPosition_f = floor(coord);
  vec2 localPosition = coord - cellPosition_f;
  ivec2 cellPosition = ivec2(cellPosition_f);
  vec2 vectorToClosest = vec2(0.0);
  float minDistance = FLT_MAX;
  for (int j = -1; j <= 1; j++) {
    for (int i = -1; i <= 1; i++) {
      ivec2 cellOffset = ivec2(i, j);
      vec2 vectorToPoint = vec2(cellOffset) +
                             hash_int2_to_vec2(cellPosition + cellOffset) * params.randomness -
                             localPosition;
      float distanceToPoint = dot(vectorToPoint, vectorToPoint);
      if (distanceToPoint < minDistance) {
        minDistance = distanceToPoint;
        vectorToClosest = vectorToPoint;
      }
    }
  }
  minDistance = FLT_MAX;
  for (int j = -1; j <= 1; j++) {
    for (int i = -1; i <= 1; i++) {
      ivec2 cellOffset = ivec2(i, j);
      vec2 vectorToPoint = vec2(cellOffset) +
                             hash_int2_to_vec2(cellPosition + cellOffset) * params.randomness -
                             localPosition;
      vec2 perpendicularToEdge = vectorToPoint - vectorToClosest;
      if (dot(perpendicularToEdge, perpendicularToEdge) > 0.0001) {
        float distanceToEdge = dot((vectorToClosest + vectorToPoint) / 2.0,
                                   normalize(perpendicularToEdge));
        minDistance = min(minDistance, distanceToEdge);
      }
    }
  }
  return minDistance;
}
float voronoi_n_sphere_radius(VoronoiParams params, vec2 coord)
{
  vec2 cellPosition_f = floor(coord);
  vec2 localPosition = coord - cellPosition_f;
  ivec2 cellPosition = ivec2(cellPosition_f);
  vec2 closestPoint = vec2(0.0);
  ivec2 closestPointOffset = ivec2(0);
  float minDistance = FLT_MAX;
  for (int j = -1; j <= 1; j++) {
    for (int i = -1; i <= 1; i++) {
      ivec2 cellOffset = ivec2(i, j);
      vec2 pointPosition = vec2(cellOffset) +
                             hash_int2_to_vec2(cellPosition + cellOffset) * params.randomness;
      float distanceToPoint = distance(pointPosition, localPosition);
      if (distanceToPoint < minDistance) {
        minDistance = distanceToPoint;
        closestPoint = pointPosition;
        closestPointOffset = cellOffset;
      }
    }
  }
  minDistance = FLT_MAX;
  vec2 closestPointToClosestPoint = vec2(0.0);
  for (int j = -1; j <= 1; j++) {
    for (int i = -1; i <= 1; i++) {
      if (i == 0 && j == 0) {
        continue;
      }
      ivec2 cellOffset = ivec2(i, j) + closestPointOffset;
      vec2 pointPosition = vec2(cellOffset) +
                             hash_int2_to_vec2(cellPosition + cellOffset) * params.randomness;
      float distanceToPoint = distance(closestPoint, pointPosition);
      if (distanceToPoint < minDistance) {
        minDistance = distanceToPoint;
        closestPointToClosestPoint = pointPosition;
      }
    }
  }
  return distance(closestPointToClosestPoint, closestPoint) / 2.0;
}
vec4 voronoi_position(vec3 coord)
{
  return vec4(coord.x, coord.y, coord.z, 0.0);
}
VoronoiOutput voronoi_f1(VoronoiParams params, vec3 coord)
{
  vec3 cellPosition_f = floor(coord);
  vec3 localPosition = coord - cellPosition_f;
  ivec3 cellPosition = ivec3(cellPosition_f);
  float minDistance = FLT_MAX;
  ivec3 targetOffset = ivec3(0);
  vec3 targetPosition = vec3(0.0);
  for (int k = -1; k <= 1; k++) {
    for (int j = -1; j <= 1; j++) {
      for (int i = -1; i <= 1; i++) {
        ivec3 cellOffset = ivec3(i, j, k);
        vec3 pointPosition = vec3(cellOffset) +
                               hash_int3_to_vec3(cellPosition + cellOffset) * params.randomness;
        float distanceToPoint = voronoi_distance(pointPosition, localPosition, params);
        if (distanceToPoint < minDistance) {
          targetOffset = cellOffset;
          minDistance = distanceToPoint;
          targetPosition = pointPosition;
        }
      }
    }
  }
  VoronoiOutput octave;
  octave.Distance = minDistance;
  octave.Color = hash_int3_to_vec3(cellPosition + targetOffset);
  octave.Position = voronoi_position(targetPosition + cellPosition_f);
  return octave;
}
VoronoiOutput voronoi_smooth_f1(VoronoiParams params, vec3 coord)
{
  vec3 cellPosition_f = floor(coord);
  vec3 localPosition = coord - cellPosition_f;
  ivec3 cellPosition = ivec3(cellPosition_f);
  float smoothDistance = 0.0;
  vec3 smoothColor = vec3(0.0);
  vec3 smoothPosition = vec3(0.0);
  float h = -1.0;
  for (int k = -2; k <= 2; k++) {
    for (int j = -2; j <= 2; j++) {
      for (int i = -2; i <= 2; i++) {
        ivec3 cellOffset = ivec3(i, j, k);
        vec3 pointPosition = vec3(cellOffset) +
                               hash_int3_to_vec3(cellPosition + cellOffset) * params.randomness;
        float distanceToPoint = voronoi_distance(pointPosition, localPosition, params);
        h = h == -1.0 ?
                1.0 :
                smoothstep(0.0,
                           1.0,
                           0.5 + 0.5 * (smoothDistance - distanceToPoint) / params.smoothness);
        float correctionFactor = params.smoothness * h * (1.0 - h);
        smoothDistance = mix(smoothDistance, distanceToPoint, h) - correctionFactor;
        correctionFactor /= 1.0 + 3.0 * params.smoothness;
        vec3 cellColor = hash_int3_to_vec3(cellPosition + cellOffset);
        smoothColor = mix(smoothColor, cellColor, h) - correctionFactor;
        smoothPosition = mix(smoothPosition, pointPosition, h) - correctionFactor;
      }
    }
  }
  VoronoiOutput octave;
  octave.Distance = smoothDistance;
  octave.Color = smoothColor;
  octave.Position = voronoi_position(cellPosition_f + smoothPosition);
  return octave;
}
VoronoiOutput voronoi_f2(VoronoiParams params, vec3 coord)
{
  vec3 cellPosition_f = floor(coord);
  vec3 localPosition = coord - cellPosition_f;
  ivec3 cellPosition = ivec3(cellPosition_f);
  float distanceF1 = FLT_MAX;
  float distanceF2 = FLT_MAX;
  ivec3 offsetF1 = ivec3(0);
  vec3 positionF1 = vec3(0.0);
  ivec3 offsetF2 = ivec3(0);
  vec3 positionF2 = vec3(0.0);
  for (int k = -1; k <= 1; k++) {
    for (int j = -1; j <= 1; j++) {
      for (int i = -1; i <= 1; i++) {
        ivec3 cellOffset = ivec3(i, j, k);
        vec3 pointPosition = vec3(cellOffset) +
                               hash_int3_to_vec3(cellPosition + cellOffset) * params.randomness;
        float distanceToPoint = voronoi_distance(pointPosition, localPosition, params);
        if (distanceToPoint < distanceF1) {
          distanceF2 = distanceF1;
          distanceF1 = distanceToPoint;
          offsetF2 = offsetF1;
          offsetF1 = cellOffset;
          positionF2 = positionF1;
          positionF1 = pointPosition;
        }
        else if (distanceToPoint < distanceF2) {
          distanceF2 = distanceToPoint;
          offsetF2 = cellOffset;
          positionF2 = pointPosition;
        }
      }
    }
  }
  VoronoiOutput octave;
  octave.Distance = distanceF2;
  octave.Color = hash_int3_to_vec3(cellPosition + offsetF2);
  octave.Position = voronoi_position(positionF2 + cellPosition_f);
  return octave;
}
float voronoi_distance_to_edge(VoronoiParams params, vec3 coord)
{
  vec3 cellPosition_f = floor(coord);
  vec3 localPosition = coord - cellPosition_f;
  ivec3 cellPosition = ivec3(cellPosition_f);
  vec3 vectorToClosest = vec3(0.0);
  float minDistance = FLT_MAX;
  for (int k = -1; k <= 1; k++) {
    for (int j = -1; j <= 1; j++) {
      for (int i = -1; i <= 1; i++) {
        ivec3 cellOffset = ivec3(i, j, k);
        vec3 vectorToPoint = vec3(cellOffset) +
                               hash_int3_to_vec3(cellPosition + cellOffset) * params.randomness -
                               localPosition;
        float distanceToPoint = dot(vectorToPoint, vectorToPoint);
        if (distanceToPoint < minDistance) {
          minDistance = distanceToPoint;
          vectorToClosest = vectorToPoint;
        }
      }
    }
  }
  minDistance = FLT_MAX;
  for (int k = -1; k <= 1; k++) {
    for (int j = -1; j <= 1; j++) {
      for (int i = -1; i <= 1; i++) {
        ivec3 cellOffset = ivec3(i, j, k);
        vec3 vectorToPoint = vec3(cellOffset) +
                               hash_int3_to_vec3(cellPosition + cellOffset) * params.randomness -
                               localPosition;
        vec3 perpendicularToEdge = vectorToPoint - vectorToClosest;
        if (dot(perpendicularToEdge, perpendicularToEdge) > 0.0001) {
          float distanceToEdge = dot((vectorToClosest + vectorToPoint) / 2.0,
                                     normalize(perpendicularToEdge));
          minDistance = min(minDistance, distanceToEdge);
        }
      }
    }
  }
  return minDistance;
}
float voronoi_n_sphere_radius(VoronoiParams params, vec3 coord)
{
  vec3 cellPosition_f = floor(coord);
  vec3 localPosition = coord - cellPosition_f;
  ivec3 cellPosition = ivec3(cellPosition_f);
  vec3 closestPoint = vec3(0.0);
  ivec3 closestPointOffset = ivec3(0);
  float minDistance = FLT_MAX;
  for (int k = -1; k <= 1; k++) {
    for (int j = -1; j <= 1; j++) {
      for (int i = -1; i <= 1; i++) {
        ivec3 cellOffset = ivec3(i, j, k);
        vec3 pointPosition = vec3(cellOffset) +
                               hash_int3_to_vec3(cellPosition + cellOffset) * params.randomness;
        float distanceToPoint = distance(pointPosition, localPosition);
        if (distanceToPoint < minDistance) {
          minDistance = distanceToPoint;
          closestPoint = pointPosition;
          closestPointOffset = cellOffset;
        }
      }
    }
  }
  minDistance = FLT_MAX;
  vec3 closestPointToClosestPoint = vec3(0.0);
  for (int k = -1; k <= 1; k++) {
    for (int j = -1; j <= 1; j++) {
      for (int i = -1; i <= 1; i++) {
        if (i == 0 && j == 0 && k == 0) {
          continue;
        }
        ivec3 cellOffset = ivec3(i, j, k) + closestPointOffset;
        vec3 pointPosition = vec3(cellOffset) +
                               hash_int3_to_vec3(cellPosition + cellOffset) * params.randomness;
        float distanceToPoint = distance(closestPoint, pointPosition);
        if (distanceToPoint < minDistance) {
          minDistance = distanceToPoint;
          closestPointToClosestPoint = pointPosition;
        }
      }
    }
  }
  return distance(closestPointToClosestPoint, closestPoint) / 2.0;
}
vec4 voronoi_position(vec4 coord)
{
  return coord;
}
VoronoiOutput voronoi_f1(VoronoiParams params, vec4 coord)
{
  vec4 cellPosition_f = floor(coord);
  vec4 localPosition = coord - cellPosition_f;
  ivec4 cellPosition = ivec4(cellPosition_f);
  float minDistance = FLT_MAX;
  ivec4 targetOffset = ivec4(0);
  vec4 targetPosition = vec4(0.0);
  for (int u = -1; u <= 1; u++) {
    for (int k = -1; k <= 1; k++) {
      for (int j = -1; j <= 1; j++) {
        for (int i = -1; i <= 1; i++) {
          ivec4 cellOffset = ivec4(i, j, k, u);
          vec4 pointPosition = vec4(cellOffset) +
                                 hash_int4_to_vec4(cellPosition + cellOffset) * params.randomness;
          float distanceToPoint = voronoi_distance(pointPosition, localPosition, params);
          if (distanceToPoint < minDistance) {
            targetOffset = cellOffset;
            minDistance = distanceToPoint;
            targetPosition = pointPosition;
          }
        }
      }
    }
  }
  VoronoiOutput octave;
  octave.Distance = minDistance;
  octave.Color = hash_int4_to_vec3(cellPosition + targetOffset);
  octave.Position = voronoi_position(targetPosition + cellPosition_f);
  return octave;
}
VoronoiOutput voronoi_smooth_f1(VoronoiParams params, vec4 coord)
{
  vec4 cellPosition_f = floor(coord);
  vec4 localPosition = coord - cellPosition_f;
  ivec4 cellPosition = ivec4(cellPosition_f);
  float smoothDistance = 0.0;
  vec3 smoothColor = vec3(0.0);
  vec4 smoothPosition = vec4(0.0);
  float h = -1.0;
  for (int u = -2; u <= 2; u++) {
    for (int k = -2; k <= 2; k++) {
      for (int j = -2; j <= 2; j++) {
        for (int i = -2; i <= 2; i++) {
          ivec4 cellOffset = ivec4(i, j, k, u);
          vec4 pointPosition = vec4(cellOffset) +
                                 hash_int4_to_vec4(cellPosition + cellOffset) * params.randomness;
          float distanceToPoint = voronoi_distance(pointPosition, localPosition, params);
          h = h == -1.0 ?
                  1.0 :
                  smoothstep(0.0,
                             1.0,
                             0.5 + 0.5 * (smoothDistance - distanceToPoint) / params.smoothness);
          float correctionFactor = params.smoothness * h * (1.0 - h);
          smoothDistance = mix(smoothDistance, distanceToPoint, h) - correctionFactor;
          correctionFactor /= 1.0 + 3.0 * params.smoothness;
          vec3 cellColor = hash_int4_to_vec3(cellPosition + cellOffset);
          smoothColor = mix(smoothColor, cellColor, h) - correctionFactor;
          smoothPosition = mix(smoothPosition, pointPosition, h) - correctionFactor;
        }
      }
    }
  }
  VoronoiOutput octave;
  octave.Distance = smoothDistance;
  octave.Color = smoothColor;
  octave.Position = voronoi_position(cellPosition_f + smoothPosition);
  return octave;
}
VoronoiOutput voronoi_f2(VoronoiParams params, vec4 coord)
{
  vec4 cellPosition_f = floor(coord);
  vec4 localPosition = coord - cellPosition_f;
  ivec4 cellPosition = ivec4(cellPosition_f);
  float distanceF1 = FLT_MAX;
  float distanceF2 = FLT_MAX;
  ivec4 offsetF1 = ivec4(0);
  vec4 positionF1 = vec4(0.0);
  ivec4 offsetF2 = ivec4(0);
  vec4 positionF2 = vec4(0.0);
  for (int u = -1; u <= 1; u++) {
    for (int k = -1; k <= 1; k++) {
      for (int j = -1; j <= 1; j++) {
        for (int i = -1; i <= 1; i++) {
          ivec4 cellOffset = ivec4(i, j, k, u);
          vec4 pointPosition = vec4(cellOffset) +
                                 hash_int4_to_vec4(cellPosition + cellOffset) * params.randomness;
          float distanceToPoint = voronoi_distance(pointPosition, localPosition, params);
          if (distanceToPoint < distanceF1) {
            distanceF2 = distanceF1;
            distanceF1 = distanceToPoint;
            offsetF2 = offsetF1;
            offsetF1 = cellOffset;
            positionF2 = positionF1;
            positionF1 = pointPosition;
          }
          else if (distanceToPoint < distanceF2) {
            distanceF2 = distanceToPoint;
            offsetF2 = cellOffset;
            positionF2 = pointPosition;
          }
        }
      }
    }
  }
  VoronoiOutput octave;
  octave.Distance = distanceF2;
  octave.Color = hash_int4_to_vec3(cellPosition + offsetF2);
  octave.Position = voronoi_position(positionF2 + cellPosition_f);
  return octave;
}
float voronoi_distance_to_edge(VoronoiParams params, vec4 coord)
{
  vec4 cellPosition_f = floor(coord);
  vec4 localPosition = coord - cellPosition_f;
  ivec4 cellPosition = ivec4(cellPosition_f);
  vec4 vectorToClosest = vec4(0.0);
  float minDistance = FLT_MAX;
  for (int u = -1; u <= 1; u++) {
    for (int k = -1; k <= 1; k++) {
      for (int j = -1; j <= 1; j++) {
        for (int i = -1; i <= 1; i++) {
          ivec4 cellOffset = ivec4(i, j, k, u);
          vec4 vectorToPoint = vec4(cellOffset) +
                                 hash_int4_to_vec4(cellPosition + cellOffset) * params.randomness -
                                 localPosition;
          float distanceToPoint = dot(vectorToPoint, vectorToPoint);
          if (distanceToPoint < minDistance) {
            minDistance = distanceToPoint;
            vectorToClosest = vectorToPoint;
          }
        }
      }
    }
  }
  minDistance = FLT_MAX;
  for (int u = -1; u <= 1; u++) {
    for (int k = -1; k <= 1; k++) {
      for (int j = -1; j <= 1; j++) {
        for (int i = -1; i <= 1; i++) {
          ivec4 cellOffset = ivec4(i, j, k, u);
          vec4 vectorToPoint = vec4(cellOffset) +
                                 hash_int4_to_vec4(cellPosition + cellOffset) * params.randomness -
                                 localPosition;
          vec4 perpendicularToEdge = vectorToPoint - vectorToClosest;
          if (dot(perpendicularToEdge, perpendicularToEdge) > 0.0001) {
            float distanceToEdge = dot((vectorToClosest + vectorToPoint) / 2.0,
                                       normalize(perpendicularToEdge));
            minDistance = min(minDistance, distanceToEdge);
          }
        }
      }
    }
  }
  return minDistance;
}
float voronoi_n_sphere_radius(VoronoiParams params, vec4 coord)
{
  vec4 cellPosition_f = floor(coord);
  vec4 localPosition = coord - cellPosition_f;
  ivec4 cellPosition = ivec4(cellPosition_f);
  vec4 closestPoint = vec4(0.0);
  ivec4 closestPointOffset = ivec4(0);
  float minDistance = FLT_MAX;
  for (int u = -1; u <= 1; u++) {
    for (int k = -1; k <= 1; k++) {
      for (int j = -1; j <= 1; j++) {
        for (int i = -1; i <= 1; i++) {
          ivec4 cellOffset = ivec4(i, j, k, u);
          vec4 pointPosition = vec4(cellOffset) +
                                 hash_int4_to_vec4(cellPosition + cellOffset) * params.randomness;
          float distanceToPoint = distance(pointPosition, localPosition);
          if (distanceToPoint < minDistance) {
            minDistance = distanceToPoint;
            closestPoint = pointPosition;
            closestPointOffset = cellOffset;
          }
        }
      }
    }
  }
  minDistance = FLT_MAX;
  vec4 closestPointToClosestPoint = vec4(0.0);
  for (int u = -1; u <= 1; u++) {
    for (int k = -1; k <= 1; k++) {
      for (int j = -1; j <= 1; j++) {
        for (int i = -1; i <= 1; i++) {
          if (i == 0 && j == 0 && k == 0 && u == 0) {
            continue;
          }
          ivec4 cellOffset = ivec4(i, j, k, u) + closestPointOffset;
          vec4 pointPosition = vec4(cellOffset) +
                                 hash_int4_to_vec4(cellPosition + cellOffset) * params.randomness;
          float distanceToPoint = distance(closestPoint, pointPosition);
          if (distanceToPoint < minDistance) {
            minDistance = distanceToPoint;
            closestPointToClosestPoint = pointPosition;
          }
        }
      }
    }
  }
  return distance(closestPointToClosestPoint, closestPoint) / 2.0;
}
#define FRACTAL_VORONOI_DISTANCE_TO_EDGE_FUNCTION(T) \
  float fractal_voronoi_distance_to_edge(VoronoiParams params, T coord) \
  { \
    float amplitude = 1.0; \
    float max_amplitude = params.max_distance; \
    float scale = 1.0; \
    float distance = 8.0; \
\
    bool zero_input = params.detail == 0.0 || params.roughness == 0.0; \
\
    for (int i = 0; i <= ceil(params.detail); ++i) { \
      float octave_distance = voronoi_distance_to_edge(params, coord * scale); \
\
      if (zero_input) { \
        distance = octave_distance; \
        break; \
      } \
      else if (i <= params.detail) { \
        max_amplitude = mix(max_amplitude, params.max_distance / scale, amplitude); \
        distance = mix(distance, min(distance, octave_distance / scale), amplitude); \
        scale *= params.lacunarity; \
        amplitude *= params.roughness; \
      } \
      else { \
        float remainder = params.detail - floor(params.detail); \
        if (remainder != 0.0) { \
          float lerp_amplitude = mix(max_amplitude, params.max_distance / scale, amplitude); \
          max_amplitude = mix(max_amplitude, lerp_amplitude, remainder); \
          float lerp_distance = mix(distance, min(distance, octave_distance / scale), amplitude); \
          distance = mix(distance, min(distance, lerp_distance), remainder); \
        } \
      } \
    } \
\
    if (params.normalize) { \
      distance /= max_amplitude; \
    } \
\
    return distance; \
  }
VoronoiOutput fractal_voronoi_x_fx(VoronoiParams params, float coord)
{
  float amplitude = 1.0;
  float max_amplitude = 0.0;
  float scale = 1.0;
  VoronoiOutput Output;
  Output.Distance = 0.0;
  Output.Color = vec3(0.0, 0.0, 0.0);
  Output.Position = vec4(0.0, 0.0, 0.0, 0.0);
  bool zero_input = params.detail == 0.0 || params.roughness == 0.0;
  for (int i = 0; i <= ceil(params.detail); ++i) {
    VoronoiOutput octave;
    if (params.feature == SHD_VORONOI_F2) {
      octave = voronoi_f2(params, coord * scale);
    }
    else if (params.feature == SHD_VORONOI_SMOOTH_F1 && params.smoothness != 0.0) {
      octave = voronoi_smooth_f1(params, coord * scale);
    }
    else {
      octave = voronoi_f1(params, coord * scale);
    }
    if (zero_input) {
      max_amplitude = 1.0;
      Output = octave;
      break;
    }
    else if (i <= params.detail) {
      max_amplitude += amplitude;
      Output.Distance += octave.Distance * amplitude;
      Output.Color += octave.Color * amplitude;
      Output.Position = mix(Output.Position, octave.Position / scale, amplitude);
      scale *= params.lacunarity;
      amplitude *= params.roughness;
    }
    else {
      float remainder = params.detail - floor(params.detail);
      if (remainder != 0.0) {
        max_amplitude = mix(max_amplitude, max_amplitude + amplitude, remainder);
        Output.Distance = mix(
            Output.Distance, Output.Distance + octave.Distance * amplitude, remainder);
        Output.Color = mix(Output.Color, Output.Color + octave.Color * amplitude, remainder);
        Output.Position = mix(
            Output.Position, mix(Output.Position, octave.Position / scale, amplitude), remainder);
      }
    }
  }
  if (params.normalize) {
    Output.Distance /= max_amplitude * params.max_distance;
    Output.Color /= max_amplitude;
  }
  Output.Position = safe_divide(Output.Position, params.scale);
  return Output;
}
FRACTAL_VORONOI_DISTANCE_TO_EDGE_FUNCTION(float)
VoronoiOutput fractal_voronoi_x_fx(VoronoiParams params, vec2 coord)
{
  float amplitude = 1.0;
  float max_amplitude = 0.0;
  float scale = 1.0;
  VoronoiOutput Output;
  Output.Distance = 0.0;
  Output.Color = vec3(0.0, 0.0, 0.0);
  Output.Position = vec4(0.0, 0.0, 0.0, 0.0);
  bool zero_input = params.detail == 0.0 || params.roughness == 0.0;
  for (int i = 0; i <= ceil(params.detail); ++i) {
    VoronoiOutput octave;
    if (params.feature == SHD_VORONOI_F2) {
      octave = voronoi_f2(params, coord * scale);
    }
    else if (params.feature == SHD_VORONOI_SMOOTH_F1 && params.smoothness != 0.0) {
      octave = voronoi_smooth_f1(params, coord * scale);
    }
    else {
      octave = voronoi_f1(params, coord * scale);
    }
    if (zero_input) {
      max_amplitude = 1.0;
      Output = octave;
      break;
    }
    else if (i <= params.detail) {
      max_amplitude += amplitude;
      Output.Distance += octave.Distance * amplitude;
      Output.Color += octave.Color * amplitude;
      Output.Position = mix(Output.Position, octave.Position / scale, amplitude);
      scale *= params.lacunarity;
      amplitude *= params.roughness;
    }
    else {
      float remainder = params.detail - floor(params.detail);
      if (remainder != 0.0) {
        max_amplitude = mix(max_amplitude, max_amplitude + amplitude, remainder);
        Output.Distance = mix(
            Output.Distance, Output.Distance + octave.Distance * amplitude, remainder);
        Output.Color = mix(Output.Color, Output.Color + octave.Color * amplitude, remainder);
        Output.Position = mix(
            Output.Position, mix(Output.Position, octave.Position / scale, amplitude), remainder);
      }
    }
  }
  if (params.normalize) {
    Output.Distance /= max_amplitude * params.max_distance;
    Output.Color /= max_amplitude;
  }
  Output.Position = safe_divide(Output.Position, params.scale);
  return Output;
}
FRACTAL_VORONOI_DISTANCE_TO_EDGE_FUNCTION(vec2)
VoronoiOutput fractal_voronoi_x_fx(VoronoiParams params, vec3 coord)
{
  float amplitude = 1.0;
  float max_amplitude = 0.0;
  float scale = 1.0;
  VoronoiOutput Output;
  Output.Distance = 0.0;
  Output.Color = vec3(0.0, 0.0, 0.0);
  Output.Position = vec4(0.0, 0.0, 0.0, 0.0);
  bool zero_input = params.detail == 0.0 || params.roughness == 0.0;
  for (int i = 0; i <= ceil(params.detail); ++i) {
    VoronoiOutput octave;
    if (params.feature == SHD_VORONOI_F2) {
      octave = voronoi_f2(params, coord * scale);
    }
    else if (params.feature == SHD_VORONOI_SMOOTH_F1 && params.smoothness != 0.0) {
      octave = voronoi_smooth_f1(params, coord * scale);
    }
    else {
      octave = voronoi_f1(params, coord * scale);
    }
    if (zero_input) {
      max_amplitude = 1.0;
      Output = octave;
      break;
    }
    else if (i <= params.detail) {
      max_amplitude += amplitude;
      Output.Distance += octave.Distance * amplitude;
      Output.Color += octave.Color * amplitude;
      Output.Position = mix(Output.Position, octave.Position / scale, amplitude);
      scale *= params.lacunarity;
      amplitude *= params.roughness;
    }
    else {
      float remainder = params.detail - floor(params.detail);
      if (remainder != 0.0) {
        max_amplitude = mix(max_amplitude, max_amplitude + amplitude, remainder);
        Output.Distance = mix(
            Output.Distance, Output.Distance + octave.Distance * amplitude, remainder);
        Output.Color = mix(Output.Color, Output.Color + octave.Color * amplitude, remainder);
        Output.Position = mix(
            Output.Position, mix(Output.Position, octave.Position / scale, amplitude), remainder);
      }
    }
  }
  if (params.normalize) {
    Output.Distance /= max_amplitude * params.max_distance;
    Output.Color /= max_amplitude;
  }
  Output.Position = safe_divide(Output.Position, params.scale);
  return Output;
}
FRACTAL_VORONOI_DISTANCE_TO_EDGE_FUNCTION(vec3)
VoronoiOutput fractal_voronoi_x_fx(VoronoiParams params, vec4 coord)
{
  float amplitude = 1.0;
  float max_amplitude = 0.0;
  float scale = 1.0;
  VoronoiOutput Output;
  Output.Distance = 0.0;
  Output.Color = vec3(0.0, 0.0, 0.0);
  Output.Position = vec4(0.0, 0.0, 0.0, 0.0);
  bool zero_input = params.detail == 0.0 || params.roughness == 0.0;
  for (int i = 0; i <= ceil(params.detail); ++i) {
    VoronoiOutput octave;
    if (params.feature == SHD_VORONOI_F2) {
      octave = voronoi_f2(params, coord * scale);
    }
    else if (params.feature == SHD_VORONOI_SMOOTH_F1 && params.smoothness != 0.0) {
      octave = voronoi_smooth_f1(params, coord * scale);
    }
    else {
      octave = voronoi_f1(params, coord * scale);
    }
    if (zero_input) {
      max_amplitude = 1.0;
      Output = octave;
      break;
    }
    else if (i <= params.detail) {
      max_amplitude += amplitude;
      Output.Distance += octave.Distance * amplitude;
      Output.Color += octave.Color * amplitude;
      Output.Position = mix(Output.Position, octave.Position / scale, amplitude);
      scale *= params.lacunarity;
      amplitude *= params.roughness;
    }
    else {
      float remainder = params.detail - floor(params.detail);
      if (remainder != 0.0) {
        max_amplitude = mix(max_amplitude, max_amplitude + amplitude, remainder);
        Output.Distance = mix(
            Output.Distance, Output.Distance + octave.Distance * amplitude, remainder);
        Output.Color = mix(Output.Color, Output.Color + octave.Color * amplitude, remainder);
        Output.Position = mix(
            Output.Position, mix(Output.Position, octave.Position / scale, amplitude), remainder);
      }
    }
  }
  if (params.normalize) {
    Output.Distance /= max_amplitude * params.max_distance;
    Output.Color /= max_amplitude;
  }
  Output.Position = safe_divide(Output.Position, params.scale);
  return Output;
}
FRACTAL_VORONOI_DISTANCE_TO_EDGE_FUNCTION(vec4)
#define INITIALIZE_VORONOIPARAMS(FEATURE) \
  params.feature = FEATURE; \
  params.metric = int(metric); \
  params.scale = scale; \
  params.detail = clamp(detail, 0.0, 15.0); \
  params.roughness = clamp(roughness, 0.0, 1.0); \
  params.lacunarity = lacunarity; \
  params.smoothness = clamp(smoothness / 2.0, 0.0, 0.5); \
  params.exponent = exponent; \
  params.randomness = clamp(randomness, 0.0, 1.0); \
  params.max_distance = 0.0; \
  params.normalize = bool(normalize);
void node_tex_voronoi_f1_1d(vec3 coord,
                            float w,
                            float scale,
                            float detail,
                            float roughness,
                            float lacunarity,
                            float smoothness,
                            float exponent,
                            float randomness,
                            float metric,
                            float normalize,
                            out float outDistance,
                            out vec4 outColor,
                            out vec3 outPosition,
                            out float outW,
                            out float outRadius)
{
  VoronoiParams params;
  INITIALIZE_VORONOIPARAMS(SHD_VORONOI_F1)
  w *= scale;
  params.max_distance = 0.5 + 0.5 * params.randomness;
  VoronoiOutput Output = fractal_voronoi_x_fx(params, w);
  outDistance = Output.Distance;
  outColor = vec4(Output.Color, 1.0);
  outW = Output.Position.w;
}
void node_tex_voronoi_smooth_f1_1d(vec3 coord,
                                   float w,
                                   float scale,
                                   float detail,
                                   float roughness,
                                   float lacunarity,
                                   float smoothness,
                                   float exponent,
                                   float randomness,
                                   float metric,
                                   float normalize,
                                   out float outDistance,
                                   out vec4 outColor,
                                   out vec3 outPosition,
                                   out float outW,
                                   out float outRadius)
{
  VoronoiParams params;
  INITIALIZE_VORONOIPARAMS(SHD_VORONOI_SMOOTH_F1)
  w *= scale;
  params.max_distance = 0.5 + 0.5 * params.randomness;
  VoronoiOutput Output = fractal_voronoi_x_fx(params, w);
  outDistance = Output.Distance;
  outColor = vec4(Output.Color, 1.0);
  outW = Output.Position.w;
}
void node_tex_voronoi_f2_1d(vec3 coord,
                            float w,
                            float scale,
                            float detail,
                            float roughness,
                            float lacunarity,
                            float smoothness,
                            float exponent,
                            float randomness,
                            float metric,
                            float normalize,
                            out float outDistance,
                            out vec4 outColor,
                            out vec3 outPosition,
                            out float outW,
                            out float outRadius)
{
  VoronoiParams params;
  INITIALIZE_VORONOIPARAMS(SHD_VORONOI_F2)
  w *= scale;
  params.max_distance = (0.5 + 0.5 * params.randomness) * 2.0;
  VoronoiOutput Output = fractal_voronoi_x_fx(params, w);
  outDistance = Output.Distance;
  outColor = vec4(Output.Color, 1.0);
  outW = Output.Position.w;
}
void node_tex_voronoi_distance_to_edge_1d(vec3 coord,
                                          float w,
                                          float scale,
                                          float detail,
                                          float roughness,
                                          float lacunarity,
                                          float smoothness,
                                          float exponent,
                                          float randomness,
                                          float metric,
                                          float normalize,
                                          out float outDistance,
                                          out vec4 outColor,
                                          out vec3 outPosition,
                                          out float outW,
                                          out float outRadius)
{
  VoronoiParams params;
  INITIALIZE_VORONOIPARAMS(SHD_VORONOI_DISTANCE_TO_EDGE)
  w *= scale;
  params.max_distance = 0.5 + 0.5 * params.randomness;
  outDistance = fractal_voronoi_distance_to_edge(params, w);
}
void node_tex_voronoi_n_sphere_radius_1d(vec3 coord,
                                         float w,
                                         float scale,
                                         float detail,
                                         float roughness,
                                         float lacunarity,
                                         float smoothness,
                                         float exponent,
                                         float randomness,
                                         float metric,
                                         float normalize,
                                         out float outDistance,
                                         out vec4 outColor,
                                         out vec3 outPosition,
                                         out float outW,
                                         out float outRadius)
{
  VoronoiParams params;
  INITIALIZE_VORONOIPARAMS(SHD_VORONOI_N_SPHERE_RADIUS)
  w *= scale;
  outRadius = voronoi_n_sphere_radius(params, w);
}
void node_tex_voronoi_f1_2d(vec3 coord,
                            float w,
                            float scale,
                            float detail,
                            float roughness,
                            float lacunarity,
                            float smoothness,
                            float exponent,
                            float randomness,
                            float metric,
                            float normalize,
                            out float outDistance,
                            out vec4 outColor,
                            out vec3 outPosition,
                            out float outW,
                            out float outRadius)
{
  VoronoiParams params;
  INITIALIZE_VORONOIPARAMS(SHD_VORONOI_F1)
  coord *= scale;
  params.max_distance = voronoi_distance(
      vec2(0.0), vec2(0.5 + 0.5 * params.randomness), params);
  VoronoiOutput Output = fractal_voronoi_x_fx(params, coord.xy);
  outDistance = Output.Distance;
  outColor = vec4(Output.Color, 1.0);
  outPosition = Output.Position.xyz;
}
void node_tex_voronoi_smooth_f1_2d(vec3 coord,
                                   float w,
                                   float scale,
                                   float detail,
                                   float roughness,
                                   float lacunarity,
                                   float smoothness,
                                   float exponent,
                                   float randomness,
                                   float metric,
                                   float normalize,
                                   out float outDistance,
                                   out vec4 outColor,
                                   out vec3 outPosition,
                                   out float outW,
                                   out float outRadius)
{
  VoronoiParams params;
  INITIALIZE_VORONOIPARAMS(SHD_VORONOI_SMOOTH_F1)
  coord *= scale;
  params.max_distance = voronoi_distance(
      vec2(0.0), vec2(0.5 + 0.5 * params.randomness), params);
  VoronoiOutput Output = fractal_voronoi_x_fx(params, coord.xy);
  outDistance = Output.Distance;
  outColor = vec4(Output.Color, 1.0);
  outPosition = Output.Position.xyz;
}
void node_tex_voronoi_f2_2d(vec3 coord,
                            float w,
                            float scale,
                            float detail,
                            float roughness,
                            float lacunarity,
                            float smoothness,
                            float exponent,
                            float randomness,
                            float metric,
                            float normalize,
                            out float outDistance,
                            out vec4 outColor,
                            out vec3 outPosition,
                            out float outW,
                            out float outRadius)
{
  VoronoiParams params;
  INITIALIZE_VORONOIPARAMS(SHD_VORONOI_F2)
  coord *= scale;
  params.max_distance = voronoi_distance(
                            vec2(0.0), vec2(0.5 + 0.5 * params.randomness), params) *
                        2.0;
  VoronoiOutput Output = fractal_voronoi_x_fx(params, coord.xy);
  outDistance = Output.Distance;
  outColor = vec4(Output.Color, 1.0);
  outPosition = Output.Position.xyz;
}
void node_tex_voronoi_distance_to_edge_2d(vec3 coord,
                                          float w,
                                          float scale,
                                          float detail,
                                          float roughness,
                                          float lacunarity,
                                          float smoothness,
                                          float exponent,
                                          float randomness,
                                          float metric,
                                          float normalize,
                                          out float outDistance,
                                          out vec4 outColor,
                                          out vec3 outPosition,
                                          out float outW,
                                          out float outRadius)
{
  VoronoiParams params;
  INITIALIZE_VORONOIPARAMS(SHD_VORONOI_DISTANCE_TO_EDGE)
  coord *= scale;
  params.max_distance = 0.5 + 0.5 * params.randomness;
  outDistance = fractal_voronoi_distance_to_edge(params, coord.xy);
}
void node_tex_voronoi_n_sphere_radius_2d(vec3 coord,
                                         float w,
                                         float scale,
                                         float detail,
                                         float roughness,
                                         float lacunarity,
                                         float smoothness,
                                         float exponent,
                                         float randomness,
                                         float metric,
                                         float normalize,
                                         out float outDistance,
                                         out vec4 outColor,
                                         out vec3 outPosition,
                                         out float outW,
                                         out float outRadius)
{
  VoronoiParams params;
  INITIALIZE_VORONOIPARAMS(SHD_VORONOI_N_SPHERE_RADIUS)
  coord *= scale;
  outRadius = voronoi_n_sphere_radius(params, coord.xy);
}
void node_tex_voronoi_f1_3d(vec3 coord,
                            float w,
                            float scale,
                            float detail,
                            float roughness,
                            float lacunarity,
                            float smoothness,
                            float exponent,
                            float randomness,
                            float metric,
                            float normalize,
                            out float outDistance,
                            out vec4 outColor,
                            out vec3 outPosition,
                            out float outW,
                            out float outRadius)
{
  VoronoiParams params;
  INITIALIZE_VORONOIPARAMS(SHD_VORONOI_F1)
  coord *= scale;
  params.max_distance = voronoi_distance(
      vec3(0.0), vec3(0.5 + 0.5 * params.randomness), params);
  VoronoiOutput Output = fractal_voronoi_x_fx(params, coord);
  outDistance = Output.Distance;
  outColor = vec4(Output.Color, 1.0);
  outPosition = Output.Position.xyz;
}
void node_tex_voronoi_smooth_f1_3d(vec3 coord,
                                   float w,
                                   float scale,
                                   float detail,
                                   float roughness,
                                   float lacunarity,
                                   float smoothness,
                                   float exponent,
                                   float randomness,
                                   float metric,
                                   float normalize,
                                   out float outDistance,
                                   out vec4 outColor,
                                   out vec3 outPosition,
                                   out float outW,
                                   out float outRadius)
{
  VoronoiParams params;
  INITIALIZE_VORONOIPARAMS(SHD_VORONOI_SMOOTH_F1)
  coord *= scale;
  params.max_distance = voronoi_distance(
      vec3(0.0), vec3(0.5 + 0.5 * params.randomness), params);
  VoronoiOutput Output = fractal_voronoi_x_fx(params, coord);
  outDistance = Output.Distance;
  outColor = vec4(Output.Color, 1.0);
  outPosition = Output.Position.xyz;
}
void node_tex_voronoi_f2_3d(vec3 coord,
                            float w,
                            float scale,
                            float detail,
                            float roughness,
                            float lacunarity,
                            float smoothness,
                            float exponent,
                            float randomness,
                            float metric,
                            float normalize,
                            out float outDistance,
                            out vec4 outColor,
                            out vec3 outPosition,
                            out float outW,
                            out float outRadius)
{
  VoronoiParams params;
  INITIALIZE_VORONOIPARAMS(SHD_VORONOI_F2)
  coord *= scale;
  params.max_distance = voronoi_distance(
                            vec3(0.0), vec3(0.5 + 0.5 * params.randomness), params) *
                        2.0;
  VoronoiOutput Output = fractal_voronoi_x_fx(params, coord);
  outDistance = Output.Distance;
  outColor = vec4(Output.Color, 1.0);
  outPosition = Output.Position.xyz;
}
void node_tex_voronoi_distance_to_edge_3d(vec3 coord,
                                          float w,
                                          float scale,
                                          float detail,
                                          float roughness,
                                          float lacunarity,
                                          float smoothness,
                                          float exponent,
                                          float randomness,
                                          float metric,
                                          float normalize,
                                          out float outDistance,
                                          out vec4 outColor,
                                          out vec3 outPosition,
                                          out float outW,
                                          out float outRadius)
{
  VoronoiParams params;
  INITIALIZE_VORONOIPARAMS(SHD_VORONOI_DISTANCE_TO_EDGE)
  coord *= scale;
  params.max_distance = 0.5 + 0.5 * params.randomness;
  outDistance = fractal_voronoi_distance_to_edge(params, coord);
}
void node_tex_voronoi_n_sphere_radius_3d(vec3 coord,
                                         float w,
                                         float scale,
                                         float detail,
                                         float roughness,
                                         float lacunarity,
                                         float smoothness,
                                         float exponent,
                                         float randomness,
                                         float metric,
                                         float normalize,
                                         out float outDistance,
                                         out vec4 outColor,
                                         out vec3 outPosition,
                                         out float outW,
                                         out float outRadius)
{
  VoronoiParams params;
  INITIALIZE_VORONOIPARAMS(SHD_VORONOI_N_SPHERE_RADIUS)
  coord *= scale;
  outRadius = voronoi_n_sphere_radius(params, coord);
}
void node_tex_voronoi_f1_4d(vec3 coord,
                            float w,
                            float scale,
                            float detail,
                            float roughness,
                            float lacunarity,
                            float smoothness,
                            float exponent,
                            float randomness,
                            float metric,
                            float normalize,
                            out float outDistance,
                            out vec4 outColor,
                            out vec3 outPosition,
                            out float outW,
                            out float outRadius)
{
  VoronoiParams params;
  INITIALIZE_VORONOIPARAMS(SHD_VORONOI_F1)
  w *= scale;
  coord *= scale;
  params.max_distance = voronoi_distance(
      vec4(0.0), vec4(0.5 + 0.5 * params.randomness), params);
  VoronoiOutput Output = fractal_voronoi_x_fx(params, vec4(coord, w));
  outDistance = Output.Distance;
  outColor = vec4(Output.Color, 1.0);
  outPosition = Output.Position.xyz;
  outW = Output.Position.w;
}
void node_tex_voronoi_smooth_f1_4d(vec3 coord,
                                   float w,
                                   float scale,
                                   float detail,
                                   float roughness,
                                   float lacunarity,
                                   float smoothness,
                                   float exponent,
                                   float randomness,
                                   float metric,
                                   float normalize,
                                   out float outDistance,
                                   out vec4 outColor,
                                   out vec3 outPosition,
                                   out float outW,
                                   out float outRadius)
{
  VoronoiParams params;
  INITIALIZE_VORONOIPARAMS(SHD_VORONOI_SMOOTH_F1)
  w *= scale;
  coord *= scale;
  params.max_distance = voronoi_distance(
      vec4(0.0), vec4(0.5 + 0.5 * params.randomness), params);
  VoronoiOutput Output = fractal_voronoi_x_fx(params, vec4(coord, w));
  outDistance = Output.Distance;
  outColor = vec4(Output.Color, 1.0);
  outPosition = Output.Position.xyz;
  outW = Output.Position.w;
}
void node_tex_voronoi_f2_4d(vec3 coord,
                            float w,
                            float scale,
                            float detail,
                            float roughness,
                            float lacunarity,
                            float smoothness,
                            float exponent,
                            float randomness,
                            float metric,
                            float normalize,
                            out float outDistance,
                            out vec4 outColor,
                            out vec3 outPosition,
                            out float outW,
                            out float outRadius)
{
  VoronoiParams params;
  INITIALIZE_VORONOIPARAMS(SHD_VORONOI_F2)
  w *= scale;
  coord *= scale;
  params.max_distance = voronoi_distance(
                            vec4(0.0), vec4(0.5 + 0.5 * params.randomness), params) *
                        2.0;
  VoronoiOutput Output = fractal_voronoi_x_fx(params, vec4(coord, w));
  outDistance = Output.Distance;
  outColor = vec4(Output.Color, 1.0);
  outPosition = Output.Position.xyz;
  outW = Output.Position.w;
}
void node_tex_voronoi_distance_to_edge_4d(vec3 coord,
                                          float w,
                                          float scale,
                                          float detail,
                                          float roughness,
                                          float lacunarity,
                                          float smoothness,
                                          float exponent,
                                          float randomness,
                                          float metric,
                                          float normalize,
                                          out float outDistance,
                                          out vec4 outColor,
                                          out vec3 outPosition,
                                          out float outW,
                                          out float outRadius)
{
  VoronoiParams params;
  INITIALIZE_VORONOIPARAMS(SHD_VORONOI_DISTANCE_TO_EDGE)
  w *= scale;
  coord *= scale;
  params.max_distance = 0.5 + 0.5 * params.randomness;
  outDistance = fractal_voronoi_distance_to_edge(params, vec4(coord, w));
}
void node_tex_voronoi_n_sphere_radius_4d(vec3 coord,
                                         float w,
                                         float scale,
                                         float detail,
                                         float roughness,
                                         float lacunarity,
                                         float smoothness,
                                         float exponent,
                                         float randomness,
                                         float metric,
                                         float normalize,
                                         out float outDistance,
                                         out vec4 outColor,
                                         out vec3 outPosition,
                                         out float outW,
                                         out float outRadius)
{
  VoronoiParams params;
  INITIALIZE_VORONOIPARAMS(SHD_VORONOI_N_SPHERE_RADIUS)
  w *= scale;
  coord *= scale;
  outRadius = voronoi_n_sphere_radius(params, vec4(coord, w));
}

#define VORONOI_ARGS co, ww, sc, dt, rg, lc, sm, ex, rn, mt, nm, dist, col, pos, wo, rad
#define VORONOI_DIM(F) { if (dims == 0) F##_1d(VORONOI_ARGS); else if (dims == 1) F##_2d(VORONOI_ARGS); else if (dims == 2) F##_3d(VORONOI_ARGS); else F##_4d(VORONOI_ARGS); }

vec4 effect(vec2 uv) {
    vec3 co = vector_in(uv), pos = vec3(0.0);
    float ww = num(has_input_in_w(), input_in_w(uv), w), sc = num(has_input_in_scale(), input_in_scale(uv), tex_scale);
    float dt = num(has_input_in_detail(), input_in_detail(uv), detail), rg = num(has_input_in_roughness(), input_in_roughness(uv), roughness);
    float lc = num(has_input_in_lacunarity(), input_in_lacunarity(uv), lacunarity), sm = num(has_input_in_smooth(), input_in_smooth(uv), smoothness);
    float ex = num(has_input_in_exponent(), input_in_exponent(uv), exponent), rn = num(has_input_in_random(), input_in_random(uv), randomness);
    float mt = float(metric), nm = normalized ? 1.0 : 0.0, dist = 0.0, wo = 0.0, rad = 0.0;
    vec4 col = vec4(0.0, 0.0, 0.0, 1.0);
    if (feature == 0) VORONOI_DIM(node_tex_voronoi_f1)
    else if (feature == 1) VORONOI_DIM(node_tex_voronoi_f2)
    else if (feature == 2) VORONOI_DIM(node_tex_voronoi_smooth_f1)
    else if (feature == 3) VORONOI_DIM(node_tex_voronoi_distance_to_edge)
    else VORONOI_DIM(node_tex_voronoi_n_sphere_radius)
    if (output_index == 0) return grey(dist);
    if (output_index == 1) return premultiply(col);
    if (output_index == 2) return vec4(pos, 1.0);
    return grey(output_index == 3 ? wo : rad);
}
