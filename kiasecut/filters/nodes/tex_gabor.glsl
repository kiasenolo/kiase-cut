// @filter Gabor 紋理
// @category 紋理
// @description 節點用：照 Blender 的「Gabor 紋理」節點：Gabor 核疊成的條紋雜訊，可以指定方向。類型 2D（用向量的 X Y，方向是角度）或 3D（方向是向量）。向量沒接線就用影像座標。輸出「數值」、「相位」和「強度」（都是灰階）
// @source "向量"
// @input in_scale "比例" tex_scale
// @input in_freq "頻率" frequency
// @input in_aniso "各向異性" anisotropy
// @input in_angle "方向" orientation_2d
// @input in_dir "方向（向量）"
// @output value "數值"
// @output phase "相位"
// @output intensity "強度"
// @param gabor_type menu 2D "2D|3D" "類型"
// @param tex_scale float 5 -1000000 1000000 "比例"
// @param frequency float 2 0 1000000 "頻率"
// @param anisotropy float 1 0 1 "各向異性"
// @param orientation_2d float 0.7853981852531433 -1000000 1000000 "方向"
// @param orientation_3d vec3 1.4142135381698608,1.4142135381698608,0 -1000000 1000000 "方向（向量）"
// @show orientation_2d gabor_type == 2D
// @show in_angle gabor_type == 2D
// @show orientation_3d gabor_type == 3D
// @show in_dir gabor_type == 3D
// @socket in - vector
// @socket in in_dir vector
// @socket out value float
// @socket out phase float
// @socket out intensity float

// Reimplementation of Blender's Gabor Texture shader node as a compositor node: the sockets, settings and shader code are Blender's (gpu_shader_material_tex_gabor.glsl, gpu_shader_common_hash.glsl), checked against Blender 5.2.
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
#define SHD_GABOR_TYPE_2D 0.0
#define SHD_GABOR_TYPE_3D 1.0
#define IMPULSES_COUNT 8
vec2 compute_2d_gabor_kernel(vec2 position, float frequency, float orientation)
{
  float distance_squared = length_squared(position);
  float hann_window = 0.5 + 0.5 * cos(M_PI * distance_squared);
  float gaussian_envelop = exp(-M_PI * distance_squared);
  float windowed_gaussian_envelope = gaussian_envelop * hann_window;
  vec2 frequency_vector = frequency * vec2(cos(orientation), sin(orientation));
  float angle = 2.0 * M_PI * dot(position, frequency_vector);
  vec2 phasor = vec2(cos(angle), sin(angle));
  return windowed_gaussian_envelope * phasor;
}
float compute_2d_gabor_standard_deviation()
{
  float integral_of_gabor_squared = 0.25;
  float second_moment = 0.5;
  return sqrt(IMPULSES_COUNT * second_moment * integral_of_gabor_squared);
}
vec2 compute_2d_gabor_noise_cell(
    vec2 cell, vec2 position, float frequency, float isotropy, float base_orientation)
{
  vec2 noise = vec2(0.0);
  for (int i = 0; i < IMPULSES_COUNT; ++i) {
    vec3 seed_for_orientation = vec3(cell, i * 3);
    vec3 seed_for_kernel_center = vec3(cell, i * 3 + 1);
    vec3 seed_for_weight = vec3(cell, i * 3 + 2);
    float random_orientation = (hash_vec3_to_float(seed_for_orientation) - 0.5) * M_PI;
    float orientation = base_orientation + random_orientation * isotropy;
    vec2 kernel_center = hash_vec3_to_vec2(seed_for_kernel_center);
    vec2 position_in_kernel_space = position - kernel_center;
    if (length_squared(position_in_kernel_space) >= 1.0) {
      continue;
    }
    float weight = hash_vec3_to_float(seed_for_weight) < 0.5 ? -1.0 : 1.0;
    noise += weight * compute_2d_gabor_kernel(position_in_kernel_space, frequency, orientation);
  }
  return noise;
}
vec2 compute_2d_gabor_noise(vec2 coordinates,
                              float frequency,
                              float isotropy,
                              float base_orientation)
{
  vec2 cell_position = floor(coordinates);
  vec2 local_position = coordinates - cell_position;
  vec2 sum = vec2(0.0);
  for (int j = -1; j <= 1; j++) {
    for (int i = -1; i <= 1; i++) {
      vec2 cell_offset = vec2(i, j);
      vec2 current_cell_position = cell_position + cell_offset;
      vec2 position_in_cell_space = local_position - cell_offset;
      sum += compute_2d_gabor_noise_cell(
          current_cell_position, position_in_cell_space, frequency, isotropy, base_orientation);
    }
  }
  return sum;
}
vec2 compute_3d_gabor_kernel(vec3 position, float frequency, vec3 orientation)
{
  float distance_squared = length_squared(position);
  float hann_window = 0.5 + 0.5 * cos(M_PI * distance_squared);
  float gaussian_envelop = exp(-M_PI * distance_squared);
  float windowed_gaussian_envelope = gaussian_envelop * hann_window;
  vec3 frequency_vector = frequency * orientation;
  float angle = 2.0 * M_PI * dot(position, frequency_vector);
  vec2 phasor = vec2(cos(angle), sin(angle));
  return windowed_gaussian_envelope * phasor;
}
float compute_3d_gabor_standard_deviation()
{
  float integral_of_gabor_squared = 1.0 / (4.0 * M_SQRT2);
  float second_moment = 0.5;
  return sqrt(IMPULSES_COUNT * second_moment * integral_of_gabor_squared);
}
vec3 compute_3d_orientation(vec3 orientation, float isotropy, vec4 seed)
{
  if (isotropy == 0.0) {
    return orientation;
  }
  float inclination = acos(orientation.z);
  float azimuth = sign(orientation.y) * acos(orientation.x / length(orientation.xy));
  vec2 random_angles = hash_vec4_to_vec2(seed) * M_PI;
  inclination += random_angles.x * isotropy;
  azimuth += random_angles.y * isotropy;
  return vec3(
      sin(inclination) * cos(azimuth), sin(inclination) * sin(azimuth), cos(inclination));
}
vec2 compute_3d_gabor_noise_cell(
    vec3 cell, vec3 position, float frequency, float isotropy, vec3 base_orientation)
{
  vec2 noise = vec2(0.0);
  for (int i = 0; i < IMPULSES_COUNT; ++i) {
    vec4 seed_for_orientation = vec4(cell, i * 3);
    vec4 seed_for_kernel_center = vec4(cell, i * 3 + 1);
    vec4 seed_for_weight = vec4(cell, i * 3 + 2);
    vec3 orientation = compute_3d_orientation(base_orientation, isotropy, seed_for_orientation);
    vec3 kernel_center = hash_vec4_to_vec3(seed_for_kernel_center);
    vec3 position_in_kernel_space = position - kernel_center;
    if (length_squared(position_in_kernel_space) >= 1.0) {
      continue;
    }
    float weight = hash_vec4_to_float(seed_for_weight) < 0.5 ? -1.0 : 1.0;
    noise += weight * compute_3d_gabor_kernel(position_in_kernel_space, frequency, orientation);
  }
  return noise;
}
vec2 compute_3d_gabor_noise(vec3 coordinates,
                              float frequency,
                              float isotropy,
                              vec3 base_orientation)
{
  vec3 cell_position = floor(coordinates);
  vec3 local_position = coordinates - cell_position;
  vec2 sum = vec2(0.0);
  for (int k = -1; k <= 1; k++) {
    for (int j = -1; j <= 1; j++) {
      for (int i = -1; i <= 1; i++) {
        vec3 cell_offset = vec3(i, j, k);
        vec3 current_cell_position = cell_position + cell_offset;
        vec3 position_in_cell_space = local_position - cell_offset;
        sum += compute_3d_gabor_noise_cell(
            current_cell_position, position_in_cell_space, frequency, isotropy, base_orientation);
      }
    }
  }
  return sum;
}
void node_tex_gabor(vec3 coordinates,
                    float scale,
                    float frequency,
                    float anisotropy,
                    float orientation_2d,
                    vec3 orientation_3d,
                    float type,
                    out float output_value,
                    out float output_phase,
                    out float output_intensity)
{
  vec3 scaled_coordinates = coordinates * scale;
  float isotropy = 1.0 - clamp(anisotropy, 0.0, 1.0);
  frequency = max(0.001, frequency);
  vec2 phasor = vec2(0.0);
  float standard_deviation = 1.0;
  if (type == SHD_GABOR_TYPE_2D) {
    phasor = compute_2d_gabor_noise(scaled_coordinates.xy, frequency, isotropy, orientation_2d);
    standard_deviation = compute_2d_gabor_standard_deviation();
  }
  else if (type == SHD_GABOR_TYPE_3D) {
    vec3 orientation = normalize(orientation_3d);
    phasor = compute_3d_gabor_noise(scaled_coordinates, frequency, isotropy, orientation);
    standard_deviation = compute_3d_gabor_standard_deviation();
  }
  float normalization_factor = 6.0 * standard_deviation;
  output_value = (phasor.y / normalization_factor) * 0.5 + 0.5;
  output_phase = (atan(phasor.y, phasor.x) + M_PI) / (2.0 * M_PI);
  output_intensity = length(phasor) / normalization_factor;
}

vec4 effect(vec2 uv) {
    float v, p, i;
    node_tex_gabor(vector_in(uv), num(has_input_in_scale(), input_in_scale(uv), tex_scale), num(has_input_in_freq(), input_in_freq(uv), frequency),
                   num(has_input_in_aniso(), input_in_aniso(uv), anisotropy), num(has_input_in_angle(), input_in_angle(uv), orientation_2d),
                   (has_input_in_dir() ? unpremultiply(input_in_dir(uv)).rgb : orientation_3d), float(gabor_type), v, p, i);
    return grey(output_index == 0 ? v : output_index == 1 ? p : i);
}
