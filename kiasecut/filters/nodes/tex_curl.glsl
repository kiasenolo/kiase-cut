// @filter Curl 流線
// @category 紋理
// @description 節點用：Curl 雜訊：取雜訊 ψ 的偏導 (∂ψ/∂y, −∂ψ/∂x) 當速度場，像流體一樣打轉、不會聚在一點。輸出「速度」（向量 X、Y，有正有負，可以用向量數學加到座標上做扭曲）和「流線」（白雜訊顆粒沿著速度場拖出來的線條，灰階）。「相位」接時間，流線會沿著流向動，每 6.2832 回到原樣。向量沒接線就用影像座標（長邊 -1 到 1，Y 向上）
// @source "向量"
// @input in_scale "比例" tex_scale
// @input in_strength "強度" strength
// @input in_phase "相位" phase
// @output velocity "速度"
// @output flow "流線"
// @param tex_scale float 3 -1000000 1000000 "比例"
// @param seed int 0 0 1000000 "Seed"
// @param offset vec2 0,0 -1000000 1000000 "偏移"
// @param detail float 1 0 7 "層數"
// @param gain float 0.5 0 1 "增益"
// @param strength float 1 -1000000 1000000 "強度"
// @param steps int 20 1 64 "流線步數"
// @param step_px float 3 0.1 100 "每步長度（像素）"
// @param grain float 3 0.5 100 "顆粒大小（像素）"
// @param phase float 0 -1000000 1000000 "相位"
// @socket in - vector
// @socket out velocity vector
// @socket out flow float

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
// the slope (d/dx, d/dy) of one corner of simplex noise
vec2 corner_slope(vec2 d, ivec2 c, int s) {
    float t = max(0.5 - dot(d, d), 0.0), a = cell_hash(c, s).x * 6.28318530718;
    vec2 g = vec2(cos(a), sin(a));
    float t3 = t * t * t;
    return t3 * t * g - 8.0 * t3 * dot(g, d) * d;
}
vec2 simplex_slope(vec2 p, int s) {
    const float F = 0.36602540378, G = 0.21132486541;
    ivec2 i = ivec2(floor(p + (p.x + p.y) * F));
    vec2 a = p - vec2(i) + float(i.x + i.y) * G;
    ivec2 o = a.x > a.y ? ivec2(1, 0) : ivec2(0, 1);
    vec2 b = a - vec2(o) + G, c = a - 1.0 + 2.0 * G;
    return 99.2 * (corner_slope(a, i, s) + corner_slope(b, i + o, s) + corner_slope(c, i + ivec2(1), s));
}
// (∂ψ/∂y, −∂ψ/∂x) of the layers of ψ; about -1 to 1
vec2 curl(vec2 p) {
    vec2 sum = vec2(0.0);
    float total = 0.0, amp = 1.0, freq = 1.0;
    int last = int(ceil(detail));
    for (int o = 0; o <= last; o++) {
        float w = amp * (o == 0 ? 1.0 : clamp(detail - float(o - 1), 0.0, 1.0));
        sum += w * simplex_slope(p * freq, seed * 64 + o);     // (a layer twice as fine is twice as steep: eddies in eddies)
        total += w * freq;
        amp *= gain;
        freq *= 2.0;
    }
    vec2 g = sum / max(total, 1e-6) * 0.25;
    return vec2(g.y, -g.x);
}
float grain_noise(vec2 p) {
    ivec2 i = ivec2(floor(p));
    vec2 f = fract(p), u = f * f * (3.0 - 2.0 * f);
    int s = seed + 5003;
    float a = cell_hash(i, s).x, b = cell_hash(i + ivec2(1, 0), s).x;
    float c = cell_hash(i + ivec2(0, 1), s).x, d = cell_hash(i + ivec2(1, 1), s).x;
    return mix(mix(a, b, u.x), mix(c, d, u.x), u.y);
}

vec4 effect(vec2 uv) {
    float sc = num(has_input_in_scale(), input_in_scale(uv), tex_scale);
    vec2 start = vector_in(uv).xy;
    if (output_index == 0) {
        float k = num(has_input_in_strength(), input_in_strength(uv), strength);
        return vec4(curl(start * sc + offset) * k, 0.0, 1.0);
    }
    float turn = num(has_input_in_phase(), input_in_phase(uv), phase);
    float half_px = max(resolution.x, resolution.y) / 2.0;     // canvas px per 1 of the vector
    float ds = step_px / half_px;
    float centre = grain_noise(start * half_px / grain);
    float w0 = 1.0 + cos(-turn);
    float sum = centre * w0, total = w0, squares = w0 * w0;
    for (int side = -1; side <= 1; side += 2) {
        vec2 q = start;
        for (int i = 1; i <= steps; i++) {
            vec2 v = curl(q * sc + offset);
            float l = length(v);
            if (l < 1e-5) break;
            q += v / l * ds * float(side);
            float x = float(side * i) / float(steps + 1);
            float w = (0.5 + 0.5 * cos(3.14159265359 * x)) * (1.0 + cos(6.28318530718 * x * 2.0 - turn));   // (a window, and two ripples in it that the phase moves along)
            sum += w * grain_noise(q * half_px / grain);
            total += w;
            squares += w * w;
        }
    }
    // an average of many grains is nearly grey: spread it by how many different ones went in
    float many = total * total / max(squares, 1e-6) * min(1.0, step_px / grain);
    float f = 0.5 + (sum / max(total, 1e-6) - 0.5) * sqrt(max(many, 1.0)) * 0.75;
    return vec4(vec3(clamp(f, 0.0, 1.0)), 1.0);
}
