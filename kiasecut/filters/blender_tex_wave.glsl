// @filter [Blender] Wave Texture
// @category Blender
// @description Blender 的波浪紋理：條紋或同心圓，正弦、鋸齒、三角波，可加噪訊扭曲；調相位可以讓它移動
// @param kind menu 條紋 "條紋|圓環" "類型"
// @param direction menu X "X|Y|對角" "條紋方向"
// @param profile menu 正弦 "正弦|鋸齒|三角" "波形"
// @param color1 color #000000 "顏色 1"
// @param color2 color #ffffff "顏色 2"
// @param distortion float 0 -1000 1000 "扭曲"
// @param detail_scale float 1 -1000 1000 "細節比例"
// @param detail float 2 0 15 "細節"
// @param roughness float 0.5 0 1 "粗糙度"
// @param phase float 0 -1000 1000 "相位"
// @param tex_scale float 5 0.001 1000 "比例"
// @param offset vec2 0,0 -1000 1000 "位置"
// @param amount float 1 0 1 "強度"

// Source: the Wave Texture shader node of Blender (source/blender/gpu/shaders/material/
// gpu_shader_material_tex_*.glsl), rewritten by hand for KiaseCut - the same pattern and parameters,
// the cell/hash randomness is not bit-identical with Blender. The coordinates are Blender's image
// coordinates (the long side -1..1, y up) times 比例. Where the clip is transparent it stays so;
// 強度 mixes the pattern over the clip's own colours.
// Blender: https://github.com/blender/blender
// SPDX-FileCopyrightText: Blender Authors (original, GPL-2.0-or-later); KiaseCut
// SPDX-License-Identifier: GPL-3.0-or-later

vec3 tex_co(vec2 uv) {
    vec2 R = resolution;
    return vec3(vec2(uv.x * 2.0 - 1.0, 1.0 - uv.y * 2.0) * R / max(R.x, R.y) * tex_scale + offset, 0.0);
}
vec3 pcg3(uvec3 v) {
    v = v * 1664525u + 1013904223u;
    v.x += v.y * v.z; v.y += v.z * v.x; v.z += v.x * v.y;
    v ^= v >> 16u;
    v.x += v.y * v.z; v.y += v.z * v.x; v.z += v.x * v.y;
    return vec3(v) * (1.0 / 4294967295.0);
}
vec3 hash2(vec2 c) { return pcg3(uvec3(uint(int(c.x) + 65536), uint(int(c.y) + 65536), 7u)); }
vec4 finish(vec2 uv, vec3 rgb) {
    vec4 c = src(uv);
    vec3 base = c.a > 0.0 ? c.rgb / c.a : vec3(0.0);
    return vec4(mix(base, rgb, amount) * c.a, c.a);
}

// ---- Blender's perlin noise (as in replace_color.glsl) ---
// Blender's perlin noise (Jenkins lookup3 hash + gradient noise), 3D and 4D
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
uint hash3(int x, int y, int z) {
    uint a, b, c; a = b = c = 0xdeadbeefu + (3u << 2u) + 13u;
    a += uint(x); b += uint(y); c += uint(z);
    jfinal(a, b, c); return c;
}
uint hash4(int x, int y, int z, int w) {
    uint a, b, c; a = b = c = 0xdeadbeefu + (4u << 2u) + 13u;
    a += uint(x); b += uint(y); c += uint(z);
    jmix(a, b, c);
    a += uint(w);
    jfinal(a, b, c); return c;
}
float nfade(float t) { return t * t * t * (t * (t * 6.0 - 15.0) + 10.0); }
float ngrad3(uint h, float x, float y, float z) {
    h &= 15u;
    float u = h < 8u ? x : y;
    float vt = (h == 12u || h == 14u) ? x : z;
    float v = h < 4u ? y : vt;
    return (((h & 1u) != 0u) ? -u : u) + (((h & 2u) != 0u) ? -v : v);
}
float ngrad4(uint h, float x, float y, float z, float w) {
    h &= 31u;
    float u = h < 24u ? x : y;
    float v = h < 16u ? y : z;
    float s = h < 8u ? z : w;
    return (((h & 1u) != 0u) ? -u : u) + (((h & 2u) != 0u) ? -v : v) + (((h & 4u) != 0u) ? -s : s);
}
float gnoise3(vec3 p) {
    vec3 fl3 = floor(p);
    ivec3 i = ivec3(fl3);
    vec3 f = p - fl3;
    float u = nfade(f.x), v = nfade(f.y), w = nfade(f.z);
    float r = mix(
        mix(mix(ngrad3(hash3(i.x, i.y, i.z), f.x, f.y, f.z), ngrad3(hash3(i.x + 1, i.y, i.z), f.x - 1.0, f.y, f.z), u),
            mix(ngrad3(hash3(i.x, i.y + 1, i.z), f.x, f.y - 1.0, f.z), ngrad3(hash3(i.x + 1, i.y + 1, i.z), f.x - 1.0, f.y - 1.0, f.z), u), v),
        mix(mix(ngrad3(hash3(i.x, i.y, i.z + 1), f.x, f.y, f.z - 1.0), ngrad3(hash3(i.x + 1, i.y, i.z + 1), f.x - 1.0, f.y, f.z - 1.0), u),
            mix(ngrad3(hash3(i.x, i.y + 1, i.z + 1), f.x, f.y - 1.0, f.z - 1.0), ngrad3(hash3(i.x + 1, i.y + 1, i.z + 1), f.x - 1.0, f.y - 1.0, f.z - 1.0), u), v), w);
    return 0.9820 * r;
}
float gnoise4(vec4 p) {
    vec4 fl4 = floor(p);
    ivec4 i = ivec4(fl4);
    vec4 f = p - fl4;
    float u = nfade(f.x), v = nfade(f.y), t = nfade(f.z), s = nfade(f.w);
    float c[16];
    for (int k = 0; k < 16; k++) {
        int dx = k & 1, dy = (k >> 1) & 1, dz = (k >> 2) & 1, dw = (k >> 3) & 1;
        c[k] = ngrad4(hash4(i.x + dx, i.y + dy, i.z + dz, i.w + dw), f.x - float(dx), f.y - float(dy), f.z - float(dz), f.w - float(dw));
    }
    float r0 = mix(mix(mix(c[0], c[1], u), mix(c[2], c[3], u), v), mix(mix(c[4], c[5], u), mix(c[6], c[7], u), v), t);
    float r1 = mix(mix(mix(c[8], c[9], u), mix(c[10], c[11], u), v), mix(mix(c[12], c[13], u), mix(c[14], c[15], u), v), t);
    return 0.8344 * mix(r0, r1, s);
}
float fbm3(vec3 p, float detail, float rough, float lac, bool normalize_) {
    float sum = 0.0, amp = 1.0, maxamp = 0.0;
    detail = clamp(detail, 0.0, 15.0);
    int n = int(floor(detail));
    for (int i = 0; i <= 15; i++) {
        if (i > n) break;
        float t = gnoise3(p);
        sum += t * amp; maxamp += amp; amp *= rough; p *= lac;
    }
    float rmd = detail - floor(detail);
    if (rmd > 0.0) {
        float t = gnoise3(p);
        float s2 = sum + t * amp, m2 = maxamp + amp;
        return normalize_ ? mix(0.5 * sum / maxamp + 0.5, 0.5 * s2 / m2 + 0.5, rmd) : mix(sum, s2, rmd);
    }
    return normalize_ ? 0.5 * sum / maxamp + 0.5 : sum;
}
float fbm4(vec4 p, float detail, float rough, float lac, bool normalize_) {
    float sum = 0.0, amp = 1.0, maxamp = 0.0;
    detail = clamp(detail, 0.0, 15.0);
    int n = int(floor(detail));
    for (int i = 0; i <= 15; i++) {
        if (i > n) break;
        float t = gnoise4(p);
        sum += t * amp; maxamp += amp; amp *= rough; p *= lac;
    }
    float rmd = detail - floor(detail);
    if (rmd > 0.0) {
        float t = gnoise4(p);
        float s2 = sum + t * amp, m2 = maxamp + amp;
        return normalize_ ? mix(0.5 * sum / maxamp + 0.5, 0.5 * s2 / m2 + 0.5, rmd) : mix(sum, s2, rmd);
    }
    return normalize_ ? 0.5 * sum / maxamp + 0.5 : sum;
}

vec4 effect(vec2 uv) {
    vec3 p = tex_co(uv);
    float n;
    if (kind == 0) n = direction == 0 ? p.x : (direction == 1 ? p.y : (p.x + p.y) * 0.5);
    else n = length(p);
    n *= 20.0;
    n += phase;
    if (distortion != 0.0) n += distortion * (fbm3(p * detail_scale, detail, roughness, 2.0, true) * 2.0 - 1.0);
    float w;
    if (profile == 0) w = 0.5 + 0.5 * sin(n - 1.57079632679);
    else if (profile == 1) { n /= 6.28318530718; w = n - floor(n); }
    else { n /= 6.28318530718; w = abs(n - floor(n + 0.5)) * 2.0; }
    return finish(uv, mix(color1.rgb, color2.rgb, w));
}
