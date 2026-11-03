// @filter [Blender] Texture / White Noise
// @category Blender
// @description Blender 的白噪訊紋理：每個點各自隨機的雜訊（沒有連貫），有「數值」（灰階）和「顏色」兩個輸出；1D 到 4D，調 Z／W 會整張換一個樣子
// @output value "數值"
// @output color "顏色"
// @param dims menu 3D "1D|2D|3D|4D" "維度"
// @param z float 0 -1000 1000 "Z（3D、4D）"
// @param w float 0 -1000 1000 "W（1D、4D）"
// @param tex_scale float 5 0.001 1000 "比例"
// @param offset vec2 0,0 -1000 1000 "位置"
// @param amount float 1 0 1 "強度"
// @enable z dims == 3D|4D
// @enable w dims == 1D|4D

// Source: the White Noise Texture shader node of Blender (source/blender/gpu/shaders/common/
// gpu_shader_common_hash.glsl and material/gpu_shader_material_tex_white_noise.glsl), rewritten by hand
// for KiaseCut - the same Jenkins hash of the coordinates' float bits, so every point is its own random
// value. The coordinates are Blender's image coordinates (the long side -1..1, y up) times 比例.
// Where the clip is transparent it stays so; 強度 mixes the pattern over the clip's own colours.
// Blender: https://github.com/blender/blender
// SPDX-FileCopyrightText: Blender Authors (original, GPL-2.0-or-later); KiaseCut
// SPDX-License-Identifier: GPL-3.0-or-later

vec3 tex_co(vec2 uv) {
    vec2 R = resolution;
    return vec3(vec2(uv.x * 2.0 - 1.0, 1.0 - uv.y * 2.0) * R / max(R.x, R.y) * tex_scale + offset, z);
}
uint rotl(uint x, uint k) { return (x << k) | (x >> (32u - k)); }
void jmix(inout uint a, inout uint b, inout uint c) {
    a -= c; a ^= rotl(c, 4u);  c += b;
    b -= a; b ^= rotl(a, 6u);  a += c;
    c -= b; c ^= rotl(b, 8u);  b += a;
    a -= c; a ^= rotl(c, 16u); c += b;
    b -= a; b ^= rotl(a, 19u); a += c;
    c -= b; c ^= rotl(b, 4u);  b += a;
}
void jfinal(inout uint a, inout uint b, inout uint c) {
    c ^= b; c -= rotl(b, 14u);
    a ^= c; a -= rotl(c, 11u);
    b ^= a; b -= rotl(a, 25u);
    c ^= b; c -= rotl(b, 16u);
    a ^= c; a -= rotl(c, 4u);
    b ^= a; b -= rotl(a, 14u);
    c ^= b; c -= rotl(b, 24u);
}
uint hash1(uint kx) {
    uint a = 0xdeadbeefu + (1u << 2) + 13u, b = a, c = a;
    a += kx;
    jfinal(a, b, c);
    return c;
}
uint hash2(uint kx, uint ky) {
    uint a = 0xdeadbeefu + (2u << 2) + 13u, b = a, c = a;
    b += ky; a += kx;
    jfinal(a, b, c);
    return c;
}
uint hash3(uint kx, uint ky, uint kz) {
    uint a = 0xdeadbeefu + (3u << 2) + 13u, b = a, c = a;
    c += kz; b += ky; a += kx;
    jfinal(a, b, c);
    return c;
}
uint hash4(uint kx, uint ky, uint kz, uint kw) {
    uint a = 0xdeadbeefu + (4u << 2) + 13u, b = a, c = a;
    a += kx; b += ky; c += kz;
    jmix(a, b, c);
    a += kw;
    jfinal(a, b, c);
    return c;
}
float unit(uint h) { return float(h) * (1.0 / 4294967295.0); }
uint fb(float f) { return floatBitsToUint(f); }

// Blender: hash_{float,vec2,vec3,vec4}_to_float; the colour hashes the point with its coordinates rotated
float one(vec4 p, int k) {
    if (dims == 0) return unit(hash1(fb(p.w + 0.01 * float(k))));
    if (dims == 1) return unit(k == 0 ? hash2(fb(p.x), fb(p.y)) : k == 1 ? hash3(fb(p.x), fb(p.y), 0u) : hash3(fb(p.y), fb(p.x), 0u));
    if (dims == 2) return unit(k == 0 ? hash3(fb(p.x), fb(p.y), fb(p.z)) : k == 1 ? hash3(fb(p.z), fb(p.x), fb(p.y)) : hash3(fb(p.y), fb(p.z), fb(p.x)));
    return unit(k == 0 ? hash4(fb(p.x), fb(p.y), fb(p.z), fb(p.w)) : k == 1 ? hash4(fb(p.z), fb(p.x), fb(p.y), fb(p.w))
                                                                     : hash4(fb(p.y), fb(p.z), fb(p.x), fb(p.w)));
}

vec4 effect(vec2 uv) {
    vec3 t = tex_co(uv);
    vec4 p = vec4(t, w);
    vec3 rgb = output_index == 0 ? vec3(one(p, 0)) : vec3(one(p, 0), one(p, 1), one(p, 2));
    vec4 c = src(uv);
    vec3 base = c.a > 0.0 ? c.rgb / c.a : vec3(0.0);
    return vec4(mix(base, rgb, amount) * c.a, c.a);
}
