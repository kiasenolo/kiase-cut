// @filter 分形雜訊
// @category 紋理
// @description 節點用：2D 雜訊疊層。基底：Value（格點放隨機值，偏方塊感）、Simplex（三角形格子，方向性痕跡少）、Perlin。疊加：fBm、湍流（每層取絕對值，像火焰）、山脊（每層取 (1 − |n|)²，像山脊、閃電）。向量沒接線就用影像座標（長邊 -1 到 1，Y 向上）。Seed 換一個數就是另一張圖。輸出「係數」（灰階）和「顏色」（三個各自獨立的雜訊）
// @source "向量"
// @input in_scale "比例" tex_scale
// @input in_detail "層數" detail
// @input in_lacunarity "間隙度" lacunarity
// @input in_gain "增益" gain
// @output fac "係數"
// @output color "顏色"
// @param basis menu Simplex "Value|Simplex|Perlin" "基底"
// @param ntype menu fBM "fBM|湍流|山脊" "疊加"
// @param tex_scale float 5 -1000000 1000000 "比例"
// @param seed int 0 0 1000000 "Seed"
// @param offset vec2 0,0 -1000000 1000000 "偏移"
// @param detail float 3 0 11 "層數"
// @param lacunarity float 2 -1000 1000 "間隙度"
// @param gain float 0.5 0 1 "增益"
// @bake basis ntype
// @socket in - vector
// @socket out fac float
// @socket out color color

// SPDX-FileCopyrightText: KiaseCut
// SPDX-License-Identifier: GPL-3.0-or-later

vec3 uniform_coords(vec2 uv) {          // (as the other texture nodes' unlinked Vector)
    vec2 R = resolution, p = vec2(uv.x, 1.0 - uv.y) * R, q = floor(p) + 0.5;
    if (all(lessThan(abs(p - q), vec2(0.002)))) p = q;
    return vec3((p - R / 2.0) / max(R.x, R.y) * 2.0, 0.0);
}
vec3 vector_in(vec2 uv) { return has_src() ? unpremultiply(src(uv)).rgb : uniform_coords(uv); }
float num(bool linked, vec4 c, float field) { return linked ? dot(c.rgb, vec3(0.2126, 0.7152, 0.0722)) * (c.a > 0.0 ? 1.0 : 0.0) : field; }

// three numbers 0 - 1 of a cell (pcg3d)
vec3 cell_hash(ivec2 c, int s) {
    uvec3 v = uvec3(ivec3(c, s)) * 1664525u + 1013904223u;
    v.x += v.y * v.z; v.y += v.z * v.x; v.z += v.x * v.y;
    v ^= v >> 16u;
    v.x += v.y * v.z; v.y += v.z * v.x; v.z += v.x * v.y;
    return vec3(v >> 8u) / 16777216.0;
}
vec2 cell_grad(ivec2 c, int s) {
    float a = cell_hash(c, s).x * 6.28318530718;
    return vec2(cos(a), sin(a));
}
// each basis gives about -1 to 1
float value_noise(vec2 p, int s) {
    ivec2 i = ivec2(floor(p));
    vec2 f = fract(p), u = f * f * f * (f * (f * 6.0 - 15.0) + 10.0);
    float a = cell_hash(i, s).x, b = cell_hash(i + ivec2(1, 0), s).x;
    float c = cell_hash(i + ivec2(0, 1), s).x, d = cell_hash(i + ivec2(1, 1), s).x;
    return mix(mix(a, b, u.x), mix(c, d, u.x), u.y) * 2.0 - 1.0;
}
float perlin_noise(vec2 p, int s) {
    ivec2 i = ivec2(floor(p));
    vec2 f = fract(p), u = f * f * f * (f * (f * 6.0 - 15.0) + 10.0);
    float a = dot(cell_grad(i, s), f), b = dot(cell_grad(i + ivec2(1, 0), s), f - vec2(1.0, 0.0));
    float c = dot(cell_grad(i + ivec2(0, 1), s), f - vec2(0.0, 1.0)), d = dot(cell_grad(i + ivec2(1, 1), s), f - vec2(1.0));
    return mix(mix(a, b, u.x), mix(c, d, u.x), u.y) * 1.41421356237;
}
float simplex_corner(vec2 d, ivec2 c, int s) {
    float t = max(0.5 - dot(d, d), 0.0);
    return t * t * t * t * dot(cell_grad(c, s), d);
}
float simplex_noise(vec2 p, int s) {
    const float F = 0.36602540378, G = 0.21132486541;
    ivec2 i = ivec2(floor(p + (p.x + p.y) * F));
    vec2 a = p - vec2(i) + float(i.x + i.y) * G;
    ivec2 o = a.x > a.y ? ivec2(1, 0) : ivec2(0, 1);
    vec2 b = a - vec2(o) + G, c = a - 1.0 + 2.0 * G;
    return 99.2 * (simplex_corner(a, i, s) + simplex_corner(b, i + o, s) + simplex_corner(c, i + ivec2(1), s));
}
float base_noise(vec2 p, int s) { return basis == 0 ? value_noise(p, s) : basis == 1 ? simplex_noise(p, s) : perlin_noise(p, s); }

// the layers added up, 0 - 1; a fraction of 層數 fades its last layer in
float fractal(vec2 p, int s, float layers, float lac, float gn) {
    float sum = 0.0, total = 0.0, amp = 1.0, freq = 1.0;
    int last = int(ceil(layers));
    for (int o = 0; o <= last; o++) {
        float w = amp * (o == 0 ? 1.0 : clamp(layers - float(o - 1), 0.0, 1.0));
        float n = base_noise(p * freq, s * 64 + o);
        if (ntype == 1) n = abs(n);
        else if (ntype == 2) { n = max(1.0 - abs(n), 0.0); n *= n; }
        sum += w * n;
        total += w;
        amp *= gn;
        freq *= lac;
    }
    float v = sum / max(total, 1e-6);
    return ntype == 0 ? v * 0.5 + 0.5 : v;
}

vec4 effect(vec2 uv) {
    float sc = num(has_input_in_scale(), input_in_scale(uv), tex_scale);
    float dt = clamp(num(has_input_in_detail(), input_in_detail(uv), detail), 0.0, 11.0);
    float lc = num(has_input_in_lacunarity(), input_in_lacunarity(uv), lacunarity);
    float gn = max(num(has_input_in_gain(), input_in_gain(uv), gain), 0.0);
    vec2 p = vector_in(uv).xy * sc + offset;
    float r = fractal(p, seed * 3, dt, lc, gn);
    if (output_index == 0) return vec4(vec3(r), 1.0);
    return vec4(r, fractal(p, seed * 3 + 1, dt, lc, gn), fractal(p, seed * 3 + 2, dt, lc, gn), 1.0);
}
