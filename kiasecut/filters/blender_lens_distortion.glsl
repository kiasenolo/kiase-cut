// @filter [Blender] Lens Distortion
// @category Blender
// @description Blender 合成器的 Lens Distortion：鏡頭的桶狀／枕狀變形和色散（照 Blender 的做法，在線性光裡運算）；「水平」是投影機式的左右色散
// @param mode menu 放射 "放射|水平" "類型"
// @param distortion float 0 -0.999 1 "變形"
// @param dispersion float 0 0 1 "色散"
// @param jitter bool false "抖動取樣"
// @param fit bool false "填滿畫面"

// Source: Blender's Lens Distortion compositor node, ported step by step for KiaseCut (checked against
// Blender 5.2's own renders: the same up to 8-bit rounding, see tests/test_builtin_filters.py).
// The outputs of KiaseCut are premultiplied, so the colour is kept within the alpha (Blender's colour can
// exceed it where its alpha is less than 1: the picture's edge in 水平, and where 抖動取樣's random weights
// do not sum to what they should).
// Blender: https://github.com/blender/blender
//   source/blender/nodes/composite/nodes/node_composite_lens_distortion.cc
//   source/blender/compositor/shaders/compositor_radial_lens_distortion.glsl
//   source/blender/compositor/shaders/compositor_horizontal_lens_distortion.glsl
// SPDX-FileCopyrightText: Blender Authors (original); KiaseCut
// SPDX-License-Identifier: GPL-3.0-or-later
// (Blender's code is GPL-2.0-or-later.)

vec3 srgb_to_lin(vec3 c) { return mix(c / 12.92, pow((c + 0.055) / 1.055, vec3(2.4)), step(vec3(0.04045), c)); }
vec3 lin_to_srgb(vec3 c) { c = clamp(c, 0.0, 1.0); return mix(c * 12.92, 1.055 * pow(c, vec3(1.0 / 2.4)) - 0.055, step(vec3(0.0031308), c)); }

// linear, premultiplied, bilinear in linear light as Blender samples (the card would blend the sRGB values);
// nothing outside the picture (Blender leaves it empty: the edge texels blend with nothing)
vec4 texel(ivec2 i, ivec2 n) {
    if (i.x < 0 || i.y < 0 || i.x >= n.x || i.y >= n.y) return vec4(0.0);
    vec4 c = unpremultiply(texelFetch(source, i, 0));
    return vec4(srgb_to_lin(c.rgb) * c.a, c.a);
}
vec4 lin(vec2 p) {
    ivec2 n = textureSize(source, 0);
    vec2 t = p * vec2(n) - 0.5;
    ivec2 i = ivec2(floor(t));
    vec2 f = t - vec2(i);
    return mix(mix(texel(i, n), texel(i + ivec2(1, 0), n), f.x),
               mix(texel(i + ivec2(0, 1), n), texel(i + ivec2(1, 1), n), f.x), f.y);
}

vec4 encode(vec4 c) {
    float a = clamp(c.a, 0.0, 1.0);
    vec3 rgb = a > 0.0 ? lin_to_srgb(c.rgb / a) * a : vec3(0.0);
    return vec4(min(rgb, vec3(a)), a);
}

// Blender's hash (Jenkins lookup3, gpu_shader_common_hash) for the jitter
uint rot(uint x, int k) { return (x << uint(k)) | (x >> uint(32 - k)); }
uint hash_uint3(uint kx, uint ky, uint kz) {
    uint a, b, c;
    a = b = c = 0xdeadbeefu + (3u << 2u) + 13u;
    c += kz; b += ky; a += kx;
    c ^= b; c -= rot(b, 14);
    a ^= c; a -= rot(c, 11);
    b ^= a; b -= rot(a, 25);
    c ^= b; c -= rot(b, 16);
    a ^= c; a -= rot(c, 4);
    b ^= a; b -= rot(a, 14);
    c ^= b; c -= rot(b, 24);
    return c;
}
float hash_uint3_to_float(uint kx, uint ky, uint kz) { return float(hash_uint3(kx, ky, kz)) / float(0xFFFFFFFFu); }

// Blender's radial lens distortion (compositor_radial_lens_distortion.glsl), the same steps in the same order;
// the integration steps are capped at STEPS_MAX per half (Blender's have no cap: a spread of 1000 px
// or more is already past anything a picture shows)
#define STEPS_MAX 1024
vec3 chromatic_distortion;                  // red, green, blue: the distortion times 4
vec2 tex_size;
ivec2 texel_px;                             // (Blender's rows count from the bottom)

float compute_distortion_scale(float distortion, float distance_squared) {
    return 1.0 / (1.0 + sqrt(max(0.0, 1.0 - distortion * distance_squared)));
}
vec3 compute_chromatic_distortion_scale(float distance_squared) {
    return 1.0 / (1.0 + sqrt(max(vec3(0.0), 1.0 - chromatic_distortion * distance_squared)));
}
vec2 compute_distorted_uv(vec2 uv, float uv_scale) { return (uv * uv_scale + 0.5) * tex_size; }

int compute_number_of_integration_steps_heuristic(float distortion) {
    if (jitter)
        return distortion < 4.0 ? 2 : int(sqrt(distortion + 1.0));
    return int(min(distortion + 1.0, float(STEPS_MAX)));
}
ivec4 compute_number_of_integration_steps(vec2 uv, float distance_squared) {
    vec3 distortion_scale = compute_chromatic_distortion_scale(distance_squared);
    vec2 distorted_uv_red = compute_distorted_uv(uv, distortion_scale.r);
    vec2 distorted_uv_green = compute_distorted_uv(uv, distortion_scale.g);
    vec2 distorted_uv_blue = compute_distorted_uv(uv, distortion_scale.b);
    int steps_red = compute_number_of_integration_steps_heuristic(distance(distorted_uv_red, distorted_uv_green));
    int steps_blue = compute_number_of_integration_steps_heuristic(distance(distorted_uv_green, distorted_uv_blue));
    return ivec4(steps_red, steps_red + steps_blue, steps_blue, steps_red + steps_blue);
}
float get_jitter(int seed) {
    if (jitter)
        return hash_uint3_to_float(uint(texel_px.x), uint(texel_px.y), uint(seed));
    return 0.5;
}
vec4 integrate_distortion(int start, int end, float distance_squared, vec2 uv, int steps) {
    vec4 accumulated_color = vec4(0.0);
    float distortion_amount = chromatic_distortion[end] - chromatic_distortion[start];
    for (int i = 0; i < steps; i++) {
        float increment = (float(i) + get_jitter(start * steps + i)) / float(steps);
        float distortion = chromatic_distortion[start] + increment * distortion_amount;
        float distortion_scale = compute_distortion_scale(distortion, distance_squared);
        vec2 distorted_uv = compute_distorted_uv(uv, distortion_scale);
        vec4 color = lin(distorted_uv / tex_size);
        accumulated_color[start] += (1.0 - increment) * color[start];
        accumulated_color[end] += increment * color[end];
        accumulated_color.w += color.w;
    }
    return accumulated_color;
}

vec4 effect(vec2 uv_in) {
    tex_size = vec2(textureSize(source, 0));
    if (mode == 1) {                          // 水平 (Blender's projector): red and blue 5 px apart per unit of dispersion
        float shift = 5.0 * clamp(dispersion, 0.0, 1.0) / tex_size.x;
        vec4 red = lin(uv_in + vec2(shift, 0.0));
        vec4 green = lin(uv_in);
        vec4 blue = lin(uv_in - vec2(shift, 0.0));
        return encode(vec4(red.r, green.g, blue.b, (red.a + green.a + blue.a) / 3.0));
    }
    float green_distortion = clamp(distortion, -0.999, 1.0);
    float disp = clamp(dispersion, 0.0, 1.0) / 4.0;
    vec3 d3 = vec3(clamp(green_distortion + disp, -0.999, 1.0), green_distortion, clamp(green_distortion - disp, -0.999, 1.0));
    chromatic_distortion = d3 * 4.0;
    float maximum_distortion = max(d3.x, max(d3.y, d3.z));
    float scale_ = (fit && maximum_distortion > 0.0) ? 1.0 / (1.0 + 2.0 * maximum_distortion) : 1.0 / (1.0 + maximum_distortion);

    texel_px = ivec2(floor(uv_in.x * tex_size.x), tex_size.y - 1.0 - floor(uv_in.y * tex_size.y));
    vec2 center = tex_size / 2.0;
    vec2 uv = scale_ * (floor(uv_in * tex_size) + vec2(0.5) - center) / center;
    float distance_squared = dot(uv, uv);

    // if any of the colour channels gets distorted outside of the screen beyond what is possible: nothing
    if (any(greaterThan(chromatic_distortion * distance_squared, vec3(1.0))))
        return vec4(0.0);

    ivec4 number_of_steps = compute_number_of_integration_steps(uv, distance_squared);
    vec4 color = vec4(0.0);
    color += integrate_distortion(0, 1, distance_squared, uv, number_of_steps.r);
    color += integrate_distortion(1, 2, distance_squared, uv, number_of_steps.b);
    color *= vec4(vec3(2.0), 1.0) / vec4(number_of_steps);
    return encode(color);
}
